import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import QueryPage from './pages/QueryPage'
import AdminLayout from './pages/admin/AdminLayout'
import { ADMIN_SECTIONS } from './pages/admin/sections'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<QueryPage />} />
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<Navigate to="/admin/prompts" replace />} />
          {ADMIN_SECTIONS.map(s => (
            <Route key={s.path} path={s.path} element={<s.Component />} />
          ))}
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
