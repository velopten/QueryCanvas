import { useState, useEffect } from 'react'
import { getRetrievalWeights, saveRetrievalWeights, type RetrievalWeightConfig } from '../../utils/api'
import { Button, Panel, StatusText } from '../../components/ui'

export default function WeightsPanel() {
  const [data, setData] = useState<Record<string, RetrievalWeightConfig>>({})
  const [status, setStatus] = useState<string | null>(null)
  useEffect(() => { getRetrievalWeights().then(d => setData(d.data)) }, [])

  const update = (type: string, key: keyof RetrievalWeightConfig, val: number) => {
    setData({ ...data, [type]: { ...data[type], [key]: val } })
  }
  const save = async () => {
    setStatus('저장 중...')
    try {
      await saveRetrievalWeights(data)
      setStatus('저장 완료 (핫리로드됨 — 다음 검색부터 반영)')
    } catch (e) { setStatus('실패: ' + String(e)) }
  }

  const cellInput = 'w-20 border border-gray-300 rounded-md px-2 py-0.5 text-xs focus:outline-none focus:ring-2 focus:ring-accent/25 focus:border-accent'

  return (
    <Panel
      title="검색 가중치 (retrieval_weights.yaml)"
      description="per_type_n: chroma 1차 후보 수 · weight: effective_distance = distance × weight (낮을수록 우선) · inject_limit: 프롬프트에 실제 주입할 최대 개수"
      actions={<Button onClick={save}>저장</Button>}
    >
      <table className="w-full text-xs">
        <thead className="bg-gray-100">
          <tr>
            <th className="text-left px-2 py-1.5 font-medium text-gray-600">타입</th>
            <th className="text-left px-2 py-1.5 font-medium text-gray-600">per_type_n</th>
            <th className="text-left px-2 py-1.5 font-medium text-gray-600">weight</th>
            <th className="text-left px-2 py-1.5 font-medium text-gray-600">inject_limit</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data).map(([type, cfg]) => (
            <tr key={type} className="border-t border-gray-100">
              <td className="px-2 py-1.5 font-mono font-semibold text-gray-800">{type}</td>
              <td className="px-2 py-1.5"><input type="number" value={cfg.per_type_n} onChange={e => update(type, 'per_type_n', Number(e.target.value))} className={cellInput} /></td>
              <td className="px-2 py-1.5"><input type="number" step="0.05" value={cfg.weight} onChange={e => update(type, 'weight', Number(e.target.value))} className={cellInput} /></td>
              <td className="px-2 py-1.5"><input type="number" value={cfg.inject_limit} onChange={e => update(type, 'inject_limit', Number(e.target.value))} className={cellInput} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2"><StatusText status={status} /></div>
    </Panel>
  )
}
