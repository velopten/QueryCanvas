"""
조회 대상 DB 클라이언트 (SQLite).

도메인 팩의 generate_mock.py 가 만드는 mock DB에 붙는다. 다른 백엔드
(Postgres/Oracle 등)를 붙일 때는 execute/test_connection/close 세 메서드를 가진
어댑터를 여기에 추가하고 config.SQL_DIALECT 를 함께 바꾸면 된다 — 파이프라인은
이 인터페이스만 알고 있다.
"""

import sqlite3
from pathlib import Path

from config import DOMAIN
from logger import pipeline_logger

DB_PATH = Path(__file__).parent / f"mock_{DOMAIN}.db"


class SqliteDB:
    """SQLite 연결. 도메인 팩이 생성한 mock 데이터를 조회한다."""

    def __init__(self):
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()
        pipeline_logger.info("SqliteDB 초기화 완료")

    def _init_tables(self):
        """데이터가 없거나 오늘 생성된 것이 아니면 재생성 (상대 날짜 신선도 유지)."""
        from datetime import date

        import importlib
        generate = importlib.import_module(f"domains.{DOMAIN}.generate_mock").generate

        try:
            row = self.conn.execute(
                "SELECT VALUE FROM TB_META WHERE KEY = 'generated_on'"
            ).fetchone()
            if row and row[0] == date.today().isoformat():
                return  # 오늘 데이터 — 재생성 불필요
        except sqlite3.OperationalError:
            pass  # TB_META 없음 = 구버전/빈 DB → 재생성

        counts = generate(self.conn)
        pipeline_logger.info(
            "Mock 데이터 생성: " + ", ".join(f"{k}={v:,}" for k, v in counts.items())
        )

    def execute(self, sql: str, params=None) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(sql, params or [])
        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def test_connection(self) -> bool:
        try:
            self.execute("SELECT 1")
            return True
        except Exception:
            return False

    def close(self):
        self.conn.close()


_db_instance = None


def get_db():
    global _db_instance
    if _db_instance is None:
        _db_instance = SqliteDB()
    return _db_instance
