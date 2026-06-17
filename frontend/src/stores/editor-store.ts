import { create } from 'zustand'
import type { UploadResponse, DepthResult, ProcessingStep, WSMessage, AnimationParams, TaskStatusResponse, ExportStep, ExportOptions, ShareResponse, RenderResponse, StyleQualityParams, ArtStyle, QualityLevel, MPILayer } from '@/types'
import { ANIMATION_PRESETS } from '@/types'
import { uploadImage, estimateDepth, getTaskStatus, requestExport, getExportTaskStatus, createShare, initScene } from '@/services/api'
import { wsClient } from '@/services/ws'
import { logger } from '@/lib/logger'
import { getCachedResult, setCachedResult } from '@/lib/performance-cache'

// ============ 轮询配置 ============
const POLL_INTERVAL_MS = 2000  // WS 断开时每 2 秒轮询
const POLL_MAX_ATTEMPTS = 150  // 最多轮询 150 次 (5 分钟)

// ============ 状态接口 ============
interface EditorState {
  // 图片
  uploadedImage: UploadResponse | null
  originalPreview: string | null

  // 任务
  taskId: string | null
  step: ProcessingStep
  progress: number        // 0~1
  stepMessage: string
  error: string | null

  // 深度图结果
  depthResult: DepthResult | null
  depthMapUrl: string | null

  // 3D 场景
  sceneId: string | null
  sceneData: RenderResponse | null

  // MPI 层纹理
  mpiLayerUrls: MPILayer[] | null

  // 连接状态
  isWsConnected: boolean
  isPolling: boolean

  // 动画
  animation: AnimationParams
  isPlaying: boolean

  // 画风画质
  styleQuality: StyleQualityParams

  // 导出
  exportStep: ExportStep
  exportProgress: number  // 0~1
  exportMessage: string
  exportTaskId: string | null
  exportDownloadUrl: string | null
  exportError: string | null

  // 分享
  shareData: ShareResponse | null
  shareLoading: boolean
  shareError: string | null

  // Actions
  handleUpload: (file: File) => Promise<void>
  handleWSMessage: (msg: WSMessage) => void
  startPolling: () => void
  stopPolling: () => void
  setAnimation: (params: Partial<AnimationParams>) => void
  applyPreset: (presetId: string) => void
  togglePlay: () => void
  setArtStyle: (style: ArtStyle) => void
  setQuality: (quality: QualityLevel) => void
  exportMedia: (sceneId: string, options: ExportOptions) => Promise<void>
  exportDepthPng: () => void
  resetExport: () => void
  createShareLink: (sceneId: string, title?: string) => Promise<void>
  resetShare: () => void
  reset: () => void
}

// ============ 初始值 ============
const initialAnimation: AnimationParams = ANIMATION_PRESETS.swing.params

const initialState = {
  uploadedImage: null,
  originalPreview: null,
  taskId: null,
  step: 'idle' as ProcessingStep,
  progress: 0,
  stepMessage: '',
  error: null,
  depthResult: null,
  depthMapUrl: null,
  sceneId: null,
  sceneData: null,
  mpiLayerUrls: null,
  isWsConnected: false,
  isPolling: false,
  animation: { ...initialAnimation },
  isPlaying: false,
  styleQuality: { artStyle: 'original', quality: 'high' },
  exportStep: 'idle' as ExportStep,
  exportProgress: 0,
  exportMessage: '',
  exportTaskId: null,
  exportDownloadUrl: null,
  exportError: null,
  shareData: null,
  shareLoading: false,
  shareError: null,
}

// ============ Store ============
export const useEditorStore = create<EditorState>((set, get) => {
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let pollAttempts = 0
  let exportPollTimer: ReturnType<typeof setInterval> | null = null
  let exportPollAttempts = 0

  /** 启动轮询（WS 断开时降级） */
  function startPolling() {
    if (pollTimer) return  // 已在轮询
    const { taskId, step } = get()
    if (!taskId || step === 'completed' || step === 'failed') return

    logger.info('store', `WS disconnected, starting polling for task ${taskId}`)
    set({ isPolling: true })
    pollAttempts = 0

    pollTimer = setInterval(async () => {
      const { taskId, step } = get()
      if (!taskId || step === 'completed' || step === 'failed') {
        stopPolling()
        return
      }

      pollAttempts++
      if (pollAttempts > POLL_MAX_ATTEMPTS) {
        logger.warn('store', 'Polling max attempts reached, stopping')
        stopPolling()
        set({ step: 'failed', error: '任务超时，请重试' })
        return
      }

      try {
        const status: TaskStatusResponse = await getTaskStatus(taskId)
        logger.debug('store', `Poll result: status=${status.status}, progress=${status.progress}`)

        if (status.status === 'completed') {
          // ⚡ Depth Cache: 保存结果到缓存
          const img = get().uploadedImage
          if (img?.image_id && status.result?.depth_url) {
            setCachedResult(img.image_id, status.result.depth_url, status.result.mpi_layers || [], get().sceneData || {})
          }
          set({
            step: 'completed',
            progress: 1,
            stepMessage: '深度图生成完成',
            depthResult: status.result || null,
            depthMapUrl: status.result?.depth_url || '',
            mpiLayerUrls: status.result?.mpi_layers || null,
            isPolling: false,
          })
          stopPolling()
          // 深度估计完成后自动初始化 3D 场景
          _initSceneAfterDepth(status.result)
        } else if (status.status === 'failed') {
          set({
            step: 'failed',
            error: status.error_message || '处理失败',
            isPolling: false,
          })
          stopPolling()
        } else {
          // processing / pending
          const progressValue = Math.min(status.progress / 100, 1)
          set({
            step: 'estimating',
            progress: progressValue,
            stepMessage: `深度估计中... ${Math.round(progressValue * 100)}%`,
          })
        }
      } catch (err: any) {
        logger.error('store', `Poll error: ${err.message}`)
        // 轮询错误不中断，继续尝试
      }
    }, POLL_INTERVAL_MS)
  }

  /** 停止轮询 */
  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    set({ isPolling: false })
    pollAttempts = 0
  }

  /** 深度估计完成后自动初始化 3D 场景 */
  async function _initSceneAfterDepth(depthResult: DepthResult | null | undefined) {
    if (!depthResult?.image_id || !depthResult?.depth_map_id) {
      logger.warn('store', 'Cannot init scene: missing image_id or depth_map_id in depth result')
      return
    }

    try {
      const res = await initScene({
        image_id: depthResult.image_id,
        depth_map_id: depthResult.depth_map_id,
      })
      set({ sceneId: res.scene_id, sceneData: res })
      logger.info('store', `Scene initialized: ${res.scene_id}`)
    } catch (err: any) {
      logger.error('store', `Scene init failed: ${err.message}`)
      // 场景初始化失败不影响 3D 预览 (前端仍可用 imageUrl + depthMapUrl 渲染)
    }
  }

  /** WS 重连后同步任务状态，防止错过断线期间的 completed/failed 消息 */
  async function _syncTaskStatus() {
    const { taskId, step } = get()
    if (!taskId || step === 'completed' || step === 'failed') return

    try {
      logger.info('store', `Syncing task status after WS reconnect: ${taskId}`)
      const status = await getTaskStatus(taskId)
      if (status.status === 'completed') {
        // ⚡ Depth Cache: 保存结果到缓存
        const img = get().uploadedImage
        if (img?.image_id && status.result?.depth_url) {
          setCachedResult(img.image_id, status.result.depth_url, status.result.mpi_layers || [], get().sceneData || {})
        }
        set({
          step: 'completed',
          progress: 1,
          stepMessage: '深度图生成完成',
          depthResult: status.result || null,
          depthMapUrl: status.result?.depth_url || '',
          mpiLayerUrls: status.result?.mpi_layers || null,
        })
        _initSceneAfterDepth(status.result)
        logger.info('store', 'Task already completed (synced via poll)')
      } else if (status.status === 'failed') {
        set({
          step: 'failed',
          error: status.error_message || '处理失败',
        })
        logger.error('store', `Task already failed (synced via poll): ${status.error_message}`)
      } else {
        // 仍在处理中，恢复轮询
        logger.info('store', 'Task still processing after WS sync, resuming polling')
        startPolling()
      }
    } catch (err: any) {
      logger.error('store', `Task sync failed: ${err.message}, resuming polling`)
      startPolling()
    }
  }

  return {
    ...initialState,

    // ---- 上传 + 深度估计主流程 ----
    handleUpload: async (file: File) => {
      stopPolling()
      set({ step: 'uploading', progress: 0, error: null, depthResult: null, depthMapUrl: null, sceneId: null, sceneData: null, mpiLayerUrls: null })

      try {
        // 1. 生成本地预览
        const previewUrl = URL.createObjectURL(file)
        set({ originalPreview: previewUrl })

        // 2. 上传图片
        const uploadRes = await uploadImage(file)
        set({ uploadedImage: uploadRes })
        logger.info('store', `Image uploaded: ${uploadRes.image_id}`)

        // ⚡ Depth Cache: 检查是否已有缓存结果
        const cached = getCachedResult(uploadRes.image_id)
        if (cached) {
          logger.info('store', `Cache hit for ${uploadRes.image_id}, skipping inference`)
          set({
            step: 'completed',
            progress: 100,
            depthMapUrl: cached.depthMapUrl,
            mpiLayerUrls: cached.mpiLayers,
            sceneData: cached.sceneData as any,
          })
          return
        }

        // 3. 建立 WebSocket 连接（WS 断开时降级为轮询）
        let wsConnected = false
        wsClient.connect(
          uploadRes.user_id,
          get().handleWSMessage,
          () => {
            // WS 断开回调 → 启动轮询
            logger.warn('store', 'WS disconnected, falling back to polling')
            set({ isWsConnected: false })
            wsConnected = false
            // 延迟启动轮询，等 taskId 设置后再检查
            setTimeout(() => startPolling(), 500)
          },
          () => {
            // WS 重连回调 → 同步任务状态（防止错过断线期间的消息）
            logger.info('store', 'WS reconnected, syncing task status')
            set({ isWsConnected: true })
            wsConnected = true
            _syncTaskStatus()
          },
        )
        // 不立即设置 isWsConnected: true，等 WS onopen 回调设置
        set({ step: 'estimating', progress: 0, stepMessage: '正在提交深度估计任务...' })

        // 4. 触发深度估计
        const depthRes = await estimateDepth({
          image_id: uploadRes.image_id,
          model: 'depth_anything_v2',
        })
        set({ taskId: depthRes.task_id })
        logger.info('store', `Depth task created: ${depthRes.task_id}`)

        // 5. taskId 设置后，如果 WS 未连接，立即启动轮询
        if (!wsClient.connected) {
          logger.info('store', 'WS not connected after task creation, starting polling')
          startPolling()
        }

      } catch (err: any) {
        const msg = err.message || '上传失败'
        logger.error('store', `Upload failed: ${msg}`)
        set({ step: 'failed', error: msg })
      }
    },

    // ---- WebSocket 消息处理 ----
    handleWSMessage: (msg: WSMessage) => {
      const { data } = msg

      // 收到 WS 消息说明连接正常，停止轮询
      if (get().isPolling) {
        logger.info('store', 'WS reconnected, stopping polling')
        stopPolling()
        set({ isWsConnected: true })
        // WS 重连后立即同步一次任务状态，防止错过断线期间的消息
        _syncTaskStatus()
      }

      if (msg.type === 'task_progress') {
        const progressValue = Math.min(data.progress / 100, 1)
        set({
          step: 'estimating',
          progress: progressValue,
          stepMessage: data.message || `深度估计中... ${Math.round(progressValue * 100)}%`,
        })
      } else if (msg.type === 'task_completed') {
        // ⚡ Depth Cache: 保存结果到缓存
        const img = get().uploadedImage
        if (img?.image_id && data.result?.depth_url) {
          setCachedResult(img.image_id, data.result.depth_url, data.result.mpi_layers || [], get().sceneData || {})
        }
        set({
          step: 'completed',
          progress: 1,
          stepMessage: '深度图生成完成',
          depthResult: data.result || null,
          depthMapUrl: data.result?.depth_url || '',
          mpiLayerUrls: data.result?.mpi_layers || null,
          isWsConnected: true,
        })
        stopPolling()
        logger.info('store', 'Depth estimation completed via WebSocket')
        // 深度估计完成后自动初始化 3D 场景
        _initSceneAfterDepth(data.result)
      } else if (msg.type === 'task_failed') {
        set({
          step: 'failed',
          error: data.error_message || '处理失败',
        })
        stopPolling()
        logger.error('store', `Depth estimation failed: ${data.error_message}`)
      }
    },

    // ---- 轮询控制 ----
    startPolling,
    stopPolling,

    // ---- 动画控制 ----
    setAnimation: (params) => set((s) => ({ animation: { ...s.animation, ...params } })),
    applyPreset: (presetId) => {
      const preset = ANIMATION_PRESETS[presetId]
      if (preset) set({ animation: { ...preset.params } })
    },
    togglePlay: () => set((s) => ({ isPlaying: !s.isPlaying })),
    setArtStyle: (style: ArtStyle) => set((s) => ({ styleQuality: { ...s.styleQuality, artStyle: style } })),
    setQuality: (quality: QualityLevel) => set((s) => ({ styleQuality: { ...s.styleQuality, quality } })),

    // ---- 导出 (路线 B: 后端) ----
    exportMedia: async (sceneId: string, options: ExportOptions) => {
      // 停止之前的导出轮询
      if (exportPollTimer) {
        clearInterval(exportPollTimer)
        exportPollTimer = null
      }

      set({
        exportStep: 'requesting',
        exportProgress: 0,
        exportMessage: '正在提交导出任务...',
        exportTaskId: null,
        exportDownloadUrl: null,
        exportError: null,
      })

      try {
        // 1. 请求后端导出
        const res = await requestExport({
          scene_id: sceneId,
          format: options.format,
          params: {
            resolution: options.resolution,
            fps: options.fps,
            duration_seconds: options.duration_seconds,
            gif_width: options.gif_width,
            animation: options.animation ? {
              type: options.animation.type,
              amplitude: options.animation.amplitude,
              speed: options.animation.speed,
            } : undefined,
          },
        })

        set({
          exportTaskId: res.task_id,
          exportStep: 'recording',
          exportMessage: '导出任务已提交，等待处理...',
        })

        logger.info('store', `Export task created: ${res.task_id}`)

        // 2. 轮询导出任务状态
        exportPollAttempts = 0
        exportPollTimer = setInterval(async () => {
          const { exportTaskId, exportStep } = get()
          if (!exportTaskId || exportStep === 'completed' || exportStep === 'failed') {
            if (exportPollTimer) {
              clearInterval(exportPollTimer)
              exportPollTimer = null
            }
            return
          }

          exportPollAttempts++
          if (exportPollAttempts > 150) {
            if (exportPollTimer) {
              clearInterval(exportPollTimer)
              exportPollTimer = null
            }
            set({ exportStep: 'failed', exportError: '导出超时，请重试' })
            return
          }

          try {
            const status = await getExportTaskStatus(exportTaskId)

            if (status.status === 'completed') {
              const downloadUrl = status.download_url || status.result?.download_url
              set({
                exportStep: 'completed',
                exportProgress: 1,
                exportMessage: '导出完成',
                exportDownloadUrl: downloadUrl || null,
              })
              if (exportPollTimer) {
                clearInterval(exportPollTimer)
                exportPollTimer = null
              }
              logger.info('store', 'Export completed')
            } else if (status.status === 'failed') {
              set({
                exportStep: 'failed',
                exportError: status.error_message || '导出失败',
              })
              if (exportPollTimer) {
                clearInterval(exportPollTimer)
                exportPollTimer = null
              }
              logger.error('store', `Export failed: ${status.error_message}`)
            } else {
              // processing / pending
              const progressValue = Math.min(status.progress / 100, 1)
              const stepLabel = status.progress < 20 ? '准备渲染环境' :
                status.progress < 40 ? '加载场景数据' :
                status.progress < 70 ? '帧捕获中' :
                status.progress < 90 ? '编码视频' :
                '上传至存储'
              set({
                exportStep: progressValue < 0.9 ? 'recording' : 'uploading',
                exportProgress: progressValue,
                exportMessage: `${stepLabel} ${Math.round(progressValue * 100)}%`,
              })
            }
          } catch (err: any) {
            logger.error('store', `Export poll error: ${err.message}`)
          }
        }, 2000)

      } catch (err: any) {
        const msg = err.message || '导出请求失败'
        logger.error('store', `Export request failed: ${msg}`)
        set({ exportStep: 'failed', exportError: msg })
      }
    },

    // ---- 深度图导出 ----
    exportDepthPng: () => {
      const { depthMapUrl } = get()
      if (!depthMapUrl) return
      const link = document.createElement('a')
      link.href = depthMapUrl
      link.download = 'depth_map.png'
      link.target = '_blank'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
    },

    // ---- 重置导出状态 ----
    resetExport: () => {
      if (exportPollTimer) {
        clearInterval(exportPollTimer)
        exportPollTimer = null
      }
      set({
        exportStep: 'idle',
        exportProgress: 0,
        exportMessage: '',
        exportTaskId: null,
        exportDownloadUrl: null,
        exportError: null,
      })
    },

    // ---- 创建分享链接 ----
    createShareLink: async (sceneId: string, title?: string) => {
      set({ shareLoading: true, shareError: null, shareData: null })

      try {
        const res = await createShare({
          scene_id: sceneId,
          title: title || '我的 3D 照片',
          is_public: true,
          allow_download: true,
          animation: {
            type: get().animation.type,
            amplitude: get().animation.amplitude,
            speed: get().animation.speed,
          },
        })

        set({ shareData: res, shareLoading: false })
        logger.info('store', `Share link created: ${res.share_id}`)
      } catch (err: any) {
        const msg = err.message || '创建分享失败'
        logger.error('store', `Share creation failed: ${msg}`)
        set({ shareError: msg, shareLoading: false })
      }
    },

    // ---- 重置分享状态 ----
    resetShare: () => {
      set({ shareData: null, shareLoading: false, shareError: null })
    },

    // ---- 重置 ----
    reset: () => {
      stopPolling()
      if (exportPollTimer) {
        clearInterval(exportPollTimer)
        exportPollTimer = null
      }
      wsClient.disconnect()
      set({ ...initialState, animation: { ...initialAnimation } })
    },
  }
})
