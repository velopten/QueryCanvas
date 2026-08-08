import { useState, useEffect } from 'react'
import { getPrompts, updatePrompts } from '../../utils/api'
import { Button } from '../../components/ui'
import MarkdownRenderer from '../../components/MarkdownRenderer'

function PromptEditor({ label, value, onChange, onSave }: {
  label: string; value: string; onChange: (v: string) => void; onSave: () => void
}) {
  const [mode, setMode] = useState<'edit' | 'preview'>('preview')

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 bg-gray-50 border-b border-gray-200">
        <h3 className="font-semibold text-gray-800 text-sm">{label}</h3>
        <div className="flex items-center gap-2">
          <div className="flex bg-gray-200 rounded-md p-0.5">
            <button onClick={() => setMode('edit')} className={`px-2.5 py-1 text-xs rounded ${mode === 'edit' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500'}`}>편집</button>
            <button onClick={() => setMode('preview')} className={`px-2.5 py-1 text-xs rounded ${mode === 'preview' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500'}`}>미리보기</button>
          </div>
          <Button size="xs" onClick={onSave}>저장</Button>
        </div>
      </div>
      {mode === 'edit' ? (
        <textarea
          value={value}
          onChange={e => onChange(e.target.value)}
          rows={20}
          className="w-full p-4 text-sm font-mono focus:outline-none resize-y min-h-[300px]"
          spellCheck={false}
        />
      ) : (
        <div className="p-4 max-w-none max-h-[600px] overflow-y-auto">
          <MarkdownRenderer content={value} />
        </div>
      )}
    </div>
  )
}

export default function PromptsPanel() {
  const [sqlPrompt, setSqlPrompt] = useState('')
  const [uiPrompt, setUiPrompt] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getPrompts().then(d => {
      setSqlPrompt(d.sql_prompt)
      setUiPrompt(d.ui_prompt)
      setLoading(false)
    })
  }, [])

  const handleSave = async (type: 'sql' | 'ui') => {
    setStatus(null)
    await updatePrompts(type === 'sql' ? { sql_prompt: sqlPrompt } : { ui_prompt: uiPrompt })
    setStatus(`${type === 'sql' ? 'SQL 생성' : 'UI 결정'} 프롬프트가 저장되었습니다.`)
  }

  if (loading) return <p className="text-sm text-gray-500">로딩 중...</p>

  return (
    <div className="space-y-6">
      {status && <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 px-4 py-2 rounded-lg text-sm">{status}</div>}
      <PromptEditor label="SQL 생성 프롬프트" value={sqlPrompt} onChange={setSqlPrompt} onSave={() => handleSave('sql')} />
      <PromptEditor label="UI 결정 프롬프트" value={uiPrompt} onChange={setUiPrompt} onSave={() => handleSave('ui')} />
    </div>
  )
}
