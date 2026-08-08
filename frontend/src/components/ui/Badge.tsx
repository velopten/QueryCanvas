import type { ReactNode } from 'react'

export type BadgeTone =
  | 'neutral' | 'accent' | 'success' | 'danger' | 'warning'
  | 'info' | 'purple' | 'rose'

const TONE: Record<BadgeTone, string> = {
  neutral: 'bg-gray-100 text-gray-600',
  accent: 'bg-accent-soft text-accent-strong',
  success: 'bg-emerald-50 text-emerald-700',
  danger: 'bg-red-50 text-red-700',
  warning: 'bg-amber-50 text-amber-700',
  info: 'bg-sky-50 text-sky-700',
  purple: 'bg-purple-50 text-purple-700',
  rose: 'bg-rose-50 text-rose-700',
}

/** 상태/타입 표시용 칩. 색은 tone 으로만 지정한다. */
export default function Badge({ tone = 'neutral', className = '', children }: { tone?: BadgeTone; className?: string; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${TONE[tone]} ${className}`}>
      {children}
    </span>
  )
}
