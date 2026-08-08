import type { ComponentType } from 'react'
import PromptsPanel from './PromptsPanel'
import TrainingPanel from './TrainingPanel'
import VectorPanel from './VectorPanel'
import VirtualViewPanel from './VirtualViewPanel'
import WeightsPanel from './WeightsPanel'
import EvalPanel from './EvalPanel'
import SettingsPanel from './SettingsPanel'
import TracesPanel from './TracesPanel'
import LogsPanel from './LogsPanel'

export interface AdminSection {
  path: string
  label: string
  description: string
  Component: ComponentType
}

export interface AdminGroup {
  title: string
  sections: AdminSection[]
}

/** 관리자 메뉴 트리 — 사이드바와 라우트가 모두 이 정의를 사용한다. */
export const ADMIN_GROUPS: AdminGroup[] = [
  {
    title: '지식 관리',
    sections: [
      { path: 'prompts', label: '프롬프트', description: 'SQL 생성 / UI 결정 시스템 프롬프트 편집', Component: PromptsPanel },
      { path: 'training', label: '학습 데이터', description: 'AI 큐레이터로 도메인 지식 추가 및 청크 관리', Component: TrainingPanel },
      { path: 'vector', label: '벡터 저장소', description: '임베딩 현황, 재임베딩, 검색 시뮬레이션', Component: VectorPanel },
      { path: 'vviews', label: '가상 View', description: '자주 쓰는 질의를 view처럼 등록해 SQL 생성을 단순화', Component: VirtualViewPanel },
    ],
  },
  {
    title: '품질 · 평가',
    sections: [
      { path: 'eval', label: '평가', description: '골든 질문셋으로 text-to-SQL 정확도/지연/비용 회귀 확인', Component: EvalPanel },
      { path: 'weights', label: '검색 가중치', description: '타입별 벡터 검색 후보 수·가중치·주입 한도 조정', Component: WeightsPanel },
    ],
  },
  {
    title: '운영',
    sections: [
      { path: 'traces', label: '파이프라인 추적', description: '질의별 단계 로그와 사용자 피드백 확인', Component: TracesPanel },
      { path: 'logs', label: '원시 로그', description: '백엔드 파이프라인 로그 원문', Component: LogsPanel },
      { path: 'settings', label: '설정', description: 'LLM 모델 맵 런타임 변경 및 시스템 상태', Component: SettingsPanel },
    ],
  },
]

export const ADMIN_SECTIONS: AdminSection[] = ADMIN_GROUPS.flatMap(g => g.sections)
