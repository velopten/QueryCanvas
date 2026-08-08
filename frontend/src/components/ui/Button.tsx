import type { ButtonHTMLAttributes } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'xs' | 'sm' | 'md'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  busy?: boolean
}

const VARIANT: Record<ButtonVariant, string> = {
  primary: 'bg-ink text-white hover:bg-ink-hover',
  secondary: 'bg-white text-gray-700 border border-gray-300 hover:bg-gray-50',
  ghost: 'text-gray-500 hover:text-gray-800 hover:bg-gray-100',
  danger: 'bg-red-600 text-white hover:bg-red-700',
}

const SIZE: Record<ButtonSize, string> = {
  xs: 'px-2.5 py-1 text-xs rounded-md',
  sm: 'px-3 py-1.5 text-xs rounded-lg',
  md: 'px-4 py-2 text-sm rounded-lg',
}

/** 프로젝트 공통 버튼. busy=true 면 스피너와 함께 비활성화된다. */
export default function Button({ variant = 'primary', size = 'sm', busy, disabled, children, className = '', ...rest }: Props) {
  return (
    <button
      disabled={disabled || busy}
      className={`inline-flex items-center justify-center gap-1.5 font-medium transition-colors
        focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent
        disabled:opacity-40 disabled:cursor-not-allowed shrink-0
        ${VARIANT[variant]} ${SIZE[size]} ${className}`}
      {...rest}
    >
      {busy && (
        <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )}
      {children}
    </button>
  )
}
