"""
Text-to-SQL 생성기.
벡터 검색 결과 + 사용자 질문 → Claude API → SQL

- structured output(json_schema)으로 SQL만 확정적으로 수신 (코드펜스 파싱 불필요)
- 시스템 프롬프트는 [안정 블록(캐시) + 휘발 블록] 2단 구성 — prompt caching 적용
- 상위 모델의 adaptive thinking을 고려해 max_tokens 여유 확보
"""

import json
import re

import anthropic

from config import ANTHROPIC_API_KEY, get_llm
from logger import QueryTracer, pipeline_logger
import ui_engine.prompts.loader as prompts_module

BLOCKED_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# structured output 스키마 — SQL + 승격된 필터 (스키마는 캐시 키에 포함되므로 상수 고정)
SQL_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {
            "type": "string",
            "description": "실행 가능한 SELECT SQL 문 하나. 설명/마크다운 없이 순수 SQL.",
        },
        "promoted_filters": {
            "type": "array",
            "description": "WHERE 하드코딩 대신 UI 필터로 승격한 범주 조건. 없으면 빈 배열.",
            "items": {
                "type": "object",
                "properties": {
                    "column": {"type": "string", "description": "SELECT 결과 컬럼명 (별칭 기준)"},
                    "value": {"type": "string", "description": "질문이 지목한 값 (필터 초기 선택값)"},
                },
                "required": ["column", "value"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["sql", "promoted_filters"],
    "additionalProperties": False,
}

MAX_TOKENS = 16000  # adaptive thinking 토큰 포함 상한


def _extract_text(response) -> str:
    """content 블록에서 text 블록을 찾는다 (thinking 블록이 앞설 수 있음)."""
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


def _build_volatile_instructions() -> str:
    """요청마다 달라질 수 있는 지침 — 캐시 breakpoint 뒤에 붙인다."""
    parts = []

    # 큐레이터가 추가한 prompt-destination overlay 주입
    try:
        from text_to_sql.training_curator import get_prompt_addenda

        addenda = get_prompt_addenda()
        if addenda:
            directives = "\n".join(a["directive"] for a in addenda)
            parts.append(f"## 운영 규칙 (큐레이터 등록)\n{directives}")
    except Exception as e:
        pipeline_logger.debug(f"prompt addenda 로드 실패: {e}")

    return "\n\n".join(parts)


def generate_sql(
    question: str,
    context: dict,
    tracer: QueryTracer | None = None,
    previous_sql: str | None = None,
    previous_summary: str | None = None,
    resolved_context: dict | None = None,
) -> str:
    # 컨텍스트 조합
    parts = []

    # 이전 질문 컨텍스트 (꼬리질문 시 활용)
    if previous_sql:
        parts.append(f"[이전 SQL (참고용 — 이 SQL을 기반으로 필터 추가 또는 수정 가능)]\n{previous_sql}")
    if previous_summary:
        parts.append(f"[이전 결과 요약]\n{previous_summary}")

    if context.get("ddl"):
        ddl_text = "\n\n".join(item["content"] for item in context["ddl"])
        parts.append(f"[참고 DDL]\n{ddl_text}")
    if context.get("sql"):
        sql_text = "\n\n".join(item["content"] for item in context["sql"])
        parts.append(f"[참고 SQL 패턴]\n{sql_text}")
    if context.get("doc"):
        doc_text = "\n\n".join(item["content"] for item in context["doc"])
        parts.append(f"[비즈니스 문서]\n{doc_text}")
    if context.get("doc_overlay"):
        ov = "\n\n".join(item["content"] for item in context["doc_overlay"])
        parts.append(f"[운영자 추가 지식]\n{ov}")
    if context.get("doc_patch"):
        pt = "\n\n".join(item["content"] for item in context["doc_patch"])
        parts.append(f"[기존 청크 보강 (PATCH)]\n{pt}")
    if context.get("virtual_view"):
        vv = "\n\n".join(item["content"] for item in context["virtual_view"])
        parts.append(
            "[가상 View 카탈로그 — 우선 사용]\n"
            "다음 가상 view 들이 시스템에 정의되어 있습니다. 질문에 맞으면 view ID 를 일반 테이블처럼 FROM 에 쓰면 됩니다.\n"
            "(예: `SELECT * FROM VV_SALES_MONTHLY WHERE CATEGORY_NAME = '뷰티'`)\n"
            "시스템이 실행 직전에 base SQL 로 자동 변환합니다. raw 테이블 직접 조회보다 가상 view 를 우선 사용하세요.\n\n"
            + vv
        )
    if resolved_context:
        parts.append(
            "[사전 확정 컨텍스트] — 이 값들은 사용자가 disambiguation 단계에서 확정한 결과입니다. "
            "SQL 의 WHERE 절 식별자(ID, 기간 등)에 그대로 사용하세요.\n"
            + json.dumps(resolved_context, ensure_ascii=False)
        )

    user_message = "\n\n".join(parts) + f"\n\n[질문] {question}"

    # 시스템 프롬프트 2단 구성:
    #   블록 1 (안정, 캐시): 도메인 규약 프롬프트 — 모듈 attribute로 참조해 핫편집 반영
    #   블록 2 (휘발): 사용자 설정/큐레이터 지침 — 캐시 breakpoint 뒤라 변해도 캐시 유지
    stable_prompt = prompts_module.SQL_SYSTEM_PROMPT
    volatile_prompt = _build_volatile_instructions()

    system_blocks = [
        {
            "type": "text",
            "text": stable_prompt,
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }
    ]
    if volatile_prompt:
        system_blocks.append({"type": "text", "text": volatile_prompt})

    model = get_llm("MODEL_SQL_GEN")
    effort = get_llm("SQL_GEN_EFFORT")

    if tracer:
        tracer.log_step("sql_generation_request", {
            "system_prompt": stable_prompt,
            "volatile_instructions": volatile_prompt,
            "user_message": user_message,
            "model": model,
            "max_tokens": MAX_TOKENS,
            "structured_output": True,
        })

    output_config: dict = {"format": {"type": "json_schema", "schema": SQL_OUTPUT_SCHEMA}}
    # effort는 Opus/Sonnet 5 계열 전용 (Haiku 4.5는 미지원 — 400)
    if effort and not model.startswith("claude-haiku"):
        output_config["effort"] = effort

    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system_blocks,
        messages=[{"role": "user", "content": user_message}],
        output_config=output_config,
    )

    from ui_engine.cost_calculator import calculate_cost

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
    }
    cost = calculate_cost(
        response.model,
        usage["input_tokens"],
        usage["output_tokens"],
        usage["cache_creation_input_tokens"],
        usage["cache_read_input_tokens"],
    )

    raw_response = _extract_text(response).strip()

    if tracer:
        tracer.log_step("sql_generation_response", {
            "raw_response": raw_response,
            "usage": usage,
            "cost": cost,
            "model": response.model,
            "stop_reason": response.stop_reason,
        })

    # 응답 상태 검증
    if response.stop_reason == "max_tokens":
        raise ValueError("SQL 생성 응답이 토큰 한도에서 잘렸습니다. 질문을 더 구체적으로 나눠 주세요.")
    if response.stop_reason == "refusal":
        raise ValueError("모델이 이 요청을 처리할 수 없다고 판단했습니다.")

    # structured output — 스키마 보장된 JSON에서 SQL 추출
    try:
        sql = json.loads(raw_response)["sql"].strip()
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        if tracer:
            tracer.log_step("sql_parse_error", {"error": str(e), "raw": raw_response[:500]})
        raise ValueError(f"SQL 생성 응답 파싱 실패: {e}")

    # DML 키워드 검증
    if BLOCKED_KEYWORDS.search(sql):
        if tracer:
            tracer.log_step("sql_blocked", {"sql": sql, "reason": "DML/DDL 키워드 감지"})
        raise ValueError("읽기 전용 쿼리만 허용됩니다. DML/DDL 키워드가 감지되었습니다.")

    if tracer:
        tracer.log_step("sql_final", {"sql": sql})

    return sql
