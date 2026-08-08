"""
SQL 오류 자동 수정.
실행 실패한 SQL + 에러 메시지를 가벼운 모델에 보내 수정한다.
"""

import json
import re

import anthropic

from config import ANTHROPIC_API_KEY, MOCK_DB, get_llm
from logger import QueryTracer, pipeline_logger


def _model() -> str:
    """SQL 수정은 가벼운 모델로 처리 (관리자 설정에서 변경 가능)."""
    return get_llm("MODEL_FIX")

BLOCKED_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

FIX_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {"type": "string", "description": "수정된 실행 가능한 SELECT SQL"},
    },
    "required": ["sql"],
    "additionalProperties": False,
}

FIX_SYSTEM_PROMPT = f"""당신은 SQL 디버거입니다. 실행 실패한 SQL과 에러 메시지를 보고 SQL을 수정합니다.

현재 DB 환경: {"SQLite (Mock 모드)" if MOCK_DB else "Oracle"}

규칙:
- 수정된 SQL만 반환 (설명 없이, 코드 블록 없이, 순수 SQL만)
- SELECT만 허용
- 원래 의도를 유지하면서 문법 오류만 수정
{"- SQLite 문법 기준으로 수정 (EXTRACT 대신 strftime, SYSDATE 대신 date('now'), TO_CHAR 대신 strftime 사용)" if MOCK_DB else "- Oracle SQL 문법 기준으로 수정"}
{"- SQLite에서는 EXTRACT(HOUR FROM ...) 사용 불가. CAST(strftime('%H', col) AS INTEGER) 사용" if MOCK_DB else ""}
{"- SQLite에서는 타임스탬프 빼기 연산 불가. strftime으로 시간 차이 계산" if MOCK_DB else ""}
"""


def fix_sql(
    original_sql: str,
    error_message: str,
    tracer: QueryTracer | None = None,
) -> str | None:
    """
    오류가 난 SQL을 수정한다.
    Returns: 수정된 SQL 또는 None (수정 실패 시)
    """
    user_message = f"""[실행 실패한 SQL]
{original_sql}

[에러 메시지]
{error_message}

위 SQL을 수정해주세요."""

    if tracer:
        tracer.log_step("sql_fix_request", {
            "original_sql": original_sql,
            "error": error_message,
            "model": _model(),
        })

    try:
        response = client.messages.create(
            model=_model(),
            max_tokens=2000,
            system=FIX_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            output_config={"format": {"type": "json_schema", "schema": FIX_OUTPUT_SCHEMA}},
        )

        raw = next((b.text for b in response.content if b.type == "text"), "")
        fixed = json.loads(raw)["sql"].strip()

        if BLOCKED_KEYWORDS.search(fixed):
            pipeline_logger.warning(f"수정된 SQL에 DML 키워드 감지: {fixed[:100]}")
            return None

        if tracer:
            from ui_engine.cost_calculator import calculate_cost
            cost = calculate_cost(_model(), response.usage.input_tokens, response.usage.output_tokens)
            tracer.log_step("sql_fix_response", {
                "fixed_sql": fixed,
                "model": _model(),
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                "cost": cost,
            })

        return fixed
    except Exception as e:
        pipeline_logger.warning(f"SQL 수정 실패: {e}")
        if tracer:
            tracer.log_step("sql_fix_error", {"error": str(e)})
        return None
