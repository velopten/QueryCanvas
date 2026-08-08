/**
 * UiSpec — AI가 생성한 UI 트리. 백엔드 ui_decision.py가 반환한다.
 *
 * 현행 (A2UI v0.9): { format: 'a2ui', messages: [{ version, updateComponents: {...} }] }
 * 레거시 (json-render): { root: "elementId", elements: { [id]: { type, props, children? } } }
 * — 과거 저장된 히스토리 재생용으로만 유지.
 */
export interface A2uiComponent {
  id: string
  component: string
  children?: string[]
  [key: string]: unknown
}

export interface A2uiMessage {
  version: string
  updateComponents?: {
    surfaceId: string
    components: A2uiComponent[]
  }
  [key: string]: unknown
}

export type A2uiUiSpec = {
  format: 'a2ui'
  messages: A2uiMessage[]
}

export type LegacyUiSpec = {
  root: string
  elements: Record<string, {
    type: string
    props?: Record<string, unknown>
    children?: string[]
  }>
}

export type UiSpec = A2uiUiSpec | LegacyUiSpec

export function isA2uiSpec(spec: UiSpec | null | undefined): spec is A2uiUiSpec {
  return !!spec && (spec as A2uiUiSpec).format === 'a2ui'
}

export interface TraceStep {
  step: string
  timestamp: string
  data: Record<string, unknown>
}

export interface QueryTrace {
  trace_id: string
  question: string
  started_at: string
  steps: TraceStep[]
}

export interface QueryResult {
  sql: string
  data: Record<string, unknown>[]
  ui_spec: UiSpec
  trace: QueryTrace
}

export interface HistoryItem {
  question: string
  result: QueryResult
  timestamp: string
}
