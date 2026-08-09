import { useState, useRef, useEffect, useImperativeHandle, forwardRef } from 'react'

/** 입력 모드 — chat: 일반 대화 (후속 질의는 서버가 자동 라우팅), ui_edit: 현재 화면 수정 */
export type InputMode = 'chat' | 'ui_edit'

export interface SuggestedQuestion {
  label: string
  question: string
}

interface Props {
  onSubmit: (question: string, mode: InputMode) => void
  loading: boolean
  suggestions?: SuggestedQuestion[]
  /** 현재 화면(수정 가능한 결과)이 있는지 — UI 수정 모드 진입 조건 */
  hasScreen: boolean
}

export interface ChatInputHandle {
  inject: (text: string) => void
  focus: () => void
}

const ChatInput = forwardRef<ChatInputHandle, Props>(({ onSubmit, loading, suggestions, hasScreen }, ref) => {
  const [value, setValue] = useState('')
  const [mode, setMode] = useState<InputMode>('chat')
  const [menuOpen, setMenuOpen] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useImperativeHandle(ref, () => ({
    inject: (text: string) => {
      setValue(text)
      setTimeout(() => inputRef.current?.focus(), 0)
    },
    focus: () => inputRef.current?.focus(),
  }))

  useEffect(() => {
    inputRef.current?.focus()
  }, [loading])

  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 120) + 'px'
  }, [value])

  // 화면이 없으면 UI 수정 모드 무효 — 저장된 mode와 무관하게 chat으로 동작 (파생값)
  const activeMode: InputMode = hasScreen ? mode : 'chat'

  const handleSubmit = () => {
    const q = value.trim()
    if (!q || loading) return
    onSubmit(q, activeMode)
    setValue('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const placeholder = activeMode === 'ui_edit'
    ? '화면 수정 요청... (예: 차트를 라인으로 바꿔줘, 표를 위로 올려줘)'
    : '자연어로 질문하세요... (후속 질문은 자동으로 답변/재조회를 판단합니다)'

  return (
    <div className="border-t border-gray-200 bg-white px-4 py-3">
      <div className="max-w-3xl mx-auto">
        {/* 드릴다운 추천 질문 칩 */}
        {suggestions && suggestions.length > 0 && !loading && activeMode === 'chat' && (
          <div className="flex gap-2 mb-2 flex-wrap">
            {suggestions.map((s, i) => (
              <button
                key={i}
                onClick={() => { setValue(s.question); setTimeout(() => inputRef.current?.focus(), 0) }}
                className="px-3 py-1.5 text-xs bg-accent-soft text-accent-strong border border-accent-muted rounded-full hover:bg-accent-muted/60 transition-colors animate-in fade-in slide-in-from-bottom-2"
              >
                {s.label}
              </button>
            ))}
          </div>
        )}

        <div className="flex items-end gap-2 bg-gray-50 border border-gray-300 rounded-2xl px-3 py-2 focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/20 transition-all">
          {/* + 버튼 — 모드 전환 메뉴 */}
          <div className="relative shrink-0 mb-0.5">
            <button
              onClick={() => setMenuOpen(o => !o)}
              className={`p-2 rounded-xl transition-colors ${activeMode === 'ui_edit' ? 'bg-accent text-white' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-200'}`}
              title="모드 선택"
            >
              <svg className={`w-4 h-4 transition-transform ${menuOpen ? 'rotate-45' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
            </button>
            {menuOpen && (
              <div className="absolute bottom-11 left-0 z-30 bg-white border border-gray-200 rounded-xl shadow-lg py-1 min-w-[210px]"
                   onMouseLeave={() => setMenuOpen(false)}>
                <button
                  onClick={() => { setMode('chat'); setMenuOpen(false); inputRef.current?.focus() }}
                  className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-50 ${mode === 'chat' ? 'text-accent-strong font-medium' : 'text-gray-700'}`}
                >
                  일반 대화
                </button>
                <button
                  onClick={() => { if (hasScreen) { setMode('ui_edit'); setMenuOpen(false); inputRef.current?.focus() } }}
                  disabled={!hasScreen}
                  className={`w-full text-left px-3 py-2 text-sm ${!hasScreen ? 'text-gray-300 cursor-not-allowed' : mode === 'ui_edit' ? 'text-accent-strong font-medium hover:bg-gray-50' : 'text-gray-700 hover:bg-gray-50'}`}
                >
                  UI 수정
                  <span className="block text-xs text-gray-400">{hasScreen ? '현재 화면을 재조회 없이 수정' : '먼저 화면을 만들어 주세요'}</span>
                </button>
              </div>
            )}
          </div>

          {/* UI 수정 모드 칩 */}
          {activeMode === 'ui_edit' && (
            <span className="flex items-center gap-1 mb-1.5 px-2 py-0.5 text-xs bg-accent-soft text-accent-strong rounded-full shrink-0">
              UI 수정
              <button onClick={() => setMode('chat')} className="hover:text-accent" title="일반 대화로">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </span>
          )}

          <textarea
            ref={inputRef}
            value={value}
            onChange={e => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            rows={1}
            className="flex-1 bg-transparent resize-none focus:outline-none text-sm leading-6 py-1 max-h-[120px]"
            disabled={loading}
          />
          <button
            onClick={handleSubmit}
            disabled={loading || !value.trim()}
            className="p-2 bg-ink text-white rounded-xl hover:bg-ink-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0 mb-0.5"
          >
            {loading ? (
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            )}
          </button>
        </div>
        <p className="text-xs text-gray-400 text-center mt-2">
          AI는 실수할 수도 있습니다
        </p>
      </div>
    </div>
  )
})

ChatInput.displayName = 'ChatInput'
export default ChatInput
