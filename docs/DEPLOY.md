# 공개 배포 — 읽기 전용 정적 스냅샷

공개 도메인에는 **백엔드를 올리지 않습니다.** 빌드 시점에 조회 API 응답을 JSON 으로 떠서
프론트와 함께 정적 호스팅하면, 서버 없이도 지난 대화와 관리자 화면을 그대로 볼 수 있습니다.

이 방식이 주는 것:

- 서버·컨테이너·임베딩 모델이 배포에서 전부 빠짐 (모델은 lazy load 라 조회만으로는 로드되지 않음)
- LLM 호출 경로가 존재하지 않으므로 **API 키 노출도, 크레딧 소모도 구조적으로 불가능**
- 호스팅 비용 0, 유지보수 없음

대신 임의의 새 질의·화면 수정·설정 변경은 공개본에서 동작하지 않습니다. 저장된 예시 질문은
실제 실행 당시의 파이프라인 단계와 결과를 데모로 재생합니다.

## 스냅샷 만들기

백엔드를 띄운 상태에서 실행합니다. 공개할 대화 내역이 로컬 DB 에 있는 상태여야 합니다.

```bash
cd backend && uvicorn main:app --port 8008   # 터미널 1
cd backend && python scripts/snapshot_static.py   # 터미널 2
```

`frontend/public/api-snapshot/` 아래에 GET 엔드포인트 응답이 경로 그대로 저장됩니다
(`/api/history/abc` → `api-snapshot/history/abc.json`). 이 디렉터리는 저장소에 커밋합니다 —
Cloudflare Pages 는 백엔드에 접근할 수 없으므로 빌드 산출물에 들어 있어야 합니다.

스냅샷 생성기는 읽기 응답만 복사하지 않고, 공개본에서 재생할 테스트를 실제로 한 번씩 실행해
결과도 함께 저장합니다.

| 공개본 동작 | 스냅샷 생성 시 실행하는 일 | 공개본 표시 |
|---|---|---|
| 예시 질문 입력 | 저장된 히스토리 결과 사용 | 질문 분류 → 벡터 검색 → SQL 생성·검증·실행 → 시각화 결정 단계와 결과 재생 |
| `내 화면` 열기 | 저장된 SQL을 DB에 재실행 | SQL 실행 → 기존 화면 바인딩 단계 + 저장된 결과 |
| 벡터/캐시 검색 테스트 | 고정 데모 질문으로 실제 검색 | `저장된 검색 재생` 버튼 + 결과 |
| 가상 View Test Run | View별 기본 파라미터로 DB 실행 | `저장된 Test Run 재생` 버튼 + 표 |
| 골든셋 평가 | 이미 실행해 둔 최신 `eval_*.json` 복사 | 케이스별 진행 로그와 결과 재생 |

> 골든셋 평가는 API 비용이 드므로 스냅샷 생성기가 자동 실행하지 않습니다. 관리자의 `평가 실행`이나
> `python eval/run_eval.py` 로 실제 평가를 마친 뒤 스냅샷을 생성하세요. 결과가 없으면 공개본도 그 사실을 그대로 안내합니다.

### 마스킹

파이프라인 추적에는 시스템 프롬프트 전문과 PII 매핑이 들어 있습니다. 성격이 달라 플래그가 나뉩니다.

| 환경변수 | 대상 필드 | 기본 |
|---|---|---|
| `SNAPSHOT_INCLUDE_PROMPTS=1` | `system_prompt`, `user_message` | 마스킹 |
| `SNAPSHOT_INCLUDE_PII=1` | `pii_mapping` (`[PERSON_1]` → 실명 대응표) | 마스킹 |

**이 저장소는 프롬프트를 공개하는 설정으로 운영합니다.** 스냅샷을 다시 뜰 때 플래그를 빠뜨리면
추적 패널이 마스킹된 상태로 되돌아가므로 주의하세요.

```bash
SNAPSHOT_INCLUDE_PROMPTS=1 python scripts/snapshot_static.py
```

PII 매핑은 mock 데이터라도 실명 대응표 형태라 계속 가립니다.

## 로컬에서 확인

```bash
cd frontend && npm run build:static
npx serve dist          # 또는 python -m http.server --directory dist 8123
```

`npm run dev` 는 항상 일반 모드(백엔드 연동)입니다. 정적 모드는 `--mode static`
(`.env.static` 의 `VITE_STATIC=1`) 에서만 켜집니다.

## Cloudflare Pages 연결

1. Pages → **Create a project** → GitHub 저장소 연결
2. 빌드 설정
   | 항목 | 값 |
   |---|---|
   | Framework preset | None |
   | Build command | `npm run build:static` |
   | Build output directory | `dist` |
   | Root directory | `frontend` |
3. **Custom domains** 탭에서 도메인 추가 → 안내되는 CNAME 을 DNS 에 등록 (TLS 는 자동)

`frontend/public/_redirects` 가 SPA 폴백(`/* /index.html 200`)을 처리하므로
`/admin/traces` 같은 딥링크도 404 나지 않습니다.

## 공개본 갱신

대화 내역이나 설정이 바뀌었을 때만 다시 뜨면 됩니다.

```bash
cd backend && python scripts/snapshot_static.py
git add frontend/public/api-snapshot && git commit -m "chore: 공개 스냅샷 갱신" && git push
```

푸시하면 Pages 가 자동으로 다시 빌드합니다.

## 읽기 전용이 강제되는 지점

정적 모드에서는 세 겹으로 막힙니다.

| 계층 | 동작 |
|---|---|
| `utils/api.ts` | 일반 변경 요청과 LLM SSE는 `StaticModeError`; 데모 테스트만 저장된 JSON으로 우회 |
| `components/ui/Button` | `mutating` 버트은 비활성, `demoReplay` 테스트 버튼만 저장된 결과 재생 |
| 배포 자체 | 백엔드가 없으므로 호출할 대상이 존재하지 않음 |
