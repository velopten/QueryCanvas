import { useState, useEffect, useRef } from 'react'
import {
  listEvalResults, getEvalResult, runEvalStream,
  IS_STATIC, type EvalResultMeta, type EvalResultDetail, type EvalCaseResult,
} from '../../utils/api'
import { Button, Panel, Badge, EmptyState } from '../../components/ui'

function EvalSummaryCard({ meta, accent }: { meta: EvalResultMeta; accent?: boolean }) {
  const s = meta.summary
  const c = meta.config
  return (
    <div className={`rounded-xl border p-4 ${accent ? 'border-accent-muted bg-accent-soft' : 'border-gray-200 bg-white'}`}>
      <p className="text-xs text-gray-500 mb-1">{meta.file}</p>
      <p className="text-sm font-medium text-gray-800">{c.model} <span className="text-gray-400">/ effort={c.effort} / {c.agentic ? '에이전틱' : '1-pass'}</span></p>
      <div className="flex gap-4 mt-2 text-sm">
        <span className={s.accuracy >= 0.9 ? 'text-emerald-600 font-semibold' : 'text-amber-600 font-semibold'}>
          정확도 {s.passed}/{s.total} ({Math.round(s.accuracy * 100)}%)
        </span>
        <span className="text-gray-600">평균 {s.avg_gen_seconds ?? '-'}s</span>
        <span className="text-gray-600">${s.total_cost_usd ?? '-'}</span>
      </div>
    </div>
  )
}

function EvalCaseRow({ r }: { r: EvalCaseResult }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <tr onClick={() => setOpen(o => !o)} className="cursor-pointer hover:bg-gray-50 border-t border-gray-100">
        <td className="px-3 py-2">
          <Badge tone={r.passed ? 'success' : 'danger'}>{r.passed ? 'PASS' : 'FAIL'}</Badge>
        </td>
        <td className="px-3 py-2 text-sm text-gray-800">{r.id}</td>
        <td className="px-3 py-2 text-sm text-gray-500 max-w-xs truncate">{r.question}</td>
        <td className="px-3 py-2 text-sm text-gray-600 text-right">{r.gen_seconds ?? '-'}s</td>
        <td className="px-3 py-2 text-sm text-gray-600 text-right">{r.tool_calls ?? '-'}</td>
        <td className="px-3 py-2 text-sm text-gray-600 text-right">{r.cost_usd != null ? `$${r.cost_usd.toFixed(4)}` : '-'}</td>
      </tr>
      {open && (
        <tr className="border-t border-gray-100 bg-gray-50">
          <td colSpan={6} className="px-3 py-2">
            {r.failure && <p className="text-xs text-red-600 mb-2">실패 사유: {r.failure}</p>}
            {r.sql
              ? <pre className="text-xs font-mono bg-gray-900 text-gray-200 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap">{r.sql}</pre>
              : <p className="text-xs text-gray-400">생성된 SQL 없음</p>}
            <p className="text-xs text-gray-400 mt-1">결과 {r.generated_rows ?? '-'}행 · 실행 {r.exec_seconds ?? '-'}s</p>
          </td>
        </tr>
      )}
    </>
  )
}

export default function EvalPanel() {
  const [results, setResults] = useState<EvalResultMeta[]>([])
  const [detail, setDetail] = useState<{ file: string; data: EvalResultDetail } | null>(null)
  const [compare, setCompare] = useState<string[]>([])
  const [detailsCache, setDetailsCache] = useState<Record<string, EvalResultDetail>>({})
  const [running, setRunning] = useState(false)
  const [runLog, setRunLog] = useState<string[]>([])
  const abortRef = useRef<(() => void) | null>(null)

  const fetchData = () => {
    listEvalResults().then(d => setResults(d.items)).catch(() => {})
  }
  useEffect(fetchData, [])
  useEffect(() => () => abortRef.current?.(), [])

  const loadIntoCache = (file: string) => {
    getEvalResult(file)
      .then(d => setDetailsCache(prev => ({ ...prev, [file]: d })))
      .catch(() => {})
  }

  // 비교 뷰는 캐시에서 파생 (2개 선택 + 둘 다 로드 완료 시)
  const compareData = compare.length === 2 && detailsCache[compare[0]] && detailsCache[compare[1]]
    ? { a: detailsCache[compare[0]], b: detailsCache[compare[1]] }
    : null

  const handleRun = () => {
    setRunning(true)
    setRunLog(['평가 시작...'])
    setDetail(null)
    abortRef.current = runEvalStream(
      ev => {
        if (ev.phase === 'start') {
          setRunLog(prev => [...prev, `설정: ${ev.config?.model} / effort=${ev.config?.effort} / ${ev.config?.agentic ? '에이전틱' : '1-pass'} — ${ev.total}케이스`])
        } else if (ev.phase === 'case_start') {
          setRunLog(prev => [...prev, `[${ev.index}/${ev.total}] ${ev.id} 실행 중...`])
        } else if (ev.phase === 'case_done' && ev.result) {
          const r = ev.result
          const mark = r.passed ? 'PASS' : `FAIL (${r.failure})`
          setRunLog(prev => [...prev.slice(0, -1), `[${ev.index}/${ev.total}] ${r.id} ... ${mark} [${r.gen_seconds}s]`])
        } else if (ev.phase === 'summary' && ev.summary) {
          const s = ev.summary
          setRunLog(prev => [...prev, `완료 — 정확도 ${s.passed}/${s.total} (${Math.round(s.accuracy * 100)}%), 평균 ${s.avg_gen_seconds}s, $${s.total_cost_usd}`])
        }
      },
      () => { setRunning(false); fetchData() },
      msg => { setRunLog(prev => [...prev, `오류: ${msg}`]); setRunning(false) },
    )
  }

  const toggleCompare = (file: string) => {
    setCompare(prev => prev.includes(file)
      ? prev.filter(f => f !== file)
      : prev.length >= 2 ? [prev[1], file] : [...prev, file])
    loadIntoCache(file)
  }

  const openDetail = async (file: string) => {
    if (detail?.file === file) { setDetail(null); return }
    try { setDetail({ file, data: await getEvalResult(file) }) } catch { /* ignore */ }
  }

  return (
    <div className="space-y-6">
      {/* 실행 */}
      <Panel
        title="골든셋 평가 실행"
        description="현재 서버 설정(모델/effort/에이전틱)으로 골든 질문셋을 실행하고 정확도/지연/비용을 기록합니다. 프롬프트·모델·검색 가중치 변경 전후로 실행해서 회귀를 확인하세요."
        actions={
          <Button size="md" mutating demoReplay onClick={handleRun} busy={running}>
            {running ? '실행 중...' : IS_STATIC ? '저장된 평가 재생' : '평가 실행'}
          </Button>
        }
      >
        <div className="space-y-3">
          {IS_STATIC && (
            <p className="text-xs text-cyan-700 bg-cyan-50 border border-cyan-200 rounded-lg px-3 py-2">
              공개본에서는 백엔드를 호출하지 않고, 스냅샷 생성 전 실제로 실행한 최신 평가 결과를 케이스별로 재생합니다.
            </p>
          )}
          {runLog.length > 0 && (
            <div className="bg-gray-900 rounded-lg p-3 max-h-64 overflow-y-auto">
              {runLog.map((line, i) => (
                <div key={i} className={`text-xs font-mono py-0.5 ${line.includes('FAIL') || line.includes('오류') ? 'text-red-400' : line.includes('PASS') || line.includes('완료') ? 'text-emerald-400' : 'text-gray-300'}`}>
                  {line}
                </div>
              ))}
            </div>
          )}
        </div>
      </Panel>

      {/* 비교 뷰 */}
      {compareData && (
        <Panel title="실행 비교">
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <EvalSummaryCard meta={{ file: compare[0], config: compareData.a.config, summary: compareData.a.summary }} accent />
              <EvalSummaryCard meta={{ file: compare[1], config: compareData.b.config, summary: compareData.b.summary }} accent />
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-400">
                  <th className="px-3 py-1 font-medium">케이스</th>
                  <th className="px-3 py-1 font-medium">A</th>
                  <th className="px-3 py-1 font-medium">B</th>
                  <th className="px-3 py-1 text-right font-medium">A 시간</th>
                  <th className="px-3 py-1 text-right font-medium">B 시간</th>
                </tr>
              </thead>
              <tbody>
                {compareData.a.results.map(ra => {
                  const rb = compareData.b.results.find(r => r.id === ra.id)
                  const diff = rb && ra.passed !== rb.passed
                  return (
                    <tr key={ra.id} className={`border-t border-gray-100 ${diff ? 'bg-amber-50' : ''}`}>
                      <td className="px-3 py-1.5 text-gray-700">{ra.id}</td>
                      <td className={`px-3 py-1.5 text-xs font-semibold ${ra.passed ? 'text-emerald-600' : 'text-red-600'}`}>{ra.passed ? 'PASS' : 'FAIL'}</td>
                      <td className={`px-3 py-1.5 text-xs font-semibold ${rb ? (rb.passed ? 'text-emerald-600' : 'text-red-600') : 'text-gray-300'}`}>{rb ? (rb.passed ? 'PASS' : 'FAIL') : '-'}</td>
                      <td className="px-3 py-1.5 text-gray-500 text-right">{ra.gen_seconds ?? '-'}s</td>
                      <td className="px-3 py-1.5 text-gray-500 text-right">{rb?.gen_seconds ?? '-'}s</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {/* 실행 이력 */}
      <Panel
        flush
        title="실행 이력"
        description="비교 체크박스로 2개 선택 시 위에 비교 뷰가 표시됩니다"
      >
        {results.length === 0 ? (
          <EmptyState message="아직 실행 이력이 없습니다" action="위에서 평가를 실행하거나 CLI(python eval/run_eval.py)로 실행하세요" />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-400">
                <th className="px-4 py-2 font-medium">비교</th>
                <th className="px-4 py-2 font-medium">실행 시각</th>
                <th className="px-4 py-2 font-medium">설정</th>
                <th className="px-4 py-2 text-right font-medium">정확도</th>
                <th className="px-4 py-2 text-right font-medium">평균 시간</th>
                <th className="px-4 py-2 text-right font-medium">비용</th>
              </tr>
            </thead>
            <tbody>
              {results.map(m => (
                <tr key={m.file} onClick={() => openDetail(m.file)}
                    className={`border-t border-gray-100 cursor-pointer hover:bg-gray-50 ${detail?.file === m.file ? 'bg-accent-soft' : ''}`}>
                  <td className="px-4 py-2" onClick={e => e.stopPropagation()}>
                    <input type="checkbox" checked={compare.includes(m.file)} onChange={() => toggleCompare(m.file)} className="accent-accent" />
                  </td>
                  <td className="px-4 py-2 text-gray-700">{m.config.started_at?.slice(0, 19).replace('T', ' ')}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{m.config.model} / {m.config.effort} / {m.config.agentic ? '에이전틱' : '1-pass'}</td>
                  <td className={`px-4 py-2 text-right font-semibold ${m.summary.accuracy >= 0.9 ? 'text-emerald-600' : 'text-amber-600'}`}>
                    {m.summary.passed}/{m.summary.total}
                  </td>
                  <td className="px-4 py-2 text-gray-600 text-right">{m.summary.avg_gen_seconds ?? '-'}s</td>
                  <td className="px-4 py-2 text-gray-600 text-right">${m.summary.total_cost_usd ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      {/* 상세 */}
      {detail && (
        <Panel
          flush
          title={`케이스별 상세 — ${detail.file}`}
          description="행 클릭 시 생성된 SQL / 실패 사유가 펼쳐집니다"
        >
          <table className="w-full">
            <thead>
              <tr className="text-left text-xs text-gray-400">
                <th className="px-3 py-2 font-medium">결과</th>
                <th className="px-3 py-2 font-medium">케이스</th>
                <th className="px-3 py-2 font-medium">질문</th>
                <th className="px-3 py-2 text-right font-medium">생성 시간</th>
                <th className="px-3 py-2 text-right font-medium">도구 호출</th>
                <th className="px-3 py-2 text-right font-medium">비용</th>
              </tr>
            </thead>
            <tbody>
              {detail.data.results.map(r => <EvalCaseRow key={r.id} r={r} />)}
            </tbody>
          </table>
        </Panel>
      )}
    </div>
  )
}
