import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Header } from '@/components/layout/Header'
import { Footer } from '@/components/layout/Footer'
import { HomePage } from '@/pages/HomePage'
import { EditorPage } from '@/pages/EditorPage'
import { SharePage } from '@/pages/SharePage'

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-[#0a0a0f] text-white">
        <Routes>
          {/* 分享页面 — 独立布局，不需要 Header/Footer */}
          <Route path="/share/:id" element={<SharePage />} />

          {/* 常规页面 */}
          <Route path="/" element={<><Header /><main className="pt-14"><HomePage /></main><Footer /></>} />
          <Route path="/editor" element={<><Header /><main className="pt-14"><EditorPage /></main><Footer /></>} />
          <Route path="/editor/:id" element={<><Header /><main className="pt-14"><EditorPage /></main><Footer /></>} />
        </Routes>
      </div>
    </BrowserRouter>
  )
}
