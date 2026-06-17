// ============ WebSocket ============
export type WSMessageType = 'task_progress' | 'task_completed' | 'task_failed' | 'scene_update'

export interface WSMessage {
  type: WSMessageType
  data: TaskProgressData
}

export interface TaskProgressData {
  task_id: string
  progress: number
  step: string
  message: string
  task_type?: string
  result?: DepthResult
  error_message?: string
}

export interface DepthResult {
  image_id: string
  depth_map_id: string
  depth_storage_key: string
  depth_url: string
  model_used: string
  processing_time_ms: number
  mpi_layers?: MPILayer[]
  /** Normal estimation result (Phase 2: Stable Normal) */
  normal_map_url?: string
  normal_method?: string        // "stable_normal" | "sobel_depth" | "none"
}

export interface NormalResult {
  image_id: string
  normal_map_url: string
  normal_method: string         // "stable_normal" | "sobel_depth" | "none"
  confidence: number            // 0-1
  processing_time_ms: number
}

// ============ Upload ============
export interface UploadResponse {
  image_id: string
  user_id: string
  filename: string
  width: number
  height: number
  format: string
  size_bytes: number
  original_url: string
  thumbnail_url: string
  storage_key: string
  status: string
}

export interface DepthEstimateRequest {
  image_id: string
  model?: string
}

export interface DepthEstimateResponse {
  task_id: string
  image_id: string
  status: string
  estimated_time_seconds: number
}

export interface TaskStatusResponse {
  task_id: string
  status: string
  progress: number
  type?: string
  error_message?: string
  result?: DepthResult
  started_at?: string
  completed_at?: string
}

// ============ Processing ============
export type ProcessingStep = 'idle' | 'uploading' | 'estimating' | 'completed' | 'failed'

// ============ Animation ============
export type AnimationType = 'swing' | 'zoom' | 'rotate' | 'parallax' | 'dolly' | 'custom'

export interface AnimationParams {
  type: AnimationType
  duration: number
  amplitude: number
  speed: number
  loop: boolean
}

export const ANIMATION_PRESETS: Record<string, { label: string; desc: string; params: AnimationParams }> = {
  swing: { label: '微风轻拂', desc: '轻微水平视差 + 前景微动', params: { type: 'swing', duration: 3000, amplitude: 0.3, speed: 1.0, loop: true } },
  zoom: { label: '深度呼吸', desc: '缓慢缩放 + 景深变化', params: { type: 'zoom', duration: 4000, amplitude: 0.4, speed: 0.8, loop: true } },
  rotate: { label: '环绕凝视', desc: '缓慢旋转环绕', params: { type: 'rotate', duration: 5000, amplitude: 0.5, speed: 0.6, loop: true } },
  parallax: { label: '平行世界', desc: '水平视差平移', params: { type: 'parallax', duration: 4000, amplitude: 0.6, speed: 1.0, loop: true } },
  dolly: { label: '沉浸穿越', desc: '前进推进 + 景深', params: { type: 'dolly', duration: 3000, amplitude: 0.5, speed: 1.2, loop: true } },
}

// ============ Export ============
export interface ExportOptions {
  format: 'mp4' | 'gif' | 'depth_png'
  resolution: '720p' | '1080p' | '4k'
  fps: 24 | 30 | 60
  duration_seconds: number
  gif_width?: '320' | '480' | '640'
  animation?: {
    type: AnimationType
    amplitude: number
    speed: number
  }
}

export interface ExportRequest {
  scene_id: string
  format: 'mp4' | 'gif' | 'depth_png'
  params: {
    resolution: string
    fps: number
    duration_seconds: number
    gif_width?: string
    animation?: {
      type: string
      amplitude: number
      speed: number
    }
  }
}

export interface ExportResponse {
  task_id: string
  export_id: string
  scene_id: string
  format: string
  status: string
  estimated_time_seconds: number
}

export interface ExportTaskStatus {
  task_id: string
  status: string
  progress: number
  type?: string
  error_message?: string
  download_url?: string
  file_size_bytes?: number
  expires_at?: string
  format?: string
  result?: {
    export_id: string
    download_url: string
    file_size_bytes: number
  }
}

export type ExportStep = 'idle' | 'requesting' | 'recording' | 'encoding' | 'uploading' | 'completed' | 'failed'

// ============ Share ============
export interface ShareSceneData {
  scene_id: string
  image_id: string
  depth_map_id: string
  texture_url: string | null
  depth_map_url: string | null
  render_params: Record<string, any>
  animation_params: Record<string, any>
}

export interface CreateShareRequest {
  scene_id: string
  title?: string
  is_public?: boolean
  allow_download?: boolean
  expires_days?: number | null
  animation?: Record<string, any>
}

export interface ShareResponse {
  share_id: string
  scene_id: string
  user_id: string
  title: string
  is_public: boolean
  allow_download: boolean
  view_count: number
  download_count: number
  expires_at: string | null
  created_at: string
  share_url: string
  embed_code: string
  scene_data: ShareSceneData | null
}

// ============ Style & Quality ============
export type ArtStyle = 'original' | 'anime' | 'oil_painting' | 'watercolor' | 'sketch' | 'cyberpunk' | 'vintage'

export const ART_STYLES: Record<ArtStyle, { label: string; desc: string }> = {
  original: { label: '原画风', desc: '保持原始风格' },
  anime: { label: '动漫', desc: '日系动漫风格' },
  oil_painting: { label: '油画', desc: '经典油画质感' },
  watercolor: { label: '水彩', desc: '柔和水彩渲染' },
  sketch: { label: '素描', desc: '铅笔素描线条' },
  cyberpunk: { label: '赛博朋克', desc: '霓虹科技感' },
  vintage: { label: '复古', desc: '怀旧胶片色调' },
}

export type QualityLevel = 'draft' | 'standard' | 'high' | 'ultra'

export const QUALITY_LEVELS: Record<QualityLevel, { label: string; desc: string; resolution: string }> = {
  draft: { label: '草稿', desc: '快速预览', resolution: '540p' },
  standard: { label: '标准', desc: '平衡速度与质量', resolution: '720p' },
  high: { label: '高清', desc: '高质量输出', resolution: '1080p' },
  ultra: { label: '超清', desc: '最高画质', resolution: '4K' },
}

export interface StyleQualityParams {
  artStyle: ArtStyle
  quality: QualityLevel
}

// ============ Render / 3D Scene ============
export interface RenderRequest {
  image_id: string
  depth_map_id: string
}

export interface RenderResponse {
  scene_id: string
  status: string
  scene_data_url: string
  render_params: {
    fov: number
    parallax_scale: number
    near_plane: number
    far_plane: number
    camera_distance: number
    mesh_subdivision: number
    layer_count?: number
    layer_scales?: number[]
    edge_freeze_strength?: number
    camera_parallax?: boolean
  }
  animation_params: {
    type: string
    amplitude: number
    speed: number
    duration: number
    direction: string
  }
}

// ============ MPI (Multi-Plane Image) Types ============

export interface MPILayer {
  id: string                    // 层唯一标识
  textureUrl: string            // RGBA 纹理 URL (MinIO/S3)
  depthMapUrl?: string          // 该层深度图 URL (可选)
  normalUrl?: string            // 该层法线图 URL (可选, Phase 2)
  zIndex: number                // Z 轴位置 (从远到近递增)
  motionScale: number           // 视差运动倍率
  parallaxDirection: 'horizontal' | 'vertical' | 'both'
  blendMode: 'normal' | 'additive' | 'premultiplied'
  // Level 3: 逐物体
  objectId?: number | null      // 物体 ID (null=BG)
  label?: string                // 物体标签 (如 "人物", "汽车")
}

export interface MPIScene {
  layers: MPILayer[]
  cameraConfig: {
    fov: number
    nearPlane: number
    farPlane: number
    baseDistance: number
  }
  metadata: {
    width: number
    height: number
    layerCount: number
    modelUsed: string
    processingTimeMs: number
  }
}
