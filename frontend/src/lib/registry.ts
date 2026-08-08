/**
 * json-render Registry — 카탈로그의 컴포넌트 정의를 실제 React 컴포넌트와 매핑한다.
 */

import { defineRegistry } from '@json-render/react'
import { shadcnComponents } from '@json-render/shadcn'
import { catalog } from './catalog'
import { customComponents } from './customComponents'

// json-render의 ComponentFn 타입이 매우 엄격하지만 런타임에는
// `{ props, children }` 시그니처면 동작한다. 타입 단언으로 우회.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const components: any = { ...shadcnComponents, ...customComponents }

export const { registry } = defineRegistry(catalog, { components })
