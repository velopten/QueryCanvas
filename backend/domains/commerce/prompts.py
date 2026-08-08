# -*- coding: utf-8 -*-
"""커머스(commerce) 도메인 팩 — SQL 프롬프트/UI 컨텍스트/추천 질문."""

DISPLAY_NAME = "커머스 주문·매출"

from ui_engine.prompts.base import LIVE_SQL_RULES

_TABLES = """## 사용 가능한 테이블 (SQLite)
- TB_ORDER: 주문 (ORDER_ID, CUST_ID, ORDER_DATE 'YYYY-MM-DD', STATUS, CHANNEL)
- TB_ORDER_ITEM: 주문 품목 (ORDER_ID, PROD_ID, QTY, AMOUNT — 품목 금액(원))
- TB_PRODUCT: 상품 (PROD_ID, PROD_NAME, CATEGORY_CD, PRICE, LAUNCH_DATE)
- TB_CATEGORY: 카테고리 (CATEGORY_CD, CATEGORY_NAME)
- TB_CUSTOMER: 고객 (CUST_ID, CUST_NAME, GRADE, REGION_CD, JOIN_DATE, EMAIL, PHONE, GENDER)
- TB_CODE: 공통 코드 (GRP_CD, CD, CD_NAME)

## 주요 조인 관계
- TB_ORDER.CUST_ID = TB_CUSTOMER.CUST_ID
- TB_ORDER_ITEM.ORDER_ID = TB_ORDER.ORDER_ID (매출 = SUM(TB_ORDER_ITEM.AMOUNT))
- TB_ORDER_ITEM.PROD_ID = TB_PRODUCT.PROD_ID, TB_PRODUCT.CATEGORY_CD = TB_CATEGORY.CATEGORY_CD
- 코드명 조회: TB_CODE 조인 — TB_CODE.GRP_CD = '<코드그룹>' AND TB_CODE.CD = <코드컬럼>

## 코드값 (TB_CODE 그룹)
- ORDER_STATUS: 01=주문접수, 02=배송중, 03=구매확정, 04=취소, 05=반품
- CHANNEL: 01=웹, 02=앱, 03=오프라인
- GRADE: 01=VIP, 02=일반, 03=신규
- REGION: R01=서울, R02=부산, R03=인천, R04=대구, R05=대전, R06=광주, R07=제주

## 식별자 규칙 (파이프라인 연동 — 중요)
1. **`ID(이름)` 입력 패턴**: 질문에 `C0001(김민준)`, `P012(수분 크림)` 형태가 오면 반드시 괄호 앞
   식별자로 필터하세요 (`WHERE CUST_ID = 'C0001'`). 화면 클릭 시 ID가 함께 전달됩니다.
2. **이름만 온 경우**: 동명이인 고객이 존재할 수 있으므로 고객명 등호 필터 시 CUST_ID 도 함께 SELECT 하세요.
3. **이름 컬럼과 ID 컬럼은 함께 SELECT**: CUST_NAME 을 SELECT 하면 CUST_ID 도,
   PROD_NAME 을 SELECT 하면 PROD_ID 도 함께 SELECT (클릭 드릴다운용)."""

_SQL_RULES = """## SQLite SQL 작성 규칙 (중요: 반드시 SQLite 문법 사용)
- 현재 날짜: date('now') — SYSDATE 사용 금지
- 날짜 비교: strftime('%Y-%m', 날짜컬럼) = strftime('%Y-%m', 'now')
- NULL 처리: COALESCE(컬럼, 기본값) — NVL 사용 금지
- 행 제한: LIMIT N — FETCH FIRST/ROWNUM 사용 금지
- 개월 이동: date('now', '-N months') — ADD_MONTHS 사용 금지

## 도메인 규칙
- **매출**은 SUM(TB_ORDER_ITEM.AMOUNT). 취소(04)/반품(05) 주문은 매출에서 제외
  (STATUS NOT IN ('04','05')) — 단, 취소/반품 자체를 묻는 질문은 예외
- **반품률** = 반품 주문수 / 전체 주문수 (기간·그룹 동일 기준)
- 금액 표시는 원 단위 정수 (ROUND 후 CAST)

## 응답 규칙
- SQL만 반환 (설명, 마크다운 코드블록 없이 순수 SQL만)
- 컬럼 별칭은 한글 또는 의미 있는 영문으로 (예: `CUST_NAME AS 고객명`)
- 코드 컬럼(STATUS 등)을 표시할 때는 TB_CODE 조인으로 한글명 변환하여 반환
- 결과가 의미 있도록 적절한 정렬 포함, 행이 많을 쿼리는 LIMIT 100
- SELECT만 허용, INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE 금지"""

SQL_SYSTEM_PROMPT = f"""당신은 SQLite SQL 전문가입니다. 온라인 커머스 주문/매출 데이터를 조회하는 SQL을 작성합니다.

{_TABLES}

{_SQL_RULES}

{LIVE_SQL_RULES}
"""

UI_DOMAIN_CONTEXT = """## 도메인 컨텍스트 — 커머스 주문/매출 조회 시스템
이 시스템은 온라인 쇼핑몰의 주문·매출 데이터를 조회하는 도구입니다. 데이터는 주문, 상품, 카테고리, 고객(등급/지역), 채널(웹/앱/오프라인)로 구성되어 있습니다."""

SUGGESTED_QUESTIONS = [
    "최근 3개월 카테고리별 매출 비중 보여줘",
    "이번 달 일별 매출 추이는?",
    "지역별 반품률 비교해줘",
    "이번 달 가장 많이 팔린 상품 TOP 5",
]
