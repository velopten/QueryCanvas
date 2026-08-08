"""
질문내역 영구 저장 (SQLite).
서버 재시작해도 유지된다.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from logger import pipeline_logger

DB_PATH = Path(__file__).parent / "history.db"


class QueryHistoryStore:
    def __init__(self):
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_table()
        pipeline_logger.info(f"질문내역 DB 초기화 완료 ({self.count()}건)")

    def _init_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS query_history (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                question TEXT NOT NULL,
                sql TEXT,
                data TEXT,
                ui_spec TEXT,
                favorite INTEGER DEFAULT 0,
                deleted INTEGER DEFAULT 0,
                parent_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tail_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                history_id TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        self.conn.commit()
        self._migrate()

    def _migrate(self):
        cols = [row[1] for row in self.conn.execute("PRAGMA table_info(query_history)").fetchall()]
        if "deleted" not in cols:
            self.conn.execute("ALTER TABLE query_history ADD COLUMN deleted INTEGER DEFAULT 0")
            self.conn.commit()
        if "parent_id" not in cols:
            self.conn.execute("ALTER TABLE query_history ADD COLUMN parent_id TEXT")
            self.conn.commit()

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM query_history WHERE deleted = 0").fetchone()
        return row[0]

    def save(self, question: str, sql: str, data: list[dict], ui_spec: dict, parent_id: str | None = None) -> dict:
        entry_id = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()
        title = question[:30] + ("..." if len(question) > 30 else "")

        self.conn.execute(
            "INSERT INTO query_history (id, title, question, sql, data, ui_spec, favorite, parent_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (entry_id, title, question, sql, json.dumps(data, ensure_ascii=False, default=str), json.dumps(ui_spec, ensure_ascii=False), parent_id, now, now),
        )
        self.conn.commit()
        return {"id": entry_id, "title": title}

    def list_all(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, title, question, sql, ui_spec, favorite, parent_id, created_at, updated_at FROM query_history WHERE deleted = 0 ORDER BY favorite DESC, created_at DESC"
        ).fetchall()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "question": row["question"],
                "sql": row["sql"],
                "ui_spec": json.loads(row["ui_spec"]) if row["ui_spec"] else None,
                "favorite": bool(row["favorite"]),
                "parent_id": row["parent_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def get(self, entry_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM query_history WHERE id = ? AND deleted = 0", (entry_id,)
        ).fetchone()
        if not row:
            return None

        result = {
            "id": row["id"],
            "title": row["title"],
            "question": row["question"],
            "sql": row["sql"],
            "data": json.loads(row["data"]) if row["data"] else [],
            "ui_spec": json.loads(row["ui_spec"]) if row["ui_spec"] else None,
            "favorite": bool(row["favorite"]),
            "parent_id": row["parent_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

        # 부모 질문 요약 정보 포함
        if row["parent_id"]:
            parent = self.conn.execute(
                "SELECT id, title, question FROM query_history WHERE id = ?", (row["parent_id"],)
            ).fetchone()
            if parent:
                result["parent"] = {
                    "id": parent["id"],
                    "title": parent["title"],
                    "question": parent["question"],
                }

        # 꼬리질문 포함
        result["tail_messages"] = self.get_tails(row["id"])

        return result

    def update_ui_spec(self, entry_id: str, ui_spec: dict) -> bool:
        """UI 수정 요청 반영 — 화면 spec만 갱신 (데이터/SQL 불변)."""
        now = datetime.now().isoformat()
        cur = self.conn.execute(
            "UPDATE query_history SET ui_spec = ?, updated_at = ? WHERE id = ?",
            (json.dumps(ui_spec, ensure_ascii=False), now, entry_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def update_title(self, entry_id: str, title: str) -> bool:
        now = datetime.now().isoformat()
        cur = self.conn.execute(
            "UPDATE query_history SET title = ?, updated_at = ? WHERE id = ?",
            (title, now, entry_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def toggle_favorite(self, entry_id: str) -> bool | None:
        row = self.conn.execute("SELECT favorite FROM query_history WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            return None
        new_val = 0 if row["favorite"] else 1
        now = datetime.now().isoformat()
        self.conn.execute(
            "UPDATE query_history SET favorite = ?, updated_at = ? WHERE id = ?",
            (new_val, now, entry_id),
        )
        self.conn.commit()
        return bool(new_val)

    def delete(self, entry_id: str) -> bool:
        now = datetime.now().isoformat()
        cur = self.conn.execute(
            "UPDATE query_history SET deleted = 1, updated_at = ? WHERE id = ? AND deleted = 0",
            (now, entry_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    # ── 꼬리질문 ──

    def save_tail(self, history_id: str, question: str, answer: str):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO tail_messages (history_id, question, answer, created_at) VALUES (?, ?, ?, ?)",
            (history_id, question, answer, now),
        )
        self.conn.commit()

    def get_tails(self, history_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT question, answer, created_at FROM tail_messages WHERE history_id = ? ORDER BY id ASC",
            (history_id,),
        ).fetchall()
        return [{"question": r["question"], "answer": r["answer"], "created_at": r["created_at"]} for r in rows]


history_store = QueryHistoryStore()
