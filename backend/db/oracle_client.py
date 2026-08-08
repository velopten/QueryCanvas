"""
DB 클라이언트. MOCK_DB=true이면 SQLite, false이면 Oracle에 연결한다.
"""

import sqlite3
from pathlib import Path

from config import MOCK_DB, ORACLE_DSN, ORACLE_PASSWORD, ORACLE_USER
from logger import pipeline_logger

from config import DOMAIN
MOCK_DB_PATH = Path(__file__).parent / f"mock_{DOMAIN}.db"


class MockDB:
    """SQLite 기반 Mock DB. Oracle 없이 개발/테스트용."""

    def __init__(self):
        self.conn = sqlite3.connect(str(MOCK_DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()
        pipeline_logger.info("MockDB(SQLite) 초기화 완료")

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

    def _oracle_to_sqlite(self, sql: str) -> str:
        """Oracle SQL을 SQLite 호환으로 변환한다."""
        import re
        s = sql
        # SYSDATE → date('now')
        s = re.sub(r"\bSYSDATE\b", "date('now')", s, flags=re.IGNORECASE)
        # TO_CHAR(col, 'YYYYMM') → strftime('%Y%m', col)
        s = re.sub(
            r"TO_CHAR\s*\(\s*(.+?)\s*,\s*'YYYYMM'\s*\)",
            r"strftime('%Y%m', \1)",
            s, flags=re.IGNORECASE,
        )
        # TO_CHAR(col, 'YYYY-MM') → strftime('%Y-%m', col)
        s = re.sub(
            r"TO_CHAR\s*\(\s*(.+?)\s*,\s*'YYYY-MM'\s*\)",
            r"strftime('%Y-%m', \1)",
            s, flags=re.IGNORECASE,
        )
        # TO_CHAR(col, 'YYYY') → strftime('%Y', col)
        s = re.sub(
            r"TO_CHAR\s*\(\s*(.+?)\s*,\s*'YYYY'\s*\)",
            r"strftime('%Y', \1)",
            s, flags=re.IGNORECASE,
        )
        # TO_CHAR(col, 'HH24:MI') → strftime('%H:%M', col)
        s = re.sub(
            r"TO_CHAR\s*\(\s*(.+?)\s*,\s*'HH24:MI'\s*\)",
            r"strftime('%H:%M', \1)",
            s, flags=re.IGNORECASE,
        )
        # TRUNC(SYSDATE) already handled, but TRUNC(date, 'MM') → date(col, 'start of month')
        s = re.sub(
            r"TRUNC\s*\(\s*(.+?)\s*,\s*'MM'\s*\)",
            r"date(\1, 'start of month')",
            s, flags=re.IGNORECASE,
        )
        s = re.sub(
            r"TRUNC\s*\(\s*(.+?)\s*\)",
            r"date(\1)",
            s, flags=re.IGNORECASE,
        )
        # ADD_MONTHS(date, -N) → date(col, 'N months')
        s = re.sub(
            r"ADD_MONTHS\s*\(\s*(.+?)\s*,\s*(-?\d+)\s*\)",
            lambda m: f"date({m.group(1)}, '{m.group(2)} months')",
            s, flags=re.IGNORECASE,
        )
        # NVL(a, b) → COALESCE(a, b)
        s = re.sub(r"\bNVL\s*\(", "COALESCE(", s, flags=re.IGNORECASE)
        # FETCH FIRST N ROWS ONLY → LIMIT N
        s = re.sub(
            r"FETCH\s+FIRST\s+(\d+)\s+ROWS\s+ONLY",
            r"LIMIT \1",
            s, flags=re.IGNORECASE,
        )
        # TO_CHAR(col, 'MM-DD') → strftime('%m-%d', col)
        s = re.sub(
            r"TO_CHAR\s*\(\s*(.+?)\s*,\s*'MM-DD'\s*\)",
            r"strftime('%m-%d', \1)",
            s, flags=re.IGNORECASE,
        )
        # TO_CHAR(col, 'SSSSS') → (cast(strftime('%H', col) as integer)*3600 + cast(strftime('%M', col) as integer)*60 + cast(strftime('%S', col) as integer))
        s = re.sub(
            r"TO_CHAR\s*\(\s*(.+?)\s*,\s*'SSSSS'\s*\)",
            r"(CAST(strftime('%H', \1) AS INTEGER)*3600 + CAST(strftime('%M', \1) AS INTEGER)*60 + CAST(strftime('%S', \1) AS INTEGER))",
            s, flags=re.IGNORECASE,
        )
        # EXTRACT(HOUR FROM (col1 - col2)) → hours diff
        # Replace full EXTRACT(HOUR FROM ...) + EXTRACT(MINUTE FROM ...) patterns
        # with SQLite time-diff calculation
        s = re.sub(
            r"EXTRACT\s*\(\s*HOUR\s+FROM\s*\(?\s*(\w+\.\w+)\s*-\s*(\w+\.\w+)\s*\)?\s*\)",
            r"(CAST(strftime('%H', \1) AS INTEGER) - CAST(strftime('%H', \2) AS INTEGER))",
            s, flags=re.IGNORECASE,
        )
        s = re.sub(
            r"EXTRACT\s*\(\s*MINUTE\s+FROM\s*\(?\s*(\w+\.\w+)\s*-\s*(\w+\.\w+)\s*\)?\s*\)",
            r"(CAST(strftime('%M', \1) AS INTEGER) - CAST(strftime('%M', \2) AS INTEGER))",
            s, flags=re.IGNORECASE,
        )
        # Generic EXTRACT(field FROM col) → strftime equivalent
        s = re.sub(
            r"EXTRACT\s*\(\s*HOUR\s+FROM\s+(\w+\.\w+)\s*\)",
            r"CAST(strftime('%H', \1) AS INTEGER)",
            s, flags=re.IGNORECASE,
        )
        s = re.sub(
            r"EXTRACT\s*\(\s*MINUTE\s+FROM\s+(\w+\.\w+)\s*\)",
            r"CAST(strftime('%M', \1) AS INTEGER)",
            s, flags=re.IGNORECASE,
        )
        s = re.sub(
            r"EXTRACT\s*\(\s*SECOND\s+FROM\s+(\w+\.\w+)\s*\)",
            r"CAST(strftime('%S', \1) AS INTEGER)",
            s, flags=re.IGNORECASE,
        )
        # ROUND(expr, n) is supported in SQLite, no change needed
        # CONNECT BY / START WITH → not supported in SQLite, leave as-is (will fail gracefully)
        return s

    def execute(self, sql: str, params=None) -> list[dict]:
        converted = self._oracle_to_sqlite(sql)
        pipeline_logger.debug(f"SQLite 변환: {converted[:200]}")
        cur = self.conn.cursor()
        cur.execute(converted, params or [])
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


class OracleDB:
    """Oracle 읽기 전용 연결."""

    def __init__(self):
        import oracledb
        self.pool = oracledb.create_pool(
            user=ORACLE_USER,
            password=ORACLE_PASSWORD,
            dsn=ORACLE_DSN,
            min=1,
            max=5,
        )
        pipeline_logger.info(f"OracleDB 연결 풀 생성: {ORACLE_DSN}")

    def execute(self, sql: str, params=None) -> list[dict]:
        with self.pool.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or [])
                columns = [col[0] for col in cur.description] if cur.description else []
                rows = cur.fetchall()
                return [dict(zip(columns, row)) for row in rows]

    def test_connection(self) -> bool:
        try:
            self.execute("SELECT 1 FROM DUAL")
            return True
        except Exception:
            return False

    def close(self):
        self.pool.close()


_db_instance = None


def get_db():
    global _db_instance
    if _db_instance is None:
        _db_instance = MockDB() if MOCK_DB else OracleDB()
    return _db_instance
