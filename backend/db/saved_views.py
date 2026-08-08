"""
저장된 뷰 (화면의 메뉴화) — SQLite 영구 저장.

자연어로 만든 화면(질문 → SQL → A2UI spec)을 이름 붙여 메뉴처럼 저장하고,
열 때마다 SQL만 재실행해 저장된 spec에 fresh 데이터를 바인딩한다 (LLM 0회).
SQL의 상대 날짜 표현(strftime 'now' 등) 덕분에 "이번 달" 화면이 저절로 갱신된다.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from logger import pipeline_logger

DB_PATH = Path(__file__).parent / "saved_views.db"


class SavedViewStore:
    def __init__(self):
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_table()
        pipeline_logger.info(f"저장된 뷰 DB 초기화 완료 ({self.count()}건)")

    def _init_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS saved_views (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                question TEXT NOT NULL,
                sql TEXT NOT NULL,
                ui_spec TEXT NOT NULL,
                liveness_note TEXT,
                deleted INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                last_used_at TEXT
            )
        """)
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM saved_views WHERE deleted = 0").fetchone()[0]

    def create(self, name: str, question: str, sql: str, ui_spec: dict, liveness_note: str | None = None) -> dict:
        view_id = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO saved_views (id, name, question, sql, ui_spec, liveness_note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (view_id, name, question, sql, json.dumps(ui_spec, ensure_ascii=False), liveness_note, now),
        )
        self.conn.commit()
        return self.get(view_id)

    def list_all(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, name, question, liveness_note, created_at, last_used_at "
            "FROM saved_views WHERE deleted = 0 ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get(self, view_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM saved_views WHERE id = ? AND deleted = 0", (view_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["ui_spec"] = json.loads(d["ui_spec"])
        return d

    def touch(self, view_id: str):
        self.conn.execute(
            "UPDATE saved_views SET last_used_at = ? WHERE id = ?",
            (datetime.now().isoformat(), view_id),
        )
        self.conn.commit()

    def rename(self, view_id: str, name: str) -> bool:
        cur = self.conn.execute("UPDATE saved_views SET name = ? WHERE id = ? AND deleted = 0", (name, view_id))
        self.conn.commit()
        return cur.rowcount > 0

    def delete(self, view_id: str) -> bool:
        cur = self.conn.execute("UPDATE saved_views SET deleted = 1 WHERE id = ?", (view_id,))
        self.conn.commit()
        return cur.rowcount > 0


saved_view_store = SavedViewStore()
