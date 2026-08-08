/**
 * A2UI 메시지 렌더러.
 *
 * 백엔드 UI 결정 LLM이 출력하는 것은 updateComponents 메시지뿐이다.
 * surface 생성과 데이터 주입(rows/filters)은 이 컴포넌트가 담당한다:
 *   1. mount 시 createSurface (surfaceId 'result')
 *   2. data prop → updateDataModel /rows (LLM/전송 미경유, 클라이언트 주입)
 *   3. messages prop 증분 소비 (스트리밍 append-only — 새 질의는 key로 리마운트)
 *
 * 레거시 json-render spec은 SpecRenderer가 담당 (과거 히스토리 재생 전용).
 */
import { useEffect, useRef, useState } from 'react'
import { MessageProcessor, type SurfaceModel } from '@a2ui/web_core/v0_9'
import { A2uiSurface, type ReactComponentImplementation } from '@a2ui/react/v0_9'
import { appCatalog, CATALOG_ID, SURFACE_ID } from '../lib/a2ui/catalog'
import { ElementClickContext, type ElementClickHandler } from '../lib/elementClickContext'
import type { A2uiMessage } from '../types'

interface Props {
  /** 백엔드에서 받은 updateComponents 메시지 (append-only) */
  messages: A2uiMessage[]
  /** SQL 결과 — 데이터 모델 /rows 로 주입 */
  data: Record<string, unknown>[] | null
  loading?: boolean
  onElementClick?: ElementClickHandler
}

export default function A2uiRenderer({ messages, data, loading, onElementClick }: Props) {
  const [processor] = useState(() => {
    const p = new MessageProcessor<ReactComponentImplementation>([appCatalog as never])
    p.processMessages([
      { version: 'v0.9', createSurface: { surfaceId: SURFACE_ID, catalogId: CATALOG_ID } },
      { version: 'v0.9', updateDataModel: { surfaceId: SURFACE_ID, path: '/', value: { rows: [], filters: {}, meta: { loading: true } } } },
    ] as never)
    return p
  })
  const [surfaces, setSurfaces] = useState<SurfaceModel<ReactComponentImplementation>[]>(
    () => Array.from(processor.model.surfacesMap.values()),
  )
  const fedCountRef = useRef(0)

  useEffect(() => {
    const sync = () => setSurfaces(Array.from(processor.model.surfacesMap.values()))
    const created = processor.onSurfaceCreated(sync)
    const deleted = processor.onSurfaceDeleted(sync)
    sync()
    return () => { created.unsubscribe(); deleted.unsubscribe() }
  }, [processor])

  // 데이터 주입 — rows만 갱신 (사용자 필터 상태 /filters는 유지)
  useEffect(() => {
    processor.processMessages([
      { version: 'v0.9', updateDataModel: { surfaceId: SURFACE_ID, path: '/rows', value: data ?? [] } },
    ] as never)
  }, [processor, data])

  // 로딩 상태 전파 — 스켈레톤 컴포넌트(loading: {path:'/meta/loading'})가 shimmer 표시에 사용
  useEffect(() => {
    processor.processMessages([
      { version: 'v0.9', updateDataModel: { surfaceId: SURFACE_ID, path: '/meta/loading', value: !!loading } },
    ] as never)
  }, [processor, loading])

  // 메시지 증분 소비
  useEffect(() => {
    if (messages.length <= fedCountRef.current) return
    const fresh = messages.slice(fedCountRef.current)
    fedCountRef.current = messages.length
    try {
      processor.processMessages(fresh as never)
    } catch (e) {
      // 검증은 서버에서 이미 통과 — 여기 실패는 카탈로그 계약 불일치 (콘솔로만)
      console.error('[a2ui] processMessages 실패:', e)
    }
  }, [processor, messages])

  const hasComponents = messages.length > 0

  return (
    <div className="w-full">
      <ElementClickContext.Provider value={onElementClick ?? null}>
        {surfaces.map(surface => <A2uiSurface key={surface.id} surface={surface} />)}
      </ElementClickContext.Provider>
      {!hasComponents && loading && (
        <div className="text-sm text-gray-400 text-center py-4">
          <div className="inline-flex items-center gap-2">
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            UI 생성 중...
          </div>
        </div>
      )}
    </div>
  )
}
