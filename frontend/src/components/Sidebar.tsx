import { useState } from 'react'
import type { HistoryEntry, SavedView } from '../utils/api'
import { updateHistoryTitle, toggleHistoryFavorite, deleteHistory, deleteSavedView, renameSavedView } from '../utils/api'

interface Props {
  entries: HistoryEntry[]
  activeId: string | null
  onSelect: (entry: HistoryEntry) => void
  onRerun: (entry: HistoryEntry) => void
  onNewChat: () => void
  onRefresh: () => void
  /** 저장된 뷰 (내 화면) */
  views: SavedView[]
  activeViewId: string | null
  onOpenView: (view: SavedView) => void
  onRefreshViews: () => void
  /** 활성 도메인 팩 표시명 (예: "커머스 주문·매출") */
  domainLabel?: string
}

export default function Sidebar({ entries, activeId, onSelect, onRerun, onNewChat, onRefresh, views, activeViewId, onOpenView, onRefreshViews, domainLabel }: Props) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [menuId, setMenuId] = useState<string | null>(null)

  const favorites = entries.filter(e => e.favorite)
  const others = entries.filter(e => !e.favorite)

  const handleRename = async (id: string) => {
    if (editTitle.trim()) {
      await updateHistoryTitle(id, editTitle.trim())
      onRefresh()
    }
    setEditingId(null)
  }

  const handleFavorite = async (id: string) => {
    await toggleHistoryFavorite(id)
    setMenuId(null)
    onRefresh()
  }

  const handleDelete = async (id: string) => {
    await deleteHistory(id)
    setMenuId(null)
    onRefresh()
  }

  const EntryItem = ({ entry }: { entry: HistoryEntry }) => {
    const isActive = activeId === entry.id
    const isEditing = editingId === entry.id
    const isMenu = menuId === entry.id

    return (
      <div className={`group relative rounded-lg transition-colors ${isActive ? 'bg-rail-active' : 'hover:bg-rail-hover'}`}>
        {isEditing ? (
          <div className="px-3 py-2">
            <input
              autoFocus
              value={editTitle}
              onChange={e => setEditTitle(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleRename(entry.id); if (e.key === 'Escape') setEditingId(null) }}
              onBlur={() => handleRename(entry.id)}
              className="w-full bg-gray-600 text-white text-sm px-2 py-1 rounded outline-none"
            />
          </div>
        ) : (
          <button
            onClick={() => onSelect(entry)}
            className="w-full text-left px-3 py-2.5 text-sm text-gray-300"
          >
            {isActive && <span className="absolute left-0 top-2.5 bottom-2.5 w-0.5 rounded-full bg-accent" />}
            <div className="flex items-center gap-1.5">
              {entry.favorite && <span className="text-amber-400 text-xs">&#9733;</span>}
              <span className="truncate flex-1">{entry.title}</span>
            </div>
            <p className="text-xs text-gray-500 mt-0.5 truncate">{entry.question}</p>
          </button>
        )}

        {/* Action menu trigger */}
        {!isEditing && (
          <button
            onClick={(e) => { e.stopPropagation(); setMenuId(isMenu ? null : entry.id) }}
            className="absolute right-1 top-1.5 p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-gray-600 transition-opacity"
          >
            <svg className="w-4 h-4 text-gray-400" fill="currentColor" viewBox="0 0 20 20">
              <path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
            </svg>
          </button>
        )}

        {/* Dropdown menu */}
        {isMenu && (
          <div className="absolute right-0 top-8 z-20 bg-rail-active border border-gray-600 rounded-lg shadow-lg py-1 min-w-[140px]"
               onMouseLeave={() => setMenuId(null)}>
            <button onClick={() => { setEditTitle(entry.title); setEditingId(entry.id); setMenuId(null) }}
                    className="w-full text-left px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-600">
              제목 변경
            </button>
            <button onClick={() => handleFavorite(entry.id)}
                    className="w-full text-left px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-600">
              {entry.favorite ? '즐겨찾기 해제' : '즐겨찾기'}
            </button>
            <button onClick={() => onRerun(entry)}
                    className="w-full text-left px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-600">
              현재 데이터로 재조회
            </button>
            <hr className="border-gray-600 my-1" />
            <button onClick={() => handleDelete(entry.id)}
                    className="w-full text-left px-3 py-1.5 text-xs text-red-400 hover:bg-gray-600">
              삭제
            </button>
          </div>
        )}
      </div>
    )
  }

  return (
    <aside className="w-64 h-screen bg-rail text-white flex flex-col shrink-0">
      {/* Brand */}
      <div className="px-4 py-4 border-b border-rail-border">
        <p className="text-sm font-semibold tracking-tight">QueryCanvas</p>
        <p className="text-xs text-gray-400 mt-0.5">
          AI 데이터 조회{domainLabel && <span className="text-accent"> · {domainLabel}</span>}
        </p>
      </div>

      {/* New chat button */}
      <div className="p-3 border-b border-rail-border">
        <button onClick={onNewChat} className="w-full flex items-center gap-2 px-3 py-2.5 text-sm bg-rail-active hover:bg-rail-hover rounded-lg transition-colors">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          새 질문
        </button>
      </div>

      {/* History list */}
      <div className="flex-1 overflow-y-auto py-2 px-2 space-y-1">
        {/* 내 화면 — 자연어로 만든 화면을 메뉴처럼 재사용 (열 때마다 fresh 데이터) */}
        {views.length > 0 && (
          <>
            <p className="px-2 pt-2 pb-1 text-xs text-gray-500 font-medium">내 화면</p>
            {views.map(v => {
              const isActive = activeViewId === v.id
              return (
                <div key={v.id} className={`group relative rounded-lg transition-colors ${isActive ? 'bg-rail-active' : 'hover:bg-rail-hover'}`}>
                  <button onClick={() => onOpenView(v)} className="w-full text-left px-3 py-2.5 text-sm text-gray-300" title={v.question}>
                    {isActive && <span className="absolute left-0 top-2.5 bottom-2.5 w-0.5 rounded-full bg-accent" />}
                    <div className="flex items-center gap-1.5">
                      <svg className="w-3.5 h-3.5 text-accent shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h12a2 2 0 012 2v12a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM4 10h16M10 4v16" />
                      </svg>
                      <span className="truncate flex-1">{v.name}</span>
                    </div>
                  </button>
                  <div className="absolute right-1 top-1.5 flex opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={async (e) => {
                        e.stopPropagation()
                        const name = window.prompt('화면 이름 변경', v.name)
                        if (name?.trim()) { await renameSavedView(v.id, name.trim()); onRefreshViews() }
                      }}
                      className="p-1 rounded hover:bg-gray-600" title="이름 변경"
                    >
                      <svg className="w-3.5 h-3.5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                      </svg>
                    </button>
                    <button
                      onClick={async (e) => {
                        e.stopPropagation()
                        if (confirm(`'${v.name}' 화면을 삭제할까요?`)) { await deleteSavedView(v.id); onRefreshViews() }
                      }}
                      className="p-1 rounded hover:bg-gray-600" title="삭제"
                    >
                      <svg className="w-3.5 h-3.5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>
              )
            })}
          </>
        )}

        {entries.length === 0 && views.length === 0 && (
          <p className="px-2 py-8 text-xs text-gray-500 text-center">질문 내역이 없습니다</p>
        )}

        {favorites.length > 0 && (
          <>
            <p className="px-2 pt-2 pb-1 text-xs text-gray-500 font-medium">즐겨찾기</p>
            {favorites.map(e => <EntryItem key={e.id} entry={e} />)}
          </>
        )}

        {others.length > 0 && (
          <>
            {(favorites.length > 0 || views.length > 0) && <p className="px-2 pt-3 pb-1 text-xs text-gray-500 font-medium">최근 질문</p>}
            {others.map(e => <EntryItem key={e.id} entry={e} />)}
          </>
        )}
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-rail-border">
        <a href="/admin" className="flex items-center gap-2 px-3 py-2 text-sm text-gray-400 hover:text-white hover:bg-rail-hover rounded-lg transition-colors">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          관리자
        </a>
      </div>
    </aside>
  )
}
