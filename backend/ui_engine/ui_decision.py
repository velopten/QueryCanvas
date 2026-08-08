"""
UI 결정 엔진 — A2UI v0.9 메시지 스트리밍, 2단계 분할.

스테이지① plan_layout (t=0, SQL 생성과 병렬, 경량 모델):
  질문만 보고 {title, expect_chart, expect_filter}를 구조화 출력 →
  서버가 스켈레톤 updateComponents를 결정적으로 생성해 즉시 렌더.

스테이지② decide_ui_stream (SQL 실행 후):
1. 결과 스키마 + PII 값이 제외된 샘플을 프롬프트에 전달 (rows 본문은 LLM 미경유
   — 클라이언트가 /rows에 직주입하므로 가역 마스킹/복원이 불필요해짐)
2. LLM이 <a2ui-json>[createSurface, updateComponents...] 를 스트리밍 출력
3. SDK 파서(process_chunk)가 검증된 메시지를 증분 방출 (불완전 JSON은 자동 힐링)
4. 서버가 updateComponents만 걸러 yield → main.py에서 SSE 'a2ui' 이벤트
5. 스켈레톤과 같은 id(briefing/main_chart/data_table)를 재사용해 갱신

계약 (frontend/src/lib/a2ui/catalog.tsx 와 공유):
- surfaceId "result", 데이터 모델 /rows·/filters·/meta/loading, root 컴포넌트 id "root"
"""

import json
import re
from collections.abc import Iterator

import anthropic

from config import ANTHROPIC_API_KEY, get_llm
from logger import QueryTracer, pipeline_logger
from ui_engine.anonymizer import get_pii_columns
from ui_engine.a2ui_catalog import SURFACE_ID, get_stable_schema_prompt, new_format
import ui_engine.prompts.loader as prompts_module

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# 프롬프트 allowed_components와 별개로 서버에서 한 번 더 거르는 안전망
_DISALLOWED_TYPES = {
    "TextField", "CheckBox", "ChoicePicker", "Slider", "DateTimeInput",
    "Button", "Modal", "Video", "AudioPlayer", "Image",
    "Tabs", "List", "Icon",  # 카탈로그 다이어트로 제외됨
}

_CONTAINER_CHILD_KEYS = ("children",)


# ── 스테이지①: 레이아웃 플랜 (t=0 즉시, LLM 미경유) ──────────────────────────
# 처음엔 경량 LLM 플랜이었으나 실측 결과 호출 지연(~3s) + sync generator의 yield
# 타이밍 의존으로 방출이 7초대까지 밀려서, 결정적 휴리스틱으로 교체했다.
# 차트 여부가 틀려도 스테이지②가 교정하므로 (shimmer가 사라지는 정도) 리스크 없음.

_NO_CHART_RE = re.compile(r"목록|명단|상세|내역|이력|정보|누구|언제|알려줘\s*$")
_CHART_RE = re.compile(r"현황|추이|비교|통계|분포|비율|순위|평균|합계|건수|얼마나|몇\s|top|TOP|[가-힣]+별")


def plan_layout(question: str, tracer: QueryTracer | None = None) -> dict:
    """질문 키워드만으로 스켈레톤 레이아웃 결정 (즉시 반환)."""
    has_chart_signal = bool(_CHART_RE.search(question))
    has_detail_signal = bool(_NO_CHART_RE.search(question))
    expect_chart = has_chart_signal or not has_detail_signal
    title = question.strip()
    if len(title) > 30:
        title = title[:29] + "…"
    plan = {"title": title, "expect_chart": expect_chart}
    if tracer:
        tracer.log_step("ui_layout_planned", {"plan": plan, "method": "heuristic"})
    return plan


def build_skeleton_messages(plan: dict) -> list[dict]:
    """플랜 → 즉시 렌더 가능한 스켈레톤 updateComponents (서버 결정적 생성 — LLM 미경유).

    스테이지②가 같은 id(briefing/main_chart/data_table)를 갱신하고 root children을
    최종 구성으로 교체한다. loading 바인딩(/meta/loading)으로 shimmer 표시.
    """
    children = ["briefing"]
    components: list[dict] = [
        {"id": "briefing", "component": "BriefingCard", "headline": plan.get("title") or "조회 결과"},
    ]
    if plan.get("expect_chart"):
        children.append("main_chart")
        # rows 바인딩 없이 loading만 — 데이터 도착 전 자동 차트 오작동 방지, shimmer만 표시
        components.append({
            "id": "main_chart", "component": "Chart", "chartType": "bar",
            "loading": {"path": "/meta/loading"},
        })
    children.append("data_table")
    components.append({
        "id": "data_table", "component": "DataTable",
        "rows": {"path": "/rows"}, "loading": {"path": "/meta/loading"},
    })
    components.insert(0, {"id": "root", "component": "Column", "children": children})
    return [{
        "version": "v0.9",
        "updateComponents": {"surfaceId": SURFACE_ID, "components": components},
    }]


def decide_ui_stream(
    question: str,
    sql: str,
    data: list[dict],
    tracer: QueryTracer | None = None,
    catalog_prompt: str = "",  # deprecated — 카탈로그는 백엔드 소유 (하위호환 시그니처 유지)
    skeleton: list[dict] | None = None,  # 스테이지①이 이미 방출한 스켈레톤 메시지
    promoted_filters: list[dict] | None = None,  # SQL 에이전트가 UI 필터로 승격한 범주 조건
) -> Iterator[dict]:
    """
    Generator. 각 yield는 다음 중 하나:
    - {"event": "a2ui", "messages": [<검증된 A2UI 메시지>...]}
    - {"event": "spec_done", "spec": {"format": "a2ui", "messages": [...]}, "raw": str}
    - {"event": "error", "message": str}
    """
    if not data:
        empty = _empty_ui("조건에 맞는 데이터가 없습니다.")
        if tracer:
            tracer.log_step("ui_decision_skip", {"reason": "데이터 없음", "spec": empty})
        yield {"event": "a2ui", "messages": empty["messages"]}
        yield {"event": "spec_done", "spec": empty, "raw": ""}
        return

    columns = list(data[0].keys())
    total_rows = len(data)

    # PII 처리: rows 본문이 LLM을 거치지 않으므로 가역 마스킹/복원 대신 값 자체를 제외
    # (컬럼 존재는 알려야 Filter/xField 선택이 가능 — 값만 "(비공개)")
    pii_cols = get_pii_columns(data)
    sample = [
        {col: ("(비공개)" if col in pii_cols else val) for col, val in row.items()}
        for row in data[:5]  # 형태 파악용 — 5행이면 충분 (토큰 절약)
    ]

    if tracer and pii_cols:
        tracer.log_step("pii_excluded", {
            "pii_columns": pii_cols,
            "note": "UI 결정 샘플에서 PII 값 제외 — rows 본문은 LLM 미경유, 클라이언트 직주입",
        })

    pii_instruction = ""
    if pii_cols:
        pii_instruction = (
            f"\n[개인정보 컬럼] {', '.join(pii_cols)} — 샘플에서 값이 제외되어 있습니다."
            " BriefingCard의 headline/bullets/note에 개인 이름/식별자를 절대 쓰지 마세요 (집계 수치만)."
        )

    # 필터 승격 — SQL 에이전트가 WHERE 대신 UI 필터로 넘긴 조건을 초기 선택값으로
    filter_instruction = ""
    if promoted_filters:
        default_value = {f["column"]: f["value"] for f in promoted_filters}
        filter_instruction = (
            f"\n[승격된 필터 — 반드시 반영] {json.dumps(default_value, ensure_ascii=False)}"
            f"\nFilter 컴포넌트를 포함하세요: columns에 {list(default_value.keys())} 포함,"
            f" defaultValue를 위 값 그대로 설정. Chart/DataTable에 filters: {{\"path\": \"/filters\"}} 바인딩 연결."
            " 사용자 질문은 이 값 기준이지만 SQL은 전체 범주를 조회했으므로,"
            " BriefingCard 인사이트는 필터 값 기준으로 서술하세요."
        )

    # 스테이지① 스켈레톤 컨텍스트 — 같은 id를 재사용해 화면 깜빡임 없이 갱신
    skeleton_instruction = ""
    if skeleton:
        skel_comps = [
            f"{c['id']}({c['component']})"
            for m in skeleton
            for c in m.get("updateComponents", {}).get("components", [])
        ]
        skeleton_instruction = (
            f"\n[현재 화면 스켈레톤] {', '.join(skel_comps)} 가 이미 렌더링되어 있습니다."
            " 같은 id를 재사용해 내용을 갱신하고, root의 children을 최종 구성으로 다시 출력하세요."
            " 스켈레톤에 있어도 최종 화면에 불필요한 컴포넌트는 root children에서 빼면 됩니다."
        )

    user_message = f"""[사용자 질문] {question}

[실행된 SQL]
{sql}

[결과 컬럼] {', '.join(columns)}
[총 행수] {total_rows} — 전체 데이터는 데이터 모델 /rows 에 이미 주입되어 있음
{pii_instruction}{filter_instruction}{skeleton_instruction}

[샘플 데이터 (최대 5행 — 형태 참고용, 컴포넌트에 인라인 금지)]
{json.dumps(sample, ensure_ascii=False, default=str)}

surfaceId '{SURFACE_ID}' 에 대한 updateComponents 메시지를 출력하세요. root 컴포넌트 id는 'root'."""

    # 시스템 프롬프트 2단 구성 (모두 안정 — 캐시 대상):
    #   블록 1: SDK 생성 스키마/출력 계약 — 카탈로그 바뀌지 않으면 byte-identical
    #   블록 2 (캐시 breakpoint, 1h TTL): 도메인 UI 규칙 — 관리자 편집 시에만 변동
    system_blocks = [
        {"type": "text", "text": get_stable_schema_prompt()},
        {"type": "text", "text": prompts_module.UI_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}},
    ]

    model = get_llm("MODEL_UI_DECISION")

    if tracer:
        tracer.log_step("ui_decision_request", {
            "system_prompt": prompts_module.UI_SYSTEM_PROMPT,
            "user_message": user_message,
            "model": model,
            "schema_prompt_length": len(get_stable_schema_prompt()),
            "pii_columns_excluded": pii_cols,
            "skeleton_provided": bool(skeleton),
            "streaming": True,
            "protocol": "a2ui-v0.9",
        })

    parser = new_format().parser  # 요청별 fresh (파서는 stateful)
    raw_buffer = ""
    message_count = 0
    # id → 컴포넌트 정의 (최종 통합/정제용, last-write-wins).
    # 스켈레톤으로 시드 — LLM이 "재사용"하며 재출력하지 않은 컴포넌트도 최종 spec에 포함되어야 함
    components: dict[str, dict] = {}
    if skeleton:
        for m in skeleton:
            for c in m.get("updateComponents", {}).get("components", []):
                components[c["id"]] = c

    def _handle_messages(msgs: list[dict]) -> list[dict]:
        """검증된 메시지에서 updateComponents만 통과시키고 surfaceId 강제."""
        nonlocal message_count
        out = []
        for m in msgs:
            uc = m.get("updateComponents")
            if not uc:
                continue  # createSurface/updateDataModel 등은 서버 관할 — 무시
            uc["surfaceId"] = SURFACE_ID
            comps = uc.get("components") or []
            comps = [c for c in comps if c.get("component") not in _DISALLOWED_TYPES]
            comps = _remap_healing_refs(comps, set(components))
            if not comps:
                continue
            uc["components"] = comps
            for c in comps:
                components[c["id"]] = c
            message_count += 1
            out.append(m)
        return out

    try:
        with client.messages.stream(
            model=model,
            max_tokens=8000,
            system=system_blocks,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text in stream.text_stream:
                raw_buffer += text
                for part in parser.process_chunk(text):
                    if part.a2ui_json:
                        passed = _handle_messages(part.a2ui_json)
                        if passed:
                            yield {"event": "a2ui", "messages": passed}
            final = stream.get_final_message()

        from ui_engine.cost_calculator import calculate_cost
        usage = {
            "input_tokens": final.usage.input_tokens,
            "output_tokens": final.usage.output_tokens,
            "cache_creation_input_tokens": getattr(final.usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(final.usage, "cache_read_input_tokens", 0) or 0,
        }
        cost = calculate_cost(
            final.model,
            usage["input_tokens"],
            usage["output_tokens"],
            usage["cache_creation_input_tokens"],
            usage["cache_read_input_tokens"],
        )

        if final.stop_reason == "max_tokens":
            pipeline_logger.warning(
                f"UI 결정 응답이 max_tokens에서 잘림 (메시지 {message_count}개까지 수신) — UI 불완전 가능"
            )
            if tracer:
                tracer.log_step("ui_decision_truncated", {
                    "message_count": message_count,
                    "output_tokens": usage["output_tokens"],
                })

        if tracer:
            tracer.log_step("ui_decision_response", {
                "raw_response": raw_buffer,
                "usage": usage,
                "cost": cost,
                "model": final.model,
                "stop_reason": final.stop_reason,
                "message_count": message_count,
                "component_count": len(components),
            })

        # 컴포넌트가 하나도 없으면 오류 카드
        if not components:
            if tracer:
                tracer.log_step("spec_empty_after_stream", {"raw_head": raw_buffer[:500]})
            pipeline_logger.warning("A2UI 메시지에 유효 컴포넌트 없음 — 오류 카드로 대체")
            empty = _empty_ui("AI가 유효한 UI를 생성하지 못했습니다. 다시 시도해 주세요.")
            yield {"event": "a2ui", "messages": empty["messages"]}
            yield {"event": "spec_done", "spec": empty, "raw": raw_buffer}
            return

        # 후처리 1: 스트리밍 힐링이 남긴 고아 컴포넌트 정리 (loading_* 플레이스홀더 등
        # — id가 달라 last-write-wins로 덮이지 않고 root 트리 밖에 잔존)
        _prune_unreachable(components)

        # 후처리 2: Chart 규칙 (집계 SQL 아니면 제거, 2개 이상이면 첫 번째만)
        removed = _sanitize_components(components, sql, tracer)
        if removed:
            # 교정 메시지: 변경된 컨테이너 + root 재전송 (root 트리에서 빠지면 렌더 안 됨)
            corrective = {
                "version": "v0.9",
                "updateComponents": {
                    "surfaceId": SURFACE_ID,
                    "components": [components[cid] for cid in _containers_referencing(components)],
                },
            }
            yield {"event": "a2ui", "messages": [corrective]}

        # 최종 spec: 히스토리 재생용 통합 메시지 1개로 정규화
        final_spec = {
            "format": "a2ui",
            "messages": [{
                "version": "v0.9",
                "updateComponents": {
                    "surfaceId": SURFACE_ID,
                    "components": list(components.values()),
                },
            }],
        }

        if tracer:
            tracer.log_step("spec_parsed", {
                "component_count": len(components),
                "component_types": [c.get("component") for c in components.values()],
                "message_count": message_count,
                "full_spec": final_spec,
            })

        yield {"event": "spec_done", "spec": final_spec, "raw": raw_buffer}

    except Exception as e:
        pipeline_logger.exception("UI 결정 스트림 오류")
        if tracer:
            tracer.log_step("ui_decision_error", {"error": str(e)})
        yield {"event": "error", "message": str(e)}


# ── 후처리 ───────────────────────────────────────────────────────────────────

_AGG_RE = re.compile(r"\b(COUNT|SUM|AVG|MIN|MAX|GROUP\s+BY|DISTINCT)\b", re.IGNORECASE)


def _is_aggregated_sql(sql: str | None) -> bool:
    return bool(sql and _AGG_RE.search(sql))


def _sanitize_components(
    components: dict[str, dict],
    sql: str | None,
    tracer: QueryTracer | None = None,
) -> set[str]:
    """Chart 규칙 적용. components를 in-place 수정하고 제거된 id 집합을 반환."""
    chart_ids = [cid for cid, c in components.items() if c.get("component") == "Chart"]
    removed: set[str] = set()
    raw_data_chart_removed = False

    if chart_ids and not _is_aggregated_sql(sql):
        removed.update(chart_ids)  # 집계 없는 SQL → 차트 무의미
        raw_data_chart_removed = True
    elif len(chart_ids) > 1:
        removed.update(chart_ids[1:])  # 차트는 1개만

    if not removed:
        return removed

    for cid in removed:
        components.pop(cid, None)
    # 컨테이너 children에서 dangling 참조 제거
    for c in components.values():
        for key in _CONTAINER_CHILD_KEYS:
            ch = c.get(key)
            if isinstance(ch, list):
                c[key] = [x for x in ch if isinstance(x, str) and x in components]

    if tracer:
        tracer.log_step("spec_sanitized", {
            "removed_chart_ids": list(removed),
            "raw_data_chart_removed": raw_data_chart_removed,
            "after_component_count": len(components),
        })
    return removed


_LOADING_PREFIX = "loading_"


def _remap_healing_refs(comps: list[dict], known: set[str]) -> list[dict]:
    """힐링 플레이스홀더(loading_X)가 이미 알려진 X를 가리키면 원본으로 되돌린다.

    SDK 힐러는 현재 메시지 스트림만 보므로, 스켈레톤으로 이미 렌더된 컴포넌트
    (예: 데이터가 채워진 data_table)까지 loading_data_table로 치환한다 —
    그대로 두면 채워진 표가 잠깐 placeholder로 후퇴하는 깜빡임이 생긴다.
    """
    for c in comps:
        ch = c.get("children")
        if isinstance(ch, list):
            c["children"] = [
                x[len(_LOADING_PREFIX):]
                if isinstance(x, str) and x.startswith(_LOADING_PREFIX) and x[len(_LOADING_PREFIX):] in known
                else x
                for x in ch
            ]
    # 원본이 이미 알려진 loading_* 정의는 불필요 — 제거
    return [
        c for c in comps
        if not (c["id"].startswith(_LOADING_PREFIX) and c["id"][len(_LOADING_PREFIX):] in known)
    ]


def _prune_unreachable(components: dict[str, dict]) -> None:
    """root에서 도달 불가능한 컴포넌트를 제거한다 (in-place)."""
    if "root" not in components:
        return
    keep: set[str] = set()
    stack = ["root"]
    while stack:
        cid = stack.pop()
        if cid in keep or cid not in components:
            continue
        keep.add(cid)
        ch = components[cid].get("children")
        if isinstance(ch, list):
            stack.extend(x for x in ch if isinstance(x, str))
    for cid in list(components):
        if cid not in keep:
            components.pop(cid)


def _containers_referencing(components: dict[str, dict]) -> list[str]:
    """children 리스트를 가진 컨테이너 컴포넌트 id 목록 (root 포함)."""
    ids = [cid for cid, c in components.items() if isinstance(c.get("children"), list)]
    if "root" in components and "root" not in ids:
        ids.append("root")
    return ids


def _empty_ui(message: str) -> dict:
    """빈 결과/에러용 A2UI spec."""
    return {
        "format": "a2ui",
        "messages": [{
            "version": "v0.9",
            "updateComponents": {
                "surfaceId": SURFACE_ID,
                "components": [
                    {"id": "root", "component": "Column", "children": ["empty_msg"]},
                    {"id": "empty_msg", "component": "Notice", "noticeType": "info", "message": message},
                ],
            },
        }],
    }


# ── UI 수정 (화면 증분 갱신 — SQL/데이터 불변) ──────────────────────────────

def decide_ui_edit_stream(
    instruction: str,
    current_spec: dict,
    data: list[dict],
    tracer: QueryTracer | None = None,
) -> Iterator[dict]:
    """기존 A2UI 화면을 사용자 지시에 따라 수정한다.

    데이터 재조회 없음 — LLM이 현재 컴포넌트 트리를 보고 updateComponents 증분만 출력.
    같은 id 갱신이므로 프론트는 리마운트 없이 화면이 제자리에서 바뀐다.
    """
    # 현재 spec에서 컴포넌트 시드 (last-write-wins)
    components: dict[str, dict] = {}
    for m in current_spec.get("messages", []):
        for c in m.get("updateComponents", {}).get("components", []):
            components[c["id"]] = c
    if not components:
        yield {"event": "error", "message": "수정할 화면 컴포넌트가 없습니다"}
        return

    columns = list(data[0].keys()) if data else []
    user_message = f"""[현재 화면의 컴포넌트 트리 (A2UI)]
{json.dumps(list(components.values()), ensure_ascii=False)}

[결과 컬럼] {', '.join(columns)}
[총 행수] {len(data)} — 데이터는 데이터 모델 /rows 에 그대로 있음 (재조회 불가)

[사용자의 화면 수정 요청] {instruction}

요청을 반영한 updateComponents 메시지를 출력하세요.
- **components의 첫 요소는 반드시 root** (변경이 없어도 최종 children 구성 그대로 포함 — 파서 계약)
- root 다음에는 변경/추가되는 컴포넌트만 출력 (같은 id는 갱신, 나머지 기존 컴포넌트는 유지됨)
- 기존 컬럼/바인딩 범위 안에서만 수정 — 없는 컬럼을 만들지 말 것
- 첫 메시지는 createSurface (surfaceId '{SURFACE_ID}')"""

    system_blocks = [
        {"type": "text", "text": get_stable_schema_prompt()},
        {"type": "text", "text": prompts_module.UI_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}},
    ]
    model = get_llm("MODEL_UI_DECISION")

    if tracer:
        tracer.log_step("ui_edit_request", {
            "instruction": instruction,
            "component_count": len(components),
            "model": model,
        })

    parser = new_format().parser
    raw_buffer = ""
    emitted: list[dict] = []

    def _handle(msgs: list[dict]) -> list[dict]:
        out = []
        for m in msgs:
            uc = m.get("updateComponents")
            if not uc:
                continue
            uc["surfaceId"] = SURFACE_ID
            comps = [c for c in uc.get("components") or [] if c.get("component") not in _DISALLOWED_TYPES]
            comps = _remap_healing_refs(comps, set(components))
            if not comps:
                continue
            uc["components"] = comps
            for c in comps:
                components[c["id"]] = c
            out.append(m)
        return out

    try:
        with client.messages.stream(
            model=model,
            max_tokens=8000,
            system=system_blocks,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text in stream.text_stream:
                raw_buffer += text
                for part in parser.process_chunk(text):
                    if part.a2ui_json:
                        passed = _handle(part.a2ui_json)
                        if passed:
                            emitted.extend(passed)
                            yield {"event": "a2ui", "messages": passed}
            final = stream.get_final_message()

        from ui_engine.cost_calculator import calculate_cost
        usage = {
            "input_tokens": final.usage.input_tokens,
            "output_tokens": final.usage.output_tokens,
            "cache_creation_input_tokens": getattr(final.usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(final.usage, "cache_read_input_tokens", 0) or 0,
        }
        if tracer:
            tracer.log_step("ui_edit_response", {
                "raw_response": raw_buffer,
                "usage": usage,
                "cost": calculate_cost(final.model, usage["input_tokens"], usage["output_tokens"],
                                       usage["cache_creation_input_tokens"], usage["cache_read_input_tokens"]),
                "model": final.model,
                "stop_reason": final.stop_reason,
                "message_count": len(emitted),
            })

        if not emitted:
            yield {"event": "error", "message": "수정 요청을 반영한 변경이 생성되지 않았습니다. 다르게 표현해 보세요."}
            return

        _prune_unreachable(components)
        final_spec = {
            "format": "a2ui",
            "messages": [{
                "version": "v0.9",
                "updateComponents": {"surfaceId": SURFACE_ID, "components": list(components.values())},
            }],
        }
        yield {"event": "spec_done", "spec": final_spec, "raw": raw_buffer}

    except Exception as e:
        pipeline_logger.exception("UI 수정 스트림 오류")
        if tracer:
            tracer.log_step("ui_edit_error", {"error": str(e)})
        yield {"event": "error", "message": str(e)}


# ── non-streaming 래퍼 (queryExecute / rerun API용) ──

def decide_ui(
    question: str,
    sql: str,
    data: list[dict],
    tracer: QueryTracer | None = None,
    catalog_prompt: str = "",
) -> dict:
    """스트리밍 generator를 끝까지 소비하고 최종 spec만 반환."""
    final_spec: dict = _empty_ui("UI 생성 실패")
    for event in decide_ui_stream(question, sql, data, tracer, catalog_prompt):
        if event["event"] == "spec_done":
            final_spec = event["spec"]
        elif event["event"] == "error":
            return _empty_ui(event["message"])
    return final_spec
