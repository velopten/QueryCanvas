"""
추가정보 수집기.

prefilter_question 이 needs_disambiguation=true 로 판정한 경우,
이 모듈이 결정적(LLM 미사용) SQL 템플릿으로 후보를 조회한다.

각 case 의 SQL 은 yaml 로 분리되어 관리자 화면에서 편집 가능하다.

결과:
  - 후보 0건 → empty (호출자가 진행 결정)
  - 후보 1건 → auto-resolve
  - 후보 2건 이상 → needs_input (사용자 선택 요청)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from config import domain_dir
_TPL_PATH = domain_dir() / "info_collectors.yaml"
_tpls: dict[str, dict] = {}
_tpl_mtime: float = 0.0


def _load_templates() -> dict[str, dict]:
    global _tpls, _tpl_mtime
    try:
        m = _TPL_PATH.stat().st_mtime
        if m != _tpl_mtime or not _tpls:
            with _TPL_PATH.open("r", encoding="utf-8") as f:
                _tpls = yaml.safe_load(f) or {}
            _tpl_mtime = m
    except FileNotFoundError:
        _tpls = {}
    return _tpls


def reload_templates() -> dict[str, dict]:
    global _tpl_mtime
    _tpl_mtime = 0.0
    return _load_templates()


@dataclass
class CandidateGroup:
    """한 entity (이름) 에 대한 후보 목록."""
    kind: str               # "person" | "group" | "range"
    keyword: str            # 사용자가 입력한 이름/키워드
    case_id: str            # 사용된 템플릿 case id
    candidates: list[dict] = field(default_factory=list)

    @property
    def status(self) -> str:
        if len(self.candidates) == 0:
            return "empty"
        if len(self.candidates) == 1:
            return "auto"
        return "needs_input"


def collect(
    db: Any,
    extracted: dict,
    *,
    broaden_person: bool = False,
    broaden_group: bool = False,
) -> list[CandidateGroup]:
    """
    extracted (prefilter 결과) 를 받아 case 별 후보를 조회한다.
    db 는 oracle_client / mock client. .execute(sql, params) 를 가져야 한다.
    """
    tpls = _load_templates()
    groups: list[CandidateGroup] = []

    # 개인 엔티티 이름들
    for nm in extracted.get("names") or []:
        case_id = "person_exact" if not broaden_person else "person_partial"
        tpl = tpls.get(case_id)
        if not tpl:
            continue
        sql = _render(tpl["sql"], {"NAME": nm})
        try:
            rows = db.execute(sql)
        except Exception:
            rows = []
        groups.append(CandidateGroup(kind="person", keyword=nm, case_id=case_id, candidates=rows))

    # 그룹 엔티티 이름들
    for grp in extracted.get("groups") or []:
        case_id = "group_exact" if not broaden_group else "group_partial"
        tpl = tpls.get(case_id)
        if not tpl:
            continue
        sql = _render(tpl["sql"], {"NAME": grp})
        try:
            rows = db.execute(sql)
        except Exception:
            rows = []
        groups.append(CandidateGroup(kind="group", keyword=grp, case_id=case_id, candidates=rows))

    return groups


def _render(template: str, params: dict) -> str:
    """간이 :NAME 치환. SQL injection 방지를 위해 작은따옴표 escape 후 quote."""
    out = template
    for k, v in params.items():
        safe = str(v).replace("'", "''")
        out = out.replace(f":{k}", f"'{safe}'")
    return out
