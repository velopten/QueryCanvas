interface Props {
  checked: boolean
  onChange: (next: boolean) => void
  disabled?: boolean
  'aria-label'?: string
}

/** 스위치 토글. 켜짐 = 액센트. */
export default function Toggle({ checked, onChange, disabled, ...rest }: Props) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative w-11 h-6 rounded-full transition-colors shrink-0
        focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent
        disabled:opacity-40 ${checked ? 'bg-accent' : 'bg-gray-300'}`}
      {...rest}
    >
      <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${checked ? 'translate-x-5' : ''}`} />
    </button>
  )
}
