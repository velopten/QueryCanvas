/**
 * A2UI 프로덕션 카탈로그 jsdom 런타임 검증. (Node 전용 — tsconfig.app에서 제외됨)
 * 실행: npm run check:a2ui
 *
 * A2uiRenderer와 동일한 흐름을 재현한다:
 *   클라이언트가 createSurface + updateDataModel(/rows·/filters) 주입 →
 *   백엔드 UI 결정이 보내는 updateComponents만 수신 → 렌더/two-way/클릭 검증.
 */
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { pretendToBeVisual: true })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLAnchorElement: dom.window.HTMLAnchorElement,
  HTMLSelectElement: dom.window.HTMLSelectElement,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  ResizeObserver: class { observe() {} unobserve() {} disconnect() {} },
})
;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
;(globalThis as Record<string, unknown>).__A2UI_CHECK_NO_CHART = true

const { createElement } = await import('react')
const { createRoot } = await import('react-dom/client')
const { MessageProcessor } = await import('@a2ui/web_core/v0_9')
const { A2uiSurface } = await import('@a2ui/react/v0_9')
const { appCatalog, CATALOG_ID, SURFACE_ID } = await import('./catalog')
const { ElementClickContext } = await import('../elementClickContext')

const ROWS = [
  { CATEGORY_NAME: '뷰티', CUST_NAME: '김민준', CUST_ID: 'C038', ORDER_CNT: 12, AMOUNT: 123456789, RATE: 5.3, YEAR: 2026 },
  { CATEGORY_NAME: '가전', CUST_NAME: '박서준', CUST_ID: 'C071', ORDER_CNT: 4, AMOUNT: 9876543, RATE: 2.15, YEAR: 2025 },
]

// 클라이언트 주입분 (A2uiRenderer 담당)
const clientMessages = [
  { version: 'v0.9', createSurface: { surfaceId: SURFACE_ID, catalogId: CATALOG_ID } },
  { version: 'v0.9', updateDataModel: { surfaceId: SURFACE_ID, path: '/', value: { rows: ROWS, filters: {} } } },
]

// 백엔드 UI 결정이 보내는 updateComponents (LLM 출력 형태)
const serverMessages = [
  {
    version: 'v0.9',
    updateComponents: {
      surfaceId: SURFACE_ID,
      components: [
        { id: 'root', component: 'Column', children: ['briefing', 'filter', 'chart', 'table'] },
        { id: 'briefing', component: 'BriefingCard', headline: '뷰티 12건으로 최다', bullets: ['뷰티 12건', '가전 4건'] },
        { id: 'filter', component: 'Filter', columns: ['CATEGORY_NAME'], rows: { path: '/rows' }, filters: { path: '/filters' } },
        { id: 'chart', component: 'Chart', chartType: 'bar', title: '카테고리별 주문', xField: 'CATEGORY_NAME', yField: 'ORDER_CNT', rows: { path: '/rows' }, filters: { path: '/filters' } },
        {
          id: 'table', component: 'DataTable', title: '상세',
          columnFormats: {
            AMOUNT: { type: 'number', currency: '₩' },
            ORDER_CNT: { type: 'number', unit: '건' },
            RATE: { type: 'percent', decimals: 1 },
          },
          rows: { path: '/rows' }, filters: { path: '/filters' },
        },
      ],
    },
  },
]

const clicks: Array<{ value: string; field: string }> = []
const processor = new MessageProcessor([appCatalog as never])
processor.processMessages(clientMessages as never)
processor.processMessages(serverMessages as never)

const surfaces = Array.from(processor.model.surfacesMap.values())
console.log('surfaces:', surfaces.length)

const root = createRoot(document.getElementById('root')!)
root.render(
  createElement(
    ElementClickContext.Provider,
    { value: (value: string, field: string) => clicks.push({ value, field }) },
    createElement(A2uiSurface as never, { surface: surfaces[0] as never }),
  ),
)
await new Promise(r => setTimeout(r, 300))

const html = () => document.body.innerHTML
const results: [string, boolean][] = []
const check = (name: string, ok: boolean) => results.push([name, ok])

check('BriefingCard headline', html().includes('뷰티 12건으로 최다'))
check('Chart option 빌드 (placeholder)', html().includes('a2ui-chart-ok'))
check('DataTable 행 렌더', html().includes('가전'))
check('Filter 옵션 렌더', document.querySelectorAll('option').length >= 3)
check('엑셀 다운로드 버튼 (DataTable 전 기능)', html().includes('엑셀 다운로드'))

// 숫자 표기 — columnFormats 지정분 + 미지정분 자동 처리
check('columnFormats: 통화기호 + 천단위', html().includes('₩123,456,789'))
check('columnFormats: 단위 접미', html().includes('12 건'))
check('columnFormats: 백분율 소수 고정', html().includes('5.3%') && html().includes('2.2%'))
check('자동 천단위 (미지정 컬럼)', html().includes('9,876,543'))
check('연도는 천단위 구분 제외', html().includes('>2026<') && !html().includes('2,026'))

// 클릭 드릴다운: 이름 셀 클릭 → "ID(이름)" 변환되어 콜백 수신
const nameCell = Array.from(document.querySelectorAll('td')).find(td => td.textContent === '김민준')
nameCell?.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))
await new Promise(r => setTimeout(r, 100))
check('클릭 드릴다운: C038(김민준) 변환', clicks.some(c => c.value === 'C038(김민준)'))

// two-way: Filter select 변경 → /filters → DataTable 필터링
// (1행으로 줄면 DataTable이 카드 뷰로 전환되므로 텍스트 존재 여부로 판정)
const select = document.querySelector('select')
if (select) {
  const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLSelectElement.prototype, 'value')!.set!
  setter.call(select, '뷰티')
  select.dispatchEvent(new dom.window.Event('change', { bubbles: true }))
  await new Promise(r => setTimeout(r, 200))
  check('two-way: 필터 적용 → 타 범주 행 제외', !html().includes('가전') || !html().includes('C071'))
  check('two-way: 필터 적용 → 선택 범주 유지 (카드 뷰 전환)', html().includes('김민준'))
} else {
  check('Filter select 존재', false)
}

// ── 스켈레톤 시나리오 (스테이지① — 데이터 도착 전 shimmer → 도착 후 자동 전환) ──
document.body.insertAdjacentHTML('beforeend', '<div id="root2"></div>')
const processor2 = new MessageProcessor([appCatalog as never])
processor2.processMessages([
  { version: 'v0.9', createSurface: { surfaceId: SURFACE_ID, catalogId: CATALOG_ID } },
  { version: 'v0.9', updateDataModel: { surfaceId: SURFACE_ID, path: '/', value: { rows: [], filters: {}, meta: { loading: true } } } },
  {
    version: 'v0.9',
    updateComponents: {
      surfaceId: SURFACE_ID,
      components: [
        { id: 'root', component: 'Column', children: ['briefing', 'main_chart', 'data_table'] },
        { id: 'briefing', component: 'BriefingCard', headline: '카테고리별 주문 현황' },
        { id: 'main_chart', component: 'Chart', chartType: 'bar', loading: { path: '/meta/loading' } },
        { id: 'data_table', component: 'DataTable', rows: { path: '/rows' }, loading: { path: '/meta/loading' } },
      ],
    },
  },
] as never)
const surfaces2 = Array.from(processor2.model.surfacesMap.values())
const root2 = createRoot(document.getElementById('root2')!)
root2.render(createElement(A2uiSurface as never, { surface: surfaces2[0] as never }))
await new Promise(r => setTimeout(r, 200))

const root2El = () => document.getElementById('root2')!.innerHTML
check('스켈레톤: Chart shimmer (rows 없이 loading만)', root2El().includes('차트 준비 중'))
check('스켈레톤: DataTable shimmer', root2El().includes('데이터 로딩 중'))

// 데이터 도착 + 로딩 해제 → 표 자동 전환
processor2.processMessages([
  { version: 'v0.9', updateDataModel: { surfaceId: SURFACE_ID, path: '/rows', value: ROWS } },
  { version: 'v0.9', updateDataModel: { surfaceId: SURFACE_ID, path: '/meta/loading', value: false } },
] as never)
await new Promise(r => setTimeout(r, 200))
check('스켈레톤→데이터: 표 자동 전환', root2El().includes('뷰티') && !root2El().includes('데이터 로딩 중'))

// ── 필터 승격 시나리오 (defaultValue → 마운트 시 초기 필터 적용) ──
document.body.insertAdjacentHTML('beforeend', '<div id="root3"></div>')
const processor3 = new MessageProcessor([appCatalog as never])
processor3.processMessages([
  { version: 'v0.9', createSurface: { surfaceId: SURFACE_ID, catalogId: CATALOG_ID } },
  { version: 'v0.9', updateDataModel: { surfaceId: SURFACE_ID, path: '/', value: { rows: ROWS, filters: {} } } },
  {
    version: 'v0.9',
    updateComponents: {
      surfaceId: SURFACE_ID,
      components: [
        { id: 'root', component: 'Column', children: ['filter', 'table', 'stat', 'notice'] },
        { id: 'filter', component: 'Filter', columns: ['CATEGORY_NAME'], rows: { path: '/rows' }, filters: { path: '/filters' }, defaultValue: { CATEGORY_NAME: '뷰티' } },
        { id: 'table', component: 'DataTable', rows: { path: '/rows' }, filters: { path: '/filters' } },
        { id: 'stat', component: 'StatCard', label: '이번 달 주문', value: '16건', delta: '+4건 vs 지난달', tone: 'negative' },
        { id: 'notice', component: 'Notice', noticeType: 'warning', title: '주의', message: '가전 반품률 상승 추세' },
      ],
    },
  },
] as never)
const surfaces3 = Array.from(processor3.model.surfacesMap.values())
const root3 = createRoot(document.getElementById('root3')!)
root3.render(createElement(A2uiSurface as never, { surface: surfaces3[0] as never }))
await new Promise(r => setTimeout(r, 250))

const root3El = () => document.getElementById('root3')!.innerHTML
check('필터 승격: defaultValue 초기 적용 (지목 범주만 표시)', root3El().includes('김민준') && !root3El().includes('C071'))
check('StatCard 렌더 (KPI + delta)', root3El().includes('16건') && root3El().includes('+4건 vs 지난달'))
check('Notice 렌더 (warning)', root3El().includes('가전 반품률 상승 추세'))

let pass = 0
for (const [name, ok] of results) {
  console.log(`${ok ? 'PASS' : 'FAIL'} - ${name}`)
  if (ok) pass++
}
console.log(`\n${pass}/${results.length} 통과`)
if (pass < results.length) {
  console.log('\n--- HTML (앞 4000자) ---\n' + html().slice(0, 4000))
  process.exit(1)
}
process.exit(0)
