import { useState } from 'react'
import { submitFeedback } from '../utils/api'

interface Props {
  traceId: string | null
}

export default function FeedbackButtons({ traceId }: Props) {
  const [feedback, setFeedback] = useState<1 | -1 | null>(null)
  const [submitted, setSubmitted] = useState(false)

  if (!traceId) return null

  const handleFeedback = async (value: 1 | -1) => {
    if (submitted) return
    setFeedback(value)
    try {
      await submitFeedback(traceId, value)
      setSubmitted(true)
    } catch { /* ignore */ }
  }

  return (
    <div className="flex items-center gap-1">
      {submitted ? (
        <span className="text-xs text-gray-400">
          {feedback === 1 ? '감사합니다' : '개선하겠습니다'}
        </span>
      ) : (
        <>
          <span className="text-xs text-gray-400 mr-1">이 결과가 도움이 되었나요?</span>
          <button
            onClick={() => handleFeedback(1)}
            className="p-1.5 rounded-lg hover:bg-emerald-50 transition-colors group"
            title="도움이 됐어요"
          >
            <svg className="w-4 h-4 text-gray-300 group-hover:text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M14 10h4.764a2 2 0 011.789 2.894l-3.5 7A2 2 0 0115.263 21h-4.017c-.163 0-.326-.02-.485-.06L7 20m7-10V5a2 2 0 00-2-2h-.095c-.5 0-.905.405-.905.905 0 .714-.211 1.412-.608 2.006L7 11v9m7-10h-2M7 20H5a2 2 0 01-2-2v-6a2 2 0 012-2h2.5" />
            </svg>
          </button>
          <button
            onClick={() => handleFeedback(-1)}
            className="p-1.5 rounded-lg hover:bg-red-50 transition-colors group"
            title="개선이 필요해요"
          >
            <svg className="w-4 h-4 text-gray-300 group-hover:text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10 14H5.236a2 2 0 01-1.789-2.894l3.5-7A2 2 0 018.736 3h4.018a2 2 0 01.485.06l3.76.94m-7 10v5a2 2 0 002 2h.096c.5 0 .905-.405.905-.904 0-.715.211-1.413.608-2.008L17 13V4m-7 10h2m5-10h2a2 2 0 012 2v6a2 2 0 01-2 2h-2.5" />
            </svg>
          </button>
        </>
      )}
    </div>
  )
}
