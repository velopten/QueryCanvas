# -*- coding: utf-8 -*-
"""A2UI UI 결정 후처리(sanitize/빈 결과/집계 감지) + 카탈로그 검증 테스트 — LLM 호출 없음."""

import json

from ui_engine.ui_decision import (
    _empty_ui,
    _is_aggregated_sql,
    _prune_unreachable,
    _remap_healing_refs,
    _sanitize_components,
    _containers_referencing,
    build_skeleton_messages,
    plan_layout,
)
from ui_engine.a2ui_catalog import SURFACE_ID, build_catalog_dict, new_format


def chart(cid):
    return {"id": cid, "component": "Chart", "chartType": "bar", "rows": {"path": "/rows"}}


def table(cid):
    return {"id": cid, "component": "DataTable", "rows": {"path": "/rows"}}


class TestAggregatedSqlDetection:
    def test_group_by_detected(self):
        assert _is_aggregated_sql("SELECT DEPT, COUNT(*) FROM T GROUP BY DEPT")

    def test_raw_select_not_aggregated(self):
        assert not _is_aggregated_sql("SELECT EMP_NM, ATT_DATE FROM T")

    def test_none_sql(self):
        assert not _is_aggregated_sql(None)


class TestSanitizeComponents:
    AGG_SQL = "SELECT DEPT, COUNT(*) C FROM T GROUP BY DEPT"
    RAW_SQL = "SELECT EMP_NM FROM T"

    def test_multiple_charts_keep_first(self):
        comps = {
            "root": {"id": "root", "component": "Column", "children": ["c1", "c2", "t"]},
            "c1": chart("c1"), "c2": chart("c2"), "t": table("t"),
        }
        removed = _sanitize_components(comps, self.AGG_SQL)
        assert removed == {"c2"}
        assert "c1" in comps and "c2" not in comps
        assert comps["root"]["children"] == ["c1", "t"]

    def test_chart_removed_for_raw_sql(self):
        comps = {
            "root": {"id": "root", "component": "Column", "children": ["c1", "t"]},
            "c1": chart("c1"), "t": table("t"),
        }
        removed = _sanitize_components(comps, self.RAW_SQL)
        assert removed == {"c1"}
        assert comps["root"]["children"] == ["t"]

    def test_no_removal_for_single_chart_agg(self):
        comps = {
            "root": {"id": "root", "component": "Column", "children": ["c1"]},
            "c1": chart("c1"),
        }
        assert _sanitize_components(comps, self.AGG_SQL) == set()

    def test_dangling_children_pruned_on_removal(self):
        comps = {
            "root": {"id": "root", "component": "Column", "children": ["ghost", "c1", "c2"]},
            "c1": chart("c1"), "c2": chart("c2"),
        }
        _sanitize_components(comps, self.AGG_SQL)
        assert comps["root"]["children"] == ["c1"]

    def test_containers_referencing_includes_root(self):
        comps = {
            "root": {"id": "root", "component": "Column", "children": ["row1"]},
            "row1": {"id": "row1", "component": "Row", "children": ["t"]},
            "t": table("t"),
        }
        ids = _containers_referencing(comps)
        assert "root" in ids and "row1" in ids and "t" not in ids


class TestPruneUnreachable:
    def test_healing_placeholders_pruned(self):
        """스트리밍 힐링이 남긴 loading_* 고아 컴포넌트가 최종 spec에서 제거되는지."""
        comps = {
            "root": {"id": "root", "component": "Column", "children": ["b", "t"]},
            "b": {"id": "b", "component": "BriefingCard", "headline": "h"},
            "t": table("t"),
            "loading_chart": {"id": "loading_chart", "component": "Row", "children": []},
        }
        _prune_unreachable(comps)
        assert set(comps) == {"root", "b", "t"}

    def test_nested_reachability(self):
        comps = {
            "root": {"id": "root", "component": "Column", "children": ["row1"]},
            "row1": {"id": "row1", "component": "Row", "children": ["t"]},
            "t": table("t"),
            "orphan": table("orphan"),
        }
        _prune_unreachable(comps)
        assert "t" in comps and "orphan" not in comps

    def test_no_root_noop(self):
        comps = {"a": table("a")}
        _prune_unreachable(comps)
        assert "a" in comps


class TestLayoutHeuristic:
    def test_aggregate_question_expects_chart(self):
        assert plan_layout("카테고리별 평균 반품률 비교해줘")["expect_chart"] is True
        assert plan_layout("최근 3개월 매출 추이")["expect_chart"] is True

    def test_detail_question_no_chart(self):
        assert plan_layout("지난주 주문 건 목록 보여줘")["expect_chart"] is False
        assert plan_layout("김민준의 연락처 정보 알려줘")["expect_chart"] is False

    def test_long_title_truncated(self):
        q = "아주 길고 긴 질문 " * 10
        assert len(plan_layout(q)["title"]) <= 30


class TestRemapHealingRefs:
    def test_known_loading_ref_restored(self):
        """스켈레톤으로 이미 렌더된 컴포넌트의 힐링 참조는 원본 id로 복원."""
        comps = [
            {"id": "root", "component": "Column", "children": ["briefing", "loading_data_table"]},
            {"id": "briefing", "component": "BriefingCard", "headline": "h"},
            {"id": "loading_data_table", "component": "Row", "children": []},
        ]
        out = _remap_healing_refs(comps, known={"data_table", "root"})
        root = next(c for c in out if c["id"] == "root")
        assert root["children"] == ["briefing", "data_table"]
        assert not any(c["id"] == "loading_data_table" for c in out)

    def test_unknown_loading_ref_kept(self):
        """아직 정의된 적 없는 컴포넌트의 힐링 placeholder는 유지 (shimmer 용도)."""
        comps = [
            {"id": "root", "component": "Column", "children": ["loading_filter"]},
            {"id": "loading_filter", "component": "Row", "children": []},
        ]
        out = _remap_healing_refs(comps, known={"root"})
        root = next(c for c in out if c["id"] == "root")
        assert root["children"] == ["loading_filter"]
        assert any(c["id"] == "loading_filter" for c in out)


class TestSkeletonBuilder:
    def test_with_chart(self):
        msgs = build_skeleton_messages({"title": "카테고리별 매출 현황", "expect_chart": True, "expect_filter": False})
        comps = msgs[0]["updateComponents"]["components"]
        # 스트리밍 계약: root가 components 리스트의 첫 번째여야 함
        assert comps[0]["id"] == "root"
        ids = [c["id"] for c in comps]
        assert ids == ["root", "briefing", "main_chart", "data_table"]
        assert comps[0]["children"] == ["briefing", "main_chart", "data_table"]
        chart = next(c for c in comps if c["id"] == "main_chart")
        # 스켈레톤 차트는 rows 바인딩 없이 loading만 (자동 차트 오작동 방지)
        assert "rows" not in chart
        assert chart["loading"] == {"path": "/meta/loading"}

    def test_without_chart(self):
        msgs = build_skeleton_messages({"title": "주문 상세", "expect_chart": False, "expect_filter": False})
        ids = [c["id"] for c in msgs[0]["updateComponents"]["components"]]
        assert "main_chart" not in ids
        assert "data_table" in ids

    def test_headline_fallback(self):
        msgs = build_skeleton_messages({})
        briefing = next(c for c in msgs[0]["updateComponents"]["components"] if c["id"] == "briefing")
        assert briefing["headline"]


class TestEmptyUi:
    def test_shape(self):
        spec = _empty_ui("없음")
        assert spec["format"] == "a2ui"
        uc = spec["messages"][0]["updateComponents"]
        assert uc["surfaceId"] == SURFACE_ID
        ids = [c["id"] for c in uc["components"]]
        assert "root" in ids

    def test_empty_ui_passes_sdk_validation(self):
        spec = _empty_ui("데이터 없음")
        txt = "<a2ui-json>" + json.dumps(spec["messages"], ensure_ascii=False) + "</a2ui-json>"
        parts = new_format().parser.parse_response(txt)
        assert parts


class TestCatalog:
    def test_custom_components_registered(self):
        cat = build_catalog_dict()
        for name in ("Chart", "DataTable", "BriefingCard", "Filter"):
            assert name in cat["components"]
            refs = [r["$ref"] for r in cat["$defs"]["anyComponent"]["oneOf"]]
            assert f"#/components/{name}" in refs

    def test_custom_component_message_validates(self):
        msgs = [{
            "version": "v0.9",
            "updateComponents": {
                "surfaceId": SURFACE_ID,
                "components": [
                    {"id": "root", "component": "Column", "children": ["b", "f", "c", "t"]},
                    {"id": "b", "component": "BriefingCard", "headline": "요약", "bullets": ["a", "b"]},
                    {"id": "f", "component": "Filter", "columns": ["DEPT_NAME"],
                     "rows": {"path": "/rows"}, "filters": {"path": "/filters"}},
                    {"id": "c", "component": "Chart", "chartType": "bar", "xField": "DEPT_NAME",
                     "yField": "CNT", "rows": {"path": "/rows"}},
                    {"id": "t", "component": "DataTable", "rows": {"path": "/rows"}},
                ],
            },
        }]
        txt = "<a2ui-json>" + json.dumps(msgs, ensure_ascii=False) + "</a2ui-json>"
        parts = new_format().parser.parse_response(txt)
        assert parts and parts[0].a2ui_json

    def test_invalid_component_rejected(self):
        msgs = [{
            "version": "v0.9",
            "updateComponents": {
                "surfaceId": SURFACE_ID,
                "components": [{"id": "root", "component": "NoSuchComponent"}],
            },
        }]
        txt = "<a2ui-json>" + json.dumps(msgs, ensure_ascii=False) + "</a2ui-json>"
        try:
            new_format().parser.parse_response(txt)
            assert False, "검증을 통과하면 안 됨"
        except Exception:
            pass

    def test_streaming_emits_completed_messages_from_truncated_stream(self):
        """완결된 앞 메시지는 스트림이 절단돼도 방출되어야 한다 (resilient streaming)."""
        # 주의: 스트리밍 파서는 createSurface 선행 없이는 아무것도 방출하지 않음 (SDK 동작)
        msgs = [
            {"version": "v0.9", "createSurface": {"surfaceId": SURFACE_ID, "catalogId": "query-canvas/v1"}},
            {"version": "v0.9", "updateComponents": {"surfaceId": SURFACE_ID, "components": [
                {"id": "root", "component": "Column", "children": ["t"]},
                {"id": "t", "component": "DataTable", "rows": {"path": "/rows"}},
            ]}},
            {"version": "v0.9", "updateComponents": {"surfaceId": SURFACE_ID, "components": [
                {"id": "b", "component": "BriefingCard", "headline": "요약 텍스트가 깁니다"},
            ]}},
        ]
        txt = "<a2ui-json>" + json.dumps(msgs, ensure_ascii=False) + "</a2ui-json>"
        truncated = txt[:-45]  # 두 번째 메시지 중간 절단
        parser = new_format().parser
        emitted = []
        for i in range(0, len(truncated), 30):
            emitted.extend(parser.process_chunk(truncated[i:i + 30]))
        flat = [m for part in emitted for m in (part.a2ui_json or [])]
        # 완결된 첫 메시지(root+DataTable)는 방출되어야 함
        assert any(
            any(c.get("id") == "t" for c in m.get("updateComponents", {}).get("components", []))
            for m in flat
        )
