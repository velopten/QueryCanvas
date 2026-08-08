"""
API 비용 계산기.
모델별 토큰 단가 기준으로 비용을 산출한다.
단가는 2026년 기준 Anthropic 공식 가격. 캐시 읽기/쓰기 단가 반영.
"""

# 모델별 토큰 단가 (USD per 1M tokens)
# cache_write = 입력의 1.25배(5분 TTL), cache_read = 입력의 0.1배
MODEL_PRICING = {
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    # 구세대 (기록된 trace 재계산용)
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
}

_CACHE_WRITE_MULTIPLIER = 1.25
_CACHE_READ_MULTIPLIER = 0.1


def _find_pricing(model: str) -> dict:
    """정확 일치 → prefix 일치 순으로 단가를 찾는다 (dated ID 대응)."""
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    for key, pricing in MODEL_PRICING.items():
        if model.startswith(key) or key.startswith(model):
            return pricing
    return {"input": 1.00, "output": 5.00}


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> dict:
    """
    API 호출 비용을 계산한다. 프롬프트 캐시 쓰기/읽기 토큰 별도 단가 적용.
    Returns: {"input_cost", "output_cost", "cache_cost", "total_cost", "currency"}
    """
    pricing = _find_pricing(model)

    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    cache_cost = (
        (cache_creation_input_tokens / 1_000_000) * pricing["input"] * _CACHE_WRITE_MULTIPLIER
        + (cache_read_input_tokens / 1_000_000) * pricing["input"] * _CACHE_READ_MULTIPLIER
    )

    return {
        "input_cost": round(input_cost, 6),
        "output_cost": round(output_cost, 6),
        "cache_cost": round(cache_cost, 6),
        "total_cost": round(input_cost + output_cost + cache_cost, 6),
        "currency": "USD",
    }
