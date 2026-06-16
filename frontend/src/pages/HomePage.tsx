import { useCallback, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'motion/react'
import { useEditorStore } from '@/stores/editor-store'
import { Button } from '@/components/ui/button'
import { Upload, Layers, Zap, Share2, ArrowRight, Loader2 } from 'lucide-react'

const features = [
  { icon: Layers, title: 'AI 深度估计', desc: 'Depth Anything V2 自动生成高精度深度图' },
  { icon: Zap, title: '实时 3D 预览', desc: 'Three.js 驱动的交互式 3D 场景渲染' },
  { icon: Share2, title: '一键导出分享', desc: 'MP4 / GIF / 深度图多格式导出' },
]

export function HomePage() {
  const navigate = useNavigate()
  const { step, progress, stepMessage, handleUpload } = useEditorStore()
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const onFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      handleUpload(file)
      navigate('/editor')
    }
  }, [handleUpload, navigate])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) {
      handleUpload(file)
      navigate('/editor')
    }
  }, [handleUpload, navigate])

  return (
    <div className="min-h-[calc(100vh-3.5rem)] flex flex-col">
      {/* Hero */}
      <section className="flex-1 flex flex-col items-center justify-center px-6 py-20 relative">
        {/* Gradient orbs */}
        <div className="absolute top-1/4 left-1/4 w-[500px] h-[500px] bg-violet-600/10 rounded-full blur-[120px] pointer-events-none" />
        <div className="absolute bottom-1/4 right-1/4 w-[400px] h-[400px] bg-blue-600/10 rounded-full blur-[120px] pointer-events-none" />

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="text-center relative z-10"
        >
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/[0.04] border border-white/[0.06] text-[12px] text-white/50 mb-6">
            <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
            Powered by Depth Anything V2
          </div>
          <h1 className="text-5xl md:text-6xl font-bold tracking-tight text-white mb-4">
            将照片变为
            <span className="bg-gradient-to-r from-violet-400 to-blue-400 bg-clip-text text-transparent"> 3D</span>
          </h1>
          <p className="text-lg text-white/40 max-w-lg mx-auto mb-10 leading-relaxed">
            上传任意 2D 图片，AI 自动生成深度图，实时预览 3D 效果，导出动画视频
          </p>
        </motion.div>

        {/* Upload zone */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.15 }}
          className="relative z-10 w-full max-w-xl"
        >
          <div
            onDrop={onDrop}
            onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
            onDragLeave={() => setIsDragOver(false)}
            className={`
              relative rounded-2xl border-2 border-dashed p-12 text-center transition-all duration-300 cursor-pointer
              ${isDragOver
                ? 'border-violet-500/60 bg-violet-500/[0.04]'
                : 'border-white/[0.08] bg-white/[0.02] hover:border-white/[0.15] hover:bg-white/[0.03]'
              }
            `}
          >
            <Upload className="w-10 h-10 mx-auto mb-4 text-white/30" />
            <p className="text-[15px] font-medium text-white/70 mb-1">拖拽图片到此处，或点击选择</p>
            <p className="text-[13px] text-white/25 mb-5">支持 JPG / PNG / WEBP / BMP，最大 20MB</p>
            <Button
              className="bg-gradient-to-r from-violet-600 to-blue-600 hover:from-violet-500 hover:to-blue-500 text-white border-0 px-6 cursor-pointer"
              onClick={() => fileInputRef.current?.click()}
            >
              选择图片
              <ArrowRight className="w-4 h-4 ml-1.5" />
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/bmp"
              onChange={onFileChange}
              className="hidden"
            />
          </div>
        </motion.div>

        {/* Features */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.3 }}
          className="relative z-10 grid grid-cols-1 md:grid-cols-3 gap-4 mt-16 w-full max-w-3xl"
        >
          {features.map((f, i) => (
            <div key={i} className="rounded-xl bg-white/[0.02] border border-white/[0.06] p-5">
              <f.icon className="w-5 h-5 text-violet-400 mb-3" />
              <h3 className="text-[14px] font-medium text-white/80 mb-1">{f.title}</h3>
              <p className="text-[12px] text-white/30 leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </motion.div>
      </section>
    </div>
  )
}
