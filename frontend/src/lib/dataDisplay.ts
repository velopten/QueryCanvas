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
