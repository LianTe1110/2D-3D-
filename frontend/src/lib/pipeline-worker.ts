/** Level 3 性能优化: WebWorker Pipeline
 *
 * 将重计算任务从主线程移到 WebWorker, 保持 UI 60fps 渲染:
 *
 *   Main Thread (UI + WebGL)    WebWorker (计算)
 *   ─────────────────────       ──────────────
 *   uploadImage()               depthPreprocess()
 *   startRendering()            buildTextureAtlas()
 *   useFrame() 60fps            bakeLayersOffline()
 *   interact()                  computeParallaxMask()
 *
 * 通信协议: postMessage + MessageChannel
 */

// ============ Worker 消息类型 ============

export type WorkerMessageType =
  | 'depth_preprocess'
  | 'texture_atlas'
  | 'layer_bake'
  | 'parallax_mask'

export interface WorkerRequest {
  id: string
  type: WorkerMessageType
  payload: unknown
}

export interface WorkerResponse {
  id: string
  type: WorkerMessageType
  result: unknown
  error?: string
}

// ============ Worker 客户端 ============

type ResolveFn = (value: WorkerResponse) => void

class PipelineWorker {
  private worker: Worker | null = null
  private pending = new Map<string, ResolveFn>()
  private _ready = false

  async init(): Promise<void> {
    if (this._ready) return

    // 创建 Worker (使用 Blob URL 内联 worker 代码)
    const workerCode = `
      // ============ WebWorker: AI Pipeline ============

      self.onmessage = async (e: MessageEvent) => {
        const { id, type, payload } = e.data

        try {
          let result: unknown

          switch (type) {
            case 'depth_preprocess':
              result = await depthPreprocess(payload as PreprocessInput)
              break
            case 'texture_atlas':
              result = await buildTextureAtlas(payload as AtlasInput)
              break
            case 'layer_bake':
              result = await bakeLayers(payload as BakeInput)
              break
            case 'parallax_mask':
              result = await computeParallaxMask(payload as ParallaxInput)
              break
            default:
              throw new Error('Unknown type: ' + type)
          }

          self.postMessage({ id, type, result })
        } catch (err: any) {
          self.postMessage({ id, type, error: err.message })
        }
      }

      // ============ 深度预处理 ============

      interface PreprocessInput {
        depthUrl: string
        width: number
        height: number
      }

      async function depthPreprocess(input: PreprocessInput) {
        const img = await createImageBitmap(
          await fetch(input.depthUrl).then(r => r.blob())
        )

        const canvas = new OffscreenCanvas(input.width, input.height)
        const ctx = canvas.getContext('2d')!
        ctx.drawImage(img, 0, 0, input.width, input.height)

        const imageData = ctx.getImageData(0, 0, input.width, input.height)
        const depthData = new Float32Array(input.width * input.height)
        for (let i = 0; i < depthData.length; i++) {
          depthData[i] = imageData.data[i * 4] / 255.0
        }

        return {
          width: input.width,
          height: input.height,
          depthData: depthData.buffer,
        }
      }

      // ============ 纹理图集构建 ============

      interface AtlasInput {
        urls: string[]
        atlasWidth: number
        atlasHeight: number
      }

      async function buildTextureAtlas(input: AtlasInput) {
        const count = input.urls.length
        const sliceW = input.atlasWidth / count

        const canvas = new OffscreenCanvas(input.atlasWidth, input.atlasHeight)
        const ctx = canvas.getContext('2d')!

        const images = await Promise.all(
          input.urls.map(url =>
            fetch(url)
              .then(r => r.blob())
              .then(blob => createImageBitmap(blob))
          )
        )

        images.forEach((img, i) => {
          const sx = i * sliceW
          const sw = sliceW
          const sh = (img.height / img.width) * sw
          const sy = (input.atlasHeight - sh) / 2
          ctx.drawImage(img, sx, sy, sw, sh)
        })

        const blob = await canvas.convertToBlob({ type: 'image/png' })
        return {
          blob,
          regions: images.map((_, i) => ({
            uOffset: (i * sliceW) / input.atlasWidth,
            vOffset: 0,
            uScale: sliceW / input.atlasWidth,
            vScale: 1.0,
          })),
        }
      }

      // ============ 层烘焙 ============

      interface BakeInput {
        layerUrls: string[]
        depthMapUrl: string
        width: number
        height: number
      }

      async function bakeLayers(input: BakeInput) {
        const layers = await Promise.all(
          input.layerUrls.map(async (url) => {
            const blob = await fetch(url).then(r => r.blob())
            const img = await createImageBitmap(blob)
            return { width: img.width, height: img.height, bitmap: img }
          })
        )

        return {
          count: layers.length,
          sizes: layers.map(l => ({ width: l.width, height: l.height })),
        }
      }

      // ============ 视差掩码计算 ============

      interface ParallaxInput {
        cameraX: number
        cameraY: number
        motionScale: number
        width: number
        height: number
      }

      async function computeParallaxMask(input: ParallaxInput) {
        const offsetX = input.cameraX * input.motionScale * 0.05
        const offsetY = input.cameraY * input.motionScale * 0.05

        return {
          offsetX,
          offsetY,
          needsUpdate: Math.abs(offsetX) > 0.001 || Math.abs(offsetY) > 0.001,
        }
      }

      self.postMessage({ type: 'ready' })
    `

    const blob = new Blob([workerCode], { type: 'application/javascript' })
    const url = URL.createObjectURL(blob)
    this.worker = new Worker(url, { type: 'module' })

    this.worker.onmessage = (e: MessageEvent) => {
      if (e.data.type === 'ready') {
        this._ready = true
        return
      }

      const { id, result, error } = e.data as WorkerResponse
      const resolve = this.pending.get(id)
      if (resolve) {
        this.pending.delete(id)
        resolve({ id, type: e.data.type, result, error })
      }
    }

    this.worker.onerror = (err) => {
      console.error('[PipelineWorker] Error:', err)
    }

    // Wait for ready signal
    await new Promise<void>((resolve) => {
      const check = () => {
        if (this._ready) resolve()
        else setTimeout(check, 10)
      }
      check()
    })
  }

  send(type: WorkerMessageType, payload: unknown): Promise<WorkerResponse> {
    return new Promise((resolve, reject) => {
      if (!this.worker) {
        reject(new Error('Worker not initialized'))
        return
      }

      const id = crypto.randomUUID()
      this.pending.set(id, resolve)

      this.worker.postMessage({ id, type, payload })
    })
  }

  terminate(): void {
    this.worker?.terminate()
    this.worker = null
    this._ready = false
    this.pending.clear()
  }
}

// ============ 单例 ============

let _instance: PipelineWorker | null = null

export function getPipelineWorker(): PipelineWorker {
  if (!_instance) {
    _instance = new PipelineWorker()
  }
  return _instance
}

export async function initPipelineWorker(): Promise<PipelineWorker> {
  const worker = getPipelineWorker()
  await worker.init()
  return worker
}

export function terminatePipelineWorker(): void {
  _instance?.terminate()
  _instance = null
}