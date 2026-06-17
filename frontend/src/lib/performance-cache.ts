/** Level 3 性能优化: Depth Cache + Layer Bake
 *
 * ⚡ Depth Cache: 避免重复推理
 * ⚡ Layer Bake: 预生成 layer textures → 减少 GPU 实时计算
 * ⚡ Texture Pool: 复用 Three.js Texture 对象, 减少 GPU 内存分配
 */

import * as THREE from 'three'
import type { MPILayer } from '@/types'

// ============ Depth Cache ============

interface CacheEntry {
  depthMapUrl: string
  mpiLayers: MPILayer[]
  timestamp: number
  sceneData: Record<string, unknown>
}

const depthCache = new Map<string, CacheEntry>()
const CACHE_TTL = 30 * 60 * 1000 // 30 minutes

export function getCachedResult(imageId: string): CacheEntry | null {
  const entry = depthCache.get(imageId)
  if (!entry) return null

  // TTL check
  if (Date.now() - entry.timestamp > CACHE_TTL) {
    depthCache.delete(imageId)
    return null
  }

  return entry
}

export function setCachedResult(
  imageId: string,
  depthMapUrl: string,
  mpiLayers: MPILayer[],
  sceneData: Record<string, unknown>,
): void {
  depthCache.set(imageId, {
    depthMapUrl,
    mpiLayers,
    timestamp: Date.now(),
    sceneData,
  })

  // Evict oldest entries if cache is too large
  if (depthCache.size > 50) {
    const oldest = Array.from(depthCache.entries())
      .sort((a, b) => a[1].timestamp - b[1].timestamp)[0]
    if (oldest) depthCache.delete(oldest[0])
  }
}

export function invalidateCache(imageId: string): void {
  depthCache.delete(imageId)
}

// ============ Texture Pool ============

const texturePool = new Map<string, THREE.Texture>()

export function getOrLoadTexture(url: string): THREE.Texture {
  const existing = texturePool.get(url)
  if (existing) return existing

  const tex = new THREE.TextureLoader().load(url, () => {
    tex.needsUpdate = true
  })
  tex.colorSpace = THREE.NoColorSpace
  tex.minFilter = THREE.LinearFilter
  tex.magFilter = THREE.LinearFilter
  tex.anisotropy = 16
  tex.wrapS = THREE.ClampToEdgeWrapping
  tex.wrapT = THREE.ClampToEdgeWrapping

  texturePool.set(url, tex)
  return tex
}

export function releaseTexture(url: string): void {
  const tex = texturePool.get(url)
  if (tex) {
    tex.dispose()
    texturePool.delete(url)
  }
}

export function releaseAllTextures(): void {
  for (const tex of texturePool.values()) {
    tex.dispose()
  }
  texturePool.clear()
}

// ============ Layer Bake ============

export interface BakedLayer {
  texture: THREE.Texture
  softMaskTexture: THREE.Texture
  depthTexture: THREE.DataTexture | null
  zIndex: number
  motionScale: number
}

/**
 * 预烘焙 MPI 层: 将所有纹理预加载到 GPU
 * 减少 first-frame latency
 */
export function bakeLayers(layers: MPILayer[]): BakedLayer[] {
  return layers.map((layer) => {
    const texture = getOrLoadTexture(layer.textureUrl)
    const softMaskTexture = layer.normalUrl
      ? getOrLoadTexture(layer.normalUrl)
      : texture

    return {
      texture,
      softMaskTexture,
      depthTexture: null,
      zIndex: layer.zIndex,
      motionScale: layer.motionScale,
    }
  })
}

/**
 * 释放烘焙层资源
 */
export function disposeBakedLayers(baked: BakedLayer[]): void {
  for (const layer of baked) {
    // Don't dispose pooled textures here, use releaseAllTextures()
    if (layer.depthTexture) {
      layer.depthTexture.dispose()
    }
  }
}
