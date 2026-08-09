import json
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import API_HOST, API_PORT, SQL_DIALECT
from db.trace_store import trace_store
from logger import QueryTracer


def sse_event(event: str, data: dict) -> str:
    """SSE 형식 문자열 생성"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from db.client import get_db
    from text_to_sql.vector_store import vector_store

    app.state.db = get_db()

    if vector_store.count() == 0:
        vector_store.train()

    yield

    if hasattr(app.state.db, "close"):
        app.state.db.close()


app = FastAPI(
    title="QueryCanvas",
    description="AI 기반 자연어 데이터 조회 및 동적 시각화",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/Response Models ──


class QueryRequest(BaseModel):
    question: str
    previous_sql: str | None = None
    previous_summary: str | None = None
    parent_history_id: str | None = None
    catalog_prompt: str | None = None  # 프론트에서 생성한 json-render 카탈로그 prompt
    resolved_context: dict | None = None  # disambiguation 후 선택된 emp/org 등 (재전송 시 포함)
    skip_prefilter: bool = False  # 명시적으로 사전분류를 건너뛸 때
    skip_clarify: bool = False  # clarify 답변을 합쳐 재요청할 때 (되묻기 루프 방지)


class SqlExecuteRequest(BaseModel):
    sql: str


class PromptUpdateRequest(BaseModel):
    sql_prompt: str | None = None
    ui_prompt: str | None = None


class HistoryTitleRequest(BaseModel):
    title: str


class TrainingDataRequest(BaseModel):
    type: str  # ddl, sql, doc
    content: str


class CuratorPreviewRequest(BaseModel):
    content: str  # 사용자 자유 텍스트


class CuratorCommitRequest(BaseModel):
    curated: dict  # /preview 응답 그대로
    source_input: str  # 원본 사용자 입력 (감사용)


# ── Health ──


@app.get("/api/health")
async def health():
    from text_to_sql.vector_store import vector_store

    db_ok = False
    try:
        db_ok = app.state.db.test_connection()
    except Exception:
        pass
    return {
        "status": "ok",
        "db_connected": db_ok,
        "vector_store_count": vector_store.count(),
    }


# ── 도메인 메타 (프론트 초기화용) ──


@app.get("/api/meta")
async def get_meta():
    """현재 도메인 팩 정보 — 추천 질문 등 프론트 초기 데이터."""
    from config import DOMAIN
    import ui_engine.prompts.loader as prompts
    return {
        "domain": DOMAIN,
        "domain_label": prompts.DISPLAY_NAME,
        "suggested_questions": prompts.SUGGESTED_QUESTIONS,
    }


# ── 꼬리질문 (현재 데이터 기반 텍스트 답변) ──


class TailQuestionRequest(BaseModel):
    question: str
    history_id: str


@app.post("/api/query/tail")
async def tail_question(req: TailQuestionRequest):
    """현재 데이터를 기반으로 텍스트 답변을 반환한다. (AI 1회 호출)"""
    from db.query_history import history_store
    from ui_engine.question_classifier import answer_from_data

    item = history_store.get(req.history_id)
    if not item or not item["data"]:
        raise HTTPException(status_code=400, detail="답변할 데이터가 없습니다")

    tracer = QueryTracer(f"[꼬리질문] {req.question[:50]}")

    summary = ""
    if item["ui_spec"]:
        s = item["ui_spec"].get("summary", "")
        summary = s.get("headline", "") if isinstance(s, dict) else str(s)

    answer = answer_from_data(req.question, item["data"], summary, tracer)
    trace_store.save(tracer.to_dict(), history_id=req.history_id)

    # 꼬리질문 영구 저장
    history_store.save_tail(req.history_id, req.question, answer)

    return {"answer": answer}


# ── Query Pipeline (SSE Streaming) ──


@app.post("/api/query/stream")
async def query_stream(req: QueryRequest):
    """SSE 스트리밍으로 각 단계를 실시간 전송"""

    def generate():
        from text_to_sql.sql_cache import sql_cache
        from text_to_sql.sql_generator import generate_sql
        from text_to_sql.vector_store import vector_store
        from ui_engine.ui_decision import decide_ui

        tracer = QueryTracer(req.question)
        cache_used = False
        # 필터 승격: 에이전트가 WHERE 대신 UI 필터로 넘긴 범주 조건 (캐시 히트/1-pass 경로는 빈 값)
        promoted_filters: list[dict] = []
        trace_saved = {"v": False}  # closure flag

        def _ensure_trace_saved(history_id: str | None = None):
            if trace_saved["v"]:
                return
            try:
                trace_store.save(tracer.to_dict(), history_id=history_id)
            except Exception as e:
                from logger import pipeline_logger
                pipeline_logger.warning(f"trace 저장 실패: {e}")
            trace_saved["v"] = True

        # 후속 질의 자동 라우팅: 이전 결과가 있으면 tail(현재 데이터 질답) 여부를 먼저 판단
        # — 사용자가 모드를 고르지 않아도 자연스럽게 답변/재조회가 갈린다
        if req.parent_history_id:
            from db.query_history import history_store
            from ui_engine.question_classifier import classify_question, answer_from_data

            parent = history_store.get(req.parent_history_id)
            if parent and parent.get("data"):
                yield sse_event("step", {"phase": "routing", "status": "running", "message": "질문 유형을 판단하고 있습니다..."})
                qtype = classify_question(req.question, parent["data"], req.previous_summary or "", tracer)
                if qtype == "tail":
                    yield sse_event("step", {"phase": "routing", "status": "done", "message": "현재 데이터로 바로 답변합니다"})
                    answer = answer_from_data(req.question, parent["data"], req.previous_summary or "", tracer)
                    history_store.save_tail(req.parent_history_id, req.question, answer)
                    yield sse_event("tail_answer", {"answer": answer})
                    _ensure_trace_saved(history_id=req.parent_history_id)
                    yield sse_event("done", {"trace_id": tracer.trace_id, "tail": True})
                    return
                yield sse_event("step", {"phase": "routing", "status": "done", "message": "새 데이터 조회로 진행합니다"})

        # 스테이지①: 레이아웃 스켈레톤 즉시 방출 (t=0, 휴리스틱 — LLM 미경유)
        # SQL 생성이 끝나기 전에 화면 골격(제목/표/차트 자리)이 먼저 렌더된다.
        from ui_engine.ui_decision import plan_layout, build_skeleton_messages
        _plan = plan_layout(req.question, tracer)
        skeleton_msgs = build_skeleton_messages(_plan)
        # step(ui_layout) 을 a2ui 보다 먼저 — 프론트는 이 스텝에서 화면을 교체한다(리셋).
        # 순서가 뒤바뀌면 방금 보낸 스켈레톤이 리셋에 지워져 스테이지②까지 빈 화면이 된다.
        yield sse_event("step", {"phase": "ui_layout", "status": "done",
                                 "message": f"UI 결정 — {_plan.get('title', '')}"})
        yield sse_event("a2ui", {"messages": skeleton_msgs})

        # 신규 질의 보강(clarify): 조회 대상이 불명확하면 짧게 되묻고 종료 (보수적 — 대부분 통과)
        if not req.parent_history_id and not req.skip_clarify:
            from ui_engine.question_classifier import clarify_check
            c = clarify_check(req.question, tracer)
            if c.get("needs_clarification") and c.get("question_to_user"):
                yield sse_event("clarify", {"question": c["question_to_user"]})
                yield sse_event("step", {"phase": "clarify", "status": "done", "message": "추가 정보가 필요합니다"})
                _ensure_trace_saved()
                yield sse_event("done", {"trace_id": tracer.trace_id, "needs_clarify": True})
                return

        # Step -1: 사전 분류 + 추가정보 수집기 (resolved_context 가 이미 있으면 건너뜀)
        # 에이전틱 모드에서는 에이전트가 find_person/find_group 도구로 식별자를
        # 스스로 확정하므로 이 단계를 건너뛴다 (1-pass 폴백 모드 전용).
        from config import get_llm
        _agentic = get_llm("AGENTIC_SQL")
        if not _agentic and not req.skip_prefilter and not req.resolved_context and not req.previous_sql:
            from ui_engine.question_classifier import prefilter_question
            from ui_engine.info_collector import collect as collect_candidates

            yield sse_event("step", {"phase": "prefilter", "status": "running", "message": "질문을 사전 분석하고 있습니다..."})
            pf = prefilter_question(req.question, tracer)
            yield sse_event("step", {
                "phase": "prefilter", "status": "done",
                "message": f"필요 정보: {', '.join(pf.get('missing') or []) or '없음'}",
            })

            if pf.get("needs_disambiguation"):
                yield sse_event("step", {"phase": "info_collect", "status": "running", "message": "후보를 조회하고 있습니다..."})
                groups = collect_candidates(app.state.db, pf.get("extracted") or {})
                tracer.log_step("info_collect_result", {
                    "groups": [{"kind": g.kind, "keyword": g.keyword, "case_id": g.case_id, "count": len(g.candidates), "status": g.status} for g in groups],
                })

                # 후보가 2건 이상인 그룹이 있으면 사용자 선택 요청
                needs = [g for g in groups if g.status == "needs_input"]
                if needs:
                    payload = {
                        "question": req.question,
                        "extracted": pf.get("extracted"),
                        "groups": [
                            {"kind": g.kind, "keyword": g.keyword, "case_id": g.case_id, "candidates": g.candidates}
                            for g in groups
                        ],
                    }
                    yield sse_event("needs_input", payload)
                    yield sse_event("step", {"phase": "info_collect", "status": "done", "message": "사용자 선택 대기"})
                    yield sse_event("done", {"trace_id": tracer.trace_id, "needs_input": True})
                    _ensure_trace_saved()
                    return

                # 모든 그룹이 auto 또는 empty → resolved 자동 구성
                auto_resolved = {
                    g.kind: g.candidates[0] for g in groups if g.status == "auto"
                }
                if auto_resolved:
                    tracer.log_step("auto_resolved", auto_resolved)
                    yield sse_event("step", {"phase": "info_collect", "status": "done", "message": f"후보 자동 확정 ({len(auto_resolved)}건)"})
                else:
                    yield sse_event("step", {"phase": "info_collect", "status": "done", "message": "후보 없음 — LLM에게 위임"})

        # Step 0: SQL 캐시 조회
        yield sse_event("step", {"phase": "cache_lookup", "status": "running", "message": "캐시를 확인하고 있습니다..."})

        cached = sql_cache.lookup(req.question)
        if cached:
            sql = cached["sql"]
            cache_used = True
            tracer.log_step("sql_cache_hit", {
                "cached_sql": sql,
                "original_question": cached["original_question"],
                "distance": cached["distance"],
                "cached_at": cached["cached_at"],
            })
            yield sse_event("step", {
                "phase": "cache_lookup",
                "status": "done",
                "message": f"캐시 히트! (유사도: {(1 - cached['distance']) * 100:.1f}%) 기존 SQL을 재활용합니다",
            })
            # 캐시 히트 시 벡터 검색과 SQL 생성 건너뜀
            yield sse_event("step", {"phase": "vector_search", "status": "done", "message": "캐시 사용으로 생략"})
            yield sse_event("step", {"phase": "sql_generation", "status": "done", "message": "캐시된 SQL 재활용"})
            yield sse_event("sql", {"sql": sql, "from_cache": True})
        else:
            tracer.log_step("sql_cache_miss", {"message": "캐시 미스 — AI로 SQL 생성"})
            yield sse_event("step", {"phase": "cache_lookup", "status": "done", "message": "캐시 미스 — AI로 새 SQL을 생성합니다"})

            # Step 1: 벡터 검색
            yield sse_event("step", {"phase": "vector_search", "status": "running", "message": "관련 문서를 검색하고 있습니다..."})

            context = vector_store.search(req.question)
            tracer.log_step("vector_search_result", {
                "question": req.question,
                "results": {
                    "ddl": [{"content": d["content"], "distance": d["distance"], "source": d["source"]} for d in context["ddl"]],
                    "sql": [{"content": d["content"], "distance": d["distance"], "source": d["source"]} for d in context["sql"]],
                    "doc": [{"content": d["content"], "distance": d["distance"], "source": d["source"]} for d in context["doc"]],
                },
                "counts": {"ddl": len(context["ddl"]), "sql": len(context["sql"]), "doc": len(context["doc"])},
            })

            yield sse_event("step", {
                "phase": "vector_search",
                "status": "done",
                "message": f"DDL {len(context['ddl'])}건, SQL {len(context['sql'])}건, 문서 {len(context['doc'])}건 검색 완료",
            })

            # Step 2: SQL 생성 (에이전틱 모드: 모델이 도구로 스키마 검색/식별자 확정/시험 실행)
            has_prev = bool(req.previous_sql)
            msg = "이전 결과를 참고하여 AI가 SQL을 생성하고 있습니다..." if has_prev else "AI가 SQL을 생성하고 있습니다..."
            yield sse_event("step", {"phase": "sql_generation", "status": "running", "message": msg})

            sql = None
            if _agentic:
                from text_to_sql.sql_agent import generate_sql_agentic

                agent_meta = {}
                for ev in generate_sql_agentic(
                    req.question, context, app.state.db, tracer,
                    req.previous_sql, req.previous_summary,
                    resolved_context=req.resolved_context,
                ):
                    if ev["type"] == "tool":
                        yield sse_event("step", {
                            "phase": "sql_generation", "status": "running",
                            "message": f"🔧 {ev['summary']}",
                        })
                    elif ev["type"] == "status":
                        yield sse_event("step", {"phase": "sql_generation", "status": "running", "message": ev["message"]})
                    elif ev["type"] == "done":
                        sql = ev["sql"]
                        promoted_filters = ev.get("promoted_filters") or []
                        agent_meta = {"turns": ev.get("turns"), "tool_calls": ev.get("tool_calls")}
                    elif ev["type"] == "error":
                        yield sse_event("error", {"message": ev["message"]})
                        _ensure_trace_saved()
                        return

                done_msg = "SQL 생성 완료"
                if agent_meta.get("tool_calls"):
                    done_msg = f"SQL 생성 완료 (도구 {agent_meta['tool_calls']}회, {agent_meta['turns']}턴)"
                yield sse_event("sql", {"sql": sql})
                yield sse_event("step", {"phase": "sql_generation", "status": "done", "message": done_msg})
            else:
                try:
                    sql = generate_sql(req.question, context, tracer, req.previous_sql, req.previous_summary, resolved_context=req.resolved_context)
                except ValueError as e:
                    yield sse_event("error", {"message": str(e)})
                    _ensure_trace_saved()
                    return

                yield sse_event("sql", {"sql": sql})
                yield sse_event("step", {"phase": "sql_generation", "status": "done", "message": "SQL 생성 완료"})

        # Step 2.5: SQL 안전성 검증 (sqlglot AST — DML/DDL 차단, LLM 없음)
        from text_to_sql.sql_validator import validate_sql

        yield sse_event("step", {"phase": "sql_validate", "status": "running", "message": "SQL 안전성을 검증하고 있습니다..."})
        vres = validate_sql(sql, dialect=SQL_DIALECT)
        tracer.log_step("sql_validated", {
            "ok": vres.ok,
            "tables": vres.tables,
            "errors": vres.errors,
        })
        if not vres.ok:
            yield sse_event("step", {"phase": "sql_validate", "status": "error", "message": "; ".join(vres.errors)})
            yield sse_event("error", {"message": "; ".join(vres.errors)})
            _ensure_trace_saved()
            return
        yield sse_event("step", {"phase": "sql_validate", "status": "done", "message": f"읽기 전용 확인 (테이블 {len(vres.tables)}개)"})

        # Step 2.55: 가상 view 해석 (FROM VV_XXX → (base SQL) alias)
        from text_to_sql.virtual_view_resolver import resolve as vv_resolve
        vres2 = vv_resolve(sql, dialect=SQL_DIALECT)
        if vres2.errors:
            yield sse_event("step", {"phase": "vv_resolve", "status": "error", "message": "; ".join(vres2.errors)})
            yield sse_event("error", {"message": "; ".join(vres2.errors)})
            _ensure_trace_saved()
            return
        if vres2.resolved:
            sql = vres2.sql
            # 내부 SQL 변환이라 단계로 노출하지 않는다 — 갱신된 SQL 과 trace 로만 확인된다
            tracer.log_step("vv_resolved", {"resolved": vres2.resolved})
            yield sse_event("sql", {"sql": sql, "vv_resolved": True, "resolved": vres2.resolved})

        # Step 3: SQL 실행 (오류 시 최대 3회 자동 수정 재시도)
        from text_to_sql.sql_fixer import fix_sql

        MAX_RETRIES = 3
        data = None
        current_sql = sql

        for attempt in range(1, MAX_RETRIES + 2):  # 1=첫 시도, 2~4=재시도
            yield sse_event("step", {
                "phase": "sql_execution",
                "status": "running",
                "message": f"SQL을 실행하고 있습니다...{f' (재시도 {attempt - 1}/{MAX_RETRIES})' if attempt > 1 else ''}",
            })

            try:
                data = app.state.db.execute(current_sql)
                tracer.log_step("sql_executed", {
                    "row_count": len(data),
                    "columns": list(data[0].keys()) if data else [],
                    "sample_rows": data[:5],
                    "attempt": attempt,
                })
                sql = current_sql  # 성공한 SQL로 갱신
                break
            except Exception as e:
                error_msg = str(e)
                tracer.log_step("sql_execution_error", {
                    "error": error_msg,
                    "sql": current_sql,
                    "attempt": attempt,
                })

                if attempt > MAX_RETRIES:
                    yield sse_event("step", {"phase": "sql_execution", "status": "error", "message": f"SQL 실행 실패 ({MAX_RETRIES}회 수정 시도 실패)"})
                    yield sse_event("error", {"message": f"SQL 실행 오류 ({MAX_RETRIES}회 수정 시도 실패): {error_msg}"})
                    _ensure_trace_saved()
                    return

                # 자동 수정 시도
                yield sse_event("step", {
                    "phase": "sql_fix",
                    "status": "running",
                    "message": f"SQL 오류 감지 — 자동 수정 중... ({attempt}/{MAX_RETRIES})",
                })

                fixed = fix_sql(current_sql, error_msg, tracer)
                if not fixed:
                    yield sse_event("step", {"phase": "sql_fix", "status": "error", "message": "SQL 자동 수정 실패"})
                    yield sse_event("step", {"phase": "sql_execution", "status": "error", "message": "SQL 실행 실패"})
                    yield sse_event("error", {"message": f"SQL 자동 수정 실패: {error_msg}"})
                    _ensure_trace_saved()
                    return

                current_sql = fixed
                yield sse_event("sql", {"sql": current_sql, "fixed": True, "attempt": attempt})
                yield sse_event("step", {
                    "phase": "sql_fix",
                    "status": "done",
                    "message": f"SQL 수정 완료 — 재실행합니다 ({attempt}/{MAX_RETRIES})",
                })

        if data is None:
            yield sse_event("error", {"message": "SQL 실행 결과가 없습니다"})
            _ensure_trace_saved()
            return

        yield sse_event("data", {"data": data, "row_count": len(data)})
        yield sse_event("step", {"phase": "sql_execution", "status": "done", "message": f"{len(data)}건 조회 완료"})

        # rows 본문이 LLM 을 거치지 않게 되면서 이 자리의 개인정보 단계는 표시 전용 잔재가 됐다.
        # 실제 마스킹은 ui_decision 이 LLM 에 넘길 샘플을 만들 때 anonymizer 가 수행한다.

        # Step 4: UI 결정 (스테이지②) — A2UI v0.9 메시지 스트리밍, 스켈레톤 갱신
        from ui_engine.ui_decision import decide_ui_stream
        yield sse_event("step", {"phase": "ui_decision", "status": "running", "message": "AI가 UI를 스트리밍 생성 중..."})

        ui_spec: dict = {"format": "a2ui", "messages": []}
        a2ui_message_count = 0
        ui_error: str | None = None

        for event in decide_ui_stream(req.question, sql, data, tracer, skeleton=skeleton_msgs, promoted_filters=promoted_filters):
            kind = event.get("event")
            if kind == "a2ui":
                a2ui_message_count += len(event["messages"])
                yield sse_event("a2ui", {"messages": event["messages"]})
            elif kind == "spec_done":
                ui_spec = event["spec"]
            elif kind == "error":
                ui_error = event["message"]
                break

        if ui_error:
            yield sse_event("step", {"phase": "ui_decision", "status": "error", "message": f"UI 결정 실패: {ui_error}"})
            yield sse_event("error", {"message": f"UI 결정 실패: {ui_error}"})
            _ensure_trace_saved()
            return

        yield sse_event("ui_spec", {"ui_spec": ui_spec})
        component_count = sum(
            len(m.get("updateComponents", {}).get("components", []))
            for m in ui_spec.get("messages", [])
        )
        yield sse_event("step", {
            "phase": "ui_decision",
            "status": "done",
            "message": f"A2UI 메시지 {a2ui_message_count}개 → {component_count}개 컴포넌트 생성",
        })

        # SQL 실행 성공 시 캐시에 저장 (AI 생성인 경우만)
        if not cache_used and data:
            sql_cache.store(req.question, sql)
            tracer.log_step("sql_cache_stored", {"question": req.question, "sql": sql})

        # 질문내역 영구 저장
        from db.query_history import history_store
        saved = history_store.save(req.question, sql, data, ui_spec, parent_id=req.parent_history_id)
        tracer.log_step("history_saved", {"id": saved["id"], "title": saved["title"]})
        yield sse_event("saved", {"history_id": saved["id"], "title": saved["title"]})

        # 완료
        _ensure_trace_saved(history_id=saved["id"])
        yield sse_event("done", {"trace_id": tracer.trace_id, "message": "완료"})

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/query")
async def query_full(req: QueryRequest):
    """자연어 질문 → SQL 생성 → 실행 → UI 스펙 반환 (비스트리밍 폴백)"""
    from text_to_sql.sql_generator import generate_sql
    from text_to_sql.vector_store import vector_store
    from ui_engine.ui_decision import decide_ui

    tracer = QueryTracer(req.question)

    context = vector_store.search(req.question)
    tracer.log_step("vector_search_result", {
        "question": req.question,
        "results": {
            "ddl": [{"content": d["content"], "distance": d["distance"], "source": d["source"]} for d in context["ddl"]],
            "sql": [{"content": d["content"], "distance": d["distance"], "source": d["source"]} for d in context["sql"]],
            "doc": [{"content": d["content"], "distance": d["distance"], "source": d["source"]} for d in context["doc"]],
        },
        "counts": {"ddl": len(context["ddl"]), "sql": len(context["sql"]), "doc": len(context["doc"])},
    })

    try:
        sql = generate_sql(req.question, context, tracer, req.previous_sql, req.previous_summary)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        data = app.state.db.execute(sql)
        tracer.log_step("sql_executed", {
            "row_count": len(data),
            "columns": list(data[0].keys()) if data else [],
            "sample_rows": data[:5],
        })
    except Exception as e:
        tracer.log_step("sql_execution_error", {"error": str(e), "sql": sql})
        raise HTTPException(status_code=400, detail=f"SQL 실행 오류: {e}")

    ui_spec = decide_ui(req.question, sql, data, tracer, catalog_prompt=req.catalog_prompt or "")
    trace_store.save(tracer.to_dict())

    return {"sql": sql, "data": data, "ui_spec": ui_spec}


@app.post("/api/query/sql-only")
async def query_sql_only(req: QueryRequest):
    """SQL만 생성 (실행 안 함)"""
    from text_to_sql.sql_generator import generate_sql
    from text_to_sql.vector_store import vector_store

    tracer = QueryTracer(req.question)
    context = vector_store.search(req.question)
    tracer.log_step("vector_search", {
        "ddl_count": len(context["ddl"]),
        "sql_count": len(context["sql"]),
        "doc_count": len(context["doc"]),
    })

    try:
        sql = generate_sql(req.question, context, tracer)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"sql": sql}


@app.post("/api/query/execute")
async def query_execute(req: SqlExecuteRequest):
    """주어진 SQL 실행 + UI 스펙 생성"""
    from ui_engine.ui_decision import decide_ui

    tracer = QueryTracer(f"[수동 SQL] {req.sql[:80]}")

    try:
        data = app.state.db.execute(req.sql)
        tracer.log_step("sql_executed", {"row_count": len(data)})
    except Exception as e:
        tracer.log_step("sql_execution_error", {"error": str(e)})
        raise HTTPException(status_code=400, detail=f"SQL 실행 오류: {e}")

    ui_spec = decide_ui("사용자 수동 SQL 실행", req.sql, data, tracer)

    return {"data": data, "ui_spec": ui_spec}


# ── 질문내역 API ──


@app.get("/api/history")
async def list_history():
    """질문내역 목록 (즐겨찾기 우선, 최신순)"""
    from db.query_history import history_store
    return {"items": history_store.list_all()}


@app.get("/api/history/{entry_id}")
async def get_history_detail(entry_id: str):
    """질문내역 상세 (data 포함)"""
    from db.query_history import history_store
    item = history_store.get(entry_id)
    if not item:
        raise HTTPException(status_code=404, detail="질문내역을 찾을 수 없습니다")
    return item


@app.put("/api/history/{entry_id}/title")
async def update_history_title(entry_id: str, req: HistoryTitleRequest):
    """질문내역 제목 변경"""
    from db.query_history import history_store
    if not history_store.update_title(entry_id, req.title):
        raise HTTPException(status_code=404, detail="질문내역을 찾을 수 없습니다")
    return {"status": "updated", "id": entry_id, "title": req.title}


@app.post("/api/history/{entry_id}/favorite")
async def toggle_history_favorite(entry_id: str):
    """즐겨찾기 토글"""
    from db.query_history import history_store
    result = history_store.toggle_favorite(entry_id)
    if result is None:
        raise HTTPException(status_code=404, detail="질문내역을 찾을 수 없습니다")
    return {"status": "updated", "id": entry_id, "favorite": result}


@app.delete("/api/history/{entry_id}")
async def delete_history(entry_id: str):
    """질문내역 삭제"""
    from db.query_history import history_store
    if not history_store.delete(entry_id):
        raise HTTPException(status_code=404, detail="질문내역을 찾을 수 없습니다")
    return {"status": "deleted", "id": entry_id}


@app.post("/api/history/{entry_id}/rerun")
async def rerun_history(entry_id: str):
    """템플릿 재조회 — 저장된 SQL을 현재 시점으로 다시 실행 + UI 결정"""
    from db.query_history import history_store
    from ui_engine.ui_decision import decide_ui

    item = history_store.get(entry_id)
    if not item or not item["sql"]:
        raise HTTPException(status_code=404, detail="재실행할 SQL이 없습니다")

    tracer = QueryTracer(f"[재조회] {item['question'][:50]}")

    try:
        data = app.state.db.execute(item["sql"])
        tracer.log_step("rerun_executed", {"row_count": len(data), "original_id": entry_id})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SQL 실행 오류: {e}")

    ui_spec = decide_ui(item["question"], item["sql"], data, tracer)

    # 새 질문내역으로 저장
    saved = history_store.save(f"[재조회] {item['question']}", item["sql"], data, ui_spec)
    trace_store.save(tracer.to_dict())

    return {"sql": item["sql"], "data": data, "ui_spec": ui_spec, "history_id": saved["id"]}


# ── UI 수정 (화면 증분 갱신 — SQL/데이터 불변) ──


class UiEditRequest(BaseModel):
    history_id: str
    instruction: str


@app.post("/api/query/ui-edit")
async def ui_edit_stream(req: UiEditRequest):
    """현재 화면을 수정 지시에 따라 증분 갱신한다 (updateComponents만 — 재조회 없음)."""
    from db.query_history import history_store
    from ui_engine.ui_decision import decide_ui_edit_stream

    item = history_store.get(req.history_id)
    if not item:
        raise HTTPException(status_code=404, detail="수정할 화면을 찾을 수 없습니다")
    ui_spec = item.get("ui_spec")
    if not isinstance(ui_spec, dict) or ui_spec.get("format") != "a2ui":
        raise HTTPException(status_code=400, detail="A2UI 형식 화면만 수정할 수 있습니다")

    def generate():
        tracer = QueryTracer(f"[UI 수정] {req.instruction[:50]}")
        yield sse_event("step", {"phase": "ui_edit", "status": "running", "message": "화면을 수정하고 있습니다..."})

        final_spec = None
        for event in decide_ui_edit_stream(req.instruction, ui_spec, item.get("data") or [], tracer):
            kind = event.get("event")
            if kind == "a2ui":
                yield sse_event("a2ui", {"messages": event["messages"]})
            elif kind == "spec_done":
                final_spec = event["spec"]
            elif kind == "error":
                yield sse_event("step", {"phase": "ui_edit", "status": "error", "message": event["message"]})
                yield sse_event("error", {"message": event["message"]})
                trace_store.save(tracer.to_dict(), history_id=req.history_id)
                return

        if final_spec:
            history_store.update_ui_spec(req.history_id, final_spec)
            yield sse_event("ui_spec", {"ui_spec": final_spec})
        yield sse_event("step", {"phase": "ui_edit", "status": "done", "message": "화면 수정 완료"})
        trace_store.save(tracer.to_dict(), history_id=req.history_id)
        yield sse_event("done", {"trace_id": tracer.trace_id})

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── 저장된 뷰 (화면의 메뉴화) ──


class SavedViewCreateRequest(BaseModel):
    history_id: str
    name: str | None = None


class SavedViewRenameRequest(BaseModel):
    name: str


@app.post("/api/views")
async def create_saved_view(req: SavedViewCreateRequest):
    """히스토리 항목을 '내 화면'으로 저장.

    저장 시 1회만 경량 LLM으로 절대 날짜를 상대 표현으로 변환(라이브 SQL) —
    이후 열 때는 SQL 재실행 + 저장된 A2UI spec 바인딩뿐 (LLM 0회).
    """
    from db.query_history import history_store
    from db.saved_views import saved_view_store
    from text_to_sql.sql_liveness import make_sql_live

    item = history_store.get(req.history_id)
    if not item or not item["sql"]:
        raise HTTPException(status_code=404, detail="저장할 질문내역을 찾을 수 없습니다")
    ui_spec = item.get("ui_spec")
    if not isinstance(ui_spec, dict) or ui_spec.get("format") != "a2ui":
        raise HTTPException(status_code=400, detail="A2UI 형식 화면만 저장할 수 있습니다 (질문을 다시 실행해 주세요)")

    tracer = QueryTracer(f"[화면 저장] {item['question'][:50]}")
    live_sql, note = make_sql_live(item["sql"], item["question"], tracer)
    trace_store.save(tracer.to_dict())

    name = (req.name or item["title"]).strip()[:50]
    view = saved_view_store.create(name, item["question"], live_sql, ui_spec, note)
    return {"view": {k: v for k, v in view.items() if k != "ui_spec"}, "liveness_note": note}


@app.get("/api/views")
async def list_saved_views():
    from db.saved_views import saved_view_store
    return {"items": saved_view_store.list_all()}


@app.post("/api/views/{view_id}/open")
async def open_saved_view(view_id: str):
    """저장된 뷰 열기 — SQL 재실행 + 저장된 spec 반환 (LLM 미호출, 항상 fresh 데이터)."""
    from db.saved_views import saved_view_store
    from text_to_sql.virtual_view_resolver import resolve as vv_resolve

    view = saved_view_store.get(view_id)
    if not view:
        raise HTTPException(status_code=404, detail="저장된 뷰를 찾을 수 없습니다")

    final_sql = view["sql"]
    vres = vv_resolve(final_sql, dialect=SQL_DIALECT)
    if vres.resolved:
        final_sql = vres.sql

    try:
        data = app.state.db.execute(final_sql)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SQL 실행 오류: {e}")

    saved_view_store.touch(view_id)
    return {
        "view": {"id": view["id"], "name": view["name"], "question": view["question"], "liveness_note": view["liveness_note"]},
        "sql": view["sql"],
        "data": data,
        "ui_spec": view["ui_spec"],
    }


@app.put("/api/views/{view_id}")
async def rename_saved_view(view_id: str, req: SavedViewRenameRequest):
    from db.saved_views import saved_view_store
    if not saved_view_store.rename(view_id, req.name.strip()[:50]):
        raise HTTPException(status_code=404, detail="저장된 뷰를 찾을 수 없습니다")
    return {"status": "updated", "id": view_id, "name": req.name}


@app.delete("/api/views/{view_id}")
async def delete_saved_view(view_id: str):
    from db.saved_views import saved_view_store
    if not saved_view_store.delete(view_id):
        raise HTTPException(status_code=404, detail="저장된 뷰를 찾을 수 없습니다")
    return {"status": "deleted", "id": view_id}


@app.get("/api/tables")
async def list_tables():
    """학습된 테이블 목록 반환"""
    from text_to_sql.vector_store import vector_store

    docs = vector_store.get_all_documents()
    tables = []
    for doc in docs:
        if doc["type"] == "ddl":
            import re
            m = re.search(r"CREATE TABLE (\w+)", doc["content"])
            if m:
                tables.append(m.group(1))
    return {"tables": tables}


# ── Admin API ──


class VectorSearchTestRequest(BaseModel):
    query: str


@app.post("/api/admin/vector-search-test")
async def vector_search_test(req: VectorSearchTestRequest):
    """학습 데이터 벡터 검색 테스트 — 실제 서비스와 동일한 기준 (n_results=10, 타입별 제한)"""
    from text_to_sql.vector_store import vector_store
    # 실제 서비스와 동일: search()는 n_results=10 + 타입별 제한 적용
    injected_results = vector_store.search(req.query)
    # 제한 전 전체도 함께 반환 (어떤 것이 잘렸는지 확인용)
    raw_results = vector_store.search_raw(req.query, n_results=10)
    limits = vector_store.INJECT_LIMITS
    return {
        "query": req.query,
        "store": "training",
        "results": raw_results,
        "counts": {k: len(v) for k, v in raw_results.items()},
        "inject_limits": limits,
        "injected_counts": {k: len(v) for k, v in injected_results.items()},
        "n_results": 10,
    }


@app.post("/api/admin/cache-search-test")
async def cache_search_test(req: VectorSearchTestRequest):
    """SQL 캐시 벡터 검색 테스트 — 실제 서비스와 동일한 기준"""
    from text_to_sql.sql_cache import sql_cache, CACHE_HIT_THRESHOLD
    items = sql_cache.search_raw(req.query)
    return {
        "query": req.query,
        "store": "cache",
        "results": items,
        "total": len(items),
        "hit_threshold": CACHE_HIT_THRESHOLD,
    }


@app.get("/api/admin/prompts")
async def get_prompts():
    """현재 활성 도메인 팩의 프롬프트."""
    from config import DOMAIN
    from ui_engine.prompts.loader import SQL_SYSTEM_PROMPT, UI_SYSTEM_PROMPT
    return {"domain": DOMAIN, "sql_prompt": SQL_SYSTEM_PROMPT, "ui_prompt": UI_SYSTEM_PROMPT}


@app.put("/api/admin/prompts")
async def update_prompts(req: PromptUpdateRequest):
    from config import DOMAIN
    import ui_engine.prompts.loader as prompts
    if req.sql_prompt is not None:
        prompts.SQL_SYSTEM_PROMPT = req.sql_prompt
    if req.ui_prompt is not None:
        prompts.UI_SYSTEM_PROMPT = req.ui_prompt
    return {"status": "updated", "domain": DOMAIN}


@app.get("/api/admin/training-data")
async def get_training_data():
    from text_to_sql.vector_store import vector_store
    docs = vector_store.get_all_documents()
    return {"documents": docs, "total": len(docs)}


@app.post("/api/admin/training-data")
async def add_training_data(req: TrainingDataRequest):
    from text_to_sql.vector_store import vector_store
    existing = vector_store.count()
    new_id = f"{req.type}_{existing + 1}"
    vector_store.collection.add(
        documents=[req.content],
        metadatas=[{"type": req.type, "source": "admin_manual"}],
        ids=[new_id],
    )
    return {"status": "added", "id": new_id}


@app.delete("/api/admin/training-data/{doc_id}")
async def delete_training_data(doc_id: str):
    from text_to_sql.vector_store import vector_store
    vector_store.collection.delete(ids=[doc_id])
    return {"status": "deleted", "id": doc_id}


@app.post("/api/admin/training-data/curate-preview")
async def training_data_curate_preview(req: CuratorPreviewRequest):
    """
    사용자 입력을 AI(Sonnet)가 분석해서 add/patch 판단 + 구조화.
    저장은 안 함. 미리보기 후 /commit 호출 필요.
    """
    from text_to_sql.training_curator import curate

    result = curate(req.content)
    return result


@app.post("/api/admin/training-data/curate-commit")
async def training_data_curate_commit(req: CuratorCommitRequest):
    """preview 결과를 overlay 파일로 저장 + 벡터 스토어 즉시 반영."""
    from text_to_sql.training_curator import commit

    result = commit(req.curated, req.source_input)
    return result


@app.get("/api/admin/training-data/overlays")
async def training_data_list_overlays():
    from text_to_sql.training_curator import list_overlays

    return {"items": list_overlays()}


@app.delete("/api/admin/training-data/overlays/{filename}")
async def training_data_delete_overlay(filename: str):
    from text_to_sql.training_curator import delete_overlay

    return delete_overlay(filename)


@app.post("/api/admin/retrain")
async def retrain():
    from text_to_sql.vector_store import vector_store
    from text_to_sql.sql_cache import sql_cache
    result = vector_store.train()
    sql_cache.clear()
    return {"status": "retrained", "sql_cache_cleared": True, **result}


@app.post("/api/admin/retrain/stream")
async def retrain_stream():
    """재임베딩을 SSE 로 진행 상황과 함께 스트리밍."""
    def generate():
        from text_to_sql.vector_store import vector_store
        from text_to_sql.sql_cache import sql_cache
        try:
            for ev in vector_store.train_stream():
                yield sse_event("progress", ev)
            sql_cache.clear()
            yield sse_event("progress", {"phase": "cache_clear", "message": "SQL 캐시 초기화"})
            yield sse_event("done", {"status": "ok"})
        except Exception as e:
            yield sse_event("error", {"message": str(e)})
    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/admin/sql-cache")
async def get_sql_cache():
    """SQL 캐시 목록 조회"""
    from text_to_sql.sql_cache import sql_cache
    return {"items": sql_cache.get_all(), "total": sql_cache.count()}


@app.delete("/api/admin/sql-cache/{cache_id}")
async def delete_sql_cache_item(cache_id: str):
    """SQL 캐시 항목 삭제"""
    from text_to_sql.sql_cache import sql_cache
    sql_cache.delete(cache_id)
    return {"status": "deleted", "id": cache_id}


@app.delete("/api/admin/sql-cache")
async def clear_sql_cache():
    """SQL 캐시 전체 삭제"""
    from text_to_sql.sql_cache import sql_cache
    sql_cache.clear()
    return {"status": "cleared"}


@app.get("/api/admin/settings")
async def get_settings():
    from config import EFFORT_LEVELS, get_llm_settings
    from text_to_sql.sql_cache import sql_cache
    from text_to_sql.vector_store import vector_store
    return {
        "db_connected": app.state.db.test_connection(),
        "vector_store_count": vector_store.count(),
        "sql_cache_count": sql_cache.count(),
        "llm": get_llm_settings(),
        "effort_levels": list(EFFORT_LEVELS),
    }


@app.put("/api/admin/llm-settings")
async def update_llm_settings_api(payload: dict):
    """LLM 설정 런타임 변경 — 저장 즉시 다음 질의부터 적용 (재시작 불필요)."""
    from config import update_llm_settings
    try:
        merged = update_llm_settings(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "updated", "llm": merged}


@app.delete("/api/admin/llm-settings")
async def reset_llm_settings_api():
    """런타임 오버라이드 삭제 — .env/기본값으로 복귀."""
    from config import reset_llm_settings
    return {"status": "reset", "llm": reset_llm_settings()}


@app.get("/api/admin/traces")
async def get_traces(limit: int = 50):
    return {"traces": trace_store.list_recent(limit)}


@app.get("/api/admin/traces/{trace_id}")
async def get_trace_detail(trace_id: str):
    item = trace_store.get(trace_id)
    if not item:
        raise HTTPException(status_code=404, detail="추적을 찾을 수 없습니다")
    return item


class FeedbackRequest(BaseModel):
    feedback: int  # 1=좋아요, -1=싫어요
    comment: str = ""


@app.post("/api/feedback/{trace_id}")
async def submit_feedback(trace_id: str, req: FeedbackRequest):
    """파이프라인 결과에 대한 피드백 저장"""
    if not trace_store.set_feedback(trace_id, req.feedback, req.comment):
        raise HTTPException(status_code=404, detail="추적을 찾을 수 없습니다")
    return {"status": "saved", "trace_id": trace_id, "feedback": req.feedback}


@app.get("/api/admin/feedback-stats")
async def get_feedback_stats():
    """피드백 통계"""
    return trace_store.get_feedback_stats()


# ── Phase 4: 가상 View / 필수 필터 / 추가정보 수집기 / IDX_CD 매핑 Admin ──


class TestRunRequest(BaseModel):
    params: dict | None = None
    sql: str | None = None


@app.get("/api/admin/virtual-views")
async def admin_list_virtual_views():
    from admin.virtual_view_admin import list_meta
    return {"items": list_meta()}


@app.get("/api/admin/virtual-views/{view_id}")
async def admin_get_virtual_view(view_id: str):
    from admin.virtual_view_admin import get_full
    v = get_full(view_id)
    if not v:
        raise HTTPException(status_code=404, detail="view 없음")
    return v


@app.put("/api/admin/virtual-views/{view_id}")
async def admin_save_virtual_view(view_id: str, payload: dict):
    from admin.virtual_view_admin import save
    try:
        return save(view_id, meta=payload.get("meta"), sql=payload.get("sql"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/admin/virtual-views/{view_id}/test-run")
async def admin_test_view(view_id: str, req: TestRunRequest):
    from admin.virtual_view_admin import test_run
    try:
        rows = test_run(app.state.db, view_id, req.params or {})
        return {"row_count": len(rows), "rows": rows}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/admin/virtual-views/reindex")
async def admin_reindex_virtual_views():
    from admin.virtual_view_admin import reindex
    return reindex()


@app.post("/api/admin/virtual-views/reindex/stream")
async def admin_reindex_virtual_views_stream():
    """가상 view 재임베딩 SSE — 실제로는 전체 vector_store retrain 동일."""
    def generate():
        from text_to_sql.vector_store import vector_store
        try:
            for ev in vector_store.train_stream():
                yield sse_event("progress", ev)
            yield sse_event("done", {"status": "ok"})
        except Exception as e:
            yield sse_event("error", {"message": str(e)})
    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/admin/retrieval-weights")
async def admin_get_retrieval_weights():
    from text_to_sql.vector_store import load_retrieval_weights
    return {"data": load_retrieval_weights()}


@app.put("/api/admin/retrieval-weights")
async def admin_save_retrieval_weights(payload: dict):
    from pathlib import Path
    import yaml
    from text_to_sql.vector_store import reload_retrieval_weights, WEIGHTS_PATH
    data = payload.get("data") or payload
    backup = WEIGHTS_PATH.parent / "_retrieval_weights_history"
    backup.mkdir(exist_ok=True)
    if WEIGHTS_PATH.exists():
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (backup / f"retrieval_weights_{ts}.yaml.bak").write_text(
            WEIGHTS_PATH.read_text(encoding="utf-8"), encoding="utf-8",
        )
    WEIGHTS_PATH.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"data": reload_retrieval_weights()}


# ── 평가 하네스 Admin ──


class EvalRunRequest(BaseModel):
    limit: int | None = None   # 앞 N개 케이스만
    case: str | None = None    # 특정 case id만


_EVAL_FILE_RE = re.compile(r"^eval_\d{8}_\d{6}\.json$")


@app.get("/api/admin/eval/results")
async def eval_list_results():
    """평가 실행 이력 목록 (요약만, 최신순)."""
    from eval.run_eval import RESULTS_DIR

    items = []
    if RESULTS_DIR.exists():
        for p in sorted(RESULTS_DIR.glob("eval_*.json"), reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                items.append({
                    "file": p.name,
                    "config": data.get("config", {}),
                    "summary": data.get("summary", {}),
                })
            except (json.JSONDecodeError, OSError):
                continue
    return {"items": items}


@app.get("/api/admin/eval/results/{filename}")
async def eval_get_result(filename: str):
    """평가 실행 상세 (케이스별 결과 포함)."""
    from eval.run_eval import RESULTS_DIR

    if not _EVAL_FILE_RE.match(filename):
        raise HTTPException(status_code=400, detail="잘못된 파일명")
    p = RESULTS_DIR / filename
    if not p.exists():
        raise HTTPException(status_code=404, detail="결과 없음")
    return json.loads(p.read_text(encoding="utf-8"))


@app.post("/api/admin/eval/run/stream")
async def eval_run_stream(req: EvalRunRequest):
    """평가를 SSE로 실행 — 케이스별 진행 상황을 실시간 전송."""

    def generate():
        from datetime import datetime

        import yaml

        from config import get_llm_settings
        _llm = get_llm_settings()
        from eval.run_eval import GOLDEN_PATH, RESULTS_DIR, evaluate_case

        cases = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
        if req.case:
            cases = [c for c in cases if c["id"] == req.case]
        if req.limit:
            cases = cases[: req.limit]

        config_snapshot = {
            "model": _llm["MODEL_SQL_GEN"],
            "effort": _llm["SQL_GEN_EFFORT"],
            "agentic": _llm["AGENTIC_SQL"],
            "started_at": datetime.now().isoformat(),
        }
        yield sse_event("progress", {"phase": "start", "config": config_snapshot, "total": len(cases)})

        results = []
        try:
            for i, case in enumerate(cases, 1):
                yield sse_event("progress", {
                    "phase": "case_start", "index": i, "total": len(cases),
                    "id": case["id"], "question": case["question"],
                })
                r = evaluate_case(case, app.state.db, agentic=_llm["AGENTIC_SQL"])
                results.append(r)
                yield sse_event("progress", {
                    "phase": "case_done", "index": i, "total": len(cases), "result": r,
                })
        except Exception as e:
            yield sse_event("error", {"message": f"평가 중단: {e}"})
            return

        passed = sum(1 for r in results if r["passed"])
        gen_times = [r["gen_seconds"] for r in results if r["gen_seconds"]]
        costs = [r["cost_usd"] for r in results if r["cost_usd"]]
        summary = {
            "accuracy": round(passed / len(results), 3) if results else 0,
            "passed": passed,
            "total": len(results),
            "avg_gen_seconds": round(sum(gen_times) / len(gen_times), 1) if gen_times else None,
            "total_cost_usd": round(sum(costs), 4) if costs else None,
        }

        RESULTS_DIR.mkdir(exist_ok=True)
        fname = f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        (RESULTS_DIR / fname).write_text(
            json.dumps({"config": config_snapshot, "summary": summary, "results": results},
                       ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        yield sse_event("progress", {"phase": "summary", "summary": summary, "file": fname})
        yield sse_event("done", {"file": fname})

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/admin/logs")
async def get_recent_logs(limit: int = 50):
    from pathlib import Path
    from config import LOG_DIR

    log_file = Path(LOG_DIR) / "pipeline.log"
    if not log_file.exists():
        return {"logs": []}

    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    return {"logs": lines[-limit:]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=API_HOST, port=API_PORT, reload=True)
