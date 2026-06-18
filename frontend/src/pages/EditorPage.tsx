import { useCallback, useRef, useState, Suspense } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'motion/react'
import { useEditorStore } from '@/stores/editor-store'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import { Separator } from '@/components/ui/separator'
import { Scene3D } from '@/components/preview/Scene3D'
import { ANIMATION_PRESETS, ART_STYLES, QUALITY_LEVELS } from '@/types'
import type { ExportOptions, ArtStyle, QualityLevel } from '@/types'
import { exportWithFFmpegWasm, downloadBlob, downloadDepthMap } from '@/services/export-engine'
import {
  Upload, Loader2, CheckCircle2, XCircle, Play, Pause, RotateCcw,
  Download, Share2, Image as ImageIcon, Layers, Settings2, ChevronDown,
  Film, FileImage, AlertCircle, ExternalLink,
} from 'lucide-react'

export function EditorPage() {
  const navigate = useNavigate()
  const {
    step, progress, stepMessage, originalPreview, depthMapUrl, error,
    handleUpload, reset, animation, setAnimation, applyPreset, isPlaying, togglePlay,
    exportStep, exportProgress, exportMessage, exportDownloadUrl, exportError,
    exportMedia, exportDepthPng, resetExport,
    depthResult, uploadedImage, sceneId,
    shareData, shareLoading, shareError, createShareLink, resetShare,
    styleQuality, setArtStyle, setQuality,
  } = useEditorStore()
  const [isDragOver, setIsDragOver] = useState(false)
  const [activePanel, setActivePanel] = useState<'animation' | 'export'>('animation')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [frontendExporting, setFrontendExporting] = useState(false)
  const [frontendExportProgress, setFrontendExportProgress] = useState(0)
  const [frontendExportMessage, setFrontendExportMessage] = useState('')
  const [copiedField, setCopiedField] = useState<string | null>(null)

  // 前端导出 (路线 A: ffmpeg.wasm)
  const handleFrontendExport = useCallback(async (format: 'mp4' | 'gif') => {
    const canvas = document.querySelector('canvas')
    if (!canvas) return

    // 录制前确保动画在播放
    const wasPlaying = isPlaying
    if (!wasPlaying) togglePlay()

    setFrontendExporting(true)
    setFrontendExportProgress(0)
    setFrontendExportMessage('正在录制画面...')

    try {
      const options: ExportOptions = {
        format,
        resolution: '1080p',
        fps: format === 'gif' ? 15 : 30,
        duration_seconds: Math.max(1, Math.round((animation.duration || 3000) / 1000)),
        gif_width: format === 'gif' ? '480' : undefined,
        animation: {
          type: animation.type,
          amplitude: animation.amplitude,
          speed: animation.speed,
        },
      }

      const blob = await exportWithFFmpegWasm(canvas, options, (p) => {
        setFrontendExportProgress(p.progress)
        setFrontendExportMessage(p.message)
      })

      const ext = format === 'mp4' ? 'mp4' : 'gif'
      const id = sceneId ? sceneId.slice(0, 8) : Date.now().toString()
      const filename = `leiapix_3d_${id}.${ext}`
      downloadBlob(blob, filename)

      setFrontendExportMessage('导出完成!')
    } catch (err: any) {
      setFrontendExportMessage(`导出失败: ${err.message}`)
    } finally {
      // 录制结束后恢复之前的播放状态
      if (!wasPlaying) togglePlay()
      setTimeout(() => {
        setFrontendExporting(false)
        setFrontendExportProgress(0)
        setFrontendExportMessage('')
      }, 2000)
    }
  }, [animation, sceneId, isPlaying, togglePlay])

  const onFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) handleUpload(file)
  }, [handleUpload])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) handleUpload(file)
  }, [handleUpload])

  // Idle state — show upload zone inside editor
  if (step === 'idle') {
    return (
      <div className="min-h-[calc(100vh-3.5rem)] flex items-center justify-center px-6">
        <div
          onDrop={onDrop}
          onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
          onDragLeave={() => setIsDragOver(false)}
          className={`
            w-full max-w-lg rounded-2xl border-2 border-dashed p-14 text-center transition-all cursor-pointer
            ${isDragOver ? 'border-violet-500/60 bg-violet-500/[0.04]' : 'border-white/[0.08] bg-white/[0.02] hover:border-white/[0.15]'}
          `}
        >
          <Upload className="w-10 h-10 mx-auto mb-4 text-white/30" />
          <p className="text-[15px] font-medium text-white/70 mb-1">拖拽图片到此处</p>
          <p className="text-[13px] text-white/25 mb-5">或点击选择文件开始转换</p>
          <label>
            <Button
              className="bg-gradient-to-r from-violet-600 to-blue-600 hover:from-violet-500 hover:to-blue-500 text-white border-0 px-6 cursor-pointer"
              onClick={() => fileInputRef.current?.click()}
            >
              选择图片
            </Button>
            <input ref={fileInputRef} type="file" accept="image/jpeg,image/png,image/webp,image/bmp" onChange={onFileChange} className="hidden" />
          </label>
        </div>
      </div>
    )
  }

  // Processing state
  if (step === 'uploading' || step === 'estimating') {
    return (
      <div className="min-h-[calc(100vh-3.5rem)] flex items-center justify-center px-6">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="w-full max-w-2xl"
        >
          <div className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-8">
            <div className="flex items-center gap-3 mb-6">
              <Loader2 className="w-5 h-5 text-violet-400 animate-spin" />
              <h2 className="text-lg font-medium text-white/90">正在处理</h2>
            </div>
            {originalPreview && (
              <img src={originalPreview} alt="原图" className="w-full rounded-xl object-contain max-h-72 mb-6" />
            )}
            <div className="space-y-3">
              <div className="flex justify-between text-[13px]">
                <span className="text-white/50">{stepMessage || '处理中...'}</span>
                <span className="text-white/70 font-mono">{Math.round(progress * 100)}%</span>
              </div>
              <div className="w-full bg-white/[0.06] rounded-full h-1.5 overflow-hidden">
                <motion.div
                  className="bg-gradient-to-r from-violet-500 to-blue-500 h-full rounded-full"
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.round(progress * 100)}%` }}
                  transition={{ duration: 0.3 }}
                />
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    )
  }

  // Failed state
  if (step === 'failed') {
    return (
      <div className="min-h-[calc(100vh-3.5rem)] flex items-center justify-center px-6">
        <div className="rounded-2xl bg-white/[0.02] border border-red-500/20 p-8 text-center max-w-md">
          <XCircle className="w-10 h-10 text-red-400 mx-auto mb-4" />
          <h2 className="text-lg font-medium text-white/90 mb-2">处理失败</h2>
          <p className="text-[13px] text-white/40 mb-6">{error}</p>
          <div className="flex gap-3 justify-center">
            <Button variant="outline" className="border-white/[0.08] text-white/60 hover:text-white/90 hover:bg-white/[0.04]" onClick={() => navigate('/')}>
              返回首页
            </Button>
            <Button className="bg-gradient-to-r from-violet-600 to-blue-600 text-white border-0" onClick={reset}>
              重试
            </Button>
          </div>
        </div>
      </div>
    )
  }

  // Completed — Editor layout
  return (
    <div className="min-h-[calc(100vh-3.5rem)] flex flex-col lg:flex-row">
      {/* Left: Preview area */}
      <div className="flex-1 flex flex-col p-4 gap-4 min-w-0">
        {/* 3D Preview */}
        <div className="flex-1 rounded-2xl bg-white/[0.02] border border-white/[0.06] min-h-[300px] relative overflow-hidden">
          <Suspense fallback={
            <div className="absolute inset-0 flex items-center justify-center">
              <Loader2 className="w-6 h-6 text-violet-400/60 animate-spin" />
            </div>
          }>
            <Scene3D />
          </Suspense>
          {/* Fallback when no 3D scene */}
          {!depthMapUrl && (
            <div className="absolute inset-0 bg-gradient-to-br from-violet-500/[0.03] to-blue-500/[0.03] flex items-center justify-center">
              <div className="text-center">
                <div className="w-16 h-16 rounded-2xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center mx-auto mb-4">
                  <Layers className="w-7 h-7 text-violet-400/60" />
                </div>
                <p className="text-[14px] text-white/40">3D 预览区域</p>
                <p className="text-[12px] text-white/20 mt-1">深度图生成后自动渲染</p>
              </div>
            </div>
          )}
          {/* Play/Pause overlay */}
          <button
            onClick={togglePlay}
            className="absolute bottom-4 left-4 w-10 h-10 rounded-xl bg-black/40 backdrop-blur-sm border border-white/[0.08] flex items-center justify-center hover:bg-black/50 transition-colors z-10"
          >
            {isPlaying ? <Pause className="w-4 h-4 text-white/80" /> : <Play className="w-4 h-4 text-white/80 ml-0.5" />}
          </button>
        </div>

        {/* Original + Depth map comparison */}
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl bg-white/[0.02] border border-white/[0.06] p-3">
            <p className="text-[11px] text-white/30 mb-2 flex items-center gap-1.5">
              <ImageIcon className="w-3 h-3" /> 原图
            </p>
            {originalPreview && (
              <img src={originalPreview} alt="原图" className="w-full rounded-lg object-contain max-h-40" />
            )}
          </div>
          <div className="rounded-xl bg-white/[0.02] border border-white/[0.06] p-3">
            <p className="text-[11px] text-white/30 mb-2 flex items-center gap-1.5">
              <Layers className="w-3 h-3" /> 深度图
            </p>
            {depthMapUrl && (
              <img src={depthMapUrl} alt="深度图" className="w-full rounded-lg object-contain max-h-40" />
            )}
          </div>
        </div>
      </div>

      {/* Right: Control panel */}
      <div className="w-full lg:w-80 border-t lg:border-t-0 lg:border-l border-white/[0.06] bg-white/[0.01]">
        <div className="p-4 space-y-4">
          {/* Panel tabs */}
          <div className="flex gap-1 p-1 rounded-lg bg-white/[0.03]">
            <button
              onClick={() => setActivePanel('animation')}
              className={`flex-1 py-1.5 text-[12px] font-medium rounded-md transition-colors ${
                activePanel === 'animation' ? 'bg-white/[0.06] text-white/80' : 'text-white/30 hover:text-white/50'
              }`}
            >
              动画控制
            </button>
            <button
              onClick={() => setActivePanel('export')}
              className={`flex-1 py-1.5 text-[12px] font-medium rounded-md transition-colors ${
                activePanel === 'export' ? 'bg-white/[0.06] text-white/80' : 'text-white/30 hover:text-white/50'
              }`}
            >
              导出分享
            </button>
          </div>

          {activePanel === 'animation' && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
              {/* Presets */}
              <div>
                <p className="text-[11px] text-white/30 uppercase tracking-wider mb-2">动画模板</p>
                <div className="grid grid-cols-2 gap-1.5">
                  {Object.entries(ANIMATION_PRESETS).map(([key, preset]) => (
                    <button
                      key={key}
                      onClick={() => applyPreset(key)}
                      className={`text-left p-2.5 rounded-lg border transition-colors ${
                        animation.type === key
                          ? 'bg-violet-500/[0.08] border-violet-500/30 text-white/80'
                          : 'bg-white/[0.02] border-white/[0.06] text-white/40 hover:bg-white/[0.04]'
                      }`}
                    >
                      <p className="text-[12px] font-medium">{preset.label}</p>
                      <p className="text-[10px] text-white/20 mt-0.5">{preset.desc}</p>
                    </button>
                  ))}
                </div>
              </div>

              <Separator className="bg-white/[0.06]" />

              {/* Art Style */}
              <div>
                <p className="text-[11px] text-white/30 uppercase tracking-wider mb-2">画风选择</p>
                <div className="grid grid-cols-3 gap-1.5">
                  {Object.entries(ART_STYLES).map(([key, style]) => (
                    <button
                      key={key}
                      onClick={() => setArtStyle(key as ArtStyle)}
                      className={`text-left p-2 rounded-lg border transition-colors ${
                        styleQuality.artStyle === key
                          ? 'bg-violet-500/[0.08] border-violet-500/30 text-white/80'
                          : 'bg-white/[0.02] border-white/[0.06] text-white/40 hover:bg-white/[0.04]'
                      }`}
                    >
                      <p className="text-[11px] font-medium">{style.label}</p>
                      <p className="text-[9px] text-white/20 mt-0.5 leading-tight">{style.desc}</p>
                    </button>
                  ))}
                </div>
              </div>

              <Separator className="bg-white/[0.06]" />

              {/* Quality Level */}
              <div>
                <p className="text-[11px] text-white/30 uppercase tracking-wider mb-2">画质选择</p>
                <div className="grid grid-cols-4 gap-1.5">
                  {Object.entries(QUALITY_LEVELS).map(([key, q]) => (
                    <button
                      key={key}
                      onClick={() => setQuality(key as QualityLevel)}
                      className={`text-center p-2 rounded-lg border transition-colors ${
                        styleQuality.quality === key
                          ? 'bg-violet-500/[0.08] border-violet-500/30 text-white/80'
                          : 'bg-white/[0.02] border-white/[0.06] text-white/40 hover:bg-white/[0.04]'
                      }`}
                    >
                      <p className="text-[11px] font-medium">{q.label}</p>
                      <p className="text-[9px] text-white/20 mt-0.5">{q.resolution}</p>
                    </button>
                  ))}
                </div>
              </div>

              <Separator className="bg-white/[0.06]" />

              {/* Parameters */}
              <div className="space-y-3">
                <p className="text-[11px] text-white/30 uppercase tracking-wider">参数调节</p>
                <div>
                  <div className="flex justify-between text-[12px] mb-1.5">
                    <span className="text-white/40">振幅</span>
                    <span className="text-white/60 font-mono">{animation.amplitude.toFixed(1)}</span>
                  </div>
                  <Slider
                    value={[animation.amplitude * 100]}
                    onValueChange={([v]) => setAnimation({ amplitude: v / 100 })}
                    min={10} max={100} step={1}
                    className="[&_[role=slider]]:bg-violet-500"
                  />
                </div>
                <div>
                  <div className="flex justify-between text-[12px] mb-1.5">
                    <span className="text-white/40">速度</span>
                    <span className="text-white/60 font-mono">{animation.speed.toFixed(1)}x</span>
                  </div>
                  <Slider
                    value={[animation.speed * 100]}
                    onValueChange={([v]) => setAnimation({ speed: v / 100 })}
                    min={10} max={500} step={10}
                    className="[&_[role=slider]]:bg-violet-500"
                  />
                </div>
                <div>
                  <div className="flex justify-between text-[12px] mb-1.5">
                    <span className="text-white/40">时长</span>
                    <span className="text-white/60 font-mono">{(animation.duration / 1000).toFixed(1)}s</span>
                  </div>
                  <Slider
                    value={[animation.duration]}
                    onValueChange={([v]) => setAnimation({ duration: v })}
                    min={1000} max={10000} step={500}
                    className="[&_[role=slider]]:bg-violet-500"
                  />
                </div>
              </div>
            </motion.div>
          )}

          {activePanel === 'export' && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-3">
              <p className="text-[11px] text-white/30 uppercase tracking-wider mb-2">导出格式</p>

              {/* 导出进度/状态 */}
              {(exportStep !== 'idle' || frontendExporting) && (
                <div className="rounded-lg bg-white/[0.03] border border-white/[0.08] p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    {exportStep === 'failed' || frontendExportMessage.includes('失败') ? (
                      <AlertCircle className="w-4 h-4 text-red-400" />
                    ) : exportStep === 'completed' || frontendExportMessage.includes('完成') ? (
                      <CheckCircle2 className="w-4 h-4 text-green-400" />
                    ) : (
                      <Loader2 className="w-4 h-4 text-violet-400 animate-spin" />
                    )}
                    <span className="text-[12px] text-white/70">
                      {frontendExporting ? frontendExportMessage : exportMessage || '处理中...'}
                    </span>
                  </div>
                  <div className="w-full bg-white/[0.06] rounded-full h-1.5 overflow-hidden">
                    <div
                      className="bg-gradient-to-r from-violet-500 to-blue-500 h-full rounded-full transition-all duration-300"
                      style={{ width: `${Math.round((frontendExporting ? frontendExportProgress : exportProgress) * 100)}%` }}
                    />
                  </div>
                  {/* 下载链接 */}
                  {exportStep === 'completed' && exportDownloadUrl && (
                    <a
                      href={exportDownloadUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-2 text-[12px] text-violet-400 hover:text-violet-300 transition-colors"
                    >
                      <Download className="w-3.5 h-3.5" />
                      下载文件
                    </a>
                  )}
                </div>
              )}

              {/* MP4 视频 — 路线 A (前端) */}
              <button
                onClick={() => handleFrontendExport('mp4')}
                disabled={frontendExporting || exportStep === 'recording' || exportStep === 'requesting'}
                className="w-full flex items-center gap-3 p-3 rounded-lg bg-white/[0.02] border border-white/[0.06] hover:bg-white/[0.04] transition-colors text-left disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Film className="w-4 h-4 text-violet-400/60" />
                <div className="flex-1">
                  <p className="text-[13px] text-white/70">MP4 视频</p>
                  <p className="text-[11px] text-white/25">1080p / 30fps / 浏览器内编码</p>
                </div>
                <Download className="w-4 h-4 text-white/20" />
              </button>

              {/* GIF 动图 — 路线 A (前端) */}
              <button
                onClick={() => handleFrontendExport('gif')}
                disabled={frontendExporting || exportStep === 'recording' || exportStep === 'requesting'}
                className="w-full flex items-center gap-3 p-3 rounded-lg bg-white/[0.02] border border-white/[0.06] hover:bg-white/[0.04] transition-colors text-left disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Share2 className="w-4 h-4 text-violet-400/60" />
                <div className="flex-1">
                  <p className="text-[13px] text-white/70">GIF 动图</p>
                  <p className="text-[11px] text-white/25">480px / 15fps / 浏览器内编码</p>
                </div>
                <Download className="w-4 h-4 text-white/20" />
              </button>

              {/* 深度图 PNG — 直接下载 */}
              <button
                onClick={exportDepthPng}
                disabled={!depthMapUrl}
                className="w-full flex items-center gap-3 p-3 rounded-lg bg-white/[0.02] border border-white/[0.06] hover:bg-white/[0.04] transition-colors text-left disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Layers className="w-4 h-4 text-violet-400/60" />
                <div className="flex-1">
                  <p className="text-[13px] text-white/70">深度图 PNG</p>
                  <p className="text-[11px] text-white/25">原始分辨率灰度图</p>
                </div>
                <Download className="w-4 h-4 text-white/20" />
              </button>

              <Separator className="bg-white/[0.06]" />

              {/* 路线 B: 后端导出 (需要 scene_id) */}
              <p className="text-[11px] text-white/30 uppercase tracking-wider">后端高质量导出</p>
              <button
                onClick={() => {
                  if (!sceneId) return
                  exportMedia(sceneId, {
                    format: 'mp4',
                    resolution: '1080p',
                    fps: 30,
                    duration_seconds: Math.max(1, Math.round((animation.duration || 3000) / 1000)),
                    animation: {
                      type: animation.type,
                      amplitude: animation.amplitude,
                      speed: animation.speed,
                    },
                  })
                }}
                disabled={!sceneId || exportStep === 'recording' || exportStep === 'requesting'}
                className="w-full flex items-center gap-3 p-3 rounded-lg bg-white/[0.02] border border-white/[0.06] hover:bg-white/[0.04] transition-colors text-left disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <FileImage className="w-4 h-4 text-blue-400/60" />
                <div className="flex-1">
                  <p className="text-[13px] text-white/70">后端导出 MP4</p>
                  <p className="text-[11px] text-white/25">Playwright + ffmpeg / 1080p / 高质量</p>
                </div>
                <Download className="w-4 h-4 text-white/20" />
              </button>

              <Separator className="bg-white/[0.06]" />

              {/* 分享链接 */}
              <p className="text-[11px] text-white/30 uppercase tracking-wider">分享与嵌入</p>

              <button
                onClick={() => {
                  if (!sceneId) return
                  createShareLink(sceneId)
                }}
                disabled={!sceneId || shareLoading}
                className="w-full flex items-center gap-3 p-3 rounded-lg bg-white/[0.02] border border-white/[0.06] hover:bg-white/[0.04] transition-colors text-left disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Share2 className="w-4 h-4 text-green-400/60" />
                <div className="flex-1">
                  <p className="text-[13px] text-white/70">
                    {shareLoading ? '生成中...' : '生成分享链接'}
                  </p>
                  <p className="text-[11px] text-white/25">公开 3D 预览 + iframe 嵌入</p>
                </div>
                {shareLoading && <Loader2 className="w-4 h-4 text-white/30 animate-spin" />}
              </button>

              {/* 分享结果 */}
              {shareData && (
                <div className="rounded-lg bg-white/[0.03] border border-white/[0.08] p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-green-400" />
                    <span className="text-[12px] text-white/70">分享链接已生成</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      readOnly
                      value={shareData.share_url}
                      className="flex-1 bg-white/[0.04] border border-white/[0.06] rounded px-2 py-1.5 text-[11px] text-white/60 outline-none"
                      onClick={(e) => (e.target as HTMLInputElement).select()}
                    />
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(shareData.share_url)
                        setCopiedField('link')
                        setTimeout(() => setCopiedField(null), 2000)
                      }}
                      className="px-2 py-1.5 rounded bg-white/[0.06] text-[11px] text-white/60 hover:text-white/90 transition-colors whitespace-nowrap"
                    >
                      {copiedField === 'link' ? '已复制' : '复制'}
                    </button>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      readOnly
                      value={shareData.embed_code}
                      className="flex-1 bg-white/[0.04] border border-white/[0.06] rounded px-2 py-1.5 text-[11px] text-white/60 outline-none truncate"
                      onClick={(e) => (e.target as HTMLInputElement).select()}
                    />
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(shareData.embed_code)
                        setCopiedField('embed')
                        setTimeout(() => setCopiedField(null), 2000)
                      }}
                      className="px-2 py-1.5 rounded bg-white/[0.06] text-[11px] text-white/60 hover:text-white/90 transition-colors whitespace-nowrap"
                    >
                      {copiedField === 'embed' ? '已复制' : '嵌入'}
                    </button>
                  </div>
                  <a
                    href={shareData.share_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-[11px] text-violet-400/80 hover:text-violet-300 transition-colors"
                  >
                    <ExternalLink className="w-3 h-3" /> 在新窗口预览
                  </a>
                </div>
              )}

              {shareError && (
                <p className="text-[11px] text-red-400/80">{shareError}</p>
              )}
            </motion.div>
          )}

          <Separator className="bg-white/[0.06]" />

          {/* Bottom actions */}
          <div className="flex gap-2">
            <Button
              variant="outline"
              className="flex-1 border-white/[0.08] text-white/50 hover:text-white/80 hover:bg-white/[0.04] text-[13px]"
              onClick={() => { reset(); navigate('/') }}
            >
              <RotateCcw className="w-3.5 h-3.5 mr-1.5" />
              新图片
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
