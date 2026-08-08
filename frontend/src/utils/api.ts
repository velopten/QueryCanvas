import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

/**
 * 공용 SSE 스트림 리더 — fetch 스트리밍 응답을 `event:`/`data:` 쌍으로 파싱해
 * 이벤트마다 onEvent(event, data)를 호출한다. 반환값은 abort 함수.
 * queryStream / retrainStream / runEvalStream 이 모두 이 헬퍼를 사용한다.
 */
function openSseStream(
  url: string,
  init: RequestInit,
  onEvent: (event: string, data: Record<string, unknown>) => void,
  onError: (message: string) => void,
): () => void {
  const controller = new AbortController()
  ;(async () => {
    try {
      const response = await fetch(url, { ...init, signal: controller.signal })
      if (!response.ok || !response.body) {
        const detail = await response.json().catch(() => null) as { detail?: string } | null
        onError(detail?.detail || '서버 연결 실패')
        return
      }
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        let currentEvent = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim()
          } else if (line.startsWith('data: ') && currentEvent) {
            try {
              onEvent(currentEvent, JSON.parse(line.slice(6)))
            } catch { /* skip parse errors */ }
            currentEvent = ''
          }
        }
      }
    } catch (err) {
      const e = err as Error
      if (e.name !== 'AbortError') onError(e.message || '알 수 없는 오류')
    }
  })()
  return () => controller.abort()
}

// SSE streaming query
export interface NeedsInputPayload {
  question: string
  extracted: { names?: string[]; groups?: string[]; date_hint?: string | null }
  groups: Array<{
    kind: 'person' | 'group' | 'range'
    keyword: string
    case_id: string
    candidates: Record<string, unknown>[]
  }>
}

export interface StreamCallbacks {
  onStep: (data: { phase: string; status: string; message: string }) => void
  onSql: (sql: string) => void
  onData: (data: Record<string, unknown>[], rowCount: number) => void
  /** A2UI updateComponents 메시지 묶음 — UI 결정 단계에서 증분 수신 */
  onA2ui: (messages: Record<string, unknown>[]) => void
  /** 최종 spec — 스트림 종료 시 한 번 들어옴 ({format:'a2ui', messages}) */
  onUiSpec: (uiSpec: Record<string, unknown>) => void
  onSaved: (historyId: string, title: string) => void
  onError: (message: string) => void
  onDone: (traceId?: string) => void
  /** 후속 질의가 현재 데이터 질답(tail)으로 자동 라우팅된 경우 */
  onTailAnswer?: (answer: string) => void
  /** 신규 질의가 모호해 AI가 되묻는 경우 */
  onClarify?: (question: string) => void
  /** 사용자 disambiguation 요청 (선택 — 1-pass 폴백 모드 전용) */
  onNeedsInput?: (payload: NeedsInputPayload) => void
}

export interface QueryContext {
  previous_sql?: string
  previous_summary?: string
  parent_history_id?: string
  resolved_context?: Record<string, unknown>
  skip_prefilter?: boolean
  /** clarify 답변을 합쳐 재요청할 때 (되묻기 루프 방지) */
  skip_clarify?: boolean
}

export function queryStream(question: string, callbacks: StreamCallbacks, context?: QueryContext): () => void {
  return openSseStream(
    '/api/query/stream',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, ...context }),
    },
    /* eslint-disable @typescript-eslint/no-explicit-any */
    (event, data: any) => {
      switch (event) {
        case 'step': callbacks.onStep(data); break
        case 'sql': callbacks.onSql(data.sql); break
        case 'data': callbacks.onData(data.data, data.row_count); break
        case 'a2ui': callbacks.onA2ui(data.messages); break
        case 'ui_spec': callbacks.onUiSpec(data.ui_spec); break
        case 'saved': callbacks.onSaved(data.history_id, data.title); break
        case 'tail_answer': callbacks.onTailAnswer?.(data.answer); break
        case 'clarify': callbacks.onClarify?.(data.question); break
        case 'needs_input': callbacks.onNeedsInput?.(data as NeedsInputPayload); break
        case 'error': callbacks.onError(data.message); break
        case 'done': callbacks.onDone(data.trace_id); break
      }
    },
    /* eslint-enable @typescript-eslint/no-explicit-any */
    callbacks.onError,
  )
}

export async function queryExecute(sql: string) {
  const { data } = await api.post('/query/execute', { sql })
  return data
}

export async function getHealth() {
  const { data } = await api.get('/health')
  return data
}

export async function getMeta(): Promise<{ domain: string; domain_label: string; suggested_questions: string[] }> {
  const { data } = await api.get('/meta')
  return data
}

// History APIs
export interface HistoryEntry {
  id: string
  title: string
  question: string
  sql: string | null
  ui_spec: Record<string, unknown> | null
  favorite: boolean
  parent_id: string | null
  parent?: { id: string; title: string; question: string }
  created_at: string
  updated_at: string
  data?: Record<string, unknown>[]
}

export async function getHistoryList(): Promise<HistoryEntry[]> {
  const { data } = await api.get('/history')
  return data.items
}

export async function getHistoryDetail(id: string): Promise<HistoryEntry> {
  const { data } = await api.get(`/history/${id}`)
  return data
}

export async function updateHistoryTitle(id: string, title: string) {
  const { data } = await api.put(`/history/${id}/title`, { title })
  return data
}

export async function toggleHistoryFavorite(id: string) {
  const { data } = await api.post(`/history/${id}/favorite`)
  return data
}

export async function deleteHistory(id: string) {
  const { data } = await api.delete(`/history/${id}`)
  return data
}

export async function rerunHistory(id: string) {
  const { data } = await api.post(`/history/${id}/rerun`)
  return data
}

export async function submitFeedback(traceId: string, feedback: 1 | -1, comment = '') {
  const { data } = await api.post(`/feedback/${traceId}`, { feedback, comment })
  return data
}

export async function answer_from_data(question: string, historyId: string): Promise<string> {
  const { data } = await api.post('/query/tail', { question, history_id: historyId })
  return data.answer
}

export async function getTables() {
  const { data } = await api.get('/tables')
  return data
}

// ── UI 수정 (화면 증분 갱신) ──

export interface UiEditCallbacks {
  onStep: (data: { phase: string; status: string; message: string }) => void
  onA2ui: (messages: Record<string, unknown>[]) => void
  onUiSpec: (uiSpec: Record<string, unknown>) => void
  onError: (message: string) => void
  onDone: () => void
}

export function uiEditStream(historyId: string, instruction: string, cb: UiEditCallbacks): () => void {
  return openSseStream(
    '/api/query/ui-edit',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ history_id: historyId, instruction }),
    },
    /* eslint-disable @typescript-eslint/no-explicit-any */
    (event, data: any) => {
      switch (event) {
        case 'step': cb.onStep(data); break
        case 'a2ui': cb.onA2ui(data.messages); break
        case 'ui_spec': cb.onUiSpec(data.ui_spec); break
        case 'error': cb.onError(data.message); break
        case 'done': cb.onDone(); break
      }
    },
    /* eslint-enable @typescript-eslint/no-explicit-any */
    cb.onError,
  )
}

// ── 저장된 뷰 (화면의 메뉴화) ──

export interface SavedView {
  id: string
  name: string
  question: string
  liveness_note: string | null
  created_at: string
  last_used_at: string | null
}

export interface SavedViewOpenResult {
  view: { id: string; name: string; question: string; liveness_note: string | null }
  sql: string
  data: Record<string, unknown>[]
  ui_spec: Record<string, unknown>
}

export async function createSavedView(historyId: string, name?: string) {
  const { data } = await api.post('/views', { history_id: historyId, name })
  return data as { view: SavedView; liveness_note: string | null }
}

export async function listSavedViews(): Promise<SavedView[]> {
  const { data } = await api.get('/views')
  return data.items
}

export async function openSavedView(viewId: string): Promise<SavedViewOpenResult> {
  const { data } = await api.post(`/views/${viewId}/open`)
  return data
}

export async function renameSavedView(viewId: string, name: string) {
  const { data } = await api.put(`/views/${viewId}`, { name })
  return data
}

export async function deleteSavedView(viewId: string) {
  const { data } = await api.delete(`/views/${viewId}`)
  return data
}

export async function vectorSearchTest(query: string) {
  const { data } = await api.post('/admin/vector-search-test', { query })
  return data
}

export async function cacheSearchTest(query: string) {
  const { data } = await api.post('/admin/cache-search-test', { query })
  return data
}

// Admin APIs
export async function getPrompts() {
  const { data } = await api.get('/admin/prompts')
  return data
}

export async function updatePrompts(prompts: { sql_prompt?: string; ui_prompt?: string }) {
  const { data } = await api.put('/admin/prompts', prompts)
  return data
}

export async function getTrainingData() {
  const { data } = await api.get('/admin/training-data')
  return data
}

export async function addTrainingData(type: string, content: string) {
  const { data } = await api.post('/admin/training-data', { type, content })
  return data
}

export async function deleteTrainingData(docId: string) {
  const { data } = await api.delete(`/admin/training-data/${docId}`)
  return data
}

export interface CuratorPreview {
  action: 'add' | 'patch' | 'reject'
  destination?: 'vector' | 'prompt' | 'both'
  category?: string
  title?: string
  target_chunk_id?: string
  target_content?: string
  rationale?: string
  structured_md?: string
  prompt_directive?: string
}

export async function curatorPreview(content: string): Promise<CuratorPreview> {
  const { data } = await api.post('/admin/training-data/curate-preview', { content })
  return data
}

export async function curatorCommit(curated: CuratorPreview, source_input: string) {
  const { data } = await api.post('/admin/training-data/curate-commit', { curated, source_input })
  return data
}

export interface OverlayItem {
  file: string
  size: number
  preview: string
}

export async function listOverlays(): Promise<{ items: OverlayItem[] }> {
  const { data } = await api.get('/admin/training-data/overlays')
  return data
}

export async function deleteOverlay(filename: string) {
  const { data } = await api.delete(`/admin/training-data/overlays/${encodeURIComponent(filename)}`)
  return data
}

export async function retrain() {
  const { data } = await api.post('/admin/retrain')
  return data
}

export async function clearSqlCache() {
  const { data } = await api.delete('/admin/sql-cache')
  return data
}

export interface LlmSettings {
  MODEL_SQL_GEN: string
  MODEL_UI_DECISION: string
  MODEL_CLASSIFY: string
  MODEL_FIX: string
  MODEL_CURATOR: string
  SQL_GEN_EFFORT: string
  AGENTIC_SQL: boolean
}

export interface AdminSettings {
  db_connected: boolean
  vector_store_count: number
  sql_cache_count: number
  llm: LlmSettings
  effort_levels: string[]
}

export async function getSettings(): Promise<AdminSettings> {
  const { data } = await api.get('/admin/settings')
  return data
}

export async function saveLlmSettings(llm: Partial<LlmSettings>): Promise<{ status: string; llm: LlmSettings }> {
  const { data } = await api.put('/admin/llm-settings', llm)
  return data
}

export async function resetLlmSettings(): Promise<{ status: string; llm: LlmSettings }> {
  const { data } = await api.delete('/admin/llm-settings')
  return data
}

export async function getTraces() {
  const { data } = await api.get('/admin/traces')
  return data
}

export async function getLogs(limit = 50) {
  const { data } = await api.get(`/admin/logs?limit=${limit}`)
  return data
}

// ── Phase 4: Virtual Views / Required Filters / Info Collectors / Code Mappings / Retrieval Weights ──

export interface VirtualViewMeta {
  id: string
  purpose: string
  use_when: string
  required_params: string[]
  columns: { name: string; desc: string }[]
  sample_questions: string[]
}

export async function listVirtualViews(): Promise<{ items: VirtualViewMeta[] }> {
  const { data } = await api.get('/admin/virtual-views')
  return data
}
export async function getVirtualView(id: string): Promise<{ id: string; meta: Record<string, unknown>; sql: string }> {
  const { data } = await api.get(`/admin/virtual-views/${id}`)
  return data
}
export async function saveVirtualView(id: string, payload: { meta?: Record<string, unknown>; sql?: string }) {
  const { data } = await api.put(`/admin/virtual-views/${id}`, payload)
  return data
}
export async function testRunVirtualView(id: string, params: Record<string, unknown>) {
  const { data } = await api.post(`/admin/virtual-views/${id}/test-run`, { params })
  return data as { row_count: number; rows: Record<string, unknown>[] }
}
export async function reindexVirtualViews() {
  const { data } = await api.post('/admin/virtual-views/reindex')
  return data
}

export interface RetrainProgress {
  phase: string
  message: string
  current?: number
  total?: number
}

export function retrainStream(
  onProgress: (ev: RetrainProgress) => void,
  onDone: () => void,
  onError: (msg: string) => void,
  endpoint: 'retrain' | 'virtual-views/reindex' = 'retrain',
): () => void {
  return openSseStream(
    `/api/admin/${endpoint}/stream`,
    { method: 'POST' },
    (event, data) => {
      if (event === 'progress') onProgress(data as unknown as RetrainProgress)
      else if (event === 'done') onDone()
      else if (event === 'error') onError(String(data.message))
    },
    onError,
  )
}

// ── 평가 하네스 Admin ──

export interface EvalConfig {
  model: string
  effort: string
  agentic: boolean
  started_at: string
}

export interface EvalSummary {
  accuracy: number
  passed: number
  total: number
  avg_gen_seconds: number | null
  total_cost_usd: number | null
}

export interface EvalCaseResult {
  id: string
  question: string
  sql: string | null
  gen_seconds: number | null
  exec_seconds: number | null
  cost_usd: number | null
  generated_rows: number | null
  passed: boolean
  failure: string | null
  tool_calls: number | null
}

export interface EvalResultMeta {
  file: string
  config: EvalConfig
  summary: EvalSummary
}

export interface EvalResultDetail {
  config: EvalConfig
  summary: EvalSummary
  results: EvalCaseResult[]
}

export async function listEvalResults(): Promise<{ items: EvalResultMeta[] }> {
  const { data } = await api.get('/admin/eval/results')
  return data
}

export async function getEvalResult(file: string): Promise<EvalResultDetail> {
  const { data } = await api.get(`/admin/eval/results/${encodeURIComponent(file)}`)
  return data
}

export interface EvalProgress {
  phase: 'start' | 'case_start' | 'case_done' | 'summary'
  index?: number
  total?: number
  id?: string
  question?: string
  result?: EvalCaseResult
  config?: EvalConfig
  summary?: EvalSummary
  file?: string
}

export function runEvalStream(
  onProgress: (ev: EvalProgress) => void,
  onDone: (file: string) => void,
  onError: (msg: string) => void,
  options?: { limit?: number; case?: string },
): () => void {
  return openSseStream(
    '/api/admin/eval/run/stream',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options || {}),
    },
    (event, data) => {
      if (event === 'progress') onProgress(data as unknown as EvalProgress)
      else if (event === 'done') onDone(String(data.file))
      else if (event === 'error') onError(String(data.message))
    },
    onError,
  )
}

export interface RetrievalWeightConfig {
  per_type_n: number
  weight: number
  inject_limit: number
}
export async function getRetrievalWeights(): Promise<{ data: Record<string, RetrievalWeightConfig> }> {
  const { data } = await api.get('/admin/retrieval-weights')
  return data
}
export async function saveRetrievalWeights(payload: Record<string, RetrievalWeightConfig>) {
  const { data } = await api.put('/admin/retrieval-weights', { data: payload })
  return data
}
