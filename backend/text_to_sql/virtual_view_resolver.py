"""
가상 view 해석기.

LLM 이 생성한 SQL 에서 `FROM VV_XXX` 또는 `JOIN VV_XXX` 패턴을 발견하면
디스크의 base SQL 본문을 읽어 `(base SQL) alias` 형태의 subquery 로 자동 치환한다.

LLM 이 view ID 를 일반 테이블처럼 쓰게 두고, 시스템이 실행 직전에 결정적으로 변환.
프롬프트 비대화 없음. 100% 결정적.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp


@dataclass
class ResolveResult:
    sql: str
    resolved: list[str] = field(default_factory=list)   # 치환된 view ID 목록
    errors: list[str] = field(default_factory=list)


def resolve(sql: str, dialect: str = "sqlite") -> ResolveResult:
    """
    sql 안의 가상 view 참조를 base SQL subquery 로 치환.
    매칭되는 가상 view 가 없으면 원본 그대로 반환.
    """
    from text_to_sql.virtual_view_store import list_views

    views = {v.id.upper(): v for v in list_views()}
    if not views:
        return ResolveResult(sql=sql)

    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception as e:
        return ResolveResult(sql=sql, errors=[f"SQL 파싱 실패: {e}"])

    if tree is None:
        return ResolveResult(sql=sql)

    resolved: list[str] = []

    # 모든 Table 노드를 순회 — FROM/JOIN 어디 있든
    for table_node in list(tree.find_all(exp.Table)):
        name_upper = (table_node.name or "").upper()
        if name_upper not in views:
            continue
        v = views[name_upper]
        if not v.sql or not v.sql.strip():
            continue

        try:
            base_tree = sqlglot.parse_one(v.sql.strip(), read=dialect)
        except Exception as e:
            return ResolveResult(sql=sql, errors=[f"가상 view {name_upper} base SQL 파싱 실패: {e}"])

        # 원본 alias 보존 (없으면 view ID 를 alias 로)
        alias_name = table_node.alias_or_name or name_upper

        # subquery 생성: (base_tree) AS alias
        subquery = exp.Subquery(
            this=base_tree,
            alias=exp.TableAlias(this=exp.Identifier(this=alias_name, quoted=False)),
        )
        table_node.replace(subquery)
        resolved.append(name_upper)

    if not resolved:
        return ResolveResult(sql=sql)

    return ResolveResult(sql=tree.sql(dialect=dialect, pretty=True), resolved=resolved)
