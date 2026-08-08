# -*- coding: utf-8 -*-
"""info_collector 템플릿 렌더링/후보 그룹 상태 테스트."""

from ui_engine.info_collector import CandidateGroup, _render


class TestRender:
    def test_name_quoted_and_escaped(self):
        sql = _render("SELECT * FROM TB_EMP WHERE EMP_NAME = :NAME", {"NAME": "김'철수"})
        assert "''" in sql          # 작은따옴표 이스케이프
        assert ":NAME" not in sql

    def test_all_params_quoted(self):
        sql = _render("WHERE A = :X AND B = :Y", {"X": "1000", "Y": "abc"})
        assert "'1000'" in sql and "'abc'" in sql


class TestCandidateGroupStatus:
    def test_empty(self):
        assert CandidateGroup(kind="person", keyword="x", case_id="c").status == "empty"

    def test_auto(self):
        g = CandidateGroup(kind="person", keyword="x", case_id="c", candidates=[{"EMP_ID": "1"}])
        assert g.status == "auto"

    def test_needs_input(self):
        g = CandidateGroup(kind="person", keyword="x", case_id="c",
                           candidates=[{"EMP_ID": "1"}, {"EMP_ID": "2"}])
        assert g.status == "needs_input"
