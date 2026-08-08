/**
 * 경량 마크다운 렌더러. 외부 라이브러리 없이 기본 마크다운 문법을 렌더링한다.
 */
export default function MarkdownRenderer({ content }: { content: string }) {
  const lines = content.split('\n')
  const elements: React.ReactNode[] = []
  let inCodeBlock = false
  let codeLines: string[] = []

  lines.forEach((line, i) => {
    if (line.startsWith('```')) {
      if (inCodeBlock) {
        elements.push(<pre key={i} className="bg-gray-900 text-green-400 text-xs rounded-lg p-3 overflow-x-auto my-2">{codeLines.join('\n')}</pre>)
        codeLines = []
      }
      inCodeBlock = !inCodeBlock
      return
    }
    if (inCodeBlock) { codeLines.push(line); return }

    if (line.startsWith('### ')) {
      elements.push(<h4 key={i} className="text-sm font-bold text-gray-800 mt-3 mb-1">{renderInline(line.slice(4))}</h4>)
    } else if (line.startsWith('## ')) {
      elements.push(<h3 key={i} className="text-base font-bold text-gray-900 mt-4 mb-2 border-b border-gray-200 pb-1">{renderInline(line.slice(3))}</h3>)
    } else if (line.startsWith('# ')) {
      elements.push(<h2 key={i} className="text-lg font-bold text-gray-900 mt-4 mb-2">{renderInline(line.slice(2))}</h2>)
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      elements.push(<li key={i} className="text-sm text-gray-700 ml-4 list-disc">{renderInline(line.slice(2))}</li>)
    } else if (line.startsWith('  - ') || line.startsWith('  * ')) {
      elements.push(<li key={i} className="text-sm text-gray-600 ml-8 list-circle">{renderInline(line.slice(4))}</li>)
    } else if (/^\d+\.\s/.test(line)) {
      elements.push(<li key={i} className="text-sm text-gray-700 ml-4 list-decimal">{renderInline(line.replace(/^\d+\.\s/, ''))}</li>)
    } else if (line.trim() === '') {
      elements.push(<div key={i} className="h-2" />)
    } else {
      elements.push(<p key={i} className="text-sm text-gray-700 leading-relaxed">{renderInline(line)}</p>)
    }
  })

  return <div className="space-y-0.5">{elements}</div>
}

function renderInline(text: string): React.ReactNode {
  // Bold + inline code
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i} className="font-semibold text-gray-900">{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={i} className="px-1.5 py-0.5 bg-gray-100 text-red-600 rounded text-xs font-mono">{part.slice(1, -1)}</code>
    }
    return part
  })
}
