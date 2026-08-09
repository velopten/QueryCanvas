import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { ADMIN_GROUPS, ADMIN_SECTIONS } from './sections'
import { IS_STATIC } from '../../utils/api'

/**
 * 관리자 콘솔 레이아웃 — 조회 화면과 같은 다크 레일을 공유하는
 * 좌측 사이드바 내비게이션 + 섹션 헤더 + 콘텐츠 영역.
 */
export default function AdminLayout() {
  const location = useLocation()
  const current = ADMIN_SECTIONS.find(s => location.pathname === `/admin/${s.path}`)

  return (
    <div className="flex h-screen bg-gray-50">
      <aside className="w-60 h-screen bg-rail text-white flex flex-col shrink-0">
        {/* Brand */}
        <div className="px-4 py-4 border-b border-rail-border">
          <p className="text-sm font-semibold tracking-tight">QueryCanvas</p>
          <p className="text-xs text-gray-400 mt-0.5">관리자 콘솔</p>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-4">
          {ADMIN_GROUPS.map(group => (
            <div key={group.title}>
              <p className="px-3 pb-1 text-[11px] font-semibold tracking-wider text-gray-500">
                {group.title}
              </p>
              <div className="space-y-0.5">
                {group.sections.map(s => (
                  <NavLink
                    key={s.path}
                    to={`/admin/${s.path}`}
                    className={({ isActive }) =>
                      `relative flex items-center px-3 py-2 text-sm rounded-lg transition-colors ${
                        isActive
                          ? 'bg-rail-active text-white font-medium'
                          : 'text-gray-400 hover:text-white hover:bg-rail-hover'
                      }`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        {isActive && <span className="absolute left-0 top-2 bottom-2 w-0.5 rounded-full bg-accent" />}
                        {s.label}
                      </>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        {/* Footer — back to query page */}
        <div className="p-3 border-t border-rail-border">
          <a href="/" className="flex items-center gap-2 px-3 py-2 text-sm text-gray-400 hover:text-white hover:bg-rail-hover rounded-lg transition-colors">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
            조회 화면으로
          </a>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 bg-white border-b border-gray-200 flex items-center px-6 shrink-0">
          <div>
            <h1 className="text-sm font-semibold text-gray-900">{current?.label ?? '관리자'}</h1>
            {current && <p className="text-xs text-gray-500">{current.description}</p>}
          </div>
          {IS_STATIC && (
            <span className="ml-auto text-xs px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 border border-amber-200">
              읽기 전용 — 공개 스냅샷
            </span>
          )}
        </header>
        <main className="flex-1 overflow-y-auto">
          <div className="max-w-5xl mx-auto px-6 py-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
