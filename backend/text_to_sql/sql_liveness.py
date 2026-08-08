# -*- coding: utf-8 -*-
"""
저장된 뷰용 SQL 라이브 변환.

화면을 저장할 때 SQL 안의 절대 날짜 리터럴('2026-08' 등)을 실행 시점 기준
상대 표현(strftime('%Y-%m','now') 등)으로 변환한다 — 저장된 뷰를 열 때마다
"이번 달"이 자동 갱신되는 살아있는 화면이 되도록.

생성된 SQL 대부분은 이미 상대 표현을 쓰므로(changed=false) 호출은 저장 시 1회뿐.
"""

import json

import anthropic

from config import ANTHROPIC_API_KEY, get_llm
from logger import QueryTracer, pipeline_logger

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

LIVENESS_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {"type": "string", "description": "변환된 SQL (변경 없으면 원본 그대로)"},
        "changed": {"type": "boolean"},
        "note": {"type": "string", "description": "무엇을 변환했는지 한 줄 요약. 변경 없으면 빈 문자열"},
    },
    "required": ["sql", "changed", "note"],
    "additionalProperties": False,
}

_PROMPT = """당신은 SQLite SQL 변환기입니다. 저장해서 반복 실행할 SQL을 '살아있는' 형태로 만듭니다.

규칙:
- 절대 날짜 리터럴('2026-08', '2026-08-01' 등)이 질문 맥락상 "이번 달/지난달/최근 N개월/올해" 같은
  상대 의미라면 실행 시점 기준 상대 표현으로 변환:
  strftime('%Y-%m', 'now'), date('now', '-3 months'), date('now', 'start of month') 등
- 특정 시점 자체가 조회 목적인 경우(예: "2024년 1분기")는 변환하지 말 것
- SELECT 컬럼/별칭/구조는 절대 바꾸지 말 것 — 날짜 조건 표현만 변환
- 이미 상대 표현이면 changed=false로 원본 그대로 반환"""


def make_sql_live(sql: str, question: str, tracer: QueryTracer | None = None) -> tuple[str, str | None]:
    """(변환된 SQL, 변환 요약 or None) 반환. 실패 시 원본 유지."""
    try:
        response = client.messages.create(
            model=get_llm("MODEL_FIX"),
            max_tokens=1500,
            system=_PROMPT,
            messages=[{"role": "user", "content": f"[원래 질문] {question}\n\n[SQL]\n{sql}"}],
            output_config={"format": {"type": "json_schema", "schema": LIVENESS_SCHEMA}},
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        result = json.loads(text)

        if not result.get("changed"):
            if tracer:
                tracer.log_step("view_liveness_unchanged", {"sql": sql})
            return sql, None

        new_sql = result["sql"]
        # 안전망: 변환 결과가 읽기 전용 검증을 통과해야만 채택
        from text_to_sql.sql_validator import validate_sql
        from config import SQL_DIALECT
        vres = validate_sql(new_sql, dialect=SQL_DIALECT)
        if not vres.ok:
            pipeline_logger.warning(f"라이브 변환 SQL 검증 실패 — 원본 유지: {vres.errors}")
            return sql, None

        if tracer:
            tracer.log_step("view_liveness_converted", {"before": sql, "after": new_sql, "note": result.get("note")})
        return new_sql, result.get("note") or "상대 날짜 표현으로 변환됨"
    except Exception as e:
        pipeline_logger.warning(f"라이브 변환 실패 — 원본 유지: {e}")
        return sql, None
