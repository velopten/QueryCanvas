# QueryCanvas

AI 자연어 조회 + 동적 UI 생성. 도메인 팩 교체로 업무 시스템이 바뀌는 구조 (개인 포트폴리오 프로젝트).

## 실행
- Backend: `cd backend && uvicorn main:app --port 8008` (8000은 다른 프로젝트가 사용 중)
- Frontend: `cd frontend && npm run dev`
- **도메인 팩**: `DOMAIN=commerce`(기본) — 프롬프트/mock/학습데이터/골든셋이
  `backend/domains/<DOMAIN>/`으로 통째 전환. 도메인별 mock db·chroma 컬렉션·SQL 캐시 분리
- DB: mock SQLite 기본 (도메인 팩의 `generate_mock.py`가 실행일 기준 최근 12개월 데이터를 매일
  자동 재생성). Oracle은 MOCK_DB=false 옵션
- 테스트: `cd backend && python -m pytest tests` (LLM 호출 없음, requirements-test.txt만 필요)
- 평가: `cd backend && python eval/run_eval.py` (현재 DOMAIN의 골든셋, MOCK_DB=true 필요)
  - **비용 주의**: 사용자 개인 크레딧 — 가능하면 `--case`/`--limit` 부분 실행, 전체 실행은 꼭 필요할 때만
  - 웹 UI: 관리자 화면 "평가" 탭 — 실행(SSE 실시간), 이력 조회, 실행 2건 나란히 비교

## 환경설정
- `backend/.env.example` 을 `backend/.env` 로 복사 후 `ANTHROPIC_API_KEY` 채우기 (.env 는 gitignore)
- 셸/시스템 환경변수 주입 대신 `.env` 사용
- 임베딩 기본값은 `BAAI/bge-m3` (chroma 컬렉션이 dim=1024 로 생성됨 — 모델 바꾸면
  chroma_data 삭제 후 재학습)

## LLM 설정 (`backend/config.py`)
- 역할별 모델 맵: `MODEL_SQL_GEN`(기본 sonnet-5) / `MODEL_UI_DECISION`(sonnet-5) / `MODEL_CLASSIFY`, `MODEL_FIX`(haiku-4-5) / `MODEL_CURATOR`(sonnet-5) — 환경변수로 오버라이드
- `SQL_GEN_EFFORT`: SQL 생성 effort (low~max). 모델/effort 변경 전후 `eval/run_eval.py`로 회귀 확인
- `AGENTIC_SQL=true`(기본): SQL 생성이 tool use 루프(`text_to_sql/sql_agent.py`)로 동작 — 모델이 search_schema/find_person/find_group/preview_sql 도구 사용. false면 1-pass 생성 폴백
- 모든 분류/생성 호출은 structured output(json_schema) 사용 — 텍스트 파싱 금지
- 시스템 프롬프트는 [안정 블록(cache_control) + 휘발 블록] 2단 구성 — 안정 블록에 휘발 내용 넣지 말 것

## 도메인 중립 원칙 (중요)
애플리케이션 코드에는 특정 업무 도메인 용어를 넣지 않는다. 도메인 결합 자산은 전부
`backend/domains/<name>/` 팩 안에만 존재한다.
- 엔티티 추상화는 `person`(개인) / `group`(그룹·분류) / `range`(기간) 세 종류.
  info_collector case id는 `person_exact` / `person_partial` / `group_exact` / `group_partial`
- 공용 프롬프트(`ui_engine/prompts/base.py`)의 예시는 도메인 무관 표현으로 유지

## 백엔드 (`backend/`)
- `main.py` — FastAPI 진입점, SSE 스트리밍 (`sse_event`), `/query` 파이프라인
- `config.py` — 환경설정 (`API_HOST`, `API_PORT`, `MOCK_DB`, `DOMAIN`, `domain_dir()`)
- `domains/<name>/` — **도메인 팩**: `prompts.py`(SQL 프롬프트+UI 컨텍스트+추천 질문),
  `generate_mock.py`, `training_data/`, `virtual_views/`, `info_collectors.yaml`, `golden_questions.yaml`
  - 공용 프롬프트 블록은 `ui_engine/prompts/base.py`, 조립은 `ui_engine/prompts/loader.py`
  - 새 도메인 추가 = 이 6종 자산 작성 (코드 수정 불필요)
- `text_to_sql/`
  - `vector_store.py` — Chroma 기반 RAG, 학습 데이터 임베딩 (`train()`)
  - `embedding.py` — 임베딩 모델
  - `sql_generator.py` — LLM 기반 NL→SQL (1-pass, 폴백 경로)
  - `sql_agent.py` — 에이전틱 NL→SQL (tool use 루프, 기본 경로)
  - `sql_fixer.py` — 실행 실패 시 SQL 자가 수정
  - `sql_cache.py` — 질의 결과 캐시
  - `training_curator.py` — 학습 데이터 큐레이션
  - `virtual_view_resolver.py` — 가상 view → base SQL 치환
  - `sql_liveness.py` — 화면 저장 시 절대 날짜 → 상대 표현 변환 (경량 LLM 1회)
- `ui_engine/`
  - `ui_decision.py` — 결과 → UI 결정 (LLM이 A2UI v0.9 메시지 스트리밍 출력, SDK 파서로 검증/힐링)
  - `a2ui_catalog.py` — A2UI 카탈로그(커스텀 6종 등록) + 시스템 프롬프트 생성 + 파서 (`a2ui-agent-sdk`)
  - `anonymizer.py` — PII 마스킹 (LLM에는 마스킹 샘플만, rows 본문은 LLM 미경유)
  - `question_classifier.py` — 질문 분류
  - `info_collector.py` — 도메인 팩 yaml 템플릿 기반 후보 조회 (LLM 미사용)
  - `cost_calculator.py` — LLM 비용 추정
- `db/`
  - `oracle_client.py` (도메인별 mock db 초기화), `query_history.py`, `trace_store.py`
  - `saved_views.py` — 저장된 뷰(화면의 메뉴화). 열 때 SQL만 재실행 + 저장된 A2UI spec 바인딩 (LLM 0회)
- `scripts/` — DDL 추출/파싱 유틸 (실 DB 온보딩용, 스키마 무관)

## 프론트엔드 (`frontend/`, React + Vite + TS)
- 디자인 토큰: `index.css` `@theme` — 중립색 gray→slate 재매핑, 주 액션 `ink`, 단일 액센트 `accent`(violet, 활성/선택/포커스 전용), 사이드바 `rail`. 새 UI는 blue-* 대신 이 토큰 사용
- `pages/QueryPage.tsx` — 메인 질의 UI, SSE 스트림 소비
- `pages/admin/` — 관리자 콘솔 (좌측 사이드바 라우팅 `/admin/:section`)
  - `sections.ts` — 메뉴 트리 정의 (사이드바 + 라우트가 공유). 새 관리자 메뉴는 여기에 등록
  - `AdminLayout.tsx` — 다크 레일 사이드바 + Outlet
  - 패널 9종: Prompts/Training/Vector/VirtualView/Weights/Eval/Settings/Traces/Logs
    (정보 수집기 템플릿은 도메인 팩 자산 — 관리 UI 없음, yaml 직접 편집)
- `components/ui/` — 공통 프리미티브 (Button/Panel/Badge/Field/Toggle/EmptyState/StatusText). 새 화면은 이걸로 조립
- `components/`
  - `ChatInput.tsx`, `Sidebar.tsx`, `StreamingSteps.tsx`
  - `A2uiRenderer.tsx` — A2UI 메시지 렌더러 (surface 생성 + rows/filters 데이터 모델 주입 담당)
  - `SpecRenderer.tsx` — 레거시 json-render spec 렌더러 (과거 히스토리 재생 전용)
  - `TraceViewer.tsx`, `FeedbackButtons.tsx`, `MarkdownRenderer.tsx`
- `lib/`
  - `a2ui/catalog.tsx` — A2UI 카탈로그 (Chart/DataTable/BriefingCard/Filter/StatCard/Notice — zod3 알리아스로 스키마 작성)
  - `a2ui/renderCheck.tsx` — jsdom 자동 검증 (`npm run check:a2ui`)
  - `dataDisplay.ts` — 필터/클릭 변환 공용 헬퍼 (a2ui ↔ 레거시 공유)
  - `registry.ts`, `catalog.ts`, `customComponents.tsx` — 레거시 json-render 경로 (히스토리 재생 전용)
  - `chartOption.ts` — ECharts 옵션 빌더
  - `elementClickContext.ts` — 드릴다운/클릭 컨텍스트
- `utils/api.ts` — 백엔드 API/SSE 클라이언트 (`openSseStream` 공용 파서)
- `types.ts` — 공유 타입

## 파이프라인 흐름
질문 → [후속이면 **자동 라우팅** (haiku): tail=현재 데이터 질답 즉시 반환 / child=재조회]
→ **스테이지① 스켈레톤 즉시 방출** (휴리스틱, LLM 미경유) → [신규 질의는 **clarify 검토** (haiku, 보수적)
— 모호하면 되묻고 종료, 프론트가 답을 합쳐 skip_clarify 재요청]
→ vector_store RAG → sql_agent (실패 시 sql_fixer) → DB 실행 (rows가 스켈레톤 표에 즉시 표시)
→ **스테이지② ui_decision** (A2UI 메시지 스트리밍, 스켈레톤과 같은 id 갱신) → A2uiRenderer

**UI 수정 모드**: 입력창 + 버튼으로 진입 → `/api/query/ui-edit` — 현재 화면 spec + 지시로
updateComponents 증분만 생성 (SQL/데이터 불변, 같은 epoch라 리마운트 없이 제자리 갱신).
주의: 수정 출력의 첫 컴포넌트는 반드시 root (SDK 파서 계약).

A2UI 계약: catalogId `query-canvas/v1`, surfaceId `result`, 데이터 모델 `/rows`·`/filters`·`/meta/loading`.
- rows 본문은 LLM 미경유 — 클라이언트가 `/rows` 직주입. UI 결정 샘플은 PII 컬럼 값 제외
  (가역 마스킹/복원 아님 — 그건 sql_agent의 preview_sql에만 남아 있음)
- LLM은 createSurface + updateComponents만 출력 (서버가 createSurface를 걸러 전달)
- 힐링 placeholder(loading_*)는 서버가 이미 알려진 id로 리맵 — 함정 목록은 `docs/a2ui-notes.md`

## 규칙
- 새 시각화 컴포넌트는 **양쪽에 등록**: `frontend/src/lib/a2ui/catalog.tsx`(구현+zod 스키마) +
  `backend/ui_engine/a2ui_catalog.py`(JSON 스키마 — `$defs.anyComponent`에도 추가). 등록 후 `npm run check:a2ui`로 검증
- 레거시 json-render 경로(registry.ts/catalog.ts/customComponents.tsx/SpecRenderer)는 과거 히스토리 재생 전용 — 신규 기능 추가 금지
- DDL/학습 데이터 변경 시 `vector_store.train()` 재실행 필요 (chroma_data 초기화)
- 프롬프트/모델/검색 가중치 변경 시 `eval/run_eval.py` 전후 실행으로 회귀 확인
- 순수 로직(validator/rewriter/anonymizer/spec 처리) 수정 시 `backend/tests` 통과 필수 (CI: `.github/workflows/ci.yml`)
