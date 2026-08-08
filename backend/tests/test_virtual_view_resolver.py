# -*- coding: utf-8 -*-
"""가상 view → base SQL subquery 치환 테스트. view 저장소는 monkeypatch."""

from dataclasses import dataclass

import pytest

import text_to_sql.virtual_view_resolver as vvr


@dataclass
class FakeView:
    id: str
    sql: str


@pytest.fixture
def views(monkeypatch):
    def _set(view_list):
        import text_to_sql.virtual_view_store as store
        monkeypatch.setattr(store, "list_views", lambda: view_list)
    return _set


class TestResolve:
    def test_from_clause_replaced(self, views):
        views([FakeView(id="VV_EMP_CURRENT", sql="SELECT EMP_ID, EMP_NAME FROM TB_EMP")])
        r = vvr.resolve("SELECT EMP_NAME FROM VV_EMP_CURRENT WHERE EMP_NAME = '김철수'", dialect="sqlite")
        assert r.errors == []
        assert r.resolved == ["VV_EMP_CURRENT"]
        assert "TB_EMP" in r.sql
        # 원본 view ID 가 alias 로 유지됨
        assert "VV_EMP_CURRENT" in r.sql

    def test_alias_preserved(self, views):
        views([FakeView(id="VV_X", sql="SELECT 1 AS A FROM TB_ANY")])
        r = vvr.resolve("SELECT V.A FROM VV_X V", dialect="sqlite")
        assert r.resolved == ["VV_X"]
        assert " V" in r.sql or " AS V" in r.sql

    def test_no_view_match_passthrough(self, views):
        views([FakeView(id="VV_X", sql="SELECT 1 FROM TB_ANY")])
        original = "SELECT * FROM TB_EMP"
        r = vvr.resolve(original, dialect="sqlite")
        assert r.resolved == []
        assert r.sql == original

    def test_join_clause_replaced(self, views):
        views([FakeView(id="VV_ORG", sql="SELECT DEPT_CD, DEPT_NAME FROM TB_DEPT")])
        r = vvr.resolve(
            "SELECT T1.EMP_NAME, O.DEPT_NAME FROM TB_EMP T1 JOIN VV_ORG O ON T1.DEPT_CD = O.DEPT_CD",
            dialect="sqlite",
        )
        assert r.resolved == ["VV_ORG"]
        assert "TB_DEPT" in r.sql

    def test_empty_store_passthrough(self, views):
        views([])
        original = "SELECT * FROM VV_ANYTHING"
        r = vvr.resolve(original, dialect="sqlite")
        assert r.sql == original
        assert r.resolved == []

    def test_broken_base_sql_reports_error(self, views):
        # sqlglot이 파싱 못 하는 구조적으로 깨진 base SQL
        views([FakeView(id="VV_BAD", sql="SELECT FROM WHERE")])
        r = vvr.resolve("SELECT * FROM VV_BAD", dialect="sqlite")
        assert r.errors
