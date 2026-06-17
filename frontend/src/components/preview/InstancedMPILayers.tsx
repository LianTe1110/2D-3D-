/** Level 3 性能优化: GPU Instancing — InstancedMesh 减少 draw calls
 *
 * 将 N 层 MPI 渲染合并为 1 次 draw call:
 *   1. 纹理图集 (Texture Atlas): 所有层纹理合并为一张大纹理
 *   2. 共享几何体: 所有层共用一个 PlaneGeometry
 *   3. Per-instance attributes: 每个实例有独立的 UV offset、motionScale、zIndex
 *
 * 效果: 3-5 层 MPI → 从 3-5 draw calls 降至 1 draw call
 */

import { useRef, useMemo, useEffect } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { useEditorStore } from '@/stores/editor-store'
import { CameraPathEngine, PRESET_PATHS } from '@/lib/camera-path-engine'
import { getOrLoadTexture } from '@/lib/performance-cache'
import type { MPILayer } from '@/types'

// ============ Instanced MPI Shader ============

const INSTANCED_VERTEX = /* glsl */ `
  attribute vec3 instancePosition;
  attribute float instanceMotionScale;
  attribute float instanceZPosition;
  attribute vec4 instanceUVRect;  // [uOffset, vOffset, uScale, vScale]

  varying vec2 vUv;
  varying float vMotionScale;
  varying float vZPosition;
  varying vec4 vUVRect;

  void main() {
    vUv = uv;
    vMotionScale = instanceMotionScale;
    vZPosition = instanceZPosition;
    vUVRect = instanceUVRect;

    vec3 pos = position + instancePosition;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
  }
`

const INSTANCED_FRAGMENT = /* glsl */ `
  uniform sampler2D uAtlasTexture;
  uniform vec2 uCameraOffset;
  uniform int uArtStyle;
  uniform vec2 uTexelSize;
  uniform float uEdgeFreezeStrength;
  uniform int uInstanceCount;

  varying vec2 vUv;
  varying float vMotionScale;
  varying float vZPosition;
  varying vec4 vUVRect;

  vec3 applyArtStyle(vec3 color, vec2 uv, int style) {
    if (style == 1) {
      float levels = 6.0;
      return floor(color * levels + 0.5) / levels;
    }
    return color;
  }

  vec2 clampMirrorUV(vec2 uv) {
    return vec2(
      abs(fract(uv.x * 0.5 + 0.5) * 2.0 - 1.0),
      abs(fract(uv.y * 0.5 + 0.5) * 2.0 - 1.0)
    );
  }

  void main() {
    vec2 atlasUV = vUVRect.xy + vUv * vUVRect.zw;

    // Level 3: Z-position driven parallax (FG moves more, BG moves less)
    float zFactor = vZPosition * 0.5 + 0.5;
    vec2 offset = uCameraOffset * vMotionScale * 0.06 * zFactor;

    vec2 sampleUv = atlasUV + offset;
    sampleUv = clampMirrorUV(sampleUv);

    vec4 color = texture2D(uAtlasTexture, sampleUv);

    // Border feather: 防止边缘黑边
    float borderDist = min(
      min(sampleUv.x, 1.0 - sampleUv.x),
      min(sampleUv.y, 1.0 - sampleUv.y)
    );
    float borderFeather = smoothstep(0.0, 0.02, borderDist);
    color.a *= borderFeather;

    if (color.a < 0.005) discard;

    color.rgb = applyArtStyle(color.rgb, atlasUV, uArtStyle);

    gl_FragColor = vec4(color.rgb * color.a, color.a);
  }
`

// ============ Texture Atlas Builder ============

function buildTextureAtlas(
  layers: MPILayer[],
  onReady: (atlas: THREE.Texture) => void,
): void {
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')!
  const count = layers.length

  // 水平排列: 每层宽度 = canvas.width / count
  const maxW = 1024
  const maxH = 1024
  canvas.width = maxW
  canvas.height = maxH

  let loaded = 0
  const imgs: HTMLImageElement[] = []

  layers.forEach((layer, i) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => {
      imgs[i] = img
      loaded++
      if (loaded === count) {
        // 计算每层在图集中的区域
        const sliceW = maxW / count
        ctx.clearRect(0, 0, canvas.width, canvas.height)
        imgs.forEach((src, idx) => {
          const sx = idx * sliceW
          const sw = sliceW
          const sh = (src.height / src.width) * sw
          const sy = (maxH - sh) / 2
          ctx.drawImage(src, sx, sy, sw, sh)
        })

        const atlas = new THREE.CanvasTexture(canvas)
        atlas.colorSpace = THREE.NoColorSpace
        atlas.minFilter = THREE.LinearFilter
        atlas.magFilter = THREE.LinearFilter
        atlas.wrapS = THREE.ClampToEdgeWrapping
        atlas.wrapT = THREE.ClampToEdgeWrapping
        atlas.needsUpdate = true
        onReady(atlas)
      }
    }
    img.onerror = () => {
      loaded++
    }
    img.src = layer.textureUrl
  })
}

// ============ Instanced MPI Layers ============

interface InstancedMPILayersProps {
  layers: MPILayer[]
}

export function InstancedMPILayers({ layers }: InstancedMPILayersProps) {
  const meshRef = useRef<THREE.InstancedMesh>(null)
  const cameraOffsetRef = useRef(new THREE.Vector2(0, 0))
  const pathEngineRef = useRef<CameraPathEngine | null>(null)
  const atlasTextureRef = useRef<THREE.Texture | null>(null)
  const { uploadedImage, styleQuality, animation, isPlaying } = useEditorStore()
  const { camera: threeCamera } = useThree()

  const count = layers.length

  // 初始化 CameraPathEngine
  useEffect(() => {
    if (threeCamera && !pathEngineRef.current) {
      pathEngineRef.current = new CameraPathEngine(threeCamera as THREE.PerspectiveCamera)
    }
  }, [threeCamera])

  useEffect(() => {
    if (!pathEngineRef.current) return
    const pathMap: Record<string, string> = {
      swing: 'cinematic_pan',
      parallax: 'gentle_orbit',
      dolly: 'push_in',
      zoom: 'push_in',
      rotate: 'gentle_orbit',
    }
    const pathId = pathMap[animation.type]
    if (pathId && isPlaying) {
      pathEngineRef.current.play(pathId)
    } else {
      pathEngineRef.current.stop()
    }
  }, [animation.type, isPlaying])

  // 共享几何体
  const geometry = useMemo(() => {
    const imgW = uploadedImage?.width || 4
    const imgH = uploadedImage?.height || 3
    const aspect = imgW / imgH
    return new THREE.PlaneGeometry(2.0 * aspect, 2.0, 64, 64)
  }, [uploadedImage])

  // 构建纹理图集
  useEffect(() => {
    buildTextureAtlas(layers, (atlas) => {
      atlasTextureRef.current = atlas
      if (meshRef.current) {
        const mat = meshRef.current.material as THREE.ShaderMaterial
        mat.uniforms.uAtlasTexture.value = atlas
      }
    })
  }, [layers])

  // Shader 材质
  const material = useMemo(() => {
    return new THREE.ShaderMaterial({
      uniforms: {
        uAtlasTexture: { value: null },
        uCameraOffset: { value: new THREE.Vector2(0, 0) },
        uArtStyle: { value: 0 },
        uTexelSize: { value: new THREE.Vector2(1 / 1024, 1 / 1024) },
        uEdgeFreezeStrength: { value: 0.8 },
        uInstanceCount: { value: count },
      },
      vertexShader: INSTANCED_VERTEX,
      fragmentShader: INSTANCED_FRAGMENT,
      transparent: true,
      depthTest: true,
      depthWrite: true,
      blending: THREE.CustomBlending,
      blendSrc: THREE.OneFactor,
      blendDst: THREE.OneMinusSrcAlphaFactor,
      toneMapped: false,
    })
  }, [count])

  // 设置每实例属性
  useEffect(() => {
    if (!meshRef.current) return

    const mesh = meshRef.current
    const dummy = new THREE.Object3D()

    for (let i = 0; i < count; i++) {
      const layer = layers[i]
      // Level 3: 扩大 z 间距
      const zPos = layer.zIndex ?? (i === 0 ? -2.5 : i === count - 1 ? 2.0 : 0.0)

      dummy.position.set(0, 0, zPos)
      dummy.scale.set(1, 1, 1)
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)

      // Per-instance attributes
      const geo = mesh.geometry
      // motionScale
      const motionScaleAttr = geo.getAttribute('instanceMotionScale') as THREE.InstancedBufferAttribute
      const motionScale = layer.motionScale ?? (i === 0 ? 0.2 : i === count - 1 ? 1.5 : 0.7)
      if (motionScaleAttr) {
        for (let j = 0; j < motionScaleAttr.count; j++) {
          motionScaleAttr.setX(j, motionScale)
        }
      }

      // zPosition
      const zPosAttr = geo.getAttribute('instanceZPosition') as THREE.InstancedBufferAttribute
      if (zPosAttr) {
        for (let j = 0; j < zPosAttr.count; j++) {
          zPosAttr.setX(j, zPos)
        }
      }

      // UV rect
      const uvRectAttr = geo.getAttribute('instanceUVRect') as THREE.InstancedBufferAttribute
      if (uvRectAttr) {
        const sliceW = 1.0 / count
        for (let j = 0; j < uvRectAttr.count; j++) {
          uvRectAttr.setXYZW(j, i * sliceW, 0.0, sliceW, 1.0)
        }
      }
    }

    mesh.instanceMatrix.needsUpdate = true
  }, [layers, count])

  // 动画驱动
  useFrame((state) => {
    if (!meshRef.current) return

    if (pathEngineRef.current && isPlaying) {
      pathEngineRef.current.update()
      const cam = threeCamera as THREE.PerspectiveCamera
      cameraOffsetRef.current.set(cam.position.x * 0.5, cam.position.y * 0.5)
    } else if (animation.type !== 'none' && isPlaying) {
      const t = state.clock.elapsedTime * animation.speed
      if (animation.type === 'swing') {
        cameraOffsetRef.current.set(
          Math.sin(t) * animation.amplitude * 0.15,
          Math.cos(t * 0.7) * animation.amplitude * 0.05
        )
      }
    }

    const mat = meshRef.current.material as THREE.ShaderMaterial
    mat.uniforms.uCameraOffset.value.copy(cameraOffsetRef.current)
  })

  const artStyleMap: Record<string, number> = {
    original: 0, anime: 1, oil_painting: 2, watercolor: 3,
    sketch: 4, cyberpunk: 5, vintage: 6,
  }

  useEffect(() => {
    if (meshRef.current) {
      const mat = meshRef.current.material as THREE.ShaderMaterial
      mat.uniforms.uArtStyle.value = artStyleMap[styleQuality.artStyle] ?? 0
    }
  }, [styleQuality.artStyle])

  return (
    <instancedMesh
      ref={meshRef}
      args={[geometry, material, count]}
      frustumCulled={false}
    />
  )
}