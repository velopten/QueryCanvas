import type { ReactNode } from 'react'

interface Props {
  label: ReactNode
  hint?: ReactNode
  className?: string
  children: ReactNode
}

/** 라벨 + 설명 + 입력 요소 묶음. */
export default function Field({ label, hint, className = '', children }: Props) {
  return (
    <label className={`block ${className}`}>
      <span className="block text-xs font-semibold text-gray-700">{label}</span>
      {hint && <span className="block text-xs text-gray-400 mt-0.5">{hint}</span>}
      <div className="mt-1.5">{children}</div>
    </label>
  )
}

/** 공통 텍스트 입력 클래스 (input/textarea/select 에 부착). */
export const inputClass =
  'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white ' +
  'focus:outline-none focus:ring-2 focus:ring-accent/25 focus:border-accent transition-colors'

/** 코드/SQL 편집용 모노스페이스 입력 클래스. */
export const codeInputClass =
  'w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono bg-white ' +
  'focus:outline-none focus:ring-2 focus:ring-accent/25 focus:border-accent transition-colors'
