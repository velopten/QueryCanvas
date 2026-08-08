# -*- coding: utf-8 -*-
"""비용 계산기 테스트 — 신모델 단가 + 캐시 단가."""

from ui_engine.cost_calculator import calculate_cost


class TestPricing:
    def test_opus5(self):
        c = calculate_cost("claude-opus-5", 1_000_000, 1_000_000)
        assert c["input_cost"] == 5.0
        assert c["output_cost"] == 25.0

    def test_sonnet5(self):
        c = calculate_cost("claude-sonnet-5", 1_000_000, 1_000_000)
        assert c["total_cost"] == 18.0

    def test_haiku_dated_id_prefix_match(self):
        c = calculate_cost("claude-haiku-4-5-20251001", 1_000_000, 0)
        assert c["input_cost"] == 1.0

    def test_cache_pricing(self):
        # 캐시 쓰기 1.25배, 읽기 0.1배
        c = calculate_cost("claude-opus-5", 0, 0,
                           cache_creation_input_tokens=1_000_000,
                           cache_read_input_tokens=1_000_000)
        assert c["cache_cost"] == 5.0 * 1.25 + 5.0 * 0.1

    def test_unknown_model_fallback(self):
        c = calculate_cost("unknown-model-x", 1_000_000, 0)
        assert c["input_cost"] == 1.0  # Haiku 단가 fallback

    def test_total_includes_all(self):
        c = calculate_cost("claude-sonnet-5", 100_000, 10_000,
                           cache_read_input_tokens=500_000)
        assert abs(c["total_cost"] - (c["input_cost"] + c["output_cost"] + c["cache_cost"])) < 1e-9
