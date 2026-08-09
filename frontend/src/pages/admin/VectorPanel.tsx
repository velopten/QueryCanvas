import { useState, useEffect } from 'react'
import {
  getSettings, retrainStream, clearSqlCache, vectorSearchTest, cacheSearchTest,
} from '../../utils/api'
import { Button, Panel, EmptyState, inputClass } from '../../components/ui'

interface SearchItem {
  content: string; distance: number; source: string
  effective_distance?: number; weight?: number; boosted?: boolean
}
interface CacheSearchItem { question: string; sql: string; cached_at: string; distance: number; would_hit: boolean }

// 타입별 표시 메타 — 타입 구분은 정보이므로 색을 유지하되 팔레트 안에서 통일
const TYPE_META: Record<string, { label: string; chip: string; card: string; dim: string }> = {
  virtual_view: { label: '가상 View', chip: 'bg-accent-soft text-accent-strong', card: 'border-accent-muted bg-accent-soft', dim: 'border-accent-muted/50 bg-accent-soft/40' },
  snapshot:     { label: '스냅샷',    chip: 'bg-cyan-100 text-cyan-700',     card: 'border-cyan-200 bg-cyan-50',     dim: 'border-cyan-100 bg-cyan-50/40' },
  ddl:          { label: 'DDL',       chip: 'bg-purple-100 text-purple-700', card: 'border-purple-200 bg-purple-50', dim: 'border-purple-100 bg-purple-50/40' },
  sql:          { label: 'SQL',       chip: 'bg-emerald-100 text-emerald-700', card: 'border-emerald-200 bg-emerald-50', dim: 'border-emerald-100 bg-emerald-50/40' },
  doc:          { label: '문서',       chip: 'bg-amber-100 text-amber-700', card: 'border-amber-200 bg-amber-50', dim: 'border-amber-100 bg-amber-50/40' },
  doc_overlay:  { label: '오버레이',   chip: 'bg-orange-100 text-orange-700',   card: 'border-orange-200 bg-orange-50',   dim: 'border-orange-100 bg-orange-50/40' },
  doc_patch:    { label: '패치',       chip: 'bg-rose-100 text-rose-700',     card: 'border-rose-200 bg-rose-50',     dim: 'border-rose-100 bg-rose-50/40' },
}
const TYPE_ORDER = ['virtual_view', 'snapshot', 'ddl', 'sql', 'doc', 'doc_overlay', 'doc_patch'] as const
const FALLBACK_META = { label: '', chip: 'bg-gray-100 text-gray-700', card: 'border-gray-200 bg-gray-50', dim: 'border-gray-100 bg-gray-50/40' }

export default function VectorPanel() {
  const [storeType, setStoreType] = useState<'training' | 'cache'>('training')
  const [status, setStatus] = useState<string | null>(null)
  const [retraining, setRetraining] = useState(false)
  const [settings, setSettings] = useState<{ vector_store_count?: number; sql_cache_count?: number } | null>(null)
  const [testQuery, setTestQuery] = useState('')
  // training results
  const [trainingResults, setTrainingResults] = useState<Record<string, SearchItem[]> | null>(null)
  const [injectLimits, setInjectLimits] = useState<Record<string, number> | null>(null)
  const [injectedCounts, setInjectedCounts] = useState<Record<string, number> | null>(null)
  // cache results
  const [cacheResults, setCacheResults] = useState<CacheSearchItem[] | null>(null)
  const [hitThreshold, setHitThreshold] = useState<number>(0.05)
  const [searching, setSearching] = useState(false)
  const [clearingCache, setClearingCache] = useState(false)

  useEffect(() => { getSettings().then(setSettings) }, [])

  const handleRetrain = () => {
    setRetraining(true)
    setStatus('시작...')
    retrainStream(
      (ev) => {
        const pct = ev.current && ev.total ? ` (${ev.current}/${ev.total})` : ''
        setStatus(`[${ev.phase}] ${ev.message}${pct}`)
      },
      () => {
        setStatus('재임베딩 완료')
        setRetraining(false)
        getSettings().then(setSettings)
      },
      (msg) => {
        setStatus(`실패: ${msg}`)
        setRetraining(false)
      },
      'retrain',
    )
  }

  const handleClearCache = async () => {
    if (!confirm('SQL 캐시 전체를 비우시겠습니까?')) return
    setClearingCache(true)
    await clearSqlCache()
    setClearingCache(false)
    getSettings().then(setSettings)
  }

  const handleTest = async () => {
    if (!testQuery.trim()) return
    setSearching(true)
    try {
      if (storeType === 'training') {
        const res = await vectorSearchTest(testQuery.trim())
        setTrainingResults(res.results)
        setInjectLimits(res.inject_limits)
        setInjectedCounts(res.injected_counts)
        setCacheResults(null)
      } else {
        const res = await cacheSearchTest(testQuery.trim())
        setCacheResults(res.results)
        setHitThreshold(res.hit_threshold)
        setTrainingResults(null)
      }
    } catch {
      setTrainingResults(null)
      setCacheResults(null)
    }
    setSearching(false)
  }

  return (
    <div className="space-y-4">
      {/* Status cards */}
      <div className="grid grid-cols-2 gap-4">
        <Panel
          title="학습 데이터"
          description="DDL + SQL + 문서 임베딩"
          actions={
            <Button size="xs" onClick={handleRetrain} busy={retraining}>
              {retraining ? '재임베딩 중...' : '재임베딩'}
            </Button>
          }
        >
          <div className="text-2xl font-bold text-gray-900">{settings?.vector_store_count ?? '...'}</div>
          {status && <p className="mt-1 text-xs text-emerald-600">{status}</p>}
        </Panel>
        <Panel
          title="SQL 캐시"
          description="질문→SQL 매핑"
          actions={
            <Button variant="danger" size="xs" onClick={handleClearCache} busy={clearingCache}>
              {clearingCache ? '비우는 중...' : '캐시 비우기'}
            </Button>
          }
        >
          <div className="text-2xl font-bold text-gray-900">{settings?.sql_cache_count ?? '...'}</div>
        </Panel>
      </div>

      {/* Search test */}
      <Panel
        title="검색 테스트"
        description={storeType === 'training'
          ? '타입별 분리 검색 + 가중치(weight) 적용. effective_distance = distance × weight 가 낮을수록 우선. 각 타입은 inject_limit 만큼 프롬프트에 주입됩니다.'
          : '자연어 질문 → 이전에 생성된 SQL 중 유사한 항목을 검색합니다. 캐시 히트 시 AI 호출 없이 SQL을 재활용합니다.'}
        actions={
          <select
            value={storeType}
            onChange={e => { setStoreType(e.target.value as 'training' | 'cache'); setTrainingResults(null); setCacheResults(null) }}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm font-medium bg-white"
          >
            <option value="training">학습 데이터 (DDL/SQL/문서)</option>
            <option value="cache">SQL 캐시 (질문→SQL)</option>
          </select>
        }
      >
        <div className="flex gap-2 mb-3">
          <input
            value={testQuery}
            onChange={e => setTestQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleTest()}
            placeholder="검색할 질문 입력"
            className={inputClass}
          />
          <Button size="md" onClick={handleTest} busy={searching} disabled={!testQuery.trim()}>
            {searching ? '검색 중...' : '검색'}
          </Button>
        </div>

        {/* Training results */}
        {storeType === 'training' && trainingResults && (() => {
          const allTypes = Array.from(new Set([
            ...TYPE_ORDER,
            ...Object.keys(trainingResults),
            ...(injectLimits ? Object.keys(injectLimits) : []),
          ]))
          const visibleTypes = allTypes.filter(t => (trainingResults[t]?.length || 0) > 0 || (injectLimits?.[t] ?? 0) > 0)

          return (
          <div className="space-y-4">
            {injectLimits && (
              <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
                <h4 className="text-xs font-semibold text-gray-700 mb-2">AI 프롬프트 주입 기준 (타입별 가중치 + inject_limit)</h4>
                <div className="flex gap-x-4 gap-y-1.5 flex-wrap text-xs">
                  {visibleTypes.map(type => {
                    const total = trainingResults[type]?.length ?? 0
                    const injected = injectedCounts?.[type] ?? 0
                    const limit = injectLimits[type] ?? 0
                    const over = total > limit
                    const meta = TYPE_META[type] || { ...FALLBACK_META, label: type }
                    return (
                      <div key={type} className="flex items-center gap-1.5">
                        <span className={`px-1.5 py-0.5 rounded font-semibold ${meta.chip}`}>{meta.label}</span>
                        <span className={`font-mono ${over ? 'text-amber-600' : 'text-gray-700'}`}>{injected}/{total}건 주입</span>
                        <span className="text-gray-400">(최대 {limit}건)</span>
                        {over && <span className="text-amber-500 text-[10px]">{total - limit}건 미포함</span>}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            <div className="flex gap-2 text-xs flex-wrap">
              {visibleTypes.map(type => {
                const meta = TYPE_META[type] || { ...FALLBACK_META, label: type }
                return (
                  <span key={type} className={`px-2 py-1 rounded ${meta.chip}`}>
                    {meta.label}: {trainingResults[type]?.length ?? 0}건
                  </span>
                )
              })}
            </div>

            {visibleTypes.map(type => {
              const items = trainingResults[type] || []
              if (!items.length) return null
              const limit = injectLimits?.[type] ?? 999
              const meta = TYPE_META[type] || { ...FALLBACK_META, label: type }
              return (
                <div key={type}>
                  <h4 className="text-xs font-semibold text-gray-600 mb-2 flex items-center gap-2">
                    <span className={`px-1.5 py-0.5 rounded ${meta.chip}`}>{meta.label}</span>
                    <span className="text-gray-400">(최대 {limit}건 주입 · 가중치 {items[0]?.weight?.toFixed(2) ?? '1.00'})</span>
                  </h4>
                  <div className="space-y-2">
                    {items.map((item: SearchItem, i: number) => {
                      const isInjected = i < limit
                      const eff = item.effective_distance ?? item.distance
                      return (
                        <div key={i} className={`border rounded-lg p-3 relative ${isInjected ? meta.card : meta.dim}`}>
                          <span className={`absolute top-2 right-2 px-1.5 py-0.5 text-[10px] rounded font-medium ${isInjected ? 'bg-accent-muted text-accent-strong' : 'bg-gray-200 text-gray-500'}`}>
                            {isInjected ? '주입됨' : '미포함'}
                          </span>
                          <div className="flex justify-between text-xs text-gray-500 mb-1 pr-14 gap-2">
                            <span className="truncate">{item.source}</span>
                            <span className="font-mono whitespace-nowrap">
                              d={item.distance.toFixed(3)}
                              {item.effective_distance !== undefined && item.weight !== undefined && item.weight !== 1 && (
                                <span className="text-accent-strong"> × {item.weight.toFixed(2)} = {eff.toFixed(3)}</span>
                              )}
                              <span className="font-semibold text-gray-700 ml-1">({((1 - item.distance) * 100).toFixed(1)}% 유사)</span>
                            </span>
                          </div>
                          <pre className={`text-xs whitespace-pre-wrap max-h-40 overflow-y-auto ${isInjected ? 'text-gray-700' : 'text-gray-400'}`}>{item.content}</pre>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
          )
        })()}

        {/* Cache results */}
        {storeType === 'cache' && cacheResults && (
          <div className="space-y-3">
            <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
              <h4 className="text-xs font-semibold text-gray-700 mb-1">캐시 히트 기준</h4>
              <p className="text-xs text-gray-500">cosine distance ≤ {hitThreshold} (유사도 ≥ {((1 - hitThreshold) * 100).toFixed(1)}%) 일 때만 캐시 히트</p>
            </div>

            {cacheResults.length === 0 ? (
              <EmptyState message="캐시된 SQL이 없습니다" action="질문을 실행하면 자동으로 캐시됩니다" />
            ) : (
              <div className="space-y-2">
                {cacheResults.map((item, i) => (
                  <div key={i} className={`border rounded-lg p-3 relative ${item.would_hit ? 'border-emerald-300 bg-emerald-50' : 'border-gray-200 bg-white'}`}>
                    <span className={`absolute top-2 right-2 px-1.5 py-0.5 text-[10px] rounded font-medium ${item.would_hit ? 'bg-emerald-200 text-emerald-700' : 'bg-gray-200 text-gray-500'}`}>
                      {item.would_hit ? '캐시 히트' : '미스'}
                    </span>
                    <div className="text-xs text-gray-500 mb-1 pr-16">
                      <span className="font-mono">
                        거리: {item.distance.toFixed(4)}
                        <span className={`ml-2 font-semibold ${item.would_hit ? 'text-emerald-700' : 'text-gray-700'}`}>
                          ({((1 - item.distance) * 100).toFixed(1)}% 유사)
                        </span>
                      </span>
                      {item.cached_at && <span className="ml-3 text-gray-400">{new Date(item.cached_at).toLocaleString('ko-KR')}</span>}
                    </div>
                    <p className="text-sm text-gray-800 mb-1">{item.question}</p>
                    <pre className="text-xs text-emerald-400 bg-gray-900 rounded-lg p-2 whitespace-pre-wrap max-h-32 overflow-y-auto">{item.sql}</pre>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Panel>
    </div>
  )
}
