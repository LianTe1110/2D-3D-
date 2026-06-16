import { Link, useLocation } from 'react-router-dom'
import { Cuboid } from 'lucide-react'

export function Header() {
  const location = useLocation()
  const isEditor = location.pathname.startsWith('/editor')

  return (
    <header className="fixed top-0 left-0 right-0 z-50 border-b border-white/[0.06] bg-[#0a0a0f]/80 backdrop-blur-xl">
      <div className="max-w-[1440px] mx-auto px-6 h-14 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2.5 group">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center">
            <Cuboid className="w-4 h-4 text-white" />
          </div>
          <span className="text-[15px] font-semibold tracking-tight text-white">LeiaPix AI</span>
          <span className="text-[11px] text-white/30 font-medium ml-0.5">2D→3D</span>
        </Link>
        <nav className="flex items-center gap-1">
          {!isEditor && (
            <Link
              to="/"
              className="px-3 py-1.5 text-[13px] text-white/50 hover:text-white/90 transition-colors rounded-md hover:bg-white/[0.04]"
            >
              首页
            </Link>
          )}
        </nav>
      </div>
    </header>
  )
}
