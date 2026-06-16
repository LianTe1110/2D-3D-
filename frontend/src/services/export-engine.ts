/**
 * LeiaPix AI - 前端导出引擎 (路线 A: ffmpeg.wasm)
 *
 * 使用 Canvas captureStream + MediaRecorder 或手动帧捕获,
 * 通过 ffmpeg.wasm 在浏览器沙箱内编码为 MP4/GIF 供用户下载。
 *
 * 优势: 无需后端算力, 全部在浏览器内完成
 * 劣势: 受浏览器性能限制, 大分辨率/长时长可能卡顿
 */

import { FFmpeg } from '@ffmpeg/ffmpeg'
import { fetchFile, toBlobURL } from '@ffmpeg/util'
import type { ExportOptions, AnimationType } from '@/types'
import { logger } from '@/lib/logger'

// ============ FFmpeg 单例 ============

let ffmpegInstance: FFmpeg | null = null
let ffmpegLoaded = false

async function getFFmpeg(): Promise<FFmpeg> {
  if (!ffmpegInstance) {
    ffmpegInstance = new FFmpeg()
  }

  if (!ffmpegLoaded) {
    logger.info('export', 'Loading ffmpeg.wasm...')
    const baseURL = 'https://unpkg.com/@ffmpeg/core@0.12.6/dist/esm'

    await ffmpegInstance.load({
      coreURL: await toBlobURL(`${baseURL}/ffmpeg-core.js`, 'text/javascript'),
      wasmURL: await toBlobURL(`${baseURL}/ffmpeg-core.wasm`, 'application/wasm'),
    })

    ffmpegLoaded = true
    logger.info('export', 'ffmpeg.wasm loaded successfully')
  }

  return ffmpegInstance
}

// ============ Canvas 帧捕获 ============

/**
 * 从 WebGL Canvas 逐帧捕获画面
 *
 * @param canvas 目标 Canvas 元素
 * @param fps 帧率
 * @param durationSeconds 时长(秒)
 * @param onProgress 进度回调 (0~1)
 * @returns PNG 帧数据数组
 */
async function captureCanvasFrames(
  canvas: HTMLCanvasElement,
  fps: number,
  durationSeconds: number,
  onProgress?: (progress: number) => void,
): Promise<Uint8Array[]> {
  const totalFrames = fps * durationSeconds
  const frameInterval = 1000 / fps
  const frames: Uint8Array[] = []

  logger.info('export', `Capturing ${totalFrames} frames at ${fps}fps`)

  for (let i = 0; i < totalFrames; i++) {
    // 从 WebGL Canvas 读取像素
    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, 'image/png')
    })

    if (blob) {
      const arrayBuffer = await blob.arrayBuffer()
      frames.push(new Uint8Array(arrayBuffer))
    }

    onProgress?.(i / totalFrames)

    // 等待下一帧时间
    await new Promise((resolve) => setTimeout(resolve, frameInterval))
  }

  logger.info('export', `Captured ${frames.length} frames`)
  return frames
}

// ============ MP4 编码 ============

/**
 * 使用 ffmpeg.wasm 将帧序列编码为 H.264 MP4
 */
async function encodeMP4(
  frames: Uint8Array[],
  fps: number,
  width: number,
  height: number,
  onProgress?: (progress: number) => void,
): Promise<Blob> {
  const ffmpeg = await getFFmpeg()

  // 写入帧文件
  logger.info('export', 'Writing frames to ffmpeg virtual FS...')
  for (let i = 0; i < frames.length; i++) {
    const filename = `frame_${i.toString().padStart(6, '0')}.png`
    await ffmpeg.writeFile(filename, frames[i])
    onProgress?.(0.1 + (i / frames.length) * 0.3)
  }

  // 编码 MP4
  logger.info('export', 'Encoding MP4 with ffmpeg.wasm...')
  await ffmpeg.exec([
    '-framerate', String(fps),
    '-i', 'frame_%06d.png',
    '-c:v', 'libx264',
    '-preset', 'fast',
    '-crf', '23',
    '-pix_fmt', 'yuv420p',
    '-vf', `scale=${width}:${height}:force_original_aspect_ratio=decrease,pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2`,
    '-movflags', '+faststart',
    'output.mp4',
  ])

  onProgress?.(0.9)

  // 读取输出文件
  const data = await ffmpeg.readFile('output.mp4')

  // 清理虚拟文件系统
  for (let i = 0; i < frames.length; i++) {
    const filename = `frame_${i.toString().padStart(6, '0')}.png`
    await ffmpeg.deleteFile(filename)
  }
  await ffmpeg.deleteFile('output.mp4')

  onProgress?.(1.0)

  return new Blob([data], { type: 'video/mp4' })
}

// ============ GIF 编码 ============

/**
 * 使用 ffmpeg.wasm 将帧序列编码为优化调色板 GIF
 */
async function encodeGIF(
  frames: Uint8Array[],
  fps: number,
  width: number,
  onProgress?: (progress: number) => void,
): Promise<Blob> {
  const ffmpeg = await getFFmpeg()

  // 写入帧文件
  logger.info('export', 'Writing frames to ffmpeg virtual FS...')
  for (let i = 0; i < frames.length; i++) {
    const filename = `frame_${i.toString().padStart(6, '0')}.png`
    await ffmpeg.writeFile(filename, frames[i])
    onProgress?.(0.1 + (i / frames.length) * 0.2)
  }

  // Step 1: 生成调色板
  logger.info('export', 'Generating GIF palette...')
  await ffmpeg.exec([
    '-framerate', String(fps),
    '-i', 'frame_%06d.png',
    '-vf', `scale=${width}:-1:flags=lanczos,palettegen=max_colors=256:stats_mode=full`,
    'palette.png',
  ])

  onProgress?.(0.6)

  // Step 2: 用调色板编码 GIF
  logger.info('export', 'Encoding GIF with palette...')
  await ffmpeg.exec([
    '-framerate', String(fps),
    '-i', 'frame_%06d.png',
    '-i', 'palette.png',
    '-lavfi', `scale=${width}:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5`,
    'output.gif',
  ])

  onProgress?.(0.9)

  // 读取输出文件
  const data = await ffmpeg.readFile('output.gif')

  // 清理
  for (let i = 0; i < frames.length; i++) {
    const filename = `frame_${i.toString().padStart(6, '0')}.png`
    await ffmpeg.deleteFile(filename)
  }
  await ffmpeg.deleteFile('palette.png')
  await ffmpeg.deleteFile('output.gif')

  onProgress?.(1.0)

  return new Blob([data], { type: 'image/gif' })
}

// ============ 分辨率映射 ============

const RESOLUTION_MAP: Record<string, [number, number]> = {
  '720p': [1280, 720],
  '1080p': [1920, 1080],
  '4k': [3840, 2160],
}

const GIF_SIZE_MAP: Record<string, number> = {
  '320': 320,
  '480': 480,
  '640': 640,
}

// ============ 主导出函数 ============

export interface ExportProgress {
  step: 'capturing' | 'encoding' | 'completed'
  progress: number  // 0~1
  message: string
}

/**
 * 前端导出入口 (路线 A)
 *
 * 流程:
 * 1. 从 WebGL Canvas 逐帧捕获画面
 * 2. 使用 ffmpeg.wasm 编码为 MP4/GIF
 * 3. 触发浏览器下载
 *
 * @param canvas WebGL Canvas 元素
 * @param options 导出参数
 * @param onProgress 进度回调
 * @returns 下载的 Blob
 */
export async function exportWithFFmpegWasm(
  canvas: HTMLCanvasElement,
  options: ExportOptions,
  onProgress?: (progress: ExportProgress) => void,
): Promise<Blob> {
  const { format, resolution, fps, duration_seconds, gif_width } = options

  logger.info('export', `Starting frontend export: format=${format}, resolution=${resolution}, fps=${fps}, duration=${duration_seconds}s`)

  // 1. 帧捕获
  onProgress?.({ step: 'capturing', progress: 0, message: '正在录制画面...' })
  const frames = await captureCanvasFrames(
    canvas,
    fps,
    duration_seconds,
    (p) => onProgress?.({ step: 'capturing', progress: p * 0.5, message: `录制画面 ${Math.round(p * 100)}%` }),
  )

  if (frames.length === 0) {
    throw new Error('未捕获到任何帧')
  }

  // 2. 编码
  onProgress?.({ step: 'encoding', progress: 0.5, message: '正在编码...' })

  let blob: Blob

  if (format === 'mp4') {
    const [w, h] = RESOLUTION_MAP[resolution] || [1920, 1080]
    blob = await encodeMP4(frames, fps, w, h, (p) =>
      onProgress?.({ step: 'encoding', progress: 0.5 + p * 0.5, message: `编码 MP4 ${Math.round(p * 100)}%` }),
    )
  } else if (format === 'gif') {
    const gifW = GIF_SIZE_MAP[gif_width || '480'] || 480
    blob = await encodeGIF(frames, fps, gifW, (p) =>
      onProgress?.({ step: 'encoding', progress: 0.5 + p * 0.5, message: `编码 GIF ${Math.round(p * 100)}%` }),
    )
  } else {
    throw new Error(`前端不支持导出格式: ${format}`)
  }

  onProgress?.({ step: 'completed', progress: 1, message: '导出完成' })
  logger.info('export', `Export completed: ${format}, size=${blob.size} bytes`)

  return blob
}

/**
 * 深度图导出 — 直接下载深度图 PNG
 */
export function downloadDepthMap(depthMapUrl: string, filename?: string): void {
  const link = document.createElement('a')
  link.href = depthMapUrl
  link.download = filename || 'depth_map.png'
  link.target = '_blank'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

/**
 * 触发浏览器下载 Blob
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  // 延迟释放 URL
  setTimeout(() => URL.revokeObjectURL(url), 5000)
}
