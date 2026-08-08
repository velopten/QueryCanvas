"""
질문 분류기.
현재 데이터로 답변 가능한 꼬리질문인지, 새 SQL이 필요한 자식질문인지 판단한다.
비용 절약을 위해 경량 모델 사용. 분류 출력은 structured output(json_schema)으로 보장.
"""

import json

import anthropic

from config import ANTHROPIC_API_KEY, get_llm
from logger import QueryTracer

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _model() -> str:
    return get_llm("MODEL_CLASSIFY")


def _extract_text(response) -> str:
    """content 블록에서 text 블록을 찾는다."""
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


CLASSIFY_PROMPT = """당신은 질문 분류기입니다. 사용자의 후속 질문이 아래 두 유형 중 어디에 해당하는지 판단합니다.

## 유형 A: 텍스트 답변 (tail)
현재 데이터에서 바로 답할 수 있는 질문. 새로운 DB 조회가 필요 없음.
예시:
- "가장 값이 큰 항목은?" → 데이터에서 바로 확인 가능
- "비율이 30% 넘는 항목이 있어?" → 데이터에서 바로 확인 가능
- "이 중에서 값이 0인 건 뭐야?" → 데이터에서 바로 확인 가능
- "합계가 얼마야?" → 데이터에서 바로 계산 가능

## 유형 B: 데이터 조회 (child)
새로운 SQL을 실행하고 시각화가 필요한 질문. 현재 데이터에 없는 정보를 요구함.
예시:
- "그 그룹의 항목별 상세 보여줘" → 새로운 데이터 조회 필요
- "월별 추이로 보여줘" → 다른 기준의 조회 필요
- "관련된 다른 지표도 같이 보여줘" → 다른 테이블 조회 필요
"""

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["tail", "child"]},
    },
    "required": ["type"],
    "additionalProperties": False,
}


def classify_question(
    question: str,
    current_data: list[dict],
    current_summary: str,
    tracer: QueryTracer | None = None,
) -> str:
    """
    질문을 분류한다.
    Returns: "tail" (텍스트 답변) 또는 "child" (새 데이터 조회)
    """
    columns = list(current_data[0].keys()) if current_data else []
    sample = current_data[:5]

    user_msg = f"""[현재 데이터 컬럼] {', '.join(columns)}
[현재 데이터 행수] {len(current_data)}
[현재 데이터 요약] {current_summary}
[샘플 데이터] {json.dumps(sample, ensure_ascii=False, default=str)[:500]}

[사용자 후속 질문] {question}"""

    try:
        response = client.messages.create(
            model=_model(),
            max_tokens=50,
            system=CLASSIFY_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            output_config={"format": {"type": "json_schema", "schema": CLASSIFY_SCHEMA}},
        )
        result = json.loads(_extract_text(response))
        q_type = result.get("type", "child")

        if tracer:
            tracer.log_step("question_classified", {
                "question": question,
                "type": q_type,
                "model": _model(),
                "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
            })

        return q_type
    except anthropic.APIStatusError as e:
        if tracer:
            tracer.log_step("classify_api_error", {"status": e.status_code, "error": str(e)})
        return "child"  # 분류 실패 시 안전하게 자식질문으로
    except Exception as e:
        if tracer:
            tracer.log_step("classify_error", {"error": str(e)})
        return "child"


PREFILTER_PROMPT = """당신은 자연어 데이터 조회 시스템의 사전 분류기입니다.
사용자의 새 질문에서 모호성 여부와 엔티티를 추출합니다.

판단 규칙:
- 개인 이름·그룹명이 등장하지만 식별자(ID)가 명시되어 있지 않으면 needs_disambiguation=true 이고 missing 에 person/group 추가
- 형식 `식별자(이름)` (예: "C00231(김민준)") 처럼 ID가 동반되면 needs_disambiguation=false
- 기간이 전혀 없는데 광범위한 집계 질문(예: "전체 실적")이면 missing 에 "range" 추가
- 단순 집계나 카운트 등 식별자가 필요 없는 질문이면 needs_disambiguation=false, missing=[]
- date_hint 는 질문의 기간 표현을 자연어 그대로 (예: "이번달", "작년", "2024-01~2024-03"). 없으면 null."""

PREFILTER_SCHEMA = {
    "type": "object",
    "properties": {
        "needs_disambiguation": {"type": "boolean"},
        "missing": {
            "type": "array",
            "items": {"type": "string", "enum": ["person", "group", "range"]},
        },
        "extracted": {
            "type": "object",
            "properties": {
                "names": {"type": "array", "items": {"type": "string"}},
                "groups": {"type": "array", "items": {"type": "string"}},
                "date_hint": {"type": ["string", "null"]},
            },
            "required": ["names", "groups", "date_hint"],
            "additionalProperties": False,
        },
    },
    "required": ["needs_disambiguation", "missing", "extracted"],
    "additionalProperties": False,
}

_PREFILTER_FALLBACK = {
    "needs_disambiguation": False,
    "missing": [],
    "extracted": {"names": [], "groups": [], "date_hint": None},
}


def prefilter_question(question: str, tracer: QueryTracer | None = None) -> dict:
    """질문 사전 분석: 모호성 판단 + 엔티티 추출 (경량 모델 1콜, 스키마 보장)."""
    try:
        response = client.messages.create(
            model=_model(),
            max_tokens=300,
            system=PREFILTER_PROMPT,
            messages=[{"role": "user", "content": question}],
            output_config={"format": {"type": "json_schema", "schema": PREFILTER_SCHEMA}},
        )
        result = json.loads(_extract_text(response))
        if tracer:
            tracer.log_step("prefilter_result", {"question": question, "result": result})
        return result
    except Exception as e:
        if tracer:
            tracer.log_step("prefilter_error", {"error": str(e)})
        return dict(_PREFILTER_FALLBACK)


CLARIFY_PROMPT = """당신은 데이터 조회 시스템의 질문 검토자입니다. 사용자의 새 질문이 SQL로 조회 가능한 수준으로
구체적인지 판단합니다. **매우 보수적으로** — 대부분의 질문은 그대로 진행(needs_clarification=false)해야 합니다.

되물어야 하는 경우 (이때만 true):
- 조회 대상 자체가 불명확 (예: "그거 정리해줘", "현황 보여줘" — 무엇의 현황인지 없음)
- 핵심 축이 빠져 결과가 무의미해질 광범위 질문 (예: "전체 데이터 다 보여줘")

되묻지 않는 경우 (false):
- 기간이 없어도 합리적 기본값(최근/이번 달)으로 조회 가능한 질문
- 특정 이름/카테고리가 모호해도 시스템이 후보 조회로 해결 가능
- 집계 기준이 여러 개 가능해도 대표적인 해석이 있는 질문

question_to_user는 한 문장, 선택지를 2~3개 제시하는 짧은 되물음으로."""

CLARIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "needs_clarification": {"type": "boolean"},
        "question_to_user": {"type": "string", "description": "되물을 한 문장 (불필요하면 빈 문자열)"},
    },
    "required": ["needs_clarification", "question_to_user"],
    "additionalProperties": False,
}


def clarify_check(question: str, tracer: QueryTracer | None = None) -> dict:
    """신규 질문이 조회 가능한 수준인지 검토. 모호하면 되물을 질문을 반환.

    실패/예외 시 항상 진행(needs=False) — 되묻기는 부가 기능이지 게이트가 아님.
    """
    try:
        response = client.messages.create(
            model=_model(),
            max_tokens=200,
            system=CLARIFY_PROMPT,
            messages=[{"role": "user", "content": f"[질문] {question}"}],
            output_config={"format": {"type": "json_schema", "schema": CLARIFY_SCHEMA}},
        )
        result = json.loads(_extract_text(response))
        if tracer:
            tracer.log_step("clarify_check", {
                "question": question,
                "needs": result.get("needs_clarification"),
                "ask": result.get("question_to_user"),
            })
        return result
    except Exception as e:
        if tracer:
            tracer.log_step("clarify_check_error", {"error": str(e)})
        return {"needs_clarification": False, "question_to_user": ""}


def answer_from_data(
    question: str,
    current_data: list[dict],
    current_summary: str,
    tracer: QueryTracer | None = None,
) -> str:
    """현재 데이터를 기반으로 텍스트 답변을 생성한다. 개인정보는 매핑 키로 대체 후 복원."""
    from ui_engine.anonymizer import anonymize_with_mapping, restore_from_mapping

    anonymized, pii_mapping = anonymize_with_mapping(current_data[:20])

    pii_note = ""
    if pii_mapping:
        pii_note = "\n개인정보는 매핑 키([PERSON_1] 등)로 대체되어 있습니다. 답변에서 특정 개인을 언급할 때 매핑 키를 그대로 사용하세요."

    user_msg = f"""[데이터]
{json.dumps(anonymized, ensure_ascii=False, default=str)}

[데이터 요약] {current_summary}

[질문] {question}

위 데이터를 기반으로 간결하게 답변하세요. 데이터에서 확인할 수 있는 팩트만 답하고, 추측하지 마세요.
"# 답변" 같은 제목/헤딩을 붙이지 마세요. 바로 본문부터 시작하세요.{pii_note}"""

    if tracer:
        tracer.log_step("tail_request", {
            "question": question,
            "user_message": user_msg,
            "model": _model(),
            "pii_mapping": pii_mapping if pii_mapping else None,
            "data_rows": len(current_data),
            "anonymized_sample": anonymized[:3] if anonymized else [],
        })

    response = client.messages.create(
        model=_model(),
        max_tokens=500,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw_answer = _extract_text(response).strip()

    # 매핑 키를 원본으로 복원
    answer = restore_from_mapping(raw_answer, pii_mapping) if pii_mapping else raw_answer

    if tracer:
        from ui_engine.cost_calculator import calculate_cost
        cost = calculate_cost(_model(), response.usage.input_tokens, response.usage.output_tokens)
        tracer.log_step("tail_response", {
            "raw_answer": raw_answer,
            "restored_answer": answer if pii_mapping else None,
            "model": _model(),
            "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
            "cost": cost,
        })

    return answer
