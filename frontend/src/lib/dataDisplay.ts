/**
 * 데이터 표시 공통 헬퍼 — json-render 레거시 컴포넌트(customComponents)와
 * A2UI 카탈로그(a2ui/catalog)가 공유한다.
 */

export type DataRow = Record<string, unknown>

/**
 * 필터 객체를 데이터에 적용한다.
 * filters: { columnName: selectedValue, ... } — value가 빈 문자열이면 해당 컬럼 무시
 */
export function applyFilters(data: DataRow[], filters: Record<string, string> | null | undefined): DataRow[] {
  if (!filters || typeof filters !== 'object') return data
  const active = Object.entries(filters).filter(([, v]) => v !== '' && v != null)
  if (active.length === 0) return data
  return data.filter(row => active.every(([col, val]) => String(row[col] ?? '') === val))
}

/** 텍스트(non-numeric) 셀만 클릭 가능 */
export function isClickableValue(value: unknown): boolean {
  return typeof value === 'string' && value.length > 0 && isNaN(Number(value))
}

// ── 숫자 표기 ────────────────────────────────────────────────────────────────

/** 컬럼 단위 표기 지정 — UI 결정 LLM이 DataTable.columnFormats 로 내려준다. */
export interface ColumnFormat {
  /** number=천단위 구분, percent=% 접미, text=원본 그대로 (자동 포맷 해제) */
  type?: 'number' | 'percent' | 'text'
  /** 소수 자릿수 고정 (미지정이면 원본 자릿수 유지) */
  decimals?: number
  /** 숫자 뒤 단위 — 예: '건', '원', '시간' */
  unit?: string
  /** 숫자 앞 통화기호 — 예: '₩', '$' */
  currency?: string
}

export type ColumnFormats = Record<string, ColumnFormat>

/**
 * 자동 천단위 구분을 적용할 최소 절대값.
 * 연도(2026)·코드성 4자리 정수가 "2,026"으로 훼손되는 것을 막는다.
 * 명시적 columnFormats 가 있으면 이 임계값과 무관하게 지정대로 표기한다.
 */
const AUTO_SEPARATOR_MIN = 10000

/**
 * 표기를 보존해야 하는 문자열은 숫자로 취급하지 않는다.
 * 왕복(String(Number(v)) === v)이 일치할 때만 숫자 — '01', '1.50', '1e5' 는 원본 유지.
 */
function toNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  if (trimmed === '') return null
  const n = Number(trimmed)
  if (!Number.isFinite(n) || String(n) !== trimmed) return null
  return n
}

function groupDigits(n: number, decimals?: number): string {
  return new Intl.NumberFormat('ko-KR', decimals == null
    ? { maximumFractionDigits: 20 }
    : { minimumFractionDigits: decimals, maximumFractionDigits: decimals },
  ).format(n)
}

/** 셀 값 → 표시 문자열. formats 에 해당 컬럼이 없으면 큰 숫자에만 천단위 구분을 적용한다. */
export function formatCellValue(value: unknown, col: string, formats?: ColumnFormats | null): string {
  if (value == null) return ''
  const fmt = formats?.[col]
  if (fmt?.type === 'text') return String(value)

  const n = toNumber(value)
  if (n == null) return String(value)

  if (fmt) {
    const body = groupDigits(n, fmt.decimals)
    const prefix = fmt.currency ?? ''
    const suffix = fmt.type === 'percent' ? '%' : (fmt.unit ? ` ${fmt.unit}` : '')
    return `${prefix}${body}${suffix}`
  }
  return Math.abs(n) >= AUTO_SEPARATOR_MIN ? groupDigits(n) : String(value)
}

/** 컬럼이 숫자 컬럼인지 (우측 정렬 판단용) — 값이 있는 행 기준 전부 숫자여야 참 */
export function isNumericColumn(rows: DataRow[], col: string): boolean {
  let seen = 0
  for (const row of rows) {
    const v = row[col]
    if (v == null || v === '') continue
    if (toNumber(v) == null) return false
    seen++
    if (seen >= 20) break
  }
  return seen > 0
}

// 이름 컬럼을 클릭하면 동일 row의 ID 컬럼을 찾아 "ID(NAME)" 형태로 변환
// 예: CUST_NAME='김민준' + CUST_ID='C038' → 'C038(김민준)'
// SQL이 한글로 alias 한 경우도 대응한다.
const NAME_TO_ID_PAIRS: Array<[RegExp, string[]]> = [
  [/^(.+)_NAME$/i, ['$1_ID', '$1_CD']],        // CUST_NAME → CUST_ID, CATEGORY_NAME → CATEGORY_CD
  [/^(.+)_NM$/i, ['$1_ID', '$1_CD']],          // _NM 축약 별칭 대응
  [/^(.+)명$/, ['$1코드', '$1ID', '$1번호']],   // 상품명 → 상품코드/상품ID
  [/^(이름|성명|명칭)$/, ['ID', '코드', '식별자', '번호']],
]

export function transformClickValue(val: string, col: string, row: DataRow): string {
  for (const [pattern, idCols] of NAME_TO_ID_PAIRS) {
    const m = col.match(pattern)
    if (!m) continue
    const candidates = idCols.map(c => c.replace('$1', m[1] || ''))
    for (const idCol of candidates) {
      const idVal = row[idCol]
      if (idVal != null && String(idVal).trim() !== '') {
        return `${idVal}(${val})`
      }
    }
  }
  return val
}
