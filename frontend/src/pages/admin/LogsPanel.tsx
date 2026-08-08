import { useState, useEffect } from 'react'
import { getLogs } from '../../utils/api'
import { Button, EmptyState } from '../../components/ui'

export default function LogsPanel() {
  const [logs, setLogs] = useState<string[]>([])
  const [loading, setLoading] = useState(true)

  const fetchData = () => {
    getLogs(100).then(d => { setLogs(d.logs); setLoading(false) })
  }
  const load = () => { setLoading(true); fetchData() }
  useEffect(fetchData, [])

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-end">
        <Button variant="secondary" size="sm" onClick={load}>새로고침</Button>
      </div>
      {loading ? <p className="text-sm text-gray-500">로딩 중...</p> : (
        <div className="bg-gray-900 rounded-xl p-4 max-h-[600px] overflow-y-auto">
          {logs.length === 0 ? (
            <EmptyState message="로그가 없습니다" className="text-gray-500" />
          ) : (
            logs.map((line, i) => (
              <div key={i} className="text-xs font-mono text-gray-300 py-0.5 hover:bg-gray-800 px-1 rounded">
                {line}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
