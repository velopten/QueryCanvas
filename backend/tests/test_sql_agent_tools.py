# -*- coding: utf-8 -*-
"""에이전트 도구 구현 테스트 — LLM 호출 없이 도구 함수만 검증."""

import pytest

import text_to_sql.sql_agent as agent


class FakeDb:
    """execute()가 미리 등록된 응답을 돌려주는 가짜 DB."""

    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error
        self.executed: list[str] = []

    def execute(self, sql):
        self.executed.append(sql)
        if self.error:
            raise RuntimeError(self.error)
        return self.rows


@pytest.fixture(autouse=True)
def no_virtual_views(monkeypatch):
    """뷰 저장소를 비워 결정적 테스트 환경 구성."""
    import text_to_sql.virtual_view_store as vvs
    monkeypatch.setattr(vvs, "list_views", lambda: [])


class TestPreviewSqlTool:
    def test_blocks_dml(self):
        out = agent._tool_preview_sql(FakeDb(), "DELETE FROM TB_EMP", "oracle")
        assert "거부" in out

    def test_success_returns_masked_sample(self):
        db = FakeDb(rows=[{"EMP_NAME": "김철수", "CNT": 3}])
        out = agent._tool_preview_sql(db, "SELECT EMP_NAME, CNT FROM T", "sqlite")
        assert "실행 성공" in out
        assert "김철수" not in out          # PII 마스킹 확인
        assert "[PERSON_1]" in out

    def test_row_limit_wrapped_sqlite(self):
        db = FakeDb(rows=[])
        agent._tool_preview_sql(db, "SELECT * FROM T", "sqlite")
        assert "LIMIT 5" in db.executed[0]

    def test_row_limit_wrapped_oracle(self):
        db = FakeDb(rows=[])
        agent._tool_preview_sql(db, "SELECT 1 FROM DUAL", "oracle")
        assert "ROWNUM <= 5" in db.executed[0]

    def test_execution_error_reported(self):
        db = FakeDb(error="no such table: X")
        out = agent._tool_preview_sql(db, "SELECT * FROM X", "sqlite")
        assert "실행 오류" in out
        assert "no such table" in out

    def test_invalid_sql_reports_validation_failure(self):
        out = agent._tool_preview_sql(FakeDb(), "SELECT FROM WHERE", "oracle")
        assert "실패" in out


class TestFindEntityTool:
    def test_no_candidates_message(self, monkeypatch):
        import ui_engine.info_collector as ic
        monkeypatch.setattr(ic, "collect", lambda *a, **k: [])
        out = agent._tool_find_entity(FakeDb(), "person", "없는사람")
        assert "후보 없음" in out

    def test_candidates_returned_as_json(self, monkeypatch):
        import ui_engine.info_collector as ic
        from ui_engine.info_collector import CandidateGroup
        g = CandidateGroup(kind="person", keyword="김철수", case_id="person_exact",
                           candidates=[{"CUST_ID": "C1", "CUST_NAME": "김철수"}])
        monkeypatch.setattr(ic, "collect", lambda *a, **k: [g])
        out = agent._tool_find_entity(FakeDb(), "person", "김철수")
        assert "C1" in out
        assert '"count": 1' in out


class TestToolDefinitions:
    def test_all_tools_strict_with_closed_schema(self):
        for t in agent.TOOLS:
            assert t["strict"] is True
            assert t["input_schema"]["additionalProperties"] is False
            assert t["input_schema"]["required"]

    def test_summarize_call(self):
        assert "김철수" in agent._summarize_call("find_person", {"name": "김철수"})
        assert "시험 실행" in agent._summarize_call("preview_sql", {"sql": "SELECT 1"})
