/**
 * 차트/테이블 요소 클릭 이벤트를 부모(QueryPage)에 전달하기 위한 React Context.
 * SpecRenderer 안에서 렌더링되는 Chart/DataTable이 사용한다.
 *
 * 부모는 SpecRenderer를 ElementClickProvider로 감싸고 onElementClick 콜백을 등록.
 * 자식 컴포넌트는 useElementClick() 훅으로 콜백을 호출.
 */

import { createContext, useContext } from 'react'

export type ElementClickHandler = (value: string, field: string) => void

export const ElementClickContext = createContext<ElementClickHandler | null>(null)

export function useElementClick(): ElementClickHandler | null {
  return useContext(ElementClickContext)
}
