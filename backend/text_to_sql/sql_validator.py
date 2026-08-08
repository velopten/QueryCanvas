"""
SQL AST 안전성 검증기 (sqlglot 기반).

역할:
1. 생성된 SQL이 SELECT-only인지 AST 수준에서 확인 (DML/DDL 차단 —
   regex 블랙리스트와 달리 문자열/주석 속 키워드에 오탐 없음)
2. 사용된 테이블 목록 수집 (트레이스/감사용)

LLM 호출 없음. 100% 결정적.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp


@dataclass
class ValidationResult:
    ok: bool
    sql: str                                # 검증 통과한 SQL (현재는 원본 그대로)
    injected: list[str] = field(default_factory=list)   # 하위 호환 (항상 빈 리스트)
    errors: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)     # 실제로 사용된 테이블


BLOCKED_NODE_TYPES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter,
    exp.Create, exp.TruncateTable, exp.Merge,
)


def validate_sql(sql: str, dialect: str = "sqlite") -> ValidationResult:
    """SQL을 파싱하여 DML/DDL을 차단하고 사용 테이블을 수집한다."""
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except Exception as e:
        return ValidationResult(ok=False, sql=sql, errors=[f"SQL 파싱 실패: {e}"])

    if not statements or statements[0] is None:
        return ValidationResult(ok=False, sql=sql, errors=["빈 SQL"])

    for st in statements:
        if st is None:
            continue
        for node in st.walk():
            n = node[0] if isinstance(node, tuple) else node
            if isinstance(n, BLOCKED_NODE_TYPES):
                return ValidationResult(
                    ok=False, sql=sql,
                    errors=[f"DML/DDL 금지: {type(n).__name__}"],
                )

    used_tables = sorted({t.name for t in statements[0].find_all(exp.Table)})
    return ValidationResult(ok=True, sql=sql, tables=used_tables)
