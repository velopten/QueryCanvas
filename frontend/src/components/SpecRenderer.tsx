/**
 * AI가 생성한 json-render spec을 렌더링한다.
 *
 * 두 가지 모드:
 * 1. 완성 모드: `spec` props로 완성된 spec 객체를 받음 (히스토리 로드 시)
 * 2. 스트리밍 모드: `patches` props로 누적 patch 배열을 받아 progressive 합성
 *
 * 데이터(SQL 결과)는 controlled store(`/data` JSON Pointer)로 주입된다.
 * Chart/DataTable는 useStateValue("/data")로 접근.
 */

import { useEffect, useMemo, useState } from 'react'
import { Renderer, JSONUIProvider } from '@json-render/react'
import { applySpecPatch, createStateStore } from '@json-render/core'
import type { Spec } from '@json-render/core'
import { registry } from '../lib/registry'
import { ElementClickContext, type ElementClickHandler } from '../lib/elementClickContext'

export interface PatchOp {
  op: string
  path: string
  value?: unknown
}

interface Props {
  /** 완성 모드용 spec (히스토리 로드 등) */
  spec?: unknown
  /** 스트리밍 모드용 patch 배열 */
  patches?: PatchOp[]
  /** state model에 주입할 데이터 — Chart/DataTable이 dataKey="data"로 접근 */
  data: Record<string, unknown>[] | null
  loading?: boolean
  /** 차트/표 요소 클릭 콜백 — 꼬리질문 트리거용 */
  onElementClick?: ElementClickHandler
}

function buildSpecFromPatches(patches: PatchOp[]): Spec {
  const spec: Spec = { root: '', elements: {} }
  for (const p of patches) {
    try {
      applySpecPatch(spec, p as Parameters<typeof applySpecPatch>[1])
    } catch {
      // 잘못된 patch는 무시
    }
  }
  return spec
}

export default function SpecRenderer({ spec, patches, data, loading, onElementClick }: Props) {
  const finalSpec = useMemo<Spec | null>(() => {
    if (patches && patches.length > 0) return buildSpecFromPatches(patches)
    if (spec && typeof spec === 'object') return spec as Spec
    return null
  }, [patches, spec])

  // 단일 store를 유지하면서 데이터가 바뀔 때마다 set (lazy init — 최초 1회만 생성)
  const [store] = useState(() => createStateStore({ data: data || [], _meta: { loading: !!loading } }))

  // data가 바뀌면 store 업데이트
  useEffect(() => {
    store.set('/data', data || [])
  }, [store, data])

  // loading 상태를 store에 전파 (DataTable/Chart가 빈 데이터 + 로딩 상태일 때 스켈레톤 표시용)
  useEffect(() => {
    store.set('/_meta/loading', !!loading)
  }, [store, loading])

  if (!finalSpec || !finalSpec.root) {
    if (loading) {
      return (
        <div className="text-sm text-gray-400 text-center py-4">
          <div className="inline-flex items-center gap-2">
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            UI 생성 중...
          </div>
        </div>
      )
    }
    return null
  }

  return (
    <div className="w-full">
      <ElementClickContext.Provider value={onElementClick ?? null}>
        <JSONUIProvider registry={registry} store={store}>
          <Renderer spec={finalSpec} registry={registry} loading={loading} />
        </JSONUIProvider>
      </ElementClickContext.Provider>
    </div>
  )
}
