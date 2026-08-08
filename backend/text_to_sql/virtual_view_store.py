"""
가상 View 카탈로그 저장소.

- meta/*.yaml: 임베딩 대상 메타데이터
- sql/*.sql:   디스크 보관 (임베딩 X)
- _history/:   수정 시 백업

vector_store 와 sql_generator 가 이 모듈을 통해 가상 view 를 조회한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from config import domain_dir
ROOT = domain_dir() / "virtual_views"
META_DIR = ROOT / "meta"
SQL_DIR = ROOT / "sql"
HISTORY_DIR = ROOT / "_history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class VirtualView:
    id: str
    meta_path: Path
    sql_path: Path
    meta: dict
    sql: str

    @property
    def purpose(self) -> str:
        return self.meta.get("purpose", "")

    @property
    def use_when(self) -> str:
        return self.meta.get("use_when", "")

    @property
    def sample_questions(self) -> list[str]:
        return self.meta.get("sample_questions") or []

    def embedding_text(self) -> str:
        """
        임베딩 검색용 텍스트 — 사용자 질문에 직접 매칭될 텍스트만.
        SQL/구현 세부(notes/required_params/컬럼 desc) 제외 → 의미 노이즈 최소화.
        """
        samples = "\n".join(f"- {q}" for q in self.sample_questions)
        cols = self.meta.get("columns") or []
        col_names = ", ".join(c.get("name", "") for c in cols if isinstance(c, dict))
        return (
            f"# {self.id}\n"
            f"## 목적\n{self.purpose}\n"
            f"## 사용 시점\n{self.use_when}\n"
            f"## 사용 예시 질문\n{samples}\n"
            f"## 주요 컬럼\n{col_names}"
        )


def list_views() -> list[VirtualView]:
    out: list[VirtualView] = []
    if not META_DIR.exists():
        return out
    for yml in sorted(META_DIR.glob("*.yaml")):
        try:
            meta = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        sql_rel = meta.get("sql_file") or f"sql/{yml.stem}.sql"
        sql_path = (ROOT / sql_rel).resolve()
        sql_text = sql_path.read_text(encoding="utf-8") if sql_path.exists() else ""
        out.append(VirtualView(
            id=meta.get("id", yml.stem.upper()),
            meta_path=yml, sql_path=sql_path,
            meta=meta, sql=sql_text,
        ))
    return out


def get_view(view_id: str) -> VirtualView | None:
    for v in list_views():
        if v.id.upper() == view_id.upper():
            return v
    return None


def save_view(view_id: str, *, meta: dict | None = None, sql: str | None = None) -> VirtualView:
    """meta 또는 sql 본문 갱신. 변경 전 _history 에 백업."""
    v = get_view(view_id)
    if not v:
        raise ValueError(f"view 없음: {view_id}")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if meta is not None:
        (HISTORY_DIR / f"{v.id}_{ts}.yaml.bak").write_text(
            v.meta_path.read_text(encoding="utf-8"), encoding="utf-8",
        )
        v.meta_path.write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if sql is not None:
        (HISTORY_DIR / f"{v.id}_{ts}.sql.bak").write_text(
            v.sql_path.read_text(encoding="utf-8") if v.sql_path.exists() else "", encoding="utf-8",
        )
        v.sql_path.write_text(sql, encoding="utf-8")
    return get_view(view_id)  # type: ignore[return-value]
