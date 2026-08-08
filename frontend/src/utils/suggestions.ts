import type { UiSpec } from '../types'
import type { SuggestedQuestion } from '../components/ChatInput'

/**
 * 클릭된 데이터 요소를 기반으로 꼬리질문을 생성한다.
 * 도메인 용어를 쓰지 않고 값의 성격(범주 / 기간)만으로 후속 질문을 만든다.
 */
export function generateSuggestions(
  clickedValue: string,
  clickedField: string,
  _uiSpec: UiSpec,
  _previousQuestion: string,
): SuggestedQuestion[] {
  const label = clickedValue
  const fieldLower = (clickedField || '').toLowerCase()
  const isPeriod = /월|일자|날짜|기간|date|month|ym/.test(fieldLower)

  if (isPeriod) {
    return [
      { label: `${label} 상세`, question: `${label} 상세 내역 보여줘` },
      { label: `${label} 분류별`, question: `${label}을 분류별로 나눠서 보여줘` },
      { label: '이전 기간 비교', question: `${label}과 이전 기간을 비교해줘` },
    ]
  }

  return [
    { label: `${label} 상세 보기`, question: `${label}에 대해 더 자세히 보여줘` },
    { label: `${label} 추이`, question: `${label}의 월별 추이 보여줘` },
    { label: `${label} 비중`, question: `전체에서 ${label}이 차지하는 비중 보여줘` },
  ]
}
