# -*- coding: utf-8 -*-
"""sqlglot 기반 SQL 안전성 검증 테스트 (AST DML/DDL 차단 + 테이블 수집)."""

import pytest

import text_to_sql.sql_validator as sv


class TestDmlBlocking:
    def test_select_passes(self):
        r = sv.validate_sql("SELECT 1 FROM TB_EMP", dialect="sqlite")
        assert r.ok

    @pytest.mark.parametrize("sql", [
        "DELETE FROM TB_EMP",
        "UPDATE TB_EMP SET EMP_NAME = 'x'",
        "DROP TABLE TB_EMP",
        "INSERT INTO TB_EMP VALUES (1)",
    ])
    def test_dml_blocked(self, sql):
        r = sv.validate_sql(sql, dialect="sqlite")
        assert not r.ok
        assert any("DML/DDL" in e for e in r.errors)

    def test_parse_failure(self):
        # 주의: sqlglot은 관대해서 오타 수준은 표현식으로 파싱됨 (실행 단계에서 잡힘).
        # 구조적으로 깨진 SQL만 파싱 실패.
        r = sv.validate_sql("SELECT FROM WHERE", dialect="sqlite")
        assert not r.ok

    def test_nested_dml_blocked(self):
        # 서브쿼리/CTE 속 DML도 AST 순회로 차단
        r = sv.validate_sql(
            "WITH x AS (SELECT 1) DELETE FROM TB_EMP", dialect="sqlite",
        )
        assert not r.ok


class TestTableCollection:
    def test_tables_collected(self):
        r = sv.validate_sql(
            "SELECT e.EMP_NAME FROM TB_EMP e JOIN TB_DEPT d ON e.DEPT_CD = d.DEPT_CD",
            dialect="sqlite",
        )
        assert r.ok
        assert r.tables == ["TB_DEPT", "TB_EMP"]

    def test_subquery_tables_collected(self):
        r = sv.validate_sql(
            "SELECT * FROM TB_ATTENDANCE WHERE EMP_ID IN (SELECT EMP_ID FROM TB_EMP)",
            dialect="sqlite",
        )
        assert set(r.tables) == {"TB_ATTENDANCE", "TB_EMP"}

    def test_injected_always_empty(self):
        # 하위 호환 필드 — 필터 주입 기능 제거 후 항상 빈 리스트
        r = sv.validate_sql("SELECT 1 FROM TB_EMP", dialect="sqlite")
        assert r.injected == []
