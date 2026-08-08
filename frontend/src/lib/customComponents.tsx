/**
 * 커스텀 컴포넌트 구현 — Chart, DataTable, BriefingCard.
 * json-render Renderer가 spec을 만나면 호출한다.
 *
 * 데이터는 props.dataKey로 state model에서 읽는다.
 */

import { useState, useMemo, useEffect, useRef } from 'react'
import ReactECharts from 'echarts-for-react'
import XLSX from 'xlsx-js-style'
import { saveAs } from 'file-saver'
import type { BaseComponentProps } from '@json-render/react'
import { useStateValue, useStateStore } from '@json-render/react'
import { buildChartOption, type ChartProps } from './chartOption'
import { useElementClick } from './elementClickContext'
import { applyFilters, isClickableValue, transformClickValue } from './dataDisplay'

type Row = Record<string, unknown>

/**
 * AI가 dataKey를 "data" 또는 "/data" 어느 형식으로 보내든 호환되도록 정규화.
 * useStateValue는 RFC 6901 JSON Pointer 형식("/data")을 요구함.
 */
function normalizeStatePath(key: string): string {
  if (!key) return '/data'
  return key.startsWith('/') ? key : `/${key}`
}

// ── Chart ──

interface ChartCompProps extends ChartProps {
  dataKey: string
  filterPath?: string | null
  height?: number | null
}

export function Chart({ props }: BaseComponentProps<ChartCompProps>) {
  const rawData = useStateValue<Row[]>(normalizeStatePath(props.dataKey)) || []
  const filters = useStateValue<Record<string, string>>(props.filterPath ? normalizeStatePath(props.filterPath) : '/__nope__')
  const isLoading = useStateValue<boolean>('/_meta/loading') || false
  const data = useMemo(() => applyFilters(rawData, filters), [rawData, filters])
  const option = useMemo(() => buildChartOption(data, props), [data, props])

  const containerRef = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<any>(null)
  // 부모 컨테이너 너비를 직접 측정해서 ECharts에 명시적 픽셀로 전달
  // (ECharts auto-detect는 일부 케이스에서 부모 너비를 못 잡음)
  const [containerWidth, setContainerWidth] = useState<number>(0)

  useEffect(() => {
    if (!containerRef.current) return
    const el = containerRef.current
    // 초기 측정
    const initialWidth = el.clientWidth
    if (initialWidth > 0) setContainerWidth(initialWidth)

    const observer = new ResizeObserver(entries => {
      for (const entry of entries) {
        const w = entry.contentRect.width
        if (w > 0) setContainerWidth(w)
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // 너비 변경 시 차트 인스턴스에 명시적으로 resize 호출
  useEffect(() => {
    const inst = chartRef.current?.getEchartsInstance?.()
    if (inst && containerWidth > 0) {
      inst.resize({ width: containerWidth, height: props.height ?? 400 })
    }
  }, [containerWidth, props.height])

  const onElementClick = useElementClick()

  const handleEvents = useMemo(() => ({
    click: (params: { name?: string; seriesName?: string; value?: unknown; data?: { name?: string } }) => {
      if (!onElementClick) return
      const clickedValue = params.name || params.data?.name || String(params.value ?? '')
      if (clickedValue) {
        onElementClick(clickedValue, props.xLabel || props.xField || '')
      }
    },
  }), [onElementClick, props.xLabel, props.xField])

  // 차트를 그릴 수 없으면 (데이터 없음 or 집계 불가)
  if (!option || !data.length) {
    if (isLoading) {
      return (
        <div className="w-full bg-white rounded-lg border border-gray-200 p-4 flex items-center justify-center" style={{ minHeight: props.height ?? 300 }}>
          <div className="flex flex-col items-center gap-2 text-gray-400">
            <svg className="animate-spin h-6 w-6" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span className="text-xs">차트 데이터 로딩 중...</span>
          </div>
        </div>
      )
    }
    return null
  }

  const handleDownloadChart = () => {
    const inst = chartRef.current?.getEchartsInstance?.()
    if (!inst) return
    const url = inst.getDataURL({
      type: 'png',
      pixelRatio: 2,
      backgroundColor: '#ffffff',
    })
    const link = document.createElement('a')
    link.href = url
    link.download = `${props.title || 'chart'}.png`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  return (
    <div ref={containerRef} className="w-full min-w-0 block bg-white rounded-lg border border-gray-200 p-4">
      <div className="flex justify-end mb-1">
        <button
          onClick={handleDownloadChart}
          className="flex items-center gap-1 px-2.5 py-1 text-xs text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-md transition-colors"
          title="이미지 저장"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          이미지 저장
        </button>
      </div>
      <ReactECharts
        ref={chartRef}
        option={{ ...option, cursor: 'pointer' }}
        style={{
          height: props.height ?? 400,
          width: containerWidth > 0 ? containerWidth - 32 : '100%',  // padding 32 빼기
        }}
        opts={{ renderer: 'canvas' }}
        onEvents={handleEvents}
      />
    </div>
  )
}

// ── DataTable ──

interface DataTableCompProps {
  dataKey: string
  filterPath?: string | null
  title?: string | null
  pageSize?: number | null
}

export function DataTable({ props }: BaseComponentProps<DataTableCompProps>) {
  const rawData = useStateValue<Row[]>(normalizeStatePath(props.dataKey)) || []
  const filters = useStateValue<Record<string, string>>(props.filterPath ? normalizeStatePath(props.filterPath) : '/__nope__')
  const isLoading = useStateValue<boolean>('/_meta/loading') || false
  const data = useMemo(() => applyFilters(rawData, filters), [rawData, filters])
  const pageSize = props.pageSize ?? 10
  const [page, setPage] = useState(0)
  const [sortField, setSortField] = useState<string | null>(null)
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc')
  // hook은 조건부 return보다 앞에서 호출해야 함 (rules-of-hooks)
  const onElementClick = useElementClick()

  const columns = data.length > 0 ? Object.keys(data[0]) : []

  const sorted = useMemo(() => {
    if (!sortField) return data
    return [...data].sort((a, b) => {
      const va = a[sortField], vb = b[sortField]
      const cmp = typeof va === 'number' && typeof vb === 'number'
        ? va - vb
        : String(va ?? '').localeCompare(String(vb ?? ''))
      return sortOrder === 'asc' ? cmp : -cmp
    })
  }, [data, sortField, sortOrder])

  if (!data.length) {
    if (isLoading) {
      // 스켈레톤
      return (
        <div className="w-full min-w-0 bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-4 py-2 border-b border-gray-100">
            <div className="h-3 w-24 bg-gray-200 rounded animate-pulse" />
          </div>
          <div className="p-4 space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="flex gap-3">
                <div className="h-4 bg-gray-200 rounded animate-pulse flex-1" />
                <div className="h-4 bg-gray-200 rounded animate-pulse flex-1" />
                <div className="h-4 bg-gray-200 rounded animate-pulse flex-1" />
                <div className="h-4 bg-gray-200 rounded animate-pulse w-20" />
              </div>
            ))}
          </div>
          <div className="px-4 py-2 text-center text-xs text-gray-400">데이터 로딩 중...</div>
        </div>
      )
    }
    return (
      <div className="w-full min-w-0 bg-white rounded-lg border border-gray-200 p-4 flex items-center justify-center" style={{ minHeight: 80 }}>
        <span className="text-sm text-gray-400">표시할 데이터가 없습니다</span>
      </div>
    )
  }

  const totalPages = Math.ceil(sorted.length / pageSize)
  const pageData = sorted.slice(page * pageSize, (page + 1) * pageSize)

  // 단일 행이면 카드 형태로 (key-value 디테일 뷰)
  const isSingleRow = data.length === 1

  const toggleSort = (field: string) => {
    if (sortField === field) setSortOrder(o => o === 'asc' ? 'desc' : 'asc')
    else { setSortField(field); setSortOrder('asc') }
    setPage(0)
  }

  // 셀 클릭 가능 판정/변환은 dataDisplay 공용 헬퍼 사용 (A2UI 카탈로그와 공유)

  // 단일 행 → 카드 디테일 뷰
  if (isSingleRow) {
    const row = data[0]
    return (
      <div className="w-full bg-white rounded-lg border border-gray-200 overflow-hidden">
        {props.title && (
          <div className="px-5 py-3 border-b border-gray-100 bg-gradient-to-r from-slate-50 to-accent-soft">
            <h3 className="text-sm font-semibold text-gray-800">{props.title}</h3>
          </div>
        )}
        <dl className="divide-y divide-gray-100">
          {columns.map(col => {
            const val = row[col]
            const display = val == null || val === '' ? '—' : String(val)
            const clickable = onElementClick && isClickableValue(val)
            return (
              <div key={col} className="flex px-5 py-2.5 hover:bg-gray-50">
                <dt className="w-32 shrink-0 text-xs font-medium text-gray-500 uppercase tracking-wide pt-0.5">{col}</dt>
                <dd
                  className={`flex-1 text-sm break-words ${
                    clickable ? 'text-accent-strong cursor-pointer hover:underline' : 'text-gray-900'
                  }`}
                  onClick={clickable ? () => onElementClick!(transformClickValue(String(val), col, row), col) : undefined}
                >
                  {display}
                </dd>
              </div>
            )
          })}
        </dl>
      </div>
    )
  }

  const handleDownload = () => {
    const ws = XLSX.utils.json_to_sheet(data)
    const headerStyle = {
      fill: { fgColor: { rgb: '4472C4' } },
      font: { bold: true, color: { rgb: 'FFFFFF' }, sz: 11 },
      border: { bottom: { style: 'thin', color: { rgb: '2F5496' } } },
      alignment: { horizontal: 'center' },
    }
    const range = XLSX.utils.decode_range(ws['!ref'] || 'A1')
    for (let c = range.s.c; c <= range.e.c; c++) {
      const addr = XLSX.utils.encode_cell({ r: 0, c })
      if (ws[addr]) ws[addr].s = headerStyle
    }
    ws['!cols'] = columns.map(col => {
      const maxLen = Math.max(col.length, ...data.map(r => String(r[col] ?? '').length))
      return { wch: Math.min(Math.max(maxLen + 2, 8), 30) }
    })
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, ws, 'Data')
    const buf = XLSX.write(wb, { bookType: 'xlsx', type: 'array' })
    saveAs(new Blob([buf], { type: 'application/octet-stream' }), `${props.title || 'data'}.xlsx`)
  }

  return (
    <div className="w-full min-w-0 bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100">
        <span className="text-xs text-gray-500">{sorted.length}건{props.title ? ` · ${props.title}` : ''}</span>
        <button onClick={handleDownload} className="flex items-center gap-1 px-2.5 py-1 text-xs text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-md transition-colors">
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          엑셀 다운로드
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              {columns.map(col => (
                <th key={col} onClick={() => toggleSort(col)} className="px-4 py-2.5 text-left font-medium text-gray-700 cursor-pointer hover:bg-gray-100 select-none whitespace-nowrap">
                  {col}{sortField === col && <span className="ml-1">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageData.map((row, i) => (
              <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                {columns.map(col => {
                  const val = row[col]
                  const clickable = onElementClick && isClickableValue(val)
                  return (
                    <td
                      key={col}
                      onClick={clickable ? () => onElementClick!(transformClickValue(String(val), col, row), col) : undefined}
                      className={`px-4 py-2 whitespace-nowrap ${
                        clickable
                          ? 'text-accent-strong cursor-pointer hover:underline hover:bg-accent-soft'
                          : 'text-gray-800'
                      }`}
                    >
                      {String(val ?? '')}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-4 py-2 border-t border-gray-200 bg-gray-50">
          <span className="text-xs text-gray-500">{sorted.length}건 중 {page * pageSize + 1}~{Math.min((page + 1) * pageSize, sorted.length)}</span>
          <div className="flex gap-1">
            <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} className="px-2 py-1 text-xs border rounded disabled:opacity-40 hover:bg-gray-100">이전</button>
            <span className="px-2 py-1 text-xs text-gray-600">{page + 1} / {totalPages}</span>
            <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1} className="px-2 py-1 text-xs border rounded disabled:opacity-40 hover:bg-gray-100">다음</button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── BriefingCard ──

interface BriefingCardCompProps {
  headline: string
  bullets: string[]
  note?: string | null
}

export function BriefingCard({ props }: BaseComponentProps<BriefingCardCompProps>) {
  const [expanded, setExpanded] = useState(true)
  const hasDetail = (props.bullets?.length ?? 0) > 0 || (props.note && props.note.length > 0)

  return (
    <div className="w-full min-w-0 bg-gradient-to-br from-slate-50 to-accent-soft border border-accent-muted/60 rounded-xl overflow-hidden">
      <button
        onClick={() => hasDetail && setExpanded(!expanded)}
        className={`w-full px-5 py-3 flex items-center gap-3 text-left ${hasDetail ? 'hover:bg-accent-soft/50 cursor-pointer' : ''} transition-colors`}
      >
        <div className="w-7 h-7 bg-accent rounded-lg flex items-center justify-center shrink-0">
          <span className="text-white text-xs font-bold">AI</span>
        </div>
        <h3 className="text-sm font-semibold text-gray-900 flex-1">{props.headline}</h3>
        {hasDetail && (
          <svg className={`w-4 h-4 text-gray-400 shrink-0 transition-transform ${expanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        )}
      </button>
      {expanded && hasDetail && (
        <div className="border-t border-accent-muted/60">
          {props.bullets && props.bullets.length > 0 && (
            <ul className="px-5 py-3 space-y-1.5">
              {props.bullets.map((item, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                  <span className="text-accent mt-0.5 shrink-0">•</span>
                  <span className="leading-relaxed">{item}</span>
                </li>
              ))}
            </ul>
          )}
          {props.note && (
            <div className="px-5 py-2.5 bg-white/50 border-t border-accent-muted/60">
              <p className="text-xs text-gray-500 flex items-start gap-1.5">
                <span className="shrink-0 mt-px">*</span>
                <span>{props.note}</span>
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Filter ──

interface FilterCompProps {
  /** 필터링할 데이터의 state key (보통 "data") */
  dataKey: string
  /** 필터 상태를 저장할 state key (보통 "filters"). Chart/DataTable의 filterPath와 같아야 함 */
  filterPath: string
  /** 필터 가능한 컬럼 목록 (각 컬럼에 대해 dropdown 자동 생성) */
  columns: string[]
  /** 카드 제목 (선택) */
  title?: string | null
}

export function Filter({ props }: BaseComponentProps<FilterCompProps>) {
  const data = useStateValue<Row[]>(normalizeStatePath(props.dataKey)) || []
  const filterPath = normalizeStatePath(props.filterPath)
  const filters = useStateValue<Record<string, string>>(filterPath) || {}
  const store = useStateStore()

  // 각 컬럼별로 unique values 계산
  const optionsByColumn = useMemo(() => {
    const result: Record<string, string[]> = {}
    for (const col of props.columns || []) {
      const seen = new Set<string>()
      for (const row of data) {
        const v = row[col]
        if (v != null) seen.add(String(v))
      }
      result[col] = Array.from(seen).sort()
    }
    return result
  }, [data, props.columns])

  const handleChange = (col: string, val: string) => {
    const next = { ...filters, [col]: val }
    // 빈 문자열은 키 자체 제거
    if (val === '') delete next[col]
    store.set(filterPath, next)
  }

  const handleReset = () => {
    store.set(filterPath, {})
  }

  const hasActive = Object.values(filters).some(v => v !== '' && v != null)

  if (!props.columns?.length) {
    return null
  }

  return (
    <div className="w-full min-w-0 bg-white rounded-lg border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-800">{props.title || '필터'}</h3>
        {hasActive && (
          <button
            onClick={handleReset}
            className="text-xs text-accent-strong hover:text-accent"
          >
            초기화
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-3">
        {props.columns.map(col => (
          <div key={col} className="flex flex-col gap-1 min-w-[140px]">
            <label className="text-xs text-gray-500">{col}</label>
            <select
              value={filters[col] || ''}
              onChange={e => handleChange(col, e.target.value)}
              className="border border-gray-300 rounded-md px-2 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-accent/25 focus:border-accent"
            >
              <option value="">전체</option>
              {(optionsByColumn[col] || []).map(opt => (
                <option key={opt} value={opt}>{opt}</option>
              ))}
            </select>
          </div>
        ))}
      </div>
    </div>
  )
}

// 이 파일은 컴포넌트 레지스트리이므로 non-component export가 의도된 구조
// eslint-disable-next-line react-refresh/only-export-components
export const customComponents = {
  Chart,
  DataTable,
  BriefingCard,
  Filter,
}
