"""
에이전틱 SQL 생성기 — tool use 루프.

기존 고정 파이프라인(prefilter → info_collector → 1-pass 생성 → 실패 시 blind fix)을
모델 주도 루프로 일반화한다. 모델이 스스로:

- search_schema:  질문과 관련된 DDL/SQL 패턴/문서를 추가 검색 (RAG 재질의)
- find_person:    개인 이름 → 식별자 후보 조회 (동명이인 확인)
- find_group:     그룹/분류명 → 식별자 후보 조회
- preview_sql:    SQL 시험 실행 (필수 필터 검증 + 가상 view 해석 + 5행 제한)

을 수행한 뒤 최종 SQL을 structured output 으로 확정한다.

설계 원칙 — 자율성은 도구 안에서, 보장은 도구 밖에서:
결정적 가드레일(sqlglot 검증, DML 차단, 가상 view 해석)은 preview_sql 도구 내부와
파이프라인 후단(main.py)에서 그대로 적용된다. 모델은 가드레일을 우회할 수 없다.

generator 로 구현 — 진행 이벤트를 yield 하고 마지막에 {"type": "done", "sql": ...} 를 낸다.
"""

import json
import re
from collections.abc import Iterator
from typing import Any

import anthropic

from config import ANTHROPIC_API_KEY, MOCK_DB, get_llm
from logger import QueryTracer, pipeline_logger
import ui_engine.prompts.loader as prompts_module
from text_to_sql.sql_generator import (
    BLOCKED_KEYWORDS,
    SQL_OUTPUT_SCHEMA,
    _build_volatile_instructions,
)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

MAX_TURNS = 8          # 도구 호출 루프 상한 (무한 루프 방지)
MAX_TOKENS = 16000
PREVIEW_ROWS = 5

# ── 도구 정의 ──

TOOLS = [
    {
        "name": "search_schema",
        "description": (
            "질문과 관련된 테이블 DDL, SQL 패턴, 비즈니스 문서를 벡터 검색한다. "
            "최초 제공된 컨텍스트에 필요한 테이블/컬럼 정보가 부족할 때 다른 키워드로 재검색하라. "
            "예: 특정 테이블명, 업무 용어."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "검색할 자연어 키워드 또는 테이블명"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "find_person",
        "description": (
            "개인 이름으로 식별자 후보를 조회한다. "
            "질문에 사람 이름이 등장하는데 식별자가 명시되지 않았으면 반드시 이 도구로 확정하라. "
            "후보가 여럿이면(동명이인) 질문 맥락으로 판단하거나, 판단 불가 시 모든 후보의 ID를 IN 절로 사용하라."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "개인 이름"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "find_group",
        "description": (
            "그룹/분류명(부서·카테고리·상품군 등)으로 식별자 후보를 조회한다. "
            "질문에 그룹명이 등장하면 이름 컬럼 LIKE 비교 대신 이 도구로 ID를 확정하는 것을 우선하라."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "그룹 또는 분류 이름"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "preview_sql",
        "description": (
            "SQL을 5행 제한으로 시험 실행한다. 필수 필터 검증과 가상 view 해석이 자동 적용된다. "
            "최종 SQL을 확정하기 전에 반드시 1회 실행해서 문법 오류와 결과 형태를 확인하라. "
            "오류가 반환되면 오류 메시지를 근거로 SQL을 수정해 다시 시도하라."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "시험 실행할 SELECT SQL"},
            },
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
]

AGENT_ADDENDUM = """

## 작업 방식 (도구 사용)
당신에게는 search_schema / find_person / find_group / preview_sql 도구가 있습니다.

1. 제공된 컨텍스트로 부족하면 search_schema 로 추가 검색하세요.
2. 질문에 사람 이름/그룹명이 있는데 ID가 없으면 find_person / find_group 으로 ID를 확정하세요.
   이름 컬럼 등호/LIKE 필터보다 ID 필터가 항상 우선입니다.
3. SQL 초안이 서면 preview_sql 로 시험 실행하세요. 오류면 수정 후 재시도하세요.
4. preview 가 성공하면 최종 응답으로 SQL을 확정하세요.

최종 응답은 {"sql": "..."} JSON 하나만 출력합니다. preview_sql 에 넣었던 원본 SQL을
그대로 확정하면 됩니다 (필수 필터 주입/가상 view 해석은 시스템이 실행 직전 자동 적용)."""


# ── 도구 구현 ──


def _tool_search_schema(query: str) -> str:
    from text_to_sql.vector_store import vector_store

    ctx = vector_store.search(query)
    parts = []
    for kind, label in [
        ("ddl", "DDL"), ("sql", "SQL 패턴"), ("doc", "문서"),
        ("doc_overlay", "운영자 지식"), ("virtual_view", "가상 View"),
    ]:
        items = ctx.get(kind) or []
        for it in items:
            parts.append(f"[{label}] {it['content']}")
    if not parts:
        return "검색 결과 없음 — 다른 키워드로 재시도하거나 제공된 컨텍스트만으로 작성하세요."
    text = "\n\n".join(parts)
    return text[:8000]  # 컨텍스트 폭주 방지


def _tool_find_entity(db: Any, kind: str, name: str) -> str:
    from ui_engine.info_collector import collect

    extracted = {"names": [name]} if kind == "person" else {"groups": [name]}
    groups = collect(db, extracted)
    if not groups or not groups[0].candidates:
        return f"'{name}' 후보 없음. 이름 표기를 바꿔 재시도하거나, 없으면 이름 컬럼 LIKE 검색으로 대체하세요."
    rows = groups[0].candidates[:10]
    return json.dumps({"candidates": rows, "count": len(groups[0].candidates)}, ensure_ascii=False, default=str)


def _tool_preview_sql(db: Any, sql: str, dialect: str) -> str:
    from text_to_sql.sql_validator import validate_sql
    from text_to_sql.virtual_view_resolver import resolve as vv_resolve
    from ui_engine.anonymizer import anonymize_with_mapping

    if BLOCKED_KEYWORDS.search(sql):
        return "거부: SELECT만 허용됩니다. DML/DDL 키워드가 감지되었습니다."

    vres = validate_sql(sql, dialect=dialect)
    if not vres.ok:
        return f"안전성 검증 실패: {'; '.join(vres.errors)}"
    resolved_sql = sql

    vres2 = vv_resolve(resolved_sql, dialect=dialect)
    if vres2.errors:
        return f"가상 view 해석 실패: {'; '.join(vres2.errors)}"
    if vres2.resolved:
        resolved_sql = vres2.sql

    exec_sql = resolved_sql.rstrip().rstrip(";")
    if dialect == "sqlite":
        wrapped = f"SELECT * FROM ({exec_sql}) LIMIT {PREVIEW_ROWS}"
    else:
        wrapped = f"SELECT * FROM ({exec_sql}) WHERE ROWNUM <= {PREVIEW_ROWS}"

    try:
        rows = db.execute(wrapped)
    except Exception as e:
        return f"실행 오류: {e}"

    masked, _ = anonymize_with_mapping(rows)  # preview 데이터도 PII 마스킹 후 모델에 노출
    info = []
    if vres.injected:
        info.append(f"자동 주입된 필수 필터: {', '.join(vres.injected)}")
    if vres2.resolved:
        info.append(f"가상 view 해석됨: {', '.join(vres2.resolved)}")
    info.append(f"컬럼: {', '.join(rows[0].keys()) if rows else '(0행)'}")
    info.append(f"샘플 ({len(masked)}행, 최대 {PREVIEW_ROWS}): {json.dumps(masked, ensure_ascii=False, default=str)[:2000]}")
    return "실행 성공\n" + "\n".join(info)


def _mark_cache_breakpoint(messages: list[dict]) -> None:
    """루프 대화 프리픽스 캐싱 — 마지막 user 메시지 끝에 breakpoint를 이동시킨다.

    시스템 블록만 캐시하면 턴마다 RAG 컨텍스트+대화 이력이 정가로 재과금된다
    (실측: 3턴 쿼리에서 입력 19k 토큰 무캐시). breakpoint를 매 턴 앞으로 옮기면
    턴 2+의 이전 프리픽스가 90% 할인 cache read로 바뀐다.
    요청당 breakpoint 4개 제한 — 이전 마커를 지우고 [시스템 1 + 메시지 1]만 유지.
    """
    for m in messages:
        if m.get("role") != "user":
            continue  # assistant content는 SDK 객체 — 건드리지 않음
        c = m["content"]
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict):
                    b.pop("cache_control", None)
    last = messages[-1]
    if last.get("role") != "user":
        return
    c = last["content"]
    if isinstance(c, str):
        last["content"] = [{"type": "text", "text": c, "cache_control": {"type": "ephemeral"}}]
    elif isinstance(c, list) and c and isinstance(c[-1], dict):
        c[-1]["cache_control"] = {"type": "ephemeral"}


# ── 에이전트 루프 ──


def generate_sql_agentic(
    question: str,
    context: dict,
    db: Any,
    tracer: QueryTracer | None = None,
    previous_sql: str | None = None,
    previous_summary: str | None = None,
    resolved_context: dict | None = None,
) -> Iterator[dict]:
    """
    Tool use 루프로 SQL을 생성한다.

    Yields:
      {"type": "status", "message": str}      — 진행 상황 (SSE step 용)
      {"type": "tool", "name", "summary"}     — 도구 호출 알림
      {"type": "done", "sql": str}            — 최종 SQL
      {"type": "error", "message": str}       — 실패
    """
    dialect = "sqlite" if MOCK_DB else "oracle"

    # 초기 컨텍스트 조합 (generate_sql 과 동일 형식)
    parts = []
    if previous_sql:
        parts.append(f"[이전 SQL (참고용)]\n{previous_sql}")
    if previous_summary:
        parts.append(f"[이전 결과 요약]\n{previous_summary}")
    for kind, label in [
        ("ddl", "참고 DDL"), ("sql", "참고 SQL 패턴"), ("doc", "비즈니스 문서"),
        ("doc_overlay", "운영자 추가 지식"), ("doc_patch", "기존 청크 보강"),
        ("virtual_view", "가상 View 카탈로그 — 우선 사용"),
    ]:
        items = context.get(kind) or []
        if items:
            body = "\n\n".join(it["content"] for it in items)
            parts.append(f"[{label}]\n{body}")
    if resolved_context:
        parts.append(
            "[사전 확정 컨텍스트] 사용자가 확정한 식별자 — WHERE 절에 그대로 사용:\n"
            + json.dumps(resolved_context, ensure_ascii=False)
        )
    user_message = "\n\n".join(parts) + f"\n\n[질문] {question}"

    # 시스템 프롬프트: 안정 블록(도메인 규약 + 에이전트 지침, 캐시) + 휘발 블록
    stable_prompt = prompts_module.SQL_SYSTEM_PROMPT + AGENT_ADDENDUM
    volatile_prompt = _build_volatile_instructions()
    # 1h TTL: 개인 데모의 산발 사용 패턴에서 5분 TTL은 대부분 만료 → 미스 요금.
    # write 2x여도 세션 내 재사용으로 순이득 (docs 참고: extended cache TTL)
    system_blocks = [
        {"type": "text", "text": stable_prompt, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    ]
    if volatile_prompt:
        system_blocks.append({"type": "text", "text": volatile_prompt})

    model = get_llm("MODEL_SQL_GEN")
    effort = get_llm("SQL_GEN_EFFORT")

    output_config: dict = {"format": {"type": "json_schema", "schema": SQL_OUTPUT_SCHEMA}}
    if effort and not model.startswith("claude-haiku"):
        output_config["effort"] = effort

    messages: list[dict] = [{"role": "user", "content": user_message}]
    total_usage = {"input_tokens": 0, "output_tokens": 0,
                   "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    tool_call_log: list[dict] = []

    if tracer:
        tracer.log_step("sql_agent_start", {
            "model": model,
            "effort": output_config.get("effort"),
            "user_message": user_message,
            "tools": [t["name"] for t in TOOLS],
        })

    for turn in range(1, MAX_TURNS + 1):
        _mark_cache_breakpoint(messages)
        try:
            response = client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=system_blocks,
                tools=TOOLS,
                messages=messages,
                output_config=output_config,
            )
        except anthropic.APIStatusError as e:
            yield {"type": "error", "message": f"AI 호출 실패 ({e.status_code}): {getattr(e, 'message', e)}"}
            return

        for k in total_usage:
            total_usage[k] += getattr(response.usage, k, 0) or 0

        if response.stop_reason == "max_tokens":
            yield {"type": "error", "message": "SQL 생성 응답이 토큰 한도에서 잘렸습니다."}
            return
        if response.stop_reason == "refusal":
            yield {"type": "error", "message": "모델이 이 요청을 처리할 수 없다고 판단했습니다."}
            return

        if response.stop_reason == "tool_use":
            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            messages.append({"role": "assistant", "content": response.content})

            results = []
            for tb in tool_blocks:
                name, tool_input = tb.name, tb.input
                summary = _summarize_call(name, tool_input)
                yield {"type": "tool", "name": name, "summary": summary}

                try:
                    if name == "search_schema":
                        result = _tool_search_schema(tool_input["query"])
                    elif name == "find_person":
                        result = _tool_find_entity(db, "person", tool_input["name"])
                    elif name == "find_group":
                        result = _tool_find_entity(db, "group", tool_input["name"])
                    elif name == "preview_sql":
                        result = _tool_preview_sql(db, tool_input["sql"], dialect)
                    else:
                        result = f"알 수 없는 도구: {name}"
                except Exception as e:
                    pipeline_logger.exception(f"도구 {name} 실행 오류")
                    result = f"도구 실행 오류: {e}"

                tool_call_log.append({"turn": turn, "tool": name, "input": tool_input, "result": result[:1000]})
                results.append({"type": "tool_result", "tool_use_id": tb.id, "content": result})

            messages.append({"role": "user", "content": results})
            continue

        # end_turn — 최종 SQL 파싱
        raw = next((b.text for b in response.content if b.type == "text"), "").strip()
        if tracer:
            tracer.log_step("sql_agent_done", {
                "turns": turn,
                "tool_calls": tool_call_log,
                "raw_response": raw,
                "usage": total_usage,
                "stop_reason": response.stop_reason,
            })
        try:
            parsed = json.loads(raw)
            sql = parsed["sql"].strip()
            promoted_filters = [
                f for f in (parsed.get("promoted_filters") or [])
                if isinstance(f, dict) and f.get("column") and f.get("value")
            ]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            yield {"type": "error", "message": f"SQL 응답 파싱 실패: {e}"}
            return

        # 최종 가드: DML 차단 (후단 validator 가 한 번 더 검증)
        if BLOCKED_KEYWORDS.search(sql):
            if tracer:
                tracer.log_step("sql_blocked", {"sql": sql, "reason": "DML/DDL 키워드 감지"})
            yield {"type": "error", "message": "읽기 전용 쿼리만 허용됩니다."}
            return

        yield {"type": "done", "sql": sql, "promoted_filters": promoted_filters,
               "turns": turn, "tool_calls": len(tool_call_log), "usage": total_usage}
        return

    # MAX_TURNS 초과
    if tracer:
        tracer.log_step("sql_agent_max_turns", {"tool_calls": tool_call_log, "usage": total_usage})
    yield {"type": "error", "message": f"SQL 확정 실패 — 도구 호출 한도({MAX_TURNS}턴) 초과"}


def _summarize_call(name: str, tool_input: dict) -> str:
    if name == "search_schema":
        return f"스키마 추가 검색: \"{tool_input.get('query', '')[:40]}\""
    if name == "find_person":
        return f"개인 후보 조회: {tool_input.get('name', '')}"
    if name == "find_group":
        return f"그룹 후보 조회: {tool_input.get('name', '')}"
    if name == "preview_sql":
        return "SQL 시험 실행 (5행 제한)"
    return name
