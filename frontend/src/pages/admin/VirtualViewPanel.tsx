import { useState, useEffect } from 'react'
import {
  listVirtualViews, getVirtualView, saveVirtualView, testRunVirtualView,
  retrainStream, type VirtualViewMeta,
} from '../../utils/api'
import { Button, Panel, EmptyState, StatusText, codeInputClass } from '../../components/ui'

function ResultTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows.length) return null
  return (
    <div className="mt-2 max-h-60 overflow-auto border border-gray-200 rounded-lg">
      <table className="text-xs w-full">
        <thead className="bg-gray-100">
          <tr>{Object.keys(rows[0]).map(k => <th key={k} className="text-left px-2 py-1 font-medium text-gray-600">{k}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, 50).map((r, i) => (
            <tr key={i} className="border-t border-gray-100">
              {Object.values(r).map((v, j) => <td key={j} className="px-2 py-1 font-mono text-gray-700">{String(v)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function VirtualViewPanel() {
  const [items, setItems] = useState<VirtualViewMeta[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<{ id: string; meta: Record<string, unknown>; sql: string } | null>(null)
  const [sqlText, setSqlText] = useState('')
  const [metaYaml, setMetaYaml] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [testParams, setTestParams] = useState('{}')
  const [testRows, setTestRows] = useState<Record<string, unknown>[] | null>(null)
  const [reindexing, setReindexing] = useState(false)

  useEffect(() => { listVirtualViews().then(d => setItems(d.items)) }, [])
  useEffect(() => {
    if (!selected) return
    getVirtualView(selected).then(d => {
      setDetail(d); setSqlText(d.sql)
      setMetaYaml(JSON.stringify(d.meta, null, 2))
      setTestRows(null); setStatus(null)
      // required_params 기반 placeholder 자동 생성
      const meta = d.meta as { required_params?: string[]; optional_filters?: string[] }
      const today = new Date()
      const ymd = `${today.getFullYear()}${String(today.getMonth() + 1).padStart(2, '0')}${String(today.getDate()).padStart(2, '0')}`
      const monthStart = `${today.getFullYear()}${String(today.getMonth() + 1).padStart(2, '0')}01`
      const defaults: Record<string, string> = {
        STD_YMD: ymd, STA_YMD: monthStart, END_YMD: ymd,
        EMP_ID: '', DEPT_CD: '', NAME: '',
      }
      const allKeys = [...(meta.required_params || []), ...(meta.optional_filters || [])]
      const params = allKeys.reduce((acc, k) => { acc[k] = defaults[k] ?? ''; return acc }, {} as Record<string, string>)
      setTestParams(JSON.stringify(params, null, 2))
    })
  }, [selected])

  const save = async () => {
    if (!selected) return
    setStatus('저장 중...')
    try {
      let meta: Record<string, unknown> | undefined
      try { meta = JSON.parse(metaYaml) } catch { setStatus('메타 JSON 파싱 실패'); return }
      await saveVirtualView(selected, { meta, sql: sqlText })
      setStatus('저장 완료 (재임베딩 필요시 왼쪽 버튼)')
    } catch (e) { setStatus('실패: ' + String(e)) }
  }
  const test = async () => {
    if (!selected) return
    setStatus('Test Run 중...')
    try {
      const p = JSON.parse(testParams)
      const r = await testRunVirtualView(selected, p)
      setTestRows(r.rows); setStatus(`${r.row_count}건 반환`)
    } catch (e) { setStatus('실패: ' + String(e)) }
  }
  const reindex = () => {
    setReindexing(true)
    setStatus('시작...')
    retrainStream(
      (ev) => {
        const pct = ev.current && ev.total ? ` (${ev.current}/${ev.total})` : ''
        setStatus(`[${ev.phase}] ${ev.message}${pct}`)
      },
      () => { setStatus('재임베딩 완료'); setReindexing(false) },
      (msg) => { setStatus(`실패: ${msg}`); setReindexing(false) },
      'virtual-views/reindex',
    )
  }

  return (
    <div className="grid grid-cols-12 gap-4">
      <Panel
        className="col-span-4 max-h-[80vh] overflow-y-auto"
        title={`가상 View (${items.length})`}
        actions={
          <Button size="xs" variant="secondary" onClick={reindex} busy={reindexing}>
            {reindexing ? '...' : '재임베딩'}
          </Button>
        }
      >
        <div className="space-y-1">
          {items.map(it => (
            <button key={it.id} onClick={() => setSelected(it.id)}
              className={`w-full text-left px-2 py-1.5 text-xs rounded-lg transition-colors ${selected === it.id ? 'bg-accent-soft text-accent-strong' : 'hover:bg-gray-100'}`}>
              <div className="font-mono font-semibold">{it.id}</div>
              <div className="text-gray-500 truncate">{it.purpose}</div>
            </button>
          ))}
        </div>
      </Panel>
      <div className="col-span-8 space-y-3">
        {!detail ? (
          <Panel><EmptyState message="왼쪽에서 view를 선택하세요" /></Panel>
        ) : (
          <>
            <Panel title="메타 (JSON)">
              <textarea value={metaYaml} onChange={e => setMetaYaml(e.target.value)} rows={8}
                className={codeInputClass} spellCheck={false} />
            </Panel>
            <Panel title="SQL 본문">
              <textarea value={sqlText} onChange={e => setSqlText(e.target.value)} rows={12}
                className={codeInputClass} spellCheck={false} />
              <div className="flex gap-2 mt-2">
                <Button onClick={save}>저장</Button>
                <Button variant="secondary" onClick={test}>Test Run</Button>
                <StatusText status={status} />
              </div>
            </Panel>
            <Panel title="Test Run 파라미터 (JSON)">
              <textarea value={testParams} onChange={e => setTestParams(e.target.value)} rows={3}
                className={codeInputClass} spellCheck={false} />
              {testRows && <ResultTable rows={testRows} />}
            </Panel>
          </>
        )}
      </div>
    </div>
  )
}
