# -*- coding: utf-8 -*-
"""
커머스 도메인 Mock DB 생성기 — 데모/평가용 주문 데이터를 결정적(seed 고정)으로 생성한다.

특징:
- 날짜가 실행일 기준 상대 생성 (최근 12개월) → "이번 달/지난주" 질문이 항상 유효
- 고객 300명, 상품 64종/8카테고리, 주문 ~2.2만 건, 동명이인 고객 2쌍
- 스토리 있는 분포:
  * 뷰티 카테고리 매출이 최근 3개월 급성장 (비중 8% → 20%)
  * 월말(25일~) 프로모션 주문 스파이크
  * 부산 지역 고객의 반품률이 타 지역의 2배
  * 앱 채널 비중이 12개월에 걸쳐 35% → 55% 증가
- 결정적: 같은 날 실행하면 같은 데이터 (random seed 고정)

MockDB 는 시작 시 TB_META.generated_on 이 오늘이 아니면 자동 재생성한다.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta

SCHEMA = """
CREATE TABLE TB_CATEGORY (
    CATEGORY_CD TEXT PRIMARY KEY,
    CATEGORY_NAME TEXT NOT NULL
);
CREATE TABLE TB_PRODUCT (
    PROD_ID TEXT PRIMARY KEY,
    PROD_NAME TEXT NOT NULL,
    CATEGORY_CD TEXT NOT NULL,
    PRICE INTEGER NOT NULL,
    LAUNCH_DATE TEXT NOT NULL
);
CREATE TABLE TB_CUSTOMER (
    CUST_ID TEXT PRIMARY KEY,
    CUST_NAME TEXT NOT NULL,
    GRADE TEXT NOT NULL,
    REGION_CD TEXT NOT NULL,
    JOIN_DATE TEXT NOT NULL,
    EMAIL TEXT,
    PHONE TEXT,
    GENDER TEXT
);
CREATE TABLE TB_ORDER (
    ORDER_ID INTEGER PRIMARY KEY,
    CUST_ID TEXT NOT NULL,
    ORDER_DATE TEXT NOT NULL,
    STATUS TEXT NOT NULL,
    CHANNEL TEXT NOT NULL
);
CREATE TABLE TB_ORDER_ITEM (
    ORDER_ID INTEGER NOT NULL,
    PROD_ID TEXT NOT NULL,
    QTY INTEGER NOT NULL,
    AMOUNT INTEGER NOT NULL
);
CREATE TABLE TB_CODE (
    GRP_CD TEXT NOT NULL,
    CD TEXT NOT NULL,
    CD_NAME TEXT NOT NULL
);
CREATE TABLE TB_META (
    KEY TEXT PRIMARY KEY,
    VALUE TEXT
);
CREATE INDEX idx_order_date ON TB_ORDER(ORDER_DATE);
CREATE INDEX idx_order_cust ON TB_ORDER(CUST_ID);
CREATE INDEX idx_item_order ON TB_ORDER_ITEM(ORDER_ID);
"""

CODES = [
    ("ORDER_STATUS", "01", "주문접수"), ("ORDER_STATUS", "02", "배송중"),
    ("ORDER_STATUS", "03", "구매확정"), ("ORDER_STATUS", "04", "취소"),
    ("ORDER_STATUS", "05", "반품"),
    ("CHANNEL", "01", "웹"), ("CHANNEL", "02", "앱"), ("CHANNEL", "03", "오프라인"),
    ("GRADE", "01", "VIP"), ("GRADE", "02", "일반"), ("GRADE", "03", "신규"),
    ("REGION", "R01", "서울"), ("REGION", "R02", "부산"), ("REGION", "R03", "인천"),
    ("REGION", "R04", "대구"), ("REGION", "R05", "대전"), ("REGION", "R06", "광주"),
    ("REGION", "R07", "제주"),
]

CATEGORIES = [
    ("C01", "전자기기"), ("C02", "패션"), ("C03", "식품"), ("C04", "뷰티"),
    ("C05", "스포츠"), ("C06", "도서"), ("C07", "홈리빙"), ("C08", "완구"),
]

_PROD_WORDS = {
    "C01": ["무선 이어폰", "스마트워치", "블루투스 스피커", "보조배터리", "키보드", "모니터", "태블릿", "웹캠"],
    "C02": ["오버핏 셔츠", "슬랙스", "운동화", "니트", "패딩", "청바지", "코트", "볼캡"],
    "C03": ["그래놀라", "원두 커피", "올리브 오일", "파스타 면", "꿀", "견과류 믹스", "김 세트", "곡물 쉐이크"],
    "C04": ["수분 크림", "선크림", "립밤", "클렌징 폼", "앰플 세럼", "쿠션 팩트", "바디 로션", "헤어 오일"],
    "C05": ["요가 매트", "덤벨 세트", "러닝 벨트", "폼롤러", "축구공", "배드민턴 라켓", "무릎 보호대", "스포츠 양말"],
    "C06": ["소설 베스트셀러", "자기계발서", "요리책", "여행 에세이", "과학 교양서", "그림책", "경제 입문서", "시집"],
    "C07": ["아로마 캔들", "극세사 이불", "수납 정리함", "머그컵 세트", "무드등", "쿠션 커버", "원목 트레이", "가습기"],
    "C08": ["블록 세트", "보드게임", "인형", "RC카", "퍼즐 1000pc", "슬라임 키트", "미니카 세트", "물감 놀이 세트"],
}

_FIRST = ["민준", "서연", "지호", "하은", "도윤", "지우", "예준", "수아", "시우", "지아",
          "주원", "서현", "건우", "다은", "현우", "채원", "우진", "유나", "선우", "예린",
          "지훈", "소율", "은우", "가은", "정민", "하린", "태윤", "세아", "준서", "나윤"]
_LAST = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임", "한", "오", "서", "신", "권", "남궁"]

# 동명이인 (disambiguation 데모용)
DUPLICATE_NAMES = ["김민준", "이서연"]


def _pick_status(rng: random.Random, days_ago: int, is_busan: bool) -> str:
    """주문 상태 — 최근 주문은 접수/배송중, 과거는 확정 위주. 부산은 반품률 2배."""
    if days_ago <= 2:
        return rng.choice(["01", "01", "02"])
    if days_ago <= 7:
        return rng.choice(["02", "02", "03", "03"])
    r = rng.random()
    return_rate = 0.10 if is_busan else 0.05
    if r < 0.05:
        return "04"  # 취소
    if r < 0.05 + return_rate:
        return "05"  # 반품
    return "03"      # 구매확정


def generate(conn: sqlite3.Connection, today: date | None = None) -> dict[str, int]:
    """스키마 재생성 + 데이터 삽입. 반환: 테이블별 행수."""
    today = today or date.today()
    rng = random.Random(42)

    cur = conn.cursor()
    for row in cur.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index')").fetchall():
        if not row[0].startswith("sqlite_"):
            cur.execute(f"DROP {'INDEX' if 'idx' in row[0] else 'TABLE'} IF EXISTS {row[0]}")
    cur.executescript(SCHEMA)
    cur.executemany("INSERT INTO TB_CODE VALUES (?,?,?)", CODES)
    cur.executemany("INSERT INTO TB_CATEGORY VALUES (?,?)", CATEGORIES)

    # ── 상품 64종 ──
    products = []
    prices = {"C01": (15000, 450000), "C02": (12000, 220000), "C03": (4000, 45000),
              "C04": (8000, 65000), "C05": (6000, 120000), "C06": (9000, 35000),
              "C07": (7000, 90000), "C08": (10000, 80000)}
    i = 1
    for cat, _ in CATEGORIES:
        for word in _PROD_WORDS[cat]:
            lo, hi = prices[cat]
            price = rng.randrange(lo, hi, 500)
            launch = today - timedelta(days=rng.randint(60, 900))
            products.append((f"P{i:03d}", word, cat, price, launch.isoformat()))
            i += 1
    cur.executemany("INSERT INTO TB_PRODUCT VALUES (?,?,?,?,?)", products)

    # ── 고객 300명 (동명이인 2쌍 포함) ──
    customers = []
    used_names = set()
    regions = ["R01"] * 8 + ["R02"] * 4 + ["R03"] * 3 + ["R04"] * 2 + ["R05"] * 2 + ["R06"] + ["R07"]
    for n in range(1, 301):
        cid = f"C{n:04d}"
        if n <= 4:  # 동명이인: 김민준 ×2, 이서연 ×2 (지역/등급으로 구분)
            name = DUPLICATE_NAMES[0] if n <= 2 else DUPLICATE_NAMES[1]
        else:
            while True:
                name = rng.choice(_LAST) + rng.choice(_FIRST)
                if name not in used_names and name not in DUPLICATE_NAMES:
                    used_names.add(name)
                    break
        grade = "01" if rng.random() < 0.10 else ("03" if rng.random() < 0.33 else "02")
        region = rng.choice(regions)
        join = today - timedelta(days=rng.randint(10, 1100))
        customers.append((cid, name, grade, region,
                          join.isoformat(), f"user{n}@example.com",
                          f"010-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}",
                          rng.choice(["M", "F"])))
    cur.executemany("INSERT INTO TB_CUSTOMER VALUES (?,?,?,?,?,?,?,?)", customers)
    cust_region = {c[0]: c[3] for c in customers}
    vip_ids = [c[0] for c in customers if c[2] == "01"]
    all_ids = [c[0] for c in customers]

    # 카테고리별 상품 풀
    prods_by_cat = {}
    for p in products:
        prods_by_cat.setdefault(p[2], []).append(p)

    # ── 주문 12개월 ──
    orders, items = [], []
    order_id = 10000
    start = today - timedelta(days=365)
    total_days = 365

    for d in range(total_days + 1):
        day = start + timedelta(days=d)
        days_ago = (today - day).days
        progress = d / total_days  # 0=1년 전, 1=오늘

        base = 55 + (8 if day.weekday() >= 5 else 0)
        if day.day >= 25:
            base = int(base * 1.6)  # 월말 프로모션 스파이크
        n_orders = max(10, int(rng.gauss(base, 8)))

        # 뷰티 급성장: 품목 비중 8% → 최근 3개월 최대 32% (뷰티 단가가 낮아 매출 기준으로도 뚜렷하도록)
        beauty_share = 0.08 + (0.24 * max(0.0, (progress - 0.75) / 0.25))
        app_share = 0.35 + 0.20 * progress  # 앱 채널 증가

        for _ in range(n_orders):
            order_id += 1
            cust = rng.choice(vip_ids) if rng.random() < 0.25 else rng.choice(all_ids)
            is_busan = cust_region[cust] == "R02"
            status = _pick_status(rng, days_ago, is_busan)
            r = rng.random()
            channel = "02" if r < app_share else ("01" if r < app_share + 0.35 else "03")
            orders.append((order_id, cust, day.isoformat(), status, channel))

            for _ in range(rng.randint(1, 3)):
                if rng.random() < beauty_share:
                    prod = rng.choice(prods_by_cat["C04"])
                else:
                    cat = rng.choice([c for c, _ in CATEGORIES])
                    prod = rng.choice(prods_by_cat[cat])
                qty = rng.randint(1, 3)
                items.append((order_id, prod[0], qty, prod[3] * qty))

    cur.executemany("INSERT INTO TB_ORDER VALUES (?,?,?,?,?)", orders)
    cur.executemany("INSERT INTO TB_ORDER_ITEM VALUES (?,?,?,?)", items)
    cur.execute("INSERT INTO TB_META VALUES ('generated_on', ?)", (today.isoformat(),))
    conn.commit()

    return {
        "TB_CATEGORY": len(CATEGORIES), "TB_PRODUCT": len(products),
        "TB_CUSTOMER": len(customers), "TB_ORDER": len(orders),
        "TB_ORDER_ITEM": len(items),
    }
