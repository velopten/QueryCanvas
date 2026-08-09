import { useState, useEffect } from 'react'
import { TraceStepItem } from '../../components/TraceViewer'
import { getTraces, getTraceDetail, getFeedbackStats } from '../../utils/api'
import { Button, Badge, EmptyState } from '../../components/ui'
import type { QueryTrace } from '../../types'

interface TraceRow {
  trace_id: string; question: string; history_id: string | null
  parent_id: string | null; parent_title: string | null
  feedback: number | null; feedback_comment: string | null; created_at: string
}

export default function TracesPanel() {
  const [traces, setTraces] = useState<TraceRow[]>([])
  const [selectedTrace, setSelectedTrace] = useState<QueryTrace | null>(null)
  const [loading, setLoading] = useState(true)
  const [stats, setStats] = useState<{ total: number; positive: number; negative: number; no_feedback: number } | null>(null)

  const fetchData = () => {
    getTraces().then(d => { setTraces(d.traces); setLoading(false) })
    getFeedbackStats().then(setStats).catch(() => {})
  }
  const load = () => { setLoading(true); fetchData() }
  useEffect(fetchData, [])

  const handleSelect = async (traceId: string) => {
    if (selectedTrace?.trace_id === traceId) { setSelectedTrace(null); return }
    try {
      const data = await getTraceDetail(traceId)
      setSelectedTrace({ trace_id: data.trace_id, question: data.question, started_at: data.created_at, steps: data.steps })
    } catch (e) {
      // 조용히 삼키면 "눌러도 아무 일 없음" 으로 보인다 — 원인을 콘솔에 남긴다
      console.error('추적 상세를 불러오지 못했습니다', e)
    }
  }

  const feedbackBadge = (fb: number | null) => {
    if (fb === 1) return <Badge tone="success">좋아요</Badge>
    if (fb === -1) return <Badge tone="danger">싫어요</Badge>
    return <Badge>미평가</Badge>
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        {/* Feedback stats */}
        {stats ? (
          <div className="flex gap-2 text-xs">
            <Badge>전체 {stats.total}건</Badge>
            <Badge tone="success">좋아요 {stats.positive}건</Badge>
            <Badge tone="danger">싫어요 {stats.negative}건</Badge>
            <Badge>미평가 {stats.no_feedback}건</Badge>
            {stats.total > 0 && (
              <Badge tone="accent">
                만족도 {stats.positive && stats.total ? ((stats.positive / (stats.positive + stats.negative || 1)) * 100).toFixed(0) : 0}%
              </Badge>
            )}
          </div>
        ) : <span />}
        <Button variant="secondary" size="sm" onClick={load}>새로고침</Button>
      </div>

      {loading ? <p className="text-sm text-gray-500">로딩 중...</p> : traces.length === 0 ? (
        <EmptyState message="아직 추적 데이터가 없습니다" action="조회 화면에서 질문을 실행하면 파이프라인 단계가 기록됩니다" />
      ) : (() => {
        // 부모(독립 질문)만 최상위에 표시, 꼬리질문은 부모 아래에 그룹핑
        const parentTraces = traces.filter(t => !t.parent_id)
        const childMap = new Map<string, TraceRow[]>()
        traces.filter(t => t.parent_id).forEach(t => {
          // parent_id는 history_id 기준 → 부모 trace의 history_id와 매칭
          const parentTrace = traces.find(p => p.history_id === t.parent_id)
          if (parentTrace) {
            const arr = childMap.get(parentTrace.trace_id) || []
            arr.push(t)
            childMap.set(parentTrace.trace_id, arr)
          }
        })

        const renderTraceItem = (t: TraceRow, isChild = false) => (
          <div key={t.trace_id}>
            <button
              onClick={() => handleSelect(t.trace_id)}
              className={`w-full text-left px-4 py-3 border transition-colors bg-white ${
                selectedTrace?.trace_id === t.trace_id ? 'border-accent-muted bg-accent-soft' : 'border-gray-200 hover:bg-gray-50'
              } ${isChild ? 'rounded-none border-t-0' : 'rounded-lg'}`}
            >
              <div className="flex items-center justify-between">
                <span className={`text-sm truncate flex-1 ${isChild ? 'text-gray-600' : 'text-gray-800'}`}>
                  {isChild && <span className="text-gray-300 mr-2">↳</span>}
                  {isChild && <span className="text-xs text-accent mr-1.5">꼬리질문</span>}
                  {t.question}
                </span>
                <div className="flex items-center gap-2 shrink-0 ml-3">
                  {feedbackBadge(t.feedback)}
                  <span className="text-xs text-gray-400">{new Date(t.created_at).toLocaleString('ko-KR')}</span>
                </div>
              </div>
            </button>
            {selectedTrace?.trace_id === t.trace_id && selectedTrace.steps && (
              <div className={`border border-t-0 border-accent-muted bg-white px-4 py-3 space-y-2 ${isChild ? '' : childMap.has(t.trace_id) ? '' : 'rounded-b-lg'}`}>
                {selectedTrace.steps.map((step, si) => (
                  <TraceStepItem key={si} step={step} index={si} />
                ))}
              </div>
            )}
          </div>
        )

        return (
          <div className="space-y-2">
            {parentTraces.map(t => {
              const children = childMap.get(t.trace_id) || []
              return (
                <div key={t.trace_id} className="rounded-lg overflow-hidden">
                  {renderTraceItem(t)}
                  {children.map(child => renderTraceItem(child, true))}
                </div>
              )
            })}
            {/* 부모를 못 찾은 고아 꼬리질문 */}
            {traces.filter(t => t.parent_id && !parentTraces.some(p => p.history_id === t.parent_id)).map(t => renderTraceItem(t))}
          </div>
        )
      })()}
    </div>
  )
}
