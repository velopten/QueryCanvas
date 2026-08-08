import { useState } from 'react'
import type { QueryTrace, TraceStep } from '../types'

interface Props {
  trace: QueryTrace
}

const STEP_LABELS: Record<string, { label: string; color: string }> = {
  // 캐시
  sql_cache_hit: { label: '캐시 히트 (SQL 재활용)', color: 'bg-green-100 text-green-700' },
  sql_cache_miss: { label: '캐시 미스', color: 'bg-gray-100 text-gray-600' },
  // 벡터 검색
  vector_search_result: { label: '벡터 검색 결과', color: 'bg-purple-100 text-purple-700' },
  // SQL 생성
  sql_generation_request: { label: 'SQL 생성 → AI 요청', color: 'bg-accent-soft text-accent-strong' },
  sql_generation_response: { label: 'SQL 생성 ← AI 응답', color: 'bg-accent-soft text-accent-strong' },
  sql_final: { label: '최종 SQL', color: 'bg-accent-soft text-accent' },
  sql_blocked: { label: 'SQL 차단 (DML 감지)', color: 'bg-red-100 text-red-700' },
  // SQL 실행
  sql_executed: { label: 'SQL 실행 결과', color: 'bg-green-100 text-green-700' },
  sql_execution_error: { label: 'SQL 실행 오류', color: 'bg-red-100 text-red-700' },
  // SQL 수정
  sql_fix_request: { label: 'SQL 수정 → AI 요청', color: 'bg-orange-100 text-orange-700' },
  sql_fix_response: { label: 'SQL 수정 ← AI 응답', color: 'bg-orange-100 text-orange-700' },
  sql_fix_error: { label: 'SQL 수정 실패', color: 'bg-red-100 text-red-700' },
  // 개인정보
  pii_anonymized: { label: '개인정보 난독화', color: 'bg-slate-100 text-slate-700' },
  pii_restored: { label: '개인정보 복원', color: 'bg-slate-100 text-slate-700' },
  // UI 결정
  ui_decision_request: { label: 'UI 결정 → AI 요청', color: 'bg-amber-100 text-amber-700' },
  ui_decision_response: { label: 'UI 결정 ← AI 응답', color: 'bg-amber-100 text-amber-700' },
  ui_spec_parsed: { label: 'UI 스펙 파싱 완료', color: 'bg-emerald-100 text-emerald-700' },
  spec_parsed: { label: 'UI 스펙 파싱 완료', color: 'bg-emerald-100 text-emerald-700' },
  spec_parse_error: { label: 'UI 파싱 오류', color: 'bg-red-100 text-red-700' },
  ui_spec_parse_error: { label: 'UI 파싱 오류', color: 'bg-red-100 text-red-700' },
  ui_decision_skip: { label: 'UI 결정 생략', color: 'bg-gray-100 text-gray-600' },
  // 저장
  sql_cache_stored: { label: 'SQL 캐시 저장', color: 'bg-gray-100 text-gray-600' },
  history_saved: { label: '질문내역 저장', color: 'bg-gray-100 text-gray-600' },
  // 꼬리질문
  tail_request: { label: '꼬리질문 → AI 요청', color: 'bg-indigo-100 text-indigo-700' },
  tail_response: { label: '꼬리질문 ← AI 응답', color: 'bg-indigo-100 text-indigo-700' },
  question_classified: { label: '질문 분류', color: 'bg-gray-100 text-gray-600' },
}

export function TraceStepItem({ step, index }: { step: TraceStep; index: number }) {
  const [open, setOpen] = useState(false)
  const meta = STEP_LABELS[step.step] || { label: step.step, color: 'bg-gray-100 text-gray-600' }
  const time = new Date(step.timestamp).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 })
  const cost = (step.data as Record<string, unknown>)?.cost as { total_cost?: number; currency?: string } | undefined

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-gray-50 transition-colors"
      >
        <span className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold shrink-0 ${meta.color}`}>
          {index + 1}
        </span>
        <span className="font-medium text-sm text-gray-800 flex-1">{meta.label}</span>
        {cost && cost.total_cost !== undefined && (
          <span className="text-xs font-mono text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">
            ${cost.total_cost < 0.0001 ? '<0.0001' : cost.total_cost.toFixed(4)}
          </span>
        )}
        <span className="text-xs text-gray-400 font-mono">{time}</span>
        <svg className={`w-4 h-4 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="border-t border-gray-200 bg-gray-50 p-3">
          {renderStepData(step)}
        </div>
      )}
    </div>
  )
}

function renderStepData(step: TraceStep) {
  const data = step.data as Record<string, unknown>

  switch (step.step) {
    case 'vector_search_result':
      return <VectorSearchDetail data={data} />
    case 'sql_generation_request':
      return <PromptDetail data={data} />
    case 'sql_generation_response':
      return <AiResponseDetail data={data} />
    case 'sql_final':
      return <SqlBlock sql={String(data.sql || '')} />
    case 'sql_executed':
      return <SqlResultDetail data={data} />
    case 'ui_decision_request':
      return <PromptDetail data={data} />
    case 'ui_decision_response':
      return <AiResponseDetail data={data} />
    case 'ui_spec_parsed':
    case 'spec_parsed':
      return <UiSpecDetail data={data} />
    default:
      return <JsonBlock data={data} />
  }
}

function VectorSearchDetail({ data }: { data: Record<string, unknown> }) {
  const results = data.results as Record<string, { content: string; distance: number; source: string }[]>
  const counts = data.counts as Record<string, number>

  return (
    <div className="space-y-3">
      <div className="flex gap-3 text-xs">
        <span className="px-2 py-1 bg-purple-50 rounded">DDL: {counts?.ddl ?? 0}건</span>
        <span className="px-2 py-1 bg-green-50 rounded">SQL: {counts?.sql ?? 0}건</span>
        <span className="px-2 py-1 bg-yellow-50 rounded">DOC: {counts?.doc ?? 0}건</span>
      </div>
      {results && Object.entries(results).map(([type, items]) =>
        items.length > 0 && (
          <div key={type}>
            <h4 className="text-xs font-semibold text-gray-600 uppercase mb-1">{type}</h4>
            {items.map((item, i) => (
              <div key={i} className="mb-2 bg-white border border-gray-200 rounded p-2">
                <div className="flex justify-between text-xs text-gray-400 mb-1">
                  <span>{item.source}</span>
                  <span>거리: {item.distance?.toFixed(4)}</span>
                </div>
                <pre className="text-xs text-gray-700 whitespace-pre-wrap max-h-32 overflow-y-auto">{item.content}</pre>
              </div>
            ))}
          </div>
        )
      )}
    </div>
  )
}

function PromptDetail({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="space-y-3">
      {!!data.model && <div className="text-xs text-gray-500">모델: <span className="font-mono">{String(data.model)}</span></div>}
      {!!data.system_prompt && (
        <div>
          <h4 className="text-xs font-semibold text-gray-600 mb-1">시스템 프롬프트</h4>
          <pre className="text-xs text-gray-700 bg-white border border-gray-200 rounded p-2 whitespace-pre-wrap max-h-48 overflow-y-auto">{String(data.system_prompt)}</pre>
        </div>
      )}
      {!!data.user_message && (
        <div>
          <h4 className="text-xs font-semibold text-gray-600 mb-1">사용자 메시지</h4>
          <pre className="text-xs text-gray-700 bg-white border border-gray-200 rounded p-2 whitespace-pre-wrap max-h-64 overflow-y-auto">{String(data.user_message)}</pre>
        </div>
      )}
      {!!data.data_summary && (
        <div>
          <h4 className="text-xs font-semibold text-gray-600 mb-1">데이터 요약</h4>
          <JsonBlock data={data.data_summary as Record<string, unknown>} />
        </div>
      )}
    </div>
  )
}

function AiResponseDetail({ data }: { data: Record<string, unknown> }) {
  const usage = data.usage as { input_tokens?: number; output_tokens?: number } | undefined
  return (
    <div className="space-y-2">
      <div className="flex gap-3 text-xs text-gray-500">
        {!!data.model && <span>모델: <span className="font-mono">{String(data.model)}</span></span>}
        {!!data.stop_reason && <span>종료: {String(data.stop_reason)}</span>}
        {usage && <span>토큰: {usage.input_tokens} in / {usage.output_tokens} out</span>}
      </div>
      {!!data.raw_response && (
        <div>
          <h4 className="text-xs font-semibold text-gray-600 mb-1">AI 응답 원문</h4>
          <pre className="text-xs text-gray-700 bg-white border border-gray-200 rounded p-2 whitespace-pre-wrap max-h-64 overflow-y-auto">{String(data.raw_response)}</pre>
        </div>
      )}
    </div>
  )
}

function SqlBlock({ sql }: { sql: string }) {
  return <pre className="text-xs text-green-400 bg-gray-900 rounded p-3 whitespace-pre-wrap overflow-x-auto">{sql}</pre>
}

function SqlResultDetail({ data }: { data: Record<string, unknown> }) {
  const columns = data.columns as string[] | undefined
  const sampleRows = data.sample_rows as Record<string, unknown>[] | undefined
  return (
    <div className="space-y-2">
      <div className="text-xs text-gray-500">행 수: {String(data.row_count)} / 컬럼: {columns?.join(', ')}</div>
      {sampleRows && sampleRows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="text-xs w-full">
            <thead>
              <tr className="bg-gray-100">
                {columns?.map(col => <th key={col} className="px-2 py-1 text-left font-medium text-gray-600">{col}</th>)}
              </tr>
            </thead>
            <tbody>
              {sampleRows.map((row, i) => (
                <tr key={i} className="border-t border-gray-200">
                  {columns?.map(col => <td key={col} className="px-2 py-1 text-gray-700">{String(row[col] ?? '')}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function UiSpecDetail({ data }: { data: Record<string, unknown> }) {
  const elementCount = (data.element_count as number) ?? 0
  const elementTypes = (data.element_types as string[]) ?? []
  return (
    <div className="space-y-2">
      <div className="flex gap-2 text-xs flex-wrap">
        <span className="px-2 py-1 bg-accent-soft text-accent-strong rounded font-medium">루트: {String(data.root ?? '')}</span>
        <span className="px-2 py-1 bg-gray-50 text-gray-600 rounded">{elementCount}개 컴포넌트</span>
        {elementTypes.length > 0 && (
          <span className="px-2 py-1 bg-emerald-50 text-emerald-700 rounded">{elementTypes.join(', ')}</span>
        )}
      </div>
      <JsonBlock data={(data.full_spec as Record<string, unknown>) || data} />
    </div>
  )
}

function JsonBlock({ data }: { data: Record<string, unknown> }) {
  return (
    <pre className="text-xs text-gray-700 bg-white border border-gray-200 rounded p-2 whitespace-pre-wrap max-h-64 overflow-y-auto">
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}

export default function TraceViewer({ trace }: Props) {
  const [expanded, setExpanded] = useState(false)

  const elapsed = trace.steps.length >= 2
    ? ((new Date(trace.steps[trace.steps.length - 1].timestamp).getTime() - new Date(trace.steps[0].timestamp).getTime()) / 1000).toFixed(2)
    : null

  return (
    <div className="bg-gray-50 rounded-lg border border-gray-200">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm text-gray-600 hover:bg-gray-100 transition-colors"
      >
        <span className="flex items-center gap-2 font-medium">
          <svg className={`w-4 h-4 transition-transform ${expanded ? 'rotate-90' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          파이프라인 추적
        </span>
        <span className="flex items-center gap-3 text-xs text-gray-400">
          <span>{trace.steps.length}단계</span>
          {elapsed && <span>{elapsed}s</span>}
          <span className="font-mono">{trace.trace_id}</span>
        </span>
      </button>

      {expanded && (
        <div className="border-t border-gray-200 p-4 space-y-2">
          {trace.steps.map((step, i) => (
            <TraceStepItem key={i} step={step} index={i} />
          ))}
        </div>
      )}
    </div>
  )
}
