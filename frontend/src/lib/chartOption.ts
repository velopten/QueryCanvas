/**
 * Chart 컴포넌트용 ECharts 옵션 빌더.
 * data + chart props → ECharts option 객체.
 */

import type { EChartsOption } from 'echarts'

const COLORS = [
  '#5B8FF9', '#5AD8A6', '#F6BD16', '#E86452', '#6DC8EC', '#945FB9', '#FF9845', '#1E9493',
]
const HIGHLIGHT_COLOR = '#E24B4A'

export interface ChartProps {
  type: 'bar' | 'line' | 'pie' | 'gauge' | 'heatmap'
  title?: string | null
  xField?: string | null
  yField?: string | null
  xLabel?: string | null
  yLabel?: string | null
  seriesField?: string | null
  highlightField?: string | null
  highlightThreshold?: number | null
}

type Row = Record<string, unknown>

// ── 숫자 축 표기 ─────────────────────────────────────────────────────────────
// 축 눈금은 자리수가 길면 겹치므로 축약(1.2억), 툴팁은 정확한 값을 천단위로 보여준다.
// 임계값 10000은 dataDisplay 의 자동 포맷 기준과 맞춘다 — 연도 등 4자리는 그대로.
const COMPACT_MIN = 10000

function formatAxisNumber(v: number): string {
  if (!Number.isFinite(v)) return String(v)
  return Math.abs(v) >= COMPACT_MIN
    ? new Intl.NumberFormat('ko-KR', { notation: 'compact', maximumFractionDigits: 1 }).format(v)
    : new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 20 }).format(v)
}

const VALUE_AXIS = { type: 'value' as const, axisLabel: { formatter: formatAxisNumber } }

const NUMBER_TOOLTIP = {
  trigger: 'axis' as const,
  valueFormatter: (v: unknown) =>
    typeof v === 'number' && Number.isFinite(v)
      ? new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 20 }).format(v)
      : String(v ?? ''),
}

/**
 * 차트용 데이터를 정규화한다.
 * - yField가 데이터에 없거나 모든 값이 0/NaN이면 xField 기준 카운트로 자동 집계
 * - 결과: { rows, xField, yField } — 차트가 그릴 수 있는 형태
 *
 * 반환 rows가 비어있으면 차트 그릴 수 없음 (호출자가 null 처리).
 */
function normalizeForChart(
  data: Row[],
  xFieldHint: string | null | undefined,
  yFieldHint: string | null | undefined,
): { rows: Row[]; xField: string; yField: string } | null {
  if (!data.length) return null
  const cols = Object.keys(data[0])
  let xField = xFieldHint ?? cols[0]
  const yField = yFieldHint ?? cols[1]

  if (!cols.includes(xField)) xField = cols[0]

  // yField가 데이터에 없거나, 모든 값이 숫자가 아니면 자동 집계 모드
  const yIsValid = cols.includes(yField) && data.some(row => {
    const v = row[yField]
    return typeof v === 'number' || (typeof v === 'string' && !isNaN(Number(v)) && v !== '')
  })

  if (!yIsValid) {
    // xField 기준 count by 자동 집계
    const counts = new Map<string, number>()
    for (const row of data) {
      const key = String(row[xField] ?? '')
      counts.set(key, (counts.get(key) ?? 0) + 1)
    }
    const aggregated: Row[] = Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([key, cnt]) => ({ [xField]: key, count: cnt }))
    return { rows: aggregated, xField, yField: 'count' }
  }

  return { rows: data, xField, yField }
}

function buildHighlightSeries(data: Row[], yField: string, hField: string, threshold: number) {
  const normal: (number | null)[] = []
  const highlighted: (number | null)[] = []
  data.forEach(row => {
    const v = Number(row[yField])
    const h = Number(row[hField])
    if (h >= threshold) {
      normal.push(null)
      highlighted.push(v)
    } else {
      normal.push(v)
      highlighted.push(null)
    }
  })
  return { normal, highlighted }
}

function bar(data: Row[], p: ChartProps): EChartsOption | null {
  const norm = normalizeForChart(data, p.xField, p.yField)
  if (!norm || !norm.rows.length) return null
  const { rows, xField, yField } = norm
  const categories = rows.map(row => String(row[xField]))

  if (p.highlightField && typeof p.highlightThreshold === 'number') {
    const h = buildHighlightSeries(rows, yField, p.highlightField, p.highlightThreshold)
    return {
      tooltip: NUMBER_TOOLTIP,
      xAxis: { type: 'category', data: categories, name: p.xLabel ?? undefined },
      yAxis: { ...VALUE_AXIS, name: p.yLabel ?? undefined },
      series: [
        { name: p.yLabel ?? yField, type: 'bar', data: h.normal, itemStyle: { color: COLORS[0] } },
        { name: '주의', type: 'bar', data: h.highlighted, itemStyle: { color: HIGHLIGHT_COLOR } },
      ],
    }
  }

  return {
    tooltip: NUMBER_TOOLTIP,
    xAxis: { type: 'category', data: categories, name: p.xLabel ?? undefined },
    yAxis: { ...VALUE_AXIS, name: p.yLabel ?? undefined },
    series: [{
      name: p.yLabel ?? yField,
      type: 'bar',
      data: rows.map(row => Number(row[yField])),
      itemStyle: { color: COLORS[0] },
    }],
  }
}

function line(data: Row[], p: ChartProps): EChartsOption | null {
  // 다중 시리즈는 raw 데이터 그대로 사용 (집계 안 함)
  if (p.seriesField) {
    if (!data.length) return null
    const xField = p.xField ?? Object.keys(data[0])[0]
    const yField = p.yField ?? Object.keys(data[0])[1]
    const categories = data.map(row => String(row[xField]))
    const seriesNames = [...new Set(data.map(row => String(row[p.seriesField!])))]
    return {
      tooltip: NUMBER_TOOLTIP,
      legend: { data: seriesNames },
      xAxis: { type: 'category', data: categories, name: p.xLabel ?? undefined },
      yAxis: { ...VALUE_AXIS, name: p.yLabel ?? undefined },
      series: seriesNames.map((name, i) => ({
        name,
        type: 'line',
        smooth: true,
        data: data.filter(row => String(row[p.seriesField!]) === name).map(row => Number(row[yField])),
        itemStyle: { color: COLORS[i % COLORS.length] },
      })),
    }
  }

  const norm = normalizeForChart(data, p.xField, p.yField)
  if (!norm || !norm.rows.length) return null
  const { rows, xField, yField } = norm
  const categories = rows.map(row => String(row[xField]))

  return {
    tooltip: NUMBER_TOOLTIP,
    xAxis: { type: 'category', data: categories, name: p.xLabel ?? undefined },
    yAxis: { ...VALUE_AXIS, name: p.yLabel ?? undefined },
    series: [{
      name: p.yLabel ?? yField,
      type: 'line',
      smooth: true,
      data: rows.map(row => Number(row[yField])),
      itemStyle: { color: COLORS[0] },
    }],
  }
}

function pie(data: Row[], p: ChartProps): EChartsOption | null {
  const norm = normalizeForChart(data, p.xField, p.yField)
  if (!norm || !norm.rows.length) return null
  const { rows, xField: nameField, yField: valueField } = norm

  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'horizontal', bottom: 0, left: 'center' },
    series: [{
      type: 'pie',
      radius: ['35%', '60%'],
      center: ['50%', '45%'],
      data: rows.map((row, i) => ({
        name: String(row[nameField]),
        value: Number(row[valueField]),
        itemStyle: { color: COLORS[i % COLORS.length] },
      })),
      label: { formatter: '{b}\n{d}%' },
    }],
  }
}

function gauge(data: Row[], p: ChartProps): EChartsOption {
  const valueField = p.yField ?? Object.keys(data[0])[1]
  const value = Number(data[0]?.[valueField] ?? 0)
  return {
    series: [{
      type: 'gauge',
      data: [{ value, name: p.yLabel ?? valueField }],
      detail: { formatter: '{value}' },
      axisLine: { lineStyle: { width: 20, color: [[0.3, '#67e0e3'], [0.7, '#37a2da'], [1, HIGHLIGHT_COLOR]] } },
    }],
  }
}

function heatmap(data: Row[], p: ChartProps): EChartsOption {
  const xField = p.xField ?? Object.keys(data[0])[0]
  const yField = p.yField ?? Object.keys(data[0])[1]
  const valueField = p.seriesField ?? Object.keys(data[0])[2]

  const xCats = [...new Set(data.map(row => String(row[xField])))]
  const yCats = [...new Set(data.map(row => String(row[yField])))]
  const values = data.map(row => [
    xCats.indexOf(String(row[xField])),
    yCats.indexOf(String(row[yField])),
    Number(row[valueField]) || 0,
  ])
  const maxVal = Math.max(...values.map(v => v[2]))

  return {
    tooltip: { position: 'top' },
    xAxis: { type: 'category', data: xCats, name: p.xLabel ?? undefined },
    yAxis: { type: 'category', data: yCats, name: p.yLabel ?? undefined },
    visualMap: { min: 0, max: maxVal, calculable: true, orient: 'horizontal', left: 'center', bottom: 0 },
    series: [{ type: 'heatmap', data: values, label: { show: true } }],
  }
}

export function buildChartOption(data: Row[], p: ChartProps): EChartsOption | null {
  if (!data.length) return null
  const base: EChartsOption = {
    title: p.title ? { text: p.title, left: 'center', textStyle: { fontSize: 16 } } : undefined,
    color: COLORS,
  }
  let chart: EChartsOption | null
  switch (p.type) {
    case 'bar': chart = bar(data, p); break
    case 'line': chart = line(data, p); break
    case 'pie': chart = pie(data, p); break
    case 'gauge': chart = gauge(data, p); break
    case 'heatmap': chart = heatmap(data, p); break
    default: return null
  }
  if (!chart) return null
  return { ...base, ...chart }
}
