# A2UI 구현 노트

UI 스펙 계층은 A2UI v0.9 표준을 사용합니다. 백엔드는 `a2ui-agent-sdk`로 카탈로그에서
시스템 프롬프트를 생성하고 스트리밍 파서로 검증하며, 프론트는 `@a2ui/react`에 커스텀
컴포넌트를 등록해 렌더합니다.

## 계약

- catalogId `query-canvas/v1`, surfaceId `result`
- 데이터 모델 경로: `/rows`(SQL 결과), `/filters`(Filter two-way), `/meta/loading`
- LLM 응답은 `<a2ui-json>[...]</a2ui-json>` 으로 감싸야 파서가 인식합니다
- 모든 메시지에 `"version": "v0.9"` 필드가 필요합니다
- root 컴포넌트의 id는 반드시 `root`

## 구현 시 주의할 점

1. **zod 버전** — a2ui는 zod v3 피어, 이 프로젝트는 v4입니다. 카탈로그 정의는
   `zod3` 알리아스로만 작성하고 파일 간 혼용하지 마세요.
2. **anyComponent 열거** — 백엔드 카탈로그 JSON에 컴포넌트를 추가할 때 `components`
   딕셔너리만으로는 부족합니다. `$defs.anyComponent.oneOf` 에도 `$ref` 를 추가해야
   검증을 통과합니다.
3. **Action 스키마** — `{event: {name, context?}}` 형태입니다.
4. **SSR 불가** — `A2uiSurface` 가 getServerSnapshot 을 제공하지 않아 renderToString 이
   불가능합니다. 검증은 jsdom + createRoot 로 합니다 (`npm run check:a2ui`).
5. **`allowed_messages` 는 `$defs` 키 이름** — `"updateComponents"` 처럼 camelCase 를 주면
   프롬프트의 스키마가 조용히 비어버려 모델이 메시지 형태를 지어냅니다.
   `"UpdateComponentsMessage"` 형식으로 지정하세요.
6. **스트리밍 파서는 createSurface 선행 필수** — `process_chunk` 는 createSurface 를 보기
   전까지 아무것도 방출하지 않습니다. LLM이 첫 메시지로 createSurface 를 출력하게 하고
   서버가 걸러서 전달합니다.
7. **힐링 부산물 정리** — 스트리밍 힐링이 만드는 `loading_*` 플레이스홀더는 id가 달라
   last-write-wins 로 덮이지 않습니다. 최종 spec 저장 전에 root 도달성 기준으로
   프루닝해야 합니다.
8. **프롬프트 내 한글 이스케이프** — 스키마 서술의 한글이 `\uXXXX` 로 직렬화돼 토큰을
   낭비합니다. 카탈로그 description 은 영문으로 쓰고, 도메인 지침은 별도 시스템 블록에
   한글로 둡니다.
9. **Windows 경로** — `CatalogConfig.from_path` 가 `C:\` 를 URL 스킴으로 오인합니다.
   `FileSystemCatalogProvider(path)` 를 직접 생성하세요.
10. **opentelemetry 충돌** — `a2ui-agent-sdk` 가 opentelemetry 를 최신으로 끌어올려
    구버전 exporter 와 조합되면 chromadb import 가 깨집니다. exporter 도 함께 상향해
    requirements.txt 에 핀합니다.
