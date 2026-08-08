/**
 * json-render 카탈로그 정의.
 *
 * 데이터 표시/레이아웃 컴포넌트만 화이트리스트로 노출.
 * Form/Interactive 컴포넌트(Input, Select, Button 등)는 제외 — 우리 DataTable이
 * state 변화로 필터링하지 않으므로, AI가 필터를 만들면 동작하지 않고 UI만 깨짐.
 */

import { defineCatalog } from '@json-render/core'
import { schema } from '@json-render/react'
import { shadcnComponentDefinitions } from '@json-render/shadcn'
import { z } from 'zod'

// 데이터 표시 + 정적 레이아웃 컴포넌트만 허용
const ALLOWED_SHADCN_COMPONENTS = [
  // 레이아웃 (정적, 양방향 바인딩 불필요)
  'Stack',
  'Grid',
  'Card',
  'Separator',
  // 텍스트
  'Heading',
  'Text',
  // 데이터 표시
  'Badge',
  'Alert',
  'Avatar',
  'Image',
  'Progress',
  // 정보 표시 (호버/팝오버는 portal 안 써도 OK)
  'Tooltip',
  // ⚠ 제외: Tabs, Accordion, Collapsible, Dialog, Drawer, Carousel — state 기반 동작 미지원
  // ⚠ 제외: Input, Textarea, Select, Checkbox, Radio, Switch, Slider — DataTable 필터링 미연결
  // ⚠ 제외: Button, Link, DropdownMenu, Toggle, ToggleGroup, ButtonGroup, Pagination — action 핸들러 미연결
  // ⚠ 제외: Skeleton, Spinner — 로딩 상태는 우리가 알아서 표시
  // ⚠ 제외: Popover — portal 호환성 이슈
  // ⚠ 제외: Table — 우리 DataTable이 더 풍부함
] as const

const filteredShadcnDefinitions: Record<string, (typeof shadcnComponentDefinitions)[keyof typeof shadcnComponentDefinitions]> = {}
for (const name of ALLOWED_SHADCN_COMPONENTS) {
  if (name in shadcnComponentDefinitions) {
    filteredShadcnDefinitions[name] = shadcnComponentDefinitions[name as keyof typeof shadcnComponentDefinitions]
  }
}

// 커스텀 컴포넌트 정의 — 데이터 시각화 전용 (leaf 컴포넌트 = slots 없음)
export const customComponentDefinitions = {
  /**
   * Chart 컴포넌트. 데이터는 dataKey로 state model에서 참조.
   */
  Chart: {
    props: z.object({
      type: z.enum(['bar', 'line', 'pie', 'gauge', 'heatmap']),
      title: z.string().nullable(),
      dataKey: z.string(),
      filterPath: z.string().nullable(),
      xField: z.string().nullable(),
      yField: z.string().nullable(),
      xLabel: z.string().nullable(),
      yLabel: z.string().nullable(),
      seriesField: z.string().nullable(),
      highlightField: z.string().nullable(),
      highlightThreshold: z.number().nullable(),
      height: z.number().nullable(),
    }),
    slots: [] as string[],
    description:
      '동적 차트 (bar/line/pie/gauge/heatmap). 데이터는 dataKey="data"로 state에서 참조. ' +
      'filterPath를 지정하면 해당 state의 필터 객체에 따라 자동으로 데이터 필터링됨 (Filter 컴포넌트와 연동).',
    example: {
      type: 'bar',
      title: '카테고리별 매출',
      dataKey: 'data',
      filterPath: 'filters',
      xField: 'CATEGORY_NAME',
      yField: 'TOTAL_AMOUNT',
      xLabel: '카테고리',
      yLabel: '금액',
    },
  },

  /**
   * DataTable 컴포넌트. SQL 결과 표시.
   */
  DataTable: {
    props: z.object({
      dataKey: z.string(),
      filterPath: z.string().nullable(),
      title: z.string().nullable(),
      pageSize: z.number().nullable(),
    }),
    slots: [] as string[],
    description:
      '데이터 테이블. 정렬/페이지네이션/엑셀 다운로드 내장. dataKey="data". ' +
      'filterPath를 지정하면 해당 state의 필터 객체에 따라 자동으로 행 필터링 (Filter 컴포넌트와 연동).',
    example: { dataKey: 'data', filterPath: 'filters', title: '카테고리별 매출 현황' },
  },

  /**
   * Filter 컴포넌트. 컬럼별 dropdown 필터 자동 생성.
   */
  Filter: {
    props: z.object({
      dataKey: z.string(),
      filterPath: z.string(),
      columns: z.array(z.string()),
      title: z.string().nullable(),
    }),
    slots: [] as string[],
    description:
      '컬럼별 dropdown 필터 자동 생성. dataKey의 데이터에서 columns 각각의 unique value를 추출해서 select 드롭다운 표시. ' +
      '사용자 선택은 filterPath에 저장되며, 같은 filterPath를 갖는 Chart/DataTable이 자동으로 필터링됨. ' +
      'filterPath는 보통 "filters", columns에는 필터 가능한 컬럼명들 (예: ["CATEGORY_NAME", "REGION_NAME"]).',
    example: {
      dataKey: 'data',
      filterPath: 'filters',
      columns: ['CATEGORY_NAME', 'REGION_NAME'],
      title: '카테고리/지역으로 필터링',
    },
  },

  /**
   * BriefingCard 컴포넌트. AI 분석 브리핑.
   */
  BriefingCard: {
    props: z.object({
      headline: z.string(),
      bullets: z.array(z.string()),
      note: z.string().nullable(),
    }),
    slots: [] as string[],
    description:
      'AI 분석 브리핑 카드. 객관적 팩트 나열만 (판단/추측 금지). 헤드라인 + 불릿 + 참고. 접었다 펼칠 수 있음.',
    example: {
      headline: '3개 카테고리 매출 집계',
      bullets: ['뷰티 1,890만원 (63건)', '가전 1,260만원 (42건)'],
      note: '취소/반품 건을 제외한 금액 기준',
    },
  },
}

// 사용 가능한 컴포넌트 = shadcn 화이트리스트 + 커스텀
const allComponentDefinitions = {
  ...filteredShadcnDefinitions,
  ...customComponentDefinitions,
}

export const catalog = defineCatalog(schema, {
  components: allComponentDefinitions,
  actions: {},
})

export type AppCatalog = typeof catalog
