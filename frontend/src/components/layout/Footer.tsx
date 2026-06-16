export function Footer() {
  return (
    <footer className="border-t border-white/[0.04] py-6">
      <div className="max-w-[1440px] mx-auto px-6 flex items-center justify-between text-[12px] text-white/25">
        <span>© 2026 LeiaPix AI</span>
        <div className="flex gap-4">
          <span className="hover:text-white/40 cursor-pointer transition-colors">帮助</span>
          <span className="hover:text-white/40 cursor-pointer transition-colors">反馈</span>
          <span className="hover:text-white/40 cursor-pointer transition-colors">隐私</span>
        </div>
      </div>
    </footer>
  )
}
