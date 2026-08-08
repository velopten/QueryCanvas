import { useState, useEffect } from 'react'
import {
  getSettings, saveLlmSettings, resetLlmSettings,
  type AdminSettings, type LlmSettings,
} from '../../utils/api'
import { Button, Panel, Badge, Toggle, StatusText } from '../../components/ui'

const MODEL_SUGGESTIONS = ['claude-opus-5', 'claude-sonnet-5', 'claude-haiku-4-5']

const LLM_FIELD_LABELS: Record<string, string> = {
  MODEL_SQL_GEN: 'SQL 생성 모델',
  MODEL_UI_DECISION: 'UI 결정 모델',
  MODEL_CLASSIFY: '분류/꼬리질문 모델',
  MODEL_FIX: 'SQL 수정 모델',
  MODEL_CURATOR: '큐레이터 모델',
}

export default function SettingsPanel() {
  const [settings, setSettings] = useState<AdminSettings | null>(null)
  const [llmDraft, setLlmDraft] = useState<LlmSettings | null>(null)
  const [status, setStatus] = useState<string | null>(null)

  const fetchData = () => {
    getSettings().then(s => { setSettings(s); setLlmDraft(s.llm) })
  }
  useEffect(fetchData, [])

  if (!settings || !llmDraft) return <p className="text-sm text-gray-500">로딩 중...</p>

  const save = async () => {
    setStatus('저장 중...')
    try {
      const res = await saveLlmSettings(llmDraft)
      setLlmDraft(res.llm)
      setStatus('저장 완료 — 다음 질의부터 즉시 적용됩니다 (재시작 불필요)')
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setStatus(`저장 실패: ${detail || String(e)}`)
    }
  }

  const reset = async () => {
    setStatus('초기화 중...')
    try {
      const res = await resetLlmSettings()
      setLlmDraft(res.llm)
      setStatus('.env / 기본값으로 복귀됨')
    } catch (e) { setStatus(`실패: ${String(e)}`) }
  }

  const sysEntries: [string, unknown][] = [
    ['db_connected', settings.db_connected],
    ['vector_store_count', settings.vector_store_count],
    ['sql_cache_count', settings.sql_cache_count],
  ]

  return (
    <div className="space-y-6">
      {/* LLM 설정 (편집 가능) */}
      <Panel
        title="LLM 설정"
        description='저장 즉시 다음 질의부터 적용됩니다. 변경 전후 "평가" 메뉴로 회귀를 확인하세요.'
        actions={
          <>
            <Button variant="secondary" size="sm" onClick={reset}>기본값 복귀</Button>
            <Button size="md" onClick={save}>저장</Button>
          </>
        }
      >
        <datalist id="model-suggestions">
          {MODEL_SUGGESTIONS.map(m => <option key={m} value={m} />)}
        </datalist>

        <div className="grid grid-cols-2 gap-3">
          {Object.entries(LLM_FIELD_LABELS).map(([key, label]) => (
            <label key={key} className="text-xs text-gray-600">
              {label}
              <input
                list="model-suggestions"
                value={String(llmDraft[key as keyof LlmSettings] ?? '')}
                onChange={e => setLlmDraft(d => d ? { ...d, [key]: e.target.value } : d)}
                className="mt-1 w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-accent/25 focus:border-accent"
              />
            </label>
          ))}
          <label className="text-xs text-gray-600">
            SQL 생성 effort
            <select
              value={llmDraft.SQL_GEN_EFFORT}
              onChange={e => setLlmDraft(d => d ? { ...d, SQL_GEN_EFFORT: e.target.value } : d)}
              className="mt-1 w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-accent/25 focus:border-accent"
            >
              {(settings.effort_levels || []).map(l => <option key={l} value={l}>{l}</option>)}
            </select>
          </label>
          <div className="flex items-end pb-1">
            <div className="flex items-center gap-2.5">
              <Toggle
                checked={llmDraft.AGENTIC_SQL}
                onChange={v => setLlmDraft(d => d ? { ...d, AGENTIC_SQL: v } : d)}
                aria-label="에이전틱 SQL 생성"
              />
              <span className="text-xs text-gray-600">에이전틱 SQL 생성 (도구 사용 루프 — 끄면 1-pass 폴백)</span>
            </div>
          </div>
        </div>

        <div className="mt-3"><StatusText status={status} /></div>
      </Panel>

      {/* 시스템 상태 (읽기 전용) */}
      <Panel flush title="시스템 상태">
        <table className="w-full text-sm">
          <tbody>
            {sysEntries.map(([key, val]) => (
              <tr key={key} className="border-t border-gray-100 first:border-t-0">
                <td className="px-4 py-2 font-mono text-gray-700">{key}</td>
                <td className="px-4 py-2 text-gray-800">
                  {typeof val === 'boolean'
                    ? <Badge tone={val ? 'success' : 'danger'}>{String(val)}</Badge>
                    : String(val)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  )
}
