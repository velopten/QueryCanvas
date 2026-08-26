from types import SimpleNamespace

from admin import virtual_view_admin


class FakeDb:
    def __init__(self):
        self.sql = ""

    def execute(self, sql):
        self.sql = sql
        return [{"value": 1}]


def test_test_run_uses_sqlite_limit(monkeypatch):
    monkeypatch.setattr(
        virtual_view_admin.vvs,
        "get_view",
        lambda _view_id: SimpleNamespace(sql="SELECT 1 AS value"),
    )
    db = FakeDb()

    rows = virtual_view_admin.test_run(db, "VV_TEST", {})

    assert rows == [{"value": 1}]
    assert db.sql == "SELECT 1 AS value LIMIT 100"


def test_test_run_keeps_existing_limit(monkeypatch):
    monkeypatch.setattr(
        virtual_view_admin.vvs,
        "get_view",
        lambda _view_id: SimpleNamespace(sql="SELECT 1 AS value LIMIT 5"),
    )
    db = FakeDb()

    virtual_view_admin.test_run(db, "VV_TEST", {})

    assert db.sql == "SELECT 1 AS value LIMIT 5"
