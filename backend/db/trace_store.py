"""
파이프라인 추적 + 피드백 영구 저장 (SQLite).
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from logger import pipeline_logger

DB_PATH = Path(__file__).parent / "history.db"


class TraceStore:
    def __init__(self):
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_table()
        pipeline_logger.info(f"파이프라인 추적 DB 초기화 완료 ({self.count()}건)")

    def _init_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_traces (
                trace_id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                history_id TEXT,
                steps TEXT NOT NULL,
                feedback INTEGER,
                feedback_comment TEXT,
                created_at TEXT NOT NULL
            )
        """)
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM pipeline_traces").fetchone()[0]

    def save(self, trace: dict, history_id: str | None = None):
        self.conn.execute(
            "INSERT OR REPLACE INTO pipeline_traces (trace_id, question, history_id, steps, created_at) VALUES (?, ?, ?, ?, ?)",
            (trace["trace_id"], trace["question"], history_id, json.dumps(trace["steps"], ensure_ascii=False, default=str), trace.get("started_at", datetime.now().isoformat())),
        )
        self.conn.commit()

    def list_recent(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            """SELECT t.trace_id, t.question, t.history_id, t.feedback, t.feedback_comment, t.created_at,
                      h.parent_id, ph.title AS parent_title
               FROM pipeline_traces t
               LEFT JOIN query_history h ON t.history_id = h.id
               LEFT JOIN query_history ph ON h.parent_id = ph.id
               ORDER BY t.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get(self, trace_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM pipeline_traces WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        if not row:
            return None
        return {
            "trace_id": row["trace_id"],
            "question": row["question"],
            "history_id": row["history_id"],
            "steps": json.loads(row["steps"]),
            "feedback": row["feedback"],
            "feedback_comment": row["feedback_comment"],
            "created_at": row["created_at"],
        }

    def set_feedback(self, trace_id: str, feedback: int, comment: str = "") -> bool:
        """피드백 저장. feedback: 1=좋아요, -1=싫어요, 0=초기화"""
        cur = self.conn.execute(
            "UPDATE pipeline_traces SET feedback = ?, feedback_comment = ? WHERE trace_id = ?",
            (feedback, comment, trace_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def get_feedback_stats(self) -> dict:
        rows = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN feedback = 1 THEN 1 ELSE 0 END) as positive,
                SUM(CASE WHEN feedback = -1 THEN 1 ELSE 0 END) as negative,
                SUM(CASE WHEN feedback IS NULL THEN 1 ELSE 0 END) as no_feedback
            FROM pipeline_traces
        """).fetchone()
        return dict(rows)


trace_store = TraceStore()
