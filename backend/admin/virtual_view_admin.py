"""가상 View 카탈로그 admin wrapper — virtual_view_store 위에서 검증/Test Run/reindex 추가."""

from __future__ import annotations

from text_to_sql import virtual_view_store as vvs
from text_to_sql.sql_validator import validate_sql


def list_meta() -> list[dict]:
    return [
        {
            "id": v.id, "purpose": v.purpose, "use_when": v.use_when,
            "required_params": v.meta.get("required_params") or [],
            "columns": v.meta.get("columns") or [],
            "sample_questions": v.sample_questions,
        }
        for v in vvs.list_views()
    ]


def get_full(view_id: str) -> dict | None:
    v = vvs.get_view(view_id)
    if not v:
        return None
    return {"id": v.id, "meta": v.meta, "sql": v.sql}


def save(view_id: str, *, meta: dict | None = None, sql: str | None = None) -> dict:
    if sql is not None:
        # SELECT-only 검증 (필수필터는 view 자체엔 강제 못 함 — bind 가 있기 때문)
        from sqlglot import parse, exp
        try:
            parsed = parse(sql, read="oracle")
        except Exception as e:
            raise ValueError(f"SQL 파싱 실패: {e}")
        for st in parsed:
            if st is None:
                continue
            for n in st.walk():
                node = n[0] if isinstance(n, tuple) else n
                if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create)):
                    raise ValueError("SELECT 만 허용됩니다")
    new_v = vvs.save_view(view_id, meta=meta, sql=sql)
    return {"id": new_v.id, "meta": new_v.meta, "sql": new_v.sql}


def test_run(db, view_id: str, params: dict) -> list[dict]:
    v = vvs.get_view(view_id)
    if not v:
        raise ValueError(f"view 없음: {view_id}")
    sql = v.sql
    for k, val in (params or {}).items():
        if val is None:
            continue
        sql = sql.replace(f":{k}", f"'{str(val).replace(chr(39), chr(39)+chr(39))}'")
    if "FETCH FIRST" not in sql.upper() and "LIMIT" not in sql.upper():
        sql = sql.rstrip().rstrip(";") + " FETCH FIRST 100 ROWS ONLY"
    return db.execute(sql)


def reindex() -> dict:
    """vector_store 부분 재학습 (전체 train 트리거)."""
    from text_to_sql.vector_store import vector_store
    return vector_store.train()
