import { useState, useRef, useEffect, useCallback } from 'react'
import Sidebar from '../components/Sidebar'
import ChatInput, { type ChatInputHandle, type SuggestedQuestion, type InputMode } from '../components/ChatInput'
import FeedbackButtons from '../components/FeedbackButtons'
import MarkdownRenderer from '../components/MarkdownRenderer'
import SpecRenderer from '../components/SpecRenderer'
import A2uiRenderer from '../components/A2uiRenderer'
import StreamingSteps, { type StepState } from '../components/StreamingSteps'
import {
  queryStream, uiEditStream, rerunHistory, getMeta,
  getHistoryList, getHistoryDetail,
  createSavedView, listSavedViews, openSavedView, IS_STATIC,
  type QueryContext, type HistoryEntry, type SavedView, type DemoReplayMeta,
} from '../utils/api'
import type { UiSpec, A2uiMessage } from '../types'
import { isA2uiSpec } from '../types'
import { generateSuggestions } from '../utils/suggestions'

/** spec(A2UI/레거시)에서 BriefingCard를 찾아 headline 텍스트만 추출. */
function extractBriefingHeadline(spec: UiSpec | null | undefined): string | null {
  if (!spec) return null
  if (isA2uiSpec(spec)) {
    for (const m of spec.messages) {
      for (const c of m.updateComponents?.components ?? []) {
        if (c.component === 'BriefingCard' && typeof c.headline === 'string') return c.headline
      }
    }
    return null
  }
  if (!spec.elements) return null
  for (const el of Object.values(spec.elements)) {
    if (el.type === 'BriefingCard') {
      const props = el.props as { headline?: string } | undefined
      return props?.headline ?? null
    }
  }
  return null
}

interface ConversationTurn {
  type: 'query' | 'tail'
  question: string
  // query type
  sql?: string | null
  data?: Record<string, unknown>[] | null
  uiSpec?: UiSpec | null
  error?: string | null
  // tail type
  answer?: string
}

interface StreamState {
  steps: StepState[]
  sql: string | null
  data: Record<string, unknown>[] | null
  uiSpec: UiSpec | null
  /** UI 결정 단계에서 증분 수신하는 A2UI updateComponents 메시지 (progressive 렌더링용) */
  a2uiMessages: A2uiMessage[]
  /** 질의 회차 — A2uiRenderer 리마운트 키 (새 질의마다 surface 초기화) */
  epoch: number
  error: string | null
  done: boolean
  question: string | null
  traceId: string | null
}

const INITIAL_STREAM: StreamState = {
  steps: [], sql: null, data: null, uiSpec: null, a2uiMessages: [], epoch: 0, error: null, done: false, question: null, traceId: null,
}

export default function QueryPage() {
  const [loading, setLoading] = useState(false)
  const [conversations, setConversations] = useState<ConversationTurn[]>([])
  const [tailMessages, setTailMessages] = useState<{ question: string; answer: string }[]>([])
  const [stream, setStream] = useState<StreamState>(INITIAL_STREAM)
  const [historyEntries, setHistoryEntries] = useState<HistoryEntry[]>([])
  const [activeHistoryId, setActiveHistoryId] = useState<string | null>(null)
  const [savedViews, setSavedViews] = useState<SavedView[]>([])
  const [activeViewId, setActiveViewId] = useState<string | null>(null)
  const [demoReplay, setDemoReplay] = useState<DemoReplayMeta | null>(null)
  const [viewSaveState, setViewSaveState] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [parentInfo, setParentInfo] = useState<{ id: string; title: string; question: string } | null>(null)
  const [suggestions, setSuggestions] = useState<SuggestedQuestion[]>([])
  const resultEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<(() => void) | null>(null)
  const chatInputRef = useRef<ChatInputHandle>(null)

  // Load history from server on mount
  const refreshHistory = useCallback(() => {
    getHistoryList().then(setHistoryEntries).catch(() => {})
  }, [])

  useEffect(() => { refreshHistory() }, [refreshHistory])

  const refreshViews = useCallback(() => {
    listSavedViews().then(setSavedViews).catch(() => {})
  }, [])

  useEffect(() => { refreshViews() }, [refreshViews])

  // 도메인 팩 메타 — 추천 질문 + 사이드바 도메인 라벨
  const [starterQuestions, setStarterQuestions] = useState<string[]>([])
  const [domainLabel, setDomainLabel] = useState<string>('')
  useEffect(() => {
    getMeta().then(m => {
      setStarterQuestions(m.suggested_questions)
      setDomainLabel(m.domain_label)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    resultEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [stream.sql, stream.data, stream.uiSpec, conversations.length, tailMessages.length])

  // SSE 콜백에서 최신 상태를 읽기 위한 미러 (deferred reset용)
  const streamRef = useRef(stream)
  useEffect(() => { streamRef.current = stream }, [stream])
  const tailsRef = useRef(tailMessages)
  useEffect(() => { tailsRef.current = tailMessages }, [tailMessages])

  /** AI가 되물은 보강 질문 상태 — 다음 입력을 원질문과 합쳐 재요청 */
  const [clarify, setClarify] = useState<{ original: string; ask: string } | null>(null)
  /** 파이프라인 확정(스켈레톤 도착) 시점에 화면을 리셋하기 위한 대기 질문 */
  const pendingResetRef = useRef<string | null>(null)

  const mergeStep = useCallback((typedStep: StepState) => {
    setStream(prev => {
      const idx = prev.steps.findIndex(s => s.phase === typedStep.phase)
      const newSteps = [...prev.steps]
      if (idx >= 0) newSteps[idx] = typedStep; else newSteps.push(typedStep)
      return { ...prev, steps: newSteps }
    })
  }, [])

  /** 정적 공개본에서 캡처된 질문 실행 과정과 결과를 순서대로 재생한다. */
  const replayDemoQuery = useCallback((question: string) => {
    abortRef.current?.()
    let cancelled = false
    abortRef.current = () => { cancelled = true }

    setLoading(true)
    setSuggestions([])
    setClarify(null)
    setActiveHistoryId(null)
    setActiveViewId(null)
    setDemoReplay(null)
    setParentInfo(null)
    setTailMessages([])
    setConversations([])
    setStream(prev => ({ ...INITIAL_STREAM, question, epoch: prev.epoch + 1 }))

    const wait = (ms: number) => new Promise(resolve => window.setTimeout(resolve, ms))
    const normalize = (value: string) => value.replace(/[\s?!.。,]/g, '').toLowerCase()

    ;(async () => {
      const entries = await getHistoryList()
      const normalizedQuestion = normalize(question)
      const entry = entries.find(item => normalize(item.question) === normalizedQuestion)
        || entries.find(item => {
          const candidate = normalize(item.question)
          return candidate.includes(normalizedQuestion) || normalizedQuestion.includes(candidate)
        })

      if (!entry) {
        if (cancelled) return
        mergeStep({ phase: 'routing', status: 'error', message: '저장된 데모 질문과 일치하지 않음' })
        setStream(prev => ({
          ...prev,
          error: '이 공개본에서는 위 예시 질문과 저장된 질문의 실행 과정을 재생할 수 있습니다.',
          done: true,
        }))
        setLoading(false)
        return
      }

      const detail = await getHistoryDetail(entry.id)
      if (cancelled) return

      const phases: Array<{ phase: string; running: string; done: string; delay: number }> = [
        { phase: 'routing', running: '질문 의도와 조회 유형을 분석하는 중', done: '데이터 조회 질문으로 분류', delay: 320 },
        { phase: 'cache_lookup', running: '유사 질문의 SQL 캐시를 확인하는 중', done: '캐시 확인 완료', delay: 340 },
        { phase: 'vector_search', running: '관련 스키마와 도메인 지식을 검색하는 중', done: '관련 컨텍스트 검색 완료', delay: 480 },
        { phase: 'sql_generation', running: '질문에 맞는 SQL을 생성하는 중', done: 'SQL 생성 완료', delay: 620 },
        { phase: 'sql_validate', running: 'SQL 문법과 접근 범위를 검증하는 중', done: 'SQL 검증 통과', delay: 360 },
      ]
      if (detail.sql?.includes('VV_SALES_MONTHLY')) {
        phases.push({ phase: 'vv_resolve', running: '가상 View를 실제 SQL로 전개하는 중', done: '가상 View 전개 완료', delay: 360 })
      }
      phases.push(
        { phase: 'sql_execution', running: '데이터베이스에서 SQL을 실행하는 중', done: `${detail.data?.length ?? 0}건 조회 완료`, delay: 460 },
        { phase: 'ui_decision', running: '결과에 맞는 시각화를 구성하는 중', done: '시각화 구성 완료', delay: 620 },
      )

      for (const phase of phases) {
        if (cancelled) return
        mergeStep({ phase: phase.phase, status: 'running', message: phase.running })
        await wait(phase.delay)
        if (cancelled) return
        mergeStep({ phase: phase.phase, status: 'done', message: phase.done })

        if (phase.phase === 'sql_generation') {
          setStream(prev => ({ ...prev, sql: detail.sql }))
        } else if (phase.phase === 'sql_execution') {
          setStream(prev => ({ ...prev, data: detail.data || [] }))
        }
      }

      if (cancelled) return
      setDemoReplay({
        replay: true,
        captured_at: detail.updated_at,
        action: 'query_pipeline_replay',
      })
      setStream(prev => ({
        ...prev,
        uiSpec: detail.ui_spec as unknown as UiSpec,
        done: true,
      }))
      setActiveHistoryId(detail.id)
      setLoading(false)
    })().catch(() => {
      if (cancelled) return
      setStream(prev => ({ ...prev, error: '저장된 데모 실행 결과를 불러오지 못했습니다.', done: true }))
      setLoading(false)
    })
  }, [mergeStep])

  /** 현재 화면을 대화 기록으로 넘기고 새 질의 화면으로 리셋 (스켈레톤 도착 시 호출) */
  const archiveAndReset = useCallback((question: string) => {
    const cur = streamRef.current
    const tails = tailsRef.current
    setConversations(prev => {
      const adds: ConversationTurn[] = []
      if (cur.done && cur.question && (cur.sql || cur.error)) {
        adds.push({ type: 'query', question: cur.question, sql: cur.sql, data: cur.data, uiSpec: cur.uiSpec, error: cur.error })
      }
      adds.push(...tails.map(m => ({ type: 'tail' as const, question: m.question, answer: m.answer })))
      return [...prev, ...adds]
    })
    setTailMessages([])
    setClarify(null)
    setActiveViewId(null)
    setDemoReplay(null)
    setViewSaveState('idle')
    setStream(prev => ({ ...INITIAL_STREAM, question, epoch: prev.epoch + 1 }))
  }, [])

  /**
   * 일반 대화 전송. 후속 질의는 서버가 tail(데이터 질답)/child(재조회)를 자동 판단하므로
   * 화면 리셋을 스켈레톤 도착(ui_layout)까지 미룬다 — tail/clarify면 현재 화면 유지.
   */
  const submitChat = useCallback((question: string, extra?: Partial<QueryContext>) => {
    if (IS_STATIC) {
      replayDemoQuery(question)
      return
    }
    const cur = streamRef.current
    const prevContext: QueryContext = { ...extra }
    if (cur.sql) {
      prevContext.previous_sql = cur.sql
      prevContext.previous_summary = extractBriefingHeadline(cur.uiSpec) || undefined
    }
    if (activeHistoryId) {
      prevContext.parent_history_id = activeHistoryId
    }

    abortRef.current?.()
    setLoading(true)
    setSuggestions([])
    pendingResetRef.current = question

    const abort = queryStream(question, {
      onStep: (step) => {
        const typedStep = step as StepState
        if (typedStep.phase === 'ui_layout' && pendingResetRef.current) {
          // 재조회 확정 — 이 시점에 화면 교체
          archiveAndReset(pendingResetRef.current)
          pendingResetRef.current = null
        }
        mergeStep(typedStep)
      },
      onSql: (sql) => setStream(prev => ({ ...prev, sql })),
      onData: (data) => setStream(prev => ({ ...prev, data })),
      onA2ui: (messages) => setStream(prev => ({ ...prev, a2uiMessages: [...prev.a2uiMessages, ...(messages as unknown as A2uiMessage[])] })),
      onUiSpec: (uiSpec) => setStream(prev => ({ ...prev, uiSpec: uiSpec as unknown as UiSpec })),
      onSaved: (historyId) => {
        setActiveHistoryId(historyId)
        refreshHistory()
      },
      onTailAnswer: (answer) => {
        // 현재 화면 유지 — 대화에 질답만 추가
        pendingResetRef.current = null
        setTailMessages(prev => [...prev, { question, answer }])
      },
      onClarify: (ask) => {
        // 보강 필요 — 스켈레톤을 지우고 되물음 표시 (다음 입력을 합쳐 재요청)
        pendingResetRef.current = null
        setClarify({ original: question, ask })
        setStream(prev => ({ ...prev, a2uiMessages: [], uiSpec: null, done: true }))
      },
      onError: (message) => { setStream(prev => ({ ...prev, error: message })); setLoading(false) },
      onDone: (traceId) => { setStream(prev => ({ ...prev, done: true, traceId: traceId || null })); setLoading(false) },
    }, Object.keys(prevContext).length > 0 ? prevContext : undefined)

    abortRef.current = abort
  }, [activeHistoryId, refreshHistory, archiveAndReset, replayDemoQuery, mergeStep])

  /** UI 수정 모드 — 현재 화면을 재조회 없이 증분 갱신 (같은 epoch → 리마운트 없음) */
  const submitUiEdit = useCallback((instruction: string) => {
    if (!activeHistoryId) return
    abortRef.current?.()
    setLoading(true)
    const abort = uiEditStream(activeHistoryId, instruction, {
      onStep: (step) => mergeStep(step as StepState),
      onA2ui: (messages) => setStream(prev => ({ ...prev, a2uiMessages: [...prev.a2uiMessages, ...(messages as unknown as A2uiMessage[])] })),
      onUiSpec: (uiSpec) => setStream(prev => ({ ...prev, uiSpec: uiSpec as unknown as UiSpec })),
      onError: (message) => {
        setTailMessages(prev => [...prev, { question: instruction, answer: `화면 수정 실패: ${message}` }])
        setLoading(false)
      },
      onDone: () => {
        setTailMessages(prev => [...prev, { question: instruction, answer: '요청하신 대로 화면을 수정했어요.' }])
        setLoading(false)
      },
    })
    abortRef.current = abort
  }, [activeHistoryId, mergeStep])

  const handleQuery = useCallback((question: string, mode: InputMode) => {
    if (mode === 'ui_edit') {
      submitUiEdit(question)
      return
    }
    if (clarify) {
      // 되물음에 대한 답 — 원질문과 합쳐 재요청 (clarify 재발동 방지)
      submitChat(`${clarify.original}\n[추가 정보] ${question}`, { skip_clarify: true })
      return
    }
    submitChat(question)
  }, [clarify, submitChat, submitUiEdit])


  const handleNewChat = () => {
    abortRef.current?.()
    pendingResetRef.current = null
    setClarify(null)
    setActiveHistoryId(null)
    setActiveViewId(null)
    setDemoReplay(null)
    setViewSaveState('idle')
    setParentInfo(null)
    setSuggestions([])
    setTailMessages([])
    setConversations([])
    setStream(INITIAL_STREAM)
  }

  const handleSelectHistory = async (entry: HistoryEntry) => {
    abortRef.current?.()
    pendingResetRef.current = null
    setClarify(null)
    setActiveHistoryId(entry.id)
    setActiveViewId(null)
    setDemoReplay(null)
    setViewSaveState('idle')
    setParentInfo(null)
    setSuggestions([])
    setTailMessages([])
    setConversations([])
    try {
      const detail = await getHistoryDetail(entry.id)
      setParentInfo(detail.parent || null)
      // 저장된 꼬리질문 복원
      const tails = (detail as { tail_messages?: { question: string; answer: string }[] }).tail_messages || []
      setTailMessages(tails)
      setStream(prev => ({
        steps: [], sql: detail.sql, data: detail.data || [],
        uiSpec: detail.ui_spec as unknown as UiSpec, a2uiMessages: [], epoch: prev.epoch + 1,
        error: null, done: true, question: detail.question, traceId: null,
      }))
    } catch {
      setStream({ ...INITIAL_STREAM, question: entry.question, error: '질문내역 로드 실패' })
    }
  }

  const handleRerun = async (entry: HistoryEntry) => {
    setActiveHistoryId(null)
    setActiveViewId(null)
    setDemoReplay(null)
    setConversations([])
    setSuggestions([])
    setLoading(true)
    setStream({ ...INITIAL_STREAM, question: `[재조회] ${entry.question}` })
    try {
      const res = await rerunHistory(entry.id)
      setDemoReplay(res._demo || null)
      setStream(prev => ({
        steps: res._demo ? [
          { phase: 'sql_execution', status: 'done', message: '저장된 SQL 실행 결과 재생' },
          { phase: 'data_binding', status: 'done', message: '저장된 화면에 결과 바인딩' },
        ] : [], sql: res.sql, data: res.data,
        uiSpec: res.ui_spec as unknown as UiSpec, a2uiMessages: [], epoch: prev.epoch + 1,
        error: null, done: true, question: `[재조회] ${entry.question}`, traceId: null,
      }))
      setActiveHistoryId(res.history_id)
      refreshHistory()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setStream(prev => ({ ...prev, error: detail || '재조회 실패' }))
    } finally { setLoading(false) }
  }


  // 저장된 뷰 열기 — SQL 재실행 + 저장된 A2UI spec에 fresh 데이터 바인딩 (LLM 0회)
  const handleOpenView = async (view: SavedView) => {
    abortRef.current?.()
    pendingResetRef.current = null
    setClarify(null)
    setActiveHistoryId(null)
    setActiveViewId(view.id)
    setDemoReplay(null)
    setViewSaveState('idle')
    setParentInfo(null)
    setSuggestions([])
    setTailMessages([])
    setConversations([])
    setLoading(true)
    setStream(prev => ({
      ...INITIAL_STREAM,
      question: `[내 화면] ${view.name}`,
      steps: IS_STATIC ? [{ phase: 'sql_execution', status: 'running', message: '저장된 SQL로 현재 데이터 재조회' }] : [],
      epoch: prev.epoch + 1,
    }))
    try {
      const res = await openSavedView(view.id)
      setDemoReplay(res._demo || null)
      setStream(prev => ({
        steps: res._demo ? [
          { phase: 'sql_execution', status: 'done', message: '저장된 SQL 실행 결과 재생' },
          { phase: 'data_binding', status: 'done', message: '기존 화면 구성에 조회 결과 바인딩' },
        ] : [], sql: res.sql, data: res.data,
        uiSpec: res.ui_spec as unknown as UiSpec, a2uiMessages: [], epoch: prev.epoch + 1,
        error: null, done: true, question: `[내 화면] ${view.name}`, traceId: null,
      }))
      refreshViews()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setStream(prev => ({ ...prev, error: detail || '화면을 여는 데 실패했습니다' }))
    } finally { setLoading(false) }
  }

  // 현재 결과를 '내 화면'으로 저장
  const handleSaveView = async () => {
    if (!activeHistoryId || viewSaveState !== 'idle') return
    const defaultName = extractBriefingHeadline(stream.uiSpec) || stream.question || ''
    const name = window.prompt('내 화면 이름', defaultName.slice(0, 30))
    if (name == null) return
    setViewSaveState('saving')
    try {
      await createSavedView(activeHistoryId, name.trim() || undefined)
      setViewSaveState('saved')
      refreshViews()
    } catch (e: unknown) {
      setViewSaveState('idle')
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(detail || '화면 저장에 실패했습니다')
    }
  }

  // 차트/표 요소 클릭 → 입력창에 값 주입 + 데이터 종류 기반 추천 질문 표시
  const handleElementClick = useCallback((value: string, field: string) => {
    // 입력창에 값 주입 (사용자가 자유롭게 이어 작성 가능)
    chatInputRef.current?.inject(`${value}의 `)
    // 컬럼명/값 종류에 따른 예상 질문 추천 칩 표시
    const uiSpec = stream.uiSpec || ({} as UiSpec)
    setSuggestions(generateSuggestions(value, field, uiSpec, stream.question || ''))
  }, [stream.uiSpec, stream.question])

  const isActive = conversations.length > 0 || loading || stream.sql || stream.data || stream.uiSpec || stream.error || !!clarify
  const visibleStarterQuestions = IS_STATIC && historyEntries.length > 0
    ? historyEntries.map(entry => entry.question)
    : starterQuestions
  // UI 수정 모드 진입 조건: 완료된 A2UI 화면 + 히스토리 존재
  const hasScreen = !!(activeHistoryId && stream.done && (stream.a2uiMessages.length > 0 || isA2uiSpec(stream.uiSpec)))

  return (
    <div className="flex h-screen bg-white">
      <Sidebar
        entries={historyEntries}
        activeId={activeHistoryId}
        onSelect={handleSelectHistory}
        onRerun={handleRerun}
        onNewChat={handleNewChat}
        onRefresh={refreshHistory}
        views={savedViews}
        activeViewId={activeViewId}
        onOpenView={handleOpenView}
        onRefreshViews={refreshViews}
        domainLabel={domainLabel}
      />

      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex-1 overflow-y-auto">
          {!isActive && (
            <div className="h-full flex flex-col items-center justify-center text-center px-4">
              <div className="w-16 h-16 bg-accent-soft rounded-2xl flex items-center justify-center mb-4">
                <svg className="w-8 h-8 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
              </div>
              <h2 className="text-lg font-semibold text-gray-800 mb-1">무엇이든 질문하세요</h2>
              <p className="text-sm text-gray-500 mb-6 max-w-md">자연어로 데이터를 조회하고 시각화할 수 있습니다</p>
              <div className="grid grid-cols-2 gap-2 max-w-lg w-full">
                {visibleStarterQuestions.map(q => (
                  <button key={q} onClick={() => handleQuery(q, 'chat')} className="text-left px-4 py-3 text-sm text-gray-600 bg-gray-50 border border-gray-200 rounded-xl hover:bg-gray-100 transition-colors">
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {isActive && (
            <div className="max-w-5xl mx-auto px-6 py-6 space-y-6">
              {/* 부모 질문 배너 */}
              {parentInfo && (
                <button
                  onClick={() => {
                    const parent = historyEntries.find(e => e.id === parentInfo.id)
                    if (parent) handleSelectHistory(parent)
                  }}
                  className="w-full flex items-center gap-2 px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 transition-colors text-left group"
                >
                  <svg className="w-4 h-4 text-gray-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
                  </svg>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-gray-400">이전 질문에서 이어진 꼬리질문입니다</p>
                    <p className="text-sm text-accent-strong group-hover:underline truncate">{parentInfo.title}</p>
                  </div>
                  <span className="text-xs text-gray-400 shrink-0">클릭하여 이동</span>
                </button>
              )}

              {conversations.map((turn, i) => (
                <div key={i} className="space-y-3">
                  <div className="flex justify-end">
                    <div className="bg-ink text-white px-4 py-2.5 rounded-2xl rounded-br-md max-w-lg text-sm">{turn.question}</div>
                  </div>

                  {turn.type === 'tail' ? (
                    <div className="flex gap-3 items-start">
                      <div className="w-7 h-7 bg-accent rounded-lg flex items-center justify-center shrink-0 mt-0.5">
                        <span className="text-white text-xs font-bold">AI</span>
                      </div>
                      <div className="bg-gray-50 border border-gray-200 rounded-xl px-4 py-3 max-w-2xl">
                        <MarkdownRenderer content={turn.answer || ''} />
                      </div>
                    </div>
                  ) : (
                    <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
                      {turn.error ? (
                        <p className="text-sm text-red-600">{turn.error}</p>
                      ) : (
                        <div className="space-y-1">
                          {extractBriefingHeadline(turn.uiSpec) && (
                            <p className="text-sm text-gray-700">{extractBriefingHeadline(turn.uiSpec)}</p>
                          )}
                          <p className="text-xs text-gray-500">{turn.data?.length ?? 0}건</p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}

              {stream.question && (
                <div className="space-y-4">
                  {conversations.length > 0 && <div className="border-b border-gray-200" />}
                  <div className="flex justify-end">
                    <div className="bg-ink text-white px-4 py-2.5 rounded-2xl rounded-br-md max-w-lg text-sm">{stream.question}</div>
                  </div>

                  {demoReplay && (
                    <div className="bg-cyan-50 border border-cyan-200 text-cyan-800 px-4 py-3 rounded-lg text-sm">
                      {demoReplay.action === 'query_pipeline_replay' ? (
                        <>
                          <p className="font-medium">실제 질문 실행 과정을 데모로 재생했습니다</p>
                          <p className="mt-1 text-xs text-cyan-700">
                            실제 환경의 질문 분석, 지식 검색, SQL 생성·검증·실행, 시각화 구성 단계를 순서대로 보여줍니다.
                            {' '}결과는 {new Date(demoReplay.captured_at).toLocaleString('ko-KR')}에 실행해 저장한 스냅샷입니다.
                          </p>
                        </>
                      ) : (
                        <>
                          <p className="font-medium">데모 재조회 결과를 재생했습니다</p>
                          <p className="mt-1 text-xs text-cyan-700">
                            실제 환경에서는 저장된 SQL만 다시 실행하고, 결과를 기존 화면 구성에 바인딩합니다. LLM은 다시 호출하지 않습니다.
                            {' '}이 공개본은 {new Date(demoReplay.captured_at).toLocaleString('ko-KR')}에 실행해 저장한 결과입니다.
                          </p>
                        </>
                      )}
                    </div>
                  )}

                  {stream.steps.length > 0 && (
                    <div className="flex gap-3 items-start">
                      <div className="w-7 h-7 bg-accent rounded-lg flex items-center justify-center shrink-0 mt-0.5">
                        <span className="text-white text-xs font-bold">AI</span>
                      </div>
                      <StreamingSteps steps={stream.steps} />
                    </div>
                  )}

                  {stream.error && <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm animate-in fade-in">{stream.error}</div>}

                  {/* 보강 되물음 (clarify) — 답하면 원질문과 합쳐 조회 */}
                  {clarify && (
                    <div className="flex gap-3 items-start animate-in fade-in slide-in-from-bottom-2">
                      <div className="w-7 h-7 bg-accent rounded-lg flex items-center justify-center shrink-0 mt-0.5">
                        <span className="text-white text-xs font-bold">AI</span>
                      </div>
                      <div className="bg-accent-soft border border-accent-muted rounded-xl px-4 py-3 max-w-2xl">
                        <p className="text-sm text-gray-800">{clarify.ask}</p>
                        <p className="text-xs text-gray-500 mt-1.5">아래 입력창에 답해 주시면 이어서 조회합니다</p>
                      </div>
                    </div>
                  )}

                  {(stream.a2uiMessages.length > 0 || stream.uiSpec) && (
                    <div className="animate-in fade-in slide-in-from-bottom-2 duration-300">
                      {stream.a2uiMessages.length > 0 ? (
                        // 라이브 스트리밍: A2UI 메시지 증분 렌더 (교정 메시지 포함 — 완료 후에도 유지)
                        <A2uiRenderer
                          key={`live-${stream.epoch}`}
                          messages={stream.a2uiMessages}
                          data={stream.data}
                          loading={!stream.done}
                          onElementClick={handleElementClick}
                        />
                      ) : isA2uiSpec(stream.uiSpec) ? (
                        // 히스토리/재조회: 저장된 통합 A2UI 메시지 재생
                        <A2uiRenderer
                          key={`replay-${stream.epoch}`}
                          messages={stream.uiSpec.messages}
                          data={stream.data}
                          loading={false}
                          onElementClick={handleElementClick}
                        />
                      ) : (
                        // 레거시 json-render spec (과거 저장분)
                        <SpecRenderer
                          spec={stream.uiSpec}
                          data={stream.data}
                          loading={!stream.done}
                          onElementClick={handleElementClick}
                        />
                      )}
                    </div>
                  )}

                  {/* 화면 저장 + Feedback */}
                  {stream.done && stream.data && (
                    <div className="flex items-center justify-end gap-3 animate-in fade-in">
                      {!IS_STATIC && activeHistoryId && !activeViewId && (
                        viewSaveState === 'saved' ? (
                          <span className="text-xs text-emerald-600">내 화면에 저장됨 — 사이드바에서 언제든 다시 열 수 있습니다</span>
                        ) : (
                          <button
                            onClick={handleSaveView}
                            disabled={viewSaveState === 'saving'}
                            className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-accent-strong border border-accent-muted rounded-lg hover:bg-accent-soft disabled:opacity-50 transition-colors"
                          >
                            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
                            </svg>
                            {viewSaveState === 'saving' ? '저장 중...' : '내 화면으로 저장'}
                          </button>
                        )
                      )}
                      <FeedbackButtons traceId={stream.traceId} />
                    </div>
                  )}

                  {/* Tail messages (꼬리질문 채팅) */}
                  {tailMessages.map((msg, i) => (
                    <div key={`tail-${i}`} className="space-y-2 animate-in fade-in slide-in-from-bottom-2">
                      <div className="flex justify-end">
                        <div className="bg-ink text-white px-4 py-2.5 rounded-2xl rounded-br-md max-w-lg text-sm">{msg.question}</div>
                      </div>
                      <div className="flex gap-3 items-start">
                        <div className="w-7 h-7 bg-accent rounded-lg flex items-center justify-center shrink-0 mt-0.5">
                          <span className="text-white text-xs font-bold">AI</span>
                        </div>
                        <div className="bg-gray-50 border border-gray-200 rounded-xl px-4 py-3 max-w-2xl">
                          <MarkdownRenderer content={msg.answer} />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <div ref={resultEndRef} />
            </div>
          )}
        </div>

        {IS_STATIC && (
          <div className="px-4 py-2 text-center text-xs text-cyan-700 border-t border-cyan-100 bg-cyan-50">
            공개 데모 — 예시 질문을 입력하면 실제 실행 시 저장한 파이프라인과 결과를 재생합니다.
          </div>
        )}
        <ChatInput
          ref={chatInputRef}
          onSubmit={handleQuery}
          loading={loading}
          suggestions={suggestions}
          hasScreen={hasScreen && !IS_STATIC}
        />
      </div>
    </div>
  )
}
