import type { UploadResponse, DepthEstimateRequest, DepthEstimateResponse, TaskStatusResponse, ExportRequest, ExportResponse, ExportTaskStatus, CreateShareRequest, ShareResponse, RenderRequest, RenderResponse } from '@/types'
import { logger } from '@/lib/logger'

const API_BASE = '/api/v1'

export async function uploadImage(file: File): Promise<UploadResponse> {
  logger.info('api', `Uploading ${file.name} (${(file.size / 1024).toFixed(0)}KB)`)
  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch(`${API_BASE}/upload`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
    const msg = err.detail?.message || err.detail || 'Upload failed'
    logger.error('api', `Upload failed: ${msg}`, err)
    throw new Error(msg)
  }

  const data = await res.json()
  logger.info('api', `Upload success: ${data.image_id}`)
  return data
}

export async function estimateDepth(req: DepthEstimateRequest): Promise<DepthEstimateResponse> {
  logger.info('api', `Estimating depth for ${req.image_id}`)
  const res = await fetch(`${API_BASE}/depth/estimate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Depth estimation failed' }))
    const msg = err.detail?.message || err.detail || 'Depth estimation failed'
    logger.error('api', `Depth estimate failed: ${msg}`, err)
    throw new Error(msg)
  }

  const data = await res.json()
  logger.info('api', `Depth task created: ${data.task_id}`)
  return data
}

export async function getTaskStatus(taskId: string): Promise<TaskStatusResponse> {
  const res = await fetch(`${API_BASE}/depth/task/${taskId}`)

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Task status query failed' }))
    logger.error('api', `Task status query failed: ${taskId}`, err)
    throw new Error(err.detail || 'Task status query failed')
  }

  return res.json()
}

// ============ Export API ============

export async function requestExport(req: ExportRequest): Promise<ExportResponse> {
  logger.info('api', `Requesting export: format=${req.format}, scene_id=${req.scene_id}`)
  const res = await fetch(`${API_BASE}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Export request failed' }))
    const msg = err.detail?.message || err.detail || 'Export request failed'
    logger.error('api', `Export request failed: ${msg}`, err)
    throw new Error(msg)
  }

  const data = await res.json()
  logger.info('api', `Export task created: ${data.task_id}`)
  return data
}

export async function getExportTaskStatus(taskId: string): Promise<ExportTaskStatus> {
  const res = await fetch(`${API_BASE}/export/task/${taskId}`)

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Export task status query failed' }))
    logger.error('api', `Export task status query failed: ${taskId}`, err)
    throw new Error(err.detail || 'Export task status query failed')
  }

  return res.json()
}

// ============ Share API ============

export async function createShare(req: CreateShareRequest): Promise<ShareResponse> {
  logger.info('api', `Creating share: scene_id=${req.scene_id}`)
  const res = await fetch(`${API_BASE}/share`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Share creation failed' }))
    const msg = err.detail?.message || err.detail || 'Share creation failed'
    logger.error('api', `Share creation failed: ${msg}`, err)
    throw new Error(msg)
  }

  const data = await res.json()
  logger.info('api', `Share created: ${data.share_id}`)
  return data
}

export async function getShare(shareId: string): Promise<ShareResponse> {
  const res = await fetch(`${API_BASE}/share/${shareId}`)

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Share not found' }))
    logger.error('api', `Share not found: ${shareId}`, err)
    throw new Error(err.detail || 'Share not found')
  }

  return res.json()
}

// ============ Render / 3D Scene API ============

export async function initScene(req: RenderRequest): Promise<RenderResponse> {
  logger.info('api', `Initializing 3D scene: image_id=${req.image_id}, depth_map_id=${req.depth_map_id}`)
  const res = await fetch(`${API_BASE}/render/3d`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Scene initialization failed' }))
    const msg = err.detail?.message || err.detail || 'Scene initialization failed'
    logger.error('api', `Scene init failed: ${msg}`, err)
    throw new Error(msg)
  }

  const data = await res.json()
  logger.info('api', `Scene initialized: ${data.scene_id}`)
  return data
}
