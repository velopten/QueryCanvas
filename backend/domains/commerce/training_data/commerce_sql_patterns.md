# 커머스 SQL 패턴 (SQLite)

## 패턴 1. 카테고리별 매출 집계

### 자연어 질문 예시
- "카테고리별 매출 보여줘"
- "최근 3개월 카테고리별 매출 비중"

```sql
SELECT c.CATEGORY_NAME AS 카테고리, SUM(i.AMOUNT) AS 매출액, COUNT(DISTINCT o.ORDER_ID) AS 주문수
FROM TB_ORDER o
JOIN TB_ORDER_ITEM i ON o.ORDER_ID = i.ORDER_ID
JOIN TB_PRODUCT p ON i.PROD_ID = p.PROD_ID
JOIN TB_CATEGORY c ON p.CATEGORY_CD = c.CATEGORY_CD
WHERE o.STATUS NOT IN ('04', '05')
  AND o.ORDER_DATE >= date('now', '-3 months')
GROUP BY c.CATEGORY_NAME
ORDER BY 매출액 DESC
```

설명: 매출은 항상 취소/반품 제외. 품목 금액은 AMOUNT에 이미 계산되어 있음.

---

## 패턴 2. 월별/일별 매출 추이 (시계열)

### 자연어 질문 예시
- "월별 매출 추이"
- "이번 달 일별 매출"

```sql
SELECT strftime('%Y-%m', o.ORDER_DATE) AS 월, SUM(i.AMOUNT) AS 매출액
FROM TB_ORDER o
JOIN TB_ORDER_ITEM i ON o.ORDER_ID = i.ORDER_ID
WHERE o.STATUS NOT IN ('04', '05')
  AND o.ORDER_DATE >= date('now', '-6 months')
GROUP BY 월
ORDER BY 월
```

---

## 패턴 3. 상품 판매 순위 (TOP N)

### 자연어 질문 예시
- "가장 많이 팔린 상품 TOP 5"
- "이번 달 베스트셀러"

```sql
SELECT p.PROD_ID, p.PROD_NAME AS 상품명, c.CATEGORY_NAME AS 카테고리,
       SUM(i.QTY) AS 판매수량, SUM(i.AMOUNT) AS 매출액
FROM TB_ORDER o
JOIN TB_ORDER_ITEM i ON o.ORDER_ID = i.ORDER_ID
JOIN TB_PRODUCT p ON i.PROD_ID = p.PROD_ID
JOIN TB_CATEGORY c ON p.CATEGORY_CD = c.CATEGORY_CD
WHERE o.STATUS NOT IN ('04', '05')
  AND strftime('%Y-%m', o.ORDER_DATE) = strftime('%Y-%m', 'now')
GROUP BY p.PROD_ID, p.PROD_NAME, c.CATEGORY_NAME
ORDER BY 판매수량 DESC
LIMIT 5
```

설명: 상품명과 함께 PROD_ID 를 반드시 SELECT (클릭 드릴다운).

---

## 패턴 4. 지역/등급별 고객 분석

### 자연어 질문 예시
- "지역별 반품률"
- "등급별 고객 수"

```sql
SELECT rc.CD_NAME AS 지역,
       COUNT(*) AS 전체주문,
       SUM(CASE WHEN o.STATUS = '05' THEN 1 ELSE 0 END) AS 반품건수,
       ROUND(100.0 * SUM(CASE WHEN o.STATUS = '05' THEN 1 ELSE 0 END) / COUNT(*), 1) AS 반품률
FROM TB_ORDER o
JOIN TB_CUSTOMER cu ON o.CUST_ID = cu.CUST_ID
JOIN TB_CODE rc ON rc.GRP_CD = 'REGION' AND rc.CD = cu.REGION_CD
GROUP BY rc.CD_NAME
ORDER BY 반품률 DESC
```

---

## 패턴 5. 특정 고객의 주문 조회 (ID 확정 후)

### 자연어 질문 예시
- "C0001(김민준)의 최근 주문 내역"
- "김민준 고객 주문" (동명이인이면 후보 확인 후 ID로)

```sql
SELECT o.ORDER_DATE AS 주문일, sc.CD_NAME AS 상태, ch.CD_NAME AS 채널,
       SUM(i.AMOUNT) AS 주문금액
FROM TB_ORDER o
JOIN TB_ORDER_ITEM i ON o.ORDER_ID = i.ORDER_ID
JOIN TB_CODE sc ON sc.GRP_CD = 'ORDER_STATUS' AND sc.CD = o.STATUS
JOIN TB_CODE ch ON ch.GRP_CD = 'CHANNEL' AND ch.CD = o.CHANNEL
WHERE o.CUST_ID = 'C0001'
  AND o.ORDER_DATE >= date('now', '-3 months')
GROUP BY o.ORDER_ID, o.ORDER_DATE, sc.CD_NAME, ch.CD_NAME
ORDER BY o.ORDER_DATE DESC
```

---

## 패턴 6. 채널별 비중 추이

### 자연어 질문 예시
- "앱 주문 비중이 늘고 있어?"
- "채널별 주문 추이"

```sql
SELECT strftime('%Y-%m', o.ORDER_DATE) AS 월, ch.CD_NAME AS 채널, COUNT(*) AS 주문수
FROM TB_ORDER o
JOIN TB_CODE ch ON ch.GRP_CD = 'CHANNEL' AND ch.CD = o.CHANNEL
WHERE o.ORDER_DATE >= date('now', '-6 months')
GROUP BY 월, ch.CD_NAME
ORDER BY 월, ch.CD_NAME
```
