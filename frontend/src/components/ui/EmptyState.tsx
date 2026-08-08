import type { ReactNode } from 'react'

interface Props {
  message: ReactNode
  /** 해소 방법 안내 (있으면 아래 줄에 표시) */
  action?: ReactNode
  className?: string
}

/** 빈 목록/결과 자리 표시. 무엇을 하면 채워지는지 안내한다. */
export default function EmptyState({ message, action, className = '' }: Props) {
  return (
    <div className={`px-4 py-10 text-center ${className}`}>
      <p className="text-sm text-gray-400">{message}</p>
      {action && <p className="text-xs text-gray-400 mt-1">{action}</p>}
    </div>
  )
}
