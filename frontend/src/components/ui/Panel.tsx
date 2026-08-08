import type { ReactNode } from 'react'

interface Props {
  title?: ReactNode
  description?: ReactNode
  /** 헤더 우측 액션 (버튼 등) */
  actions?: ReactNode
  /** true 면 본문 패딩 없음 (테이블 등 flush 콘텐츠) */
  flush?: boolean
  className?: string
  children: ReactNode
}

/** 관리자/조회 화면 공통 카드 컨테이너. */
export default function Panel({ title, description, actions, flush, className = '', children }: Props) {
  const hasHeader = title || description || actions
  return (
    <section className={`bg-white rounded-xl border border-gray-200 ${className}`}>
      {hasHeader && (
        <div className={`flex items-start justify-between gap-3 px-4 py-3 ${flush ? 'border-b border-gray-100' : ''}`}>
          <div className="min-w-0">
            {title && <h3 className="text-sm font-semibold text-gray-800">{title}</h3>}
            {description && <p className="text-xs text-gray-500 mt-0.5">{description}</p>}
          </div>
          {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
        </div>
      )}
      <div className={flush ? '' : hasHeader ? 'px-4 pb-4' : 'p-4'}>{children}</div>
    </section>
  )
}
