/** 저장/실행 상태 한 줄 표시 — '실패' 포함 시 빨강. */
export default function StatusText({ status }: { status: string | null }) {
  if (!status) return null
  const isError = status.includes('실패') || status.includes('오류')
  return (
    <span className={`text-xs self-center ${isError ? 'text-red-600' : 'text-gray-500'}`}>
      {status}
    </span>
  )
}
