/**
 * A2UI 프로덕션 카탈로그 — 커스텀 컴포넌트 4종 (Chart/DataTable/BriefingCard/Filter).
 *
 * 백엔드(backend/ui_engine/a2ui_catalog.py)와 계약 공유:
 * - catalogId: query-canvas/v1 / surfaceId: "result"
 * - 데이터 모델: /rows (SQL 결과), /filters (Filter two-way)
 *
 * 주의: a2ui는 zod v3 피어 — 스키마는 'zod3' 알리아스로만 작성 (프로젝트 zod v4와 혼용 금지).
 * 드릴다운 클릭은 elementClickContext(React Context)로 앱에 전달한다.
 */
import { useState, useMemo, useEffect, useRef } from 'react'
import { z } from 'zod3'
import ReactEChartsRaw from 'echarts-for-react'
import XLSX from 'xlsx-js-style'
import FileSaver from 'file-saver'
import {
  Catalog,
  DynamicBooleanSchema,
  DynamicStringSchema,
  DynamicValueSchema,
} from '@a2ui/web_core/v0_9'
import { createComponentImplementation, basicCatalog } from '@a2ui/react/v0_9'
import { buildChartOption, type ChartProps } from '../chartOption'
import { useElementClick } from '../elementClickContext'
import {
  applyFilters,
  formatCellValue,
  isClickableValue,
  isNumericColumn,
  transformClickValue,
  type ColumnFormats,
  type DataRow,
} from '../dataDisplay'

export const CATALOG_ID = 'query-canvas/v1'
export const SURFACE_ID = 'result'

// CJS 패키지 default interop — vite(브라우저)와 tsx(node 검증 스크립트) 양쪽 호환
const ReactECharts = ((ReactEChartsRaw as { default?: unknown }).default ?? ReactEChartsRaw) as typeof ReactEChartsRaw

// ── Chart ────────────────────────────────────────────────────────────────────

const ChartApi = {
  name: 'Chart',
  schema: z.object({
    chartType: z.enum(['bar', 'line', 'pie', 'gauge', 'heatmap']),
    title: DynamicStringSchema.optional(),
    xField: z.string().optional(),
    yField: z.string().optional(),
    xLabel: z.string().optional(),
    yLabel: z.string().optional(),
    seriesField: z.string().optional(),
    highlightField: z.string().optional(),
    highlightThreshold: z.number().optional(),
    height: z.number().optional(),
    // 스켈레톤(스테이지①)은 rows 바인딩 없이 loading만 옴 — optional
    rows: DynamicValueSchema.optional(),
    filters: DynamicValueSchema.optional(),
    loading: DynamicBooleanSchema.optional(),
  }),
}

const Chart = createComponentImplementation(ChartApi, ({ props }) => {
  const data = useMemo(
    () => applyFilters(
      (props.rows as DataRow[] | undefined) ?? [],
      props.filters as Record<string, string> | undefined,
    ),
    [props.rows, props.filters],
  )

  const option = useMemo(() => {
    const chartProps: ChartProps = {
      type: props.chartType as ChartProps['type'],
      title: (props.title as string) ?? null,
      xField: props.xField ?? null,
      yField: props.yField ?? null,
      xLabel: props.xLabel ?? null,
      yLabel: props.yLabel ?? null,
      seriesField: props.seriesField ?? null,
      highlightField: props.highlightField ?? null,
      highlightThreshold: props.highlightThreshold ?? null,
    }
    return buildChartOption(data, chartProps)
  }, [
    data, props.chartType, props.title, props.xField, props.yField,
    props.xLabel, props.yLabel, props.seriesField, props.highlightField, props.highlightThreshold,
  ])

  const containerRef = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<any>(null)
  // 부모 컨테이너 너비를 직접 측정해서 ECharts에 명시적 픽셀로 전달
  const [containerWidth, setContainerWidth] = useState<number>(0)

  useEffect(() => {
    if (!containerRef.current) return
    const el = containerRef.current
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

  useEffect(() => {
    const inst = chartRef.current?.getEchartsInstance?.()
    if (inst && containerWidth > 0) {
      inst.resize({ width: containerWidth, height: props.height ?? 400 })
    }
  }, [containerWidth, props.height])

  const onElementClick = useElementClick()
  const handleEvents = useMemo(() => ({
    click: (params: { name?: string; value?: unknown; data?: { name?: string } }) => {
      if (!onElementClick) return
      const clickedValue = params.name || params.data?.name || String(params.value ?? '')
      if (clickedValue) {
        onElementClick(clickedValue, props.xLabel || props.xField || '')
      }
    },
  }), [onElementClick, props.xLabel, props.xField])

  if (!option || !data.length) {
    // 스켈레톤/로딩 중: 데이터가 아직 없으면 shimmer 표시
    if (props.loading) {
      return (
        <div className="w-full bg-white rounded-lg border border-gray-200 p-4 flex items-center justify-center" style={{ minHeight: props.height ?? 300 }}>
          <div className="flex flex-col items-center gap-2 text-gray-400">
            <svg className="animate-spin h-6 w-6" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span className="text-xs">차트 준비 중...</span>
          </div>
        </div>
      )
    }
    return null
  }

  // node 검증 스크립트(renderCheck) 전용 — jsdom에 canvas가 없어 ECharts init 불가
  if ((globalThis as Record<string, unknown>).__A2UI_CHECK_NO_CHART) {
    return <div className="a2ui-chart-ok text-xs text-gray-400">[chart] {props.title}</div>
  }

  const handleDownloadChart = () => {
    const inst = chartRef.current?.getEchartsInstance?.()
    if (!inst) return
    const url = inst.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' })
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
          width: containerWidth > 0 ? containerWidth - 32 : '100%',
        }}
        opts={{ renderer: 'canvas' }}
        onEvents={handleEvents}
      />
    </div>
  )
})

// ── DataTable ────────────────────────────────────────────────────────────────

const DataTableApi = {
  name: 'DataTable',
  schema: z.object({
    title: DynamicStringSchema.optional(),
    pageSize: z.number().optional(),
    columnFormats: z.record(z.object({
      type: z.enum(['number', 'percent', 'text']).optional(),
      decimals: z.number().optional(),
      unit: z.string().optional(),
      currency: z.string().optional(),
    })).optional(),
    rows: DynamicValueSchema,
    filters: DynamicValueSchema.optional(),
    loading: DynamicBooleanSchema.optional(),
  }),
}

const DataTable = createComponentImplementation(DataTableApi, ({ props }) => {
  const filtered = useMemo(
    () => applyFilters(
      (props.rows as DataRow[] | undefined) ?? [],
      props.filters as Record<string, string> | undefined,
    ),
    [props.rows, props.filters],
  )
  const pageSize = props.pageSize ?? 10
  const [page, setPage] = useState(0)
  const [sortField, setSortField] = useState<string | null>(null)
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc')
  // 행이 많으면 자동으로 검색박스 노출 — "무한 선택지는 검색이 처리" 원칙
  const [search, setSearch] = useState('')
  const searchable = filtered.length > 15
  const data = useMemo(() => {
    if (!searchable || !search.trim()) return filtered
    const q = search.trim().toLowerCase()
    return filtered.filter(row => Object.values(row).some(v => String(v ?? '').toLowerCase().includes(q)))
  }, [filtered, search, searchable])
  const onElementClick = useElementClick()

  const columns = data.length > 0 ? Object.keys(data[0]) : (filtered.length > 0 ? Object.keys(filtered[0]) : [])

  const columnFormats = props.columnFormats as ColumnFormats | undefined
  // 숫자 컬럼은 우측 정렬 — 자릿수가 맞아야 큰 수 비교가 읽힌다
  const numericColumns = useMemo(
    () => new Set(columns.filter(col => columnFormats?.[col]?.type !== 'text' && isNumericColumn(filtered, col))),
    [columns, filtered, columnFormats],
  )

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
    // 검색어로 0건이 된 경우: 검색박스는 유지한 채 안내
    if (searchable && search.trim()) {
      return (
        <div className="w-full min-w-0 bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100">
            <span className="text-xs text-gray-500">0건{props.title ? ` · ${props.title}` : ''}</span>
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="검색..."
              className="w-40 border border-gray-300 rounded-md px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-accent/25 focus:border-accent"
            />
          </div>
          <p className="px-4 py-6 text-center text-sm text-gray-400">'{search}' 검색 결과가 없습니다</p>
        </div>
      )
    }
    // 스켈레톤/로딩 중: shimmer 표시 (데이터 도착 시 자동으로 표로 전환)
    if (props.loading) {
      return (
        <div className="a2ui-table-loading w-full min-w-0 bg-white rounded-lg border border-gray-200 overflow-hidden">
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
  const isSingleRow = data.length === 1

  const toggleSort = (field: string) => {
    if (sortField === field) setSortOrder(o => o === 'asc' ? 'desc' : 'asc')
    else { setSortField(field); setSortOrder('asc') }
    setPage(0)
  }

  // 단일 행이면 카드 형태 (key-value 디테일 뷰)
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
                  className={`flex-1 text-sm break-words ${clickable ? 'text-accent-strong cursor-pointer hover:underline' : 'text-gray-900'}`}
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
    FileSaver.saveAs(new Blob([buf], { type: 'application/octet-stream' }), `${props.title || 'data'}.xlsx`)
  }

  return (
    <div className="w-full min-w-0 bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="flex items-center justify-between gap-2 px-4 py-2 border-b border-gray-100">
        <span className="text-xs text-gray-500 shrink-0">{sorted.length}건{props.title ? ` · ${props.title}` : ''}</span>
        {searchable && (
          <input
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(0) }}
            placeholder="검색..."
            className="flex-1 max-w-[200px] border border-gray-300 rounded-md px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-accent/25 focus:border-accent"
          />
        )}
        <button onClick={handleDownload} className="flex items-center gap-1 px-2.5 py-1 text-xs text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-md transition-colors shrink-0">
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
                <th key={col} onClick={() => toggleSort(col)} className={`px-4 py-2.5 font-medium text-gray-700 cursor-pointer hover:bg-gray-100 select-none whitespace-nowrap ${numericColumns.has(col) ? 'text-right' : 'text-left'}`}>
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
                      className={`px-4 py-2 whitespace-nowrap ${numericColumns.has(col) ? 'text-right tabular-nums' : ''} ${clickable ? 'text-accent-strong cursor-pointer hover:underline hover:bg-accent-soft' : 'text-gray-800'}`}
                    >
                      {formatCellValue(val, col, columnFormats)}
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
            <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} className="px-2 py-1 text-xs border border-gray-200 rounded disabled:opacity-40 hover:bg-gray-100">이전</button>
            <span className="px-2 py-1 text-xs text-gray-600">{page + 1} / {totalPages}</span>
            <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1} className="px-2 py-1 text-xs border border-gray-200 rounded disabled:opacity-40 hover:bg-gray-100">다음</button>
          </div>
        </div>
      )}
    </div>
  )
})

// ── BriefingCard ─────────────────────────────────────────────────────────────

const BriefingCardApi = {
  name: 'BriefingCard',
  schema: z.object({
    headline: DynamicStringSchema,
    bullets: z.array(z.string()).optional(),
    note: DynamicStringSchema.optional(),
  }),
}

const BriefingCard = createComponentImplementation(BriefingCardApi, ({ props }) => {
  const [expanded, setExpanded] = useState(true)
  const bullets = props.bullets ?? []
  const hasDetail = bullets.length > 0 || !!props.note

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
          {bullets.length > 0 && (
            <ul className="px-5 py-3 space-y-1.5">
              {bullets.map((item: string, i: number) => (
                <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                  <span className="text-accent mt-0.5 shrink-0">•</span>
                  <span className="leading-relaxed">{String(item)}</span>
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
})

// ── StatCard (단일 KPI 강조 — "몇 명이야?" 류 단일 수치 답변) ─────────────────

const StatCardApi = {
  name: 'StatCard',
  schema: z.object({
    label: DynamicStringSchema,
    value: DynamicStringSchema,
    delta: DynamicStringSchema.optional(),
    tone: z.enum(['neutral', 'positive', 'negative']).optional(),
  }),
}

const StatCard = createComponentImplementation(StatCardApi, ({ props }) => {
  const toneClass = props.tone === 'positive' ? 'text-emerald-600'
    : props.tone === 'negative' ? 'text-red-600' : 'text-gray-500'
  return (
    <div className="flex-1 min-w-[140px] bg-white border border-gray-200 rounded-xl px-5 py-4">
      <p className="text-xs text-gray-500">{props.label}</p>
      <p className="text-2xl font-bold text-gray-900 mt-1 tracking-tight">{props.value}</p>
      {props.delta && <p className={`text-xs mt-1 font-medium ${toneClass}`}>{props.delta}</p>}
    </div>
  )
})

// ── Notice (시스템 커뮤니케이션 — 경고/안내/오류) ─────────────────────────────

const NoticeApi = {
  name: 'Notice',
  schema: z.object({
    noticeType: z.enum(['info', 'warning', 'success', 'error']),
    title: DynamicStringSchema.optional(),
    message: DynamicStringSchema,
  }),
}

const NOTICE_STYLES: Record<string, { box: string; icon: string }> = {
  info: { box: 'bg-sky-50 border-sky-200 text-sky-800', icon: 'ℹ' },
  warning: { box: 'bg-amber-50 border-amber-200 text-amber-800', icon: '⚠' },
  success: { box: 'bg-emerald-50 border-emerald-200 text-emerald-800', icon: '✓' },
  error: { box: 'bg-red-50 border-red-200 text-red-800', icon: '✕' },
}

const Notice = createComponentImplementation(NoticeApi, ({ props }) => {
  const s = NOTICE_STYLES[props.noticeType] ?? NOTICE_STYLES.info
  return (
    <div className={`w-full border rounded-lg px-4 py-3 flex items-start gap-2.5 ${s.box}`}>
      <span className="shrink-0 text-sm leading-5" aria-hidden>{s.icon}</span>
      <div className="min-w-0">
        {props.title && <p className="text-sm font-semibold">{props.title}</p>}
        <p className="text-sm">{props.message}</p>
      </div>
    </div>
  )
})

// ── Filter (two-way: /filters 바인딩에 setter 자동 주입) ──────────────────────

const FilterApi = {
  name: 'Filter',
  schema: z.object({
    title: DynamicStringSchema.optional(),
    columns: z.array(z.string()),
    rows: DynamicValueSchema,
    filters: DynamicValueSchema,
    /** 승격된 필터 초기값 — SQL이 전체 범주를 조회하고 화면이 이 값으로 초기 필터링 */
    defaultValue: z.record(z.string()).optional(),
  }),
}

const Filter = createComponentImplementation(FilterApi, ({ props }) => {
  const filters = (props.filters as unknown as Record<string, string> | undefined) ?? {}
  const p = props as typeof props & { setFilters?: (v: Record<string, string>) => void }

  // 승격된 필터 초기 적용 — 마운트 후 1회만 (사용자가 초기화하면 다시 덮지 않음)
  const defaultApplied = useRef(false)
  useEffect(() => {
    if (defaultApplied.current || !props.defaultValue) return
    defaultApplied.current = true
    if (Object.keys(filters).length === 0 && Object.keys(props.defaultValue).length > 0) {
      p.setFilters?.(props.defaultValue as Record<string, string>)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.defaultValue])

  const optionsByColumn = useMemo(() => {
    const data = (props.rows as unknown as DataRow[] | undefined) ?? []
    const result: Record<string, string[]> = {}
    for (const col of (props.columns || []) as string[]) {
      const seen = new Set<string>()
      for (const row of data) {
        const v = row[col]
        if (v != null) seen.add(String(v))
      }
      result[col] = Array.from(seen).sort()
    }
    return result
  }, [props.rows, props.columns])

  const handleChange = (col: string, val: string) => {
    const next = { ...filters, [col]: val }
    if (val === '') delete next[col]
    p.setFilters?.(next)
  }

  const hasActive = Object.values(filters).some(v => v !== '' && v != null)

  if (!props.columns?.length) return null

  return (
    <div className="w-full min-w-0 bg-white rounded-lg border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-800">{props.title || '필터'}</h3>
        {hasActive && (
          <button onClick={() => p.setFilters?.({})} className="text-xs text-accent-strong hover:text-accent">
            초기화
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-3">
        {(props.columns as string[]).map(col => (
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
})

/**
 * 앱 카탈로그 — basic 카탈로그 전체(레이아웃/텍스트 등) + 커스텀 4종.
 * catalogId는 백엔드 카탈로그(a2ui_catalog.py)와 반드시 일치해야 한다.
 */
export const appCatalog = new Catalog(
  CATALOG_ID,
  [
    ...Array.from(basicCatalog.components.values()),
    Chart,
    DataTable,
    BriefingCard,
    Filter,
    StatCard,
    Notice,
  ],
  [...Array.from(basicCatalog.functions.values())],
)
