export interface StepState {
  phase: string
  status: 'running' | 'done' | 'error'
  message: string
}

const PHASE_META: Record<string, { icon: string; label: string }> = {
  routing: { icon: '?', label: '질문 유형' },
  clarify: { icon: '?', label: '보강 질문' },
  ui_layout: { icon: '◻', label: '화면 골격' },
  ui_edit: { icon: '✎', label: '화면 수정' },
  cache_lookup: { icon: '0', label: '캐시 확인' },
  vector_search: { icon: '1', label: '벡터 검색' },
  sql_generation: { icon: '2', label: 'SQL 생성' },
  sql_fix: { icon: '!', label: 'SQL 수정' },
  sql_execution: { icon: '3', label: 'SQL 실행' },
  anonymize: { icon: '🔒', label: '개인정보 보호' },
  ui_decision: { icon: '4', label: '시각화 결정' },
}

export default function StreamingSteps({ steps }: { steps: StepState[] }) {
  if (steps.length === 0) return null

  return (
    <div className="flex items-center gap-1 flex-wrap">
      {steps.map((step, i) => {
        const meta = PHASE_META[step.phase] || { icon: '?', label: step.phase }
        const isRunning = step.status === 'running'
        const isDone = step.status === 'done'

        return (
          <div key={i} className="flex items-center gap-1">
            {i > 0 && <div className={`w-4 h-px ${isDone ? 'bg-emerald-300' : step.status === 'error' ? 'bg-red-300' : 'bg-gray-300'}`} />}
            <div
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs transition-all duration-300 ${
                isRunning
                  ? 'bg-accent-soft text-accent-strong ring-2 ring-accent-muted ring-offset-1 animate-pulse'
                  : isDone
                    ? 'bg-emerald-50 text-emerald-700'
                    : 'bg-red-50 text-red-700'
              }`}
            >
              {isRunning ? (
                <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : isDone ? (
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                </svg>
              ) : (
                <span className="font-bold">!</span>
              )}
              <span className="font-medium">{meta.label}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
