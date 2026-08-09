import { useState, useEffect } from 'react'
import {
  getTrainingData, deleteTrainingData,
  curatorPreview, curatorCommit, listOverlays, deleteOverlay,
  type CuratorPreview, type OverlayItem,
} from '../../utils/api'
import { Button, Panel, Badge, EmptyState, inputClass, type BadgeTone } from '../../components/ui'
import { IS_STATIC } from '../../utils/api'

function GuideModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-2xl max-w-3xl w-full max-h-[85vh] overflow-y-auto mx-4" onClick={e => e.stopPropagation()}>
        <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between rounded-t-xl">
          <h2 className="text-lg font-bold text-gray-900">학습 데이터 추가 가이드</h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded-lg">
            <svg className="w-5 h-5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="px-6 py-5 text-sm text-gray-700 space-y-5">
          <section>
            <h3 className="font-semibold text-gray-900 mb-2">DDL 데이터</h3>
            <p className="mb-2">테이블 스키마를 한글 설명과 함께 등록합니다. AI가 질문과 관련 테이블을 매칭하는 데 사용됩니다.</p>
            <pre className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-xs overflow-x-auto whitespace-pre-wrap">{`-- [테이블] TB_ORDER - 주문 헤더
-- [설명] 고객의 주문 건별 금액, 채널, 상태를 기록하는 테이블
-- [컬럼] ORDER_ID(주문번호, VARCHAR2, PK), CUST_ID(고객ID, VARCHAR2),
--        ORDER_DATE(주문일자, DATE), CHANNEL_CD(채널코드: 01=웹, 02=앱, 03=오프라인)
-- [조인] TB_CUSTOMER(CUST_ID), TB_ORDER_ITEM(ORDER_ID)
CREATE TABLE TB_ORDER ( ... );`}</pre>
            <div className="mt-2 bg-accent-soft border border-accent-muted rounded-lg px-3 py-2 text-xs text-accent-strong">
              <strong>핵심:</strong> 한글 설명이 벡터 검색 정확도에 직접 영향을 줍니다. 반드시 [설명], [컬럼] 주석을 포함하세요.
            </div>
          </section>

          <section>
            <h3 className="font-semibold text-gray-900 mb-2">SQL 패턴</h3>
            <p className="mb-2">자주 사용되는 쿼리 패턴을 Q/A 형태로 등록합니다. 유사 질문에 대한 SQL 생성 정확도가 높아집니다.</p>
            <pre className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-xs overflow-x-auto whitespace-pre-wrap">{`-- Q: 이번 달 카테고리별 매출 현황
-- A:
SELECT C.CATEGORY_NAME, SUM(I.AMOUNT) AS SALES
FROM TB_ORDER O
JOIN TB_ORDER_ITEM I ON O.ORDER_ID = I.ORDER_ID
JOIN TB_CATEGORY C ON I.CATEGORY_CD = C.CATEGORY_CD
WHERE strftime('%Y%m', O.ORDER_DATE) = strftime('%Y%m', 'now')
GROUP BY C.CATEGORY_NAME
ORDER BY SALES DESC;`}</pre>
            <div className="mt-2 bg-accent-soft border border-accent-muted rounded-lg px-3 py-2 text-xs text-accent-strong">
              <strong>선별 기준:</strong> 고유 날짜 처리, 코드 테이블 조인, 계층 구조, 기간 집계, 복합 필터 패턴 위주로 10~20개
            </div>
          </section>

          <section>
            <h3 className="font-semibold text-gray-900 mb-2">비즈니스 문서</h3>
            <p className="mb-2">코드값 매핑, 업무 규칙 등 AI가 질문을 이해하는 데 필요한 도메인 지식을 등록합니다.</p>
            <pre className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-xs overflow-x-auto whitespace-pre-wrap">{`## 채널 코드 (CHANNEL_CD)
- 01 = 웹: PC/모바일 웹에서 발생한 주문
- 02 = 앱: 자사 모바일 앱 주문
- 03 = 오프라인: 매장 POS 주문

## 업무 규칙
- 매출은 취소/반품 건을 제외한 금액 기준
- 반품률 = 반품 건수 / 전체 주문 건수`}</pre>
          </section>

          <section>
            <h3 className="font-semibold text-gray-900 mb-2">검증 절차</h3>
            <ol className="list-decimal list-inside space-y-1">
              <li>데이터 추가 후 "벡터 저장소" 메뉴에서 <strong>재임베딩</strong> 실행</li>
              <li>메인 화면에서 테스트 질문 실행</li>
              <li>"파이프라인 추적" 메뉴에서 벡터 검색 결과가 적절한지 확인</li>
              <li>잘못된 SQL 발생 시 → 학습 데이터 보강 또는 프롬프트 수정</li>
            </ol>
          </section>
        </div>
      </div>
    </div>
  )
}

type DocFilter = 'all' | 'ddl' | 'sql' | 'doc' | 'doc_overlay' | 'doc_patch' | 'virtual_view' | 'snapshot'

const DOC_TONE: Record<string, BadgeTone> = {
  ddl: 'purple', sql: 'success', doc: 'warning',
  doc_overlay: 'accent', doc_patch: 'rose', virtual_view: 'accent', snapshot: 'info',
}

const docLabel = (t: string) =>
  t === 'doc_overlay' ? '큐레이터 ADD' : t === 'doc_patch' ? '큐레이터 PATCH' : t?.toUpperCase()

export default function TrainingPanel() {
  const [docs, setDocs] = useState<{ id: string; content: string; type: string; source: string }[]>([])
  const [loading, setLoading] = useState(true)
  const [showGuide, setShowGuide] = useState(false)
  const [filterType, setFilterType] = useState<DocFilter>('all')

  // ── Curator state ──
  const [curatorInput, setCuratorInput] = useState('')
  const [curatorLoading, setCuratorLoading] = useState(false)
  const [curatorPreviewData, setCuratorPreviewData] = useState<CuratorPreview | null>(null)
  const [curatorError, setCuratorError] = useState<string | null>(null)
  const [committing, setCommitting] = useState(false)
  const [overlays, setOverlays] = useState<OverlayItem[]>([])

  const fetchData = () => {
    getTrainingData().then(d => { setDocs(d.documents); setLoading(false) })
    listOverlays().then(d => setOverlays(d.items))
  }
  const load = () => { setLoading(true); fetchData() }
  useEffect(fetchData, [])

  const handlePreview = async () => {
    if (!curatorInput.trim()) return
    setCuratorLoading(true)
    setCuratorError(null)
    setCuratorPreviewData(null)
    try {
      const result = await curatorPreview(curatorInput.trim())
      if (result.action === 'reject') {
        setCuratorError(result.rationale || '거부됨')
      } else {
        setCuratorPreviewData(result)
      }
    } catch (e) {
      setCuratorError(String(e))
    }
    setCuratorLoading(false)
  }

  const handleCommit = async () => {
    if (!curatorPreviewData) return
    setCommitting(true)
    try {
      await curatorCommit(curatorPreviewData, curatorInput)
      setCuratorInput('')
      setCuratorPreviewData(null)
      load()
    } catch (e) {
      setCuratorError(String(e))
    }
    setCommitting(false)
  }

  const handleDeleteOverlay = async (file: string) => {
    if (!confirm(`overlay '${file}' 삭제하시겠습니까?`)) return
    await deleteOverlay(file)
    load()
  }

  const filteredDocs = filterType === 'all' ? docs : docs.filter(d => d.type === filterType)

  const handleDelete = async (id: string) => {
    if (!confirm('삭제하시겠습니까?')) return
    await deleteTrainingData(id)
    load()
  }

  return (
    <div className="space-y-6">
      {showGuide && <GuideModal onClose={() => setShowGuide(false)} />}

      {/* AI Curator */}
      <section className="bg-accent-soft border border-accent-muted rounded-xl p-4">
        <div className="flex items-start justify-between mb-3">
          <div>
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
              <span className="px-1.5 py-0.5 bg-accent text-white text-[10px] rounded">AI</span>
              학습 데이터 큐레이터
            </h3>
            <p className="text-xs text-gray-600 mt-1">
              자유롭게 입력하면 AI가 기존 학습 데이터를 참고해 새 청크 추가 또는 기존 보강으로 정리합니다.
            </p>
          </div>
          <Button variant="ghost" size="xs" onClick={() => setShowGuide(true)}>작성 가이드</Button>
        </div>
        <textarea
          value={curatorInput}
          onChange={e => { setCuratorInput(e.target.value); setCuratorPreviewData(null); setCuratorError(null) }}
          rows={5}
          className={inputClass}
        />
        <div className="mt-2 flex items-center gap-2">
          <Button size="md" mutating onClick={handlePreview} busy={curatorLoading} disabled={!curatorInput.trim()}>
            {curatorLoading ? 'AI 분석 중...' : '미리보기'}
          </Button>
          {curatorPreviewData && (
            <Button variant="secondary" size="md" onClick={() => { setCuratorPreviewData(null); setCuratorError(null) }}>
              취소
            </Button>
          )}
        </div>

        {curatorError && (
          <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
            <strong>거부됨:</strong> {curatorError}
          </div>
        )}

        {curatorPreviewData && (
          <div className="mt-4 space-y-3">
            <div className="flex items-center gap-2 text-xs flex-wrap">
              <Badge tone={curatorPreviewData.action === 'patch' ? 'warning' : 'success'}>
                {curatorPreviewData.action === 'patch' ? '기존 보강 (PATCH)' : '신규 추가 (ADD)'}
              </Badge>
              <Badge tone={curatorPreviewData.destination === 'prompt' ? 'rose' : curatorPreviewData.destination === 'both' ? 'accent' : 'info'}>
                {curatorPreviewData.destination === 'prompt' ? '프롬프트' :
                 curatorPreviewData.destination === 'both' ? '프롬프트 + 벡터' : '벡터DB'}
              </Badge>
              {curatorPreviewData.category && <Badge>{curatorPreviewData.category}</Badge>}
              {curatorPreviewData.target_chunk_id && (
                <Badge tone="purple" className="font-mono">{curatorPreviewData.target_chunk_id}</Badge>
              )}
            </div>

            {curatorPreviewData.prompt_directive && (
              <div className="bg-rose-50 border border-rose-200 rounded-lg p-2">
                <p className="text-[11px] font-medium text-rose-700 mb-1">SQL 프롬프트에 추가될 지침</p>
                <pre className="text-xs text-rose-900 whitespace-pre-wrap">{curatorPreviewData.prompt_directive}</pre>
              </div>
            )}

            {curatorPreviewData.title && (
              <p className="text-sm font-medium text-gray-800">{curatorPreviewData.title}</p>
            )}

            {curatorPreviewData.rationale && (
              <p className="text-xs text-gray-600 italic">판단 근거: {curatorPreviewData.rationale}</p>
            )}

            {curatorPreviewData.destination !== 'prompt' && (
              <div className={`grid gap-3 ${curatorPreviewData.action === 'patch' ? 'grid-cols-2' : 'grid-cols-1'}`}>
                {curatorPreviewData.action === 'patch' && curatorPreviewData.target_content && (
                  <div>
                    <p className="text-xs font-medium text-gray-500 mb-1">기존 청크 (보강 대상)</p>
                    <pre className="text-xs bg-gray-50 border border-gray-200 rounded-lg p-3 max-h-80 overflow-y-auto whitespace-pre-wrap">{curatorPreviewData.target_content}</pre>
                  </div>
                )}
                <div>
                  <p className="text-xs font-medium text-gray-500 mb-1">
                    {curatorPreviewData.action === 'patch' ? '추가될 보강 청크 (벡터DB)' : '추가될 새 청크 (벡터DB)'}
                  </p>
                  <pre className="text-xs bg-white border border-accent-muted rounded-lg p-3 max-h-80 overflow-y-auto whitespace-pre-wrap">{curatorPreviewData.structured_md}</pre>
                </div>
              </div>
            )}

            <div className="flex items-center gap-2 pt-2">
              <Button size="md" mutating onClick={handleCommit} busy={committing}>
                {committing ? '저장 중...' : '승인하고 저장'}
              </Button>
              <span className="text-xs text-gray-500">
                overlay 파일로 저장됩니다. 원본 큐레이션 파일은 변경되지 않습니다.
              </span>
            </div>
          </div>
        )}
      </section>

      {/* Overlay 목록 */}
      {overlays.length > 0 && (
        <Panel
          title={`큐레이터 등록 파일 (${overlays.length}건)`}
          description="신규 추가(ADD) + 기존 보강(PATCH) 모든 overlay 파일을 포함합니다. 아래 청크 목록의 ADD/PATCH 필터로 따로 볼 수 있습니다."
        >
          <div className="space-y-2">
            {overlays.map(o => (
              <div key={o.file} className="border border-gray-200 rounded-lg p-2">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-mono text-gray-600">{o.file}</span>
                  {!IS_STATIC && <button onClick={() => handleDeleteOverlay(o.file)} className="text-xs text-red-500 hover:text-red-700">삭제</button>}
                </div>
                <pre className="text-[11px] text-gray-500 whitespace-pre-wrap max-h-24 overflow-y-auto">{o.preview}</pre>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {/* 청크 목록 */}
      {loading ? <p className="text-sm text-gray-500">로딩 중...</p> : (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-800">저장된 데이터 ({filteredDocs.length}/{docs.length}건)</h3>
            <div className="flex gap-1">
              {(['all', 'virtual_view', 'snapshot', 'ddl', 'sql', 'doc', 'doc_overlay', 'doc_patch'] as const).map(t => (
                <button key={t} onClick={() => setFilterType(t)}
                  className={`px-2.5 py-1 text-xs rounded-md transition-colors ${filterType === t ? 'bg-ink text-white' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}`}
                  title={t === 'doc_overlay' ? '큐레이터로 신규 추가된 청크 (action=add)' : t === 'doc_patch' ? '큐레이터로 기존 청크를 보강한 패치 (action=patch)' : ''}
                >{t === 'all' ? '전체' : docLabel(t)}</button>
              ))}
            </div>
          </div>
          {filteredDocs.length === 0 && (
            <EmptyState message="해당 타입의 청크가 없습니다" action="위 큐레이터로 도메인 지식을 추가할 수 있습니다" />
          )}
          {filteredDocs.map(doc => (
            <div key={doc.id} className="bg-white border border-gray-200 rounded-lg p-3">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <Badge tone={DOC_TONE[doc.type] ?? 'neutral'}>{docLabel(doc.type)}</Badge>
                  <span className="text-xs text-gray-400">{doc.id}</span>
                </div>
                {!IS_STATIC && <button onClick={() => handleDelete(doc.id)} className="text-xs text-red-500 hover:text-red-700">삭제</button>}
              </div>
              <pre className="text-xs text-gray-600 whitespace-pre-wrap max-h-32 overflow-y-auto">{doc.content}</pre>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
