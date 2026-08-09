# -*- coding: utf-8 -*-
"""도메인 무관 공용 프롬프트 블록 — 모든 도메인 팩이 공유한다."""

LIVE_SQL_RULES = """## 살아있는 SQL + 필터 승격 (화면 재사용을 위한 규칙)
이 SQL은 화면으로 저장되어 반복 실행될 수 있습니다.

1. **상대 기간은 반드시 실행 시점 상대 표현으로**: "이번 달/지난주/최근 3개월" 같은 표현을
   절대 날짜 리터럴로 굳히지 마세요. 절대 날짜는 사용자가 특정 시점(예: "2024년 1분기")을
   명시한 경우에만 사용합니다.

2. **저카디널리티 범주 조건은 UI 필터로 승격**: 질문이 특정 범주값(분류/구분/유형 등)을
   지목하면, WHERE로 좁히는 대신 (a) 해당 컬럼을 SELECT에 포함하고 (b) 전체 범주를 조회한 뒤
   (c) promoted_filters에 {"column": "<SELECT 별칭 기준 컬럼명>", "value": "<지목된 값>"}을 보고하세요.
   화면에서 필터가 그 값으로 초기 선택되어 사용자가 다른 범주로 즉시 전환할 수 있습니다.
   - 집계 질문이면 해당 범주로 GROUP BY (예: "A 분류 건수" → 분류별 GROUP BY + 필터 승격)
   - 승격 금지: 개인 식별자/이름 조건, 기간 조건, 고카디널리티 컬럼, 승격 시 행수가 과도해지는 경우
   - **순위/TOP N/최다·최소 질문은 승격 대상 아님** — 질문이 요구한 N 그대로 LIMIT N 유지
     (예: "1등은?" → LIMIT 1~5, 전체 순위로 넓히지 말 것)
   - 승격한 조건이 없으면 promoted_filters는 빈 배열"""


# UI 결정 공용 규칙 (출력 계약/위젯 원칙/Chart 기준/필터/BriefingCard/PII)
# — 도메인 팩의 UI_DOMAIN_CONTEXT 뒤에 붙는다
UI_BASE_RULES = """

## 출력 계약 (반드시 준수)
- **모든 메시지에 "version": "v0.9" 필드 필수.**
- 첫 메시지는 createSurface, 이후에는 updateComponents만. updateDataModel/deleteSurface 금지.
- root 컴포넌트의 id는 반드시 "root" (Column 권장).
- 출력 형태 (정확히 이 구조):
<a2ui-json>[
{"version":"v0.9","createSurface":{"surfaceId":"result","catalogId":"query-canvas/v1"}},
{"version":"v0.9","updateComponents":{"surfaceId":"result","components":[{"id":"root","component":"Column","children":["briefing","data_table"]},{"id":"briefing","component":"BriefingCard","headline":"..."},{"id":"data_table","component":"DataTable","rows":{"path":"/rows"}}]}}
]</a2ui-json>
- SQL 결과 데이터는 이미 데이터 모델 /rows 에 주입되어 있음.
  Chart/DataTable/Filter의 rows에는 항상 {"path": "/rows"} 바인딩만 사용 — 행 데이터 인라인 절대 금지.
- 컴포넌트 id는 의미있는 영문으로 (예: "briefing", "main_chart", "data_table").

## 시각화 원칙
- 표준 구성: BriefingCard + (Filter 선택) + Chart + DataTable 조합
- 차트 종류: bar(비교) / line(추이) / pie(비율) / gauge(달성률) / heatmap(2차원)

## 위젯 선택 원칙 (중요)
- **StatCard**: 단일 수치가 답인 질문("몇 명이야?", "총 얼마야?")은 gauge/표 대신 StatCard로
  크게 표시. 핵심 지표 2~4개면 Row 안에 StatCard를 나란히 배치. delta에 비교값(전월 대비 등).
- **Notice**: 주의가 필요한 팩트 전달 전용 — 임계 초과 경고(warning), 데이터 없음/부분 데이터
  안내(info), 오류(error). 일반 요약은 BriefingCard 소관이므로 중복 금지.
- **비교 데이터는 한 화면에**: 사용자가 서로 비교해야 할 데이터를 여러 화면/영역으로 나누지
  마세요 — 한 화면의 표/차트로 배치합니다.
- **Filter는 선택지가 한눈에 들어올 때만**: 저카디널리티 범주(분류/구분/유형) 전용.
  값이 많은 컬럼은 DataTable의 자체 검색이 처리하므로 Filter로 만들지 마세요.

## Chart 사용 기준 (중요)
Chart는 **집계된 데이터**를 시각화할 때만 의미 있음. 다음 경우 Chart를 만들지 마세요:
- raw 행 데이터 (건별 상세 기록 등) — yField로 쓸 숫자 컬럼이 없음
- 컬럼이 5개 이상이고 모두 detail 정보 (이름, 식별자, 날짜, 시각 등)
- 단일 행 데이터 (gauge 제외)

Chart가 적합한 경우:
- 집계 SQL 결과 (`COUNT(*)`, `SUM()`, `AVG()` 등이 SELECT에 있음)
- xField가 카테고리(분류/구분/유형 등), yField가 숫자(건수/합계/평균)인 명확한 구조
- 시계열 데이터 (월별, 일별 추이)

raw 데이터만 있고 집계가 없으면 BriefingCard + DataTable 2개로만 구성하세요.
Chart는 최대 1개만 만드세요.

## 필터 사용 (선택)
범주형 컬럼(분류명, 구분, 유형 등)이 있어서 사용자가 분류해서 보고 싶을 만한 데이터인 경우 Filter 컴포넌트를 추가하면 좋음.

사용 방법:
- Filter 컴포넌트 1개 추가 (Chart와 DataTable 위에 배치)
- Filter: columns에 필터 가능한 컬럼명 배열, rows는 {"path": "/rows"}, filters는 {"path": "/filters"}
- Chart와 DataTable에도 같은 filters: {"path": "/filters"} 를 추가하면 사용자 필터 선택이 자동 반영됨
- [승격된 필터]가 주어지면 defaultValue에 그 값을 그대로 설정 (화면이 그 값으로 초기 필터링됨)

필터 추가 권장 케이스: 분류/구분/유형/지역 등 카테고리 컬럼이 있는 데이터
필터 불필요 케이스: 행이 적거나(<10) 모두 unique한 데이터, 시계열 데이터, 단일 값 표시(gauge)

## 숫자 표기 (DataTable.columnFormats)
숫자 컬럼은 columnFormats로 단위를 붙여야 읽힌다. 컬럼명을 키로, 필요한 컬럼만 지정.
- type: number(천단위 구분) / percent(% 접미 — 값이 이미 0~100일 때만) / text(포맷 해제)
- decimals: 소수 자릿수 고정, unit: 숫자 뒤 단위, currency: 숫자 앞 통화기호
- 예: "columnFormats":{"매출액":{"type":"number","currency":"₩"},"건수":{"type":"number","unit":"건"},"비율":{"type":"percent","decimals":1}}
- 지정하지 않아도 큰 숫자는 자동으로 천단위 구분됨 — 단위/비율 의미가 있는 컬럼에만 쓸 것
- 식별자·코드·연도 컬럼에는 쓰지 말 것 (필요하면 type:"text")

## BriefingCard 작성 규칙
- headline: 핵심 한 줄 (15자 내외). 예: "3개 분류 월별 집계"
- bullets: 객관적 수치 포인트 (각 30자 이내, 최대 5개) — 문자열 배열 리터럴
- note: 데이터 해석 시 참고할 점 (선택)
- 객관적 팩트만 나열할 것. 판단/평가/원인 추정 금지
- 좋은 예: "A 분류 189건 (전체의 63%, 평균 3.0)"
- 나쁜 예: "A 분류의 수치가 심각한 수준입니다"

## 개인정보 처리
- 샘플 데이터의 개인정보 컬럼은 [PERSON_1], [PID_1] 등의 매핑 키로 대체되어 있을 수 있음
- BriefingCard의 headline/bullets/note에는 매핑 키를 절대 포함하지 마세요 (집계 수치만 사용)
- 개인 단위 정보는 차트/테이블 바인딩으로만 표시 (실데이터는 클라이언트에서 주입됨)
"""
