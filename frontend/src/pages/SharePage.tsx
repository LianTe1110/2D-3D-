import { useEffect, useRef, useState, useMemo, Suspense } from 'react'
import { useParams } from 'react-router-dom'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, PerspectiveCamera } from '@react-three/drei'
import * as THREE from 'three'
import { getShare } from '@/services/api'
import type { ShareResponse, ShareSceneData } from '@/types'
import { Loader2, Eye, Download, AlertCircle, ExternalLink } from 'lucide-react'

// ============ 视差位移着色器 (与 Scene3D 相同) ============

const VERTEX_SHADER = /* glsl */ `
  uniform sampler2D uDepthTexture;
  uniform float disparityScale;
  uniform float uTime;
  uniform int uAnimType;
  uniform float uAmplitude;
  uniform float uSpeed;

  varying vec2 vUv;
  varying float vDepthValue;

  void main() {
    vUv = uv;
    float depthValue = texture2D(uDepthTexture, uv).r;
    vDepthValue = depthValue;

    vec3 transformed = position;
    transformed.z += (depthValue * disparityScale);

    float t = uTime * uSpeed;
    if (uAnimType == 1) {
      transformed.x += sin(t) * uAmplitude * depthValue * 0.15;
      transformed.z += cos(t * 0.7) * uAmplitude * depthValue * 0.05;
    } else if (uAnimType == 2) {
      float scale = 1.0 + sin(t * 0.5) * uAmplitude * 0.08;
      transformed.xy *= scale;
      transformed.z += sin(t * 0.3) * uAmplitude * depthValue * 0.1;
    } else if (uAnimType == 3) {
      float angle = sin(t * 0.4) * uAmplitude * 0.15;
      float c = cos(angle);
      float s = sin(angle);
      transformed.xz = mat2(c, -s, s, c) * transformed.xz;
    } else if (uAnimType == 4) {
      transformed.x += sin(t * 0.6) * uAmplitude * depthValue * 0.2;
    } else if (uAnimType == 5) {
      transformed.z += sin(t * 0.5) * uAmplitude * depthValue * 0.15;
    }

    gl_Position = projectionMatrix * modelViewMatrix * vec4(transformed, 1.0);
  }
`

const FRAGMENT_SHADER = /* glsl */ `
  uniform sampler2D uTexture;
  uniform sampler2D uDepthTexture;
  uniform vec2 uTexelSize;
  uniform float uEdgeThreshold;

  varying vec2 vUv;
  varying float vDepthValue;

  float computeDepthGradient(vec2 uv) {
    float d00 = texture2D(uDepthTexture, uv + vec2(-uTexelSize.x, -uTexelSize.y)).r;
    float d10 = texture2D(uDepthTexture, uv + vec2( 0.0,          -uTexelSize.y)).r;
    float d20 = texture2D(uDepthTexture, uv + vec2( uTexelSize.x, -uTexelSize.y)).r;
    float d01 = texture2D(uDepthTexture, uv + vec2(-uTexelSize.x,  0.0)).r;
    float d21 = texture2D(uDepthTexture, uv + vec2( uTexelSize.x,  0.0)).r;
    float d02 = texture2D(uDepthTexture, uv + vec2(-uTexelSize.x,  uTexelSize.y)).r;
    float d12 = texture2D(uDepthTexture, uv + vec2( 0.0,           uTexelSize.y)).r;
    float d22 = texture2D(uDepthTexture, uv + vec2( uTexelSize.x,  uTexelSize.y)).r;
    float gx = -d00 - 2.0*d01 - d02 + d20 + 2.0*d21 + d22;
    float gy = -d00 - 2.0*d10 - d20 + d02 + 2.0*d12 + d22;
    return sqrt(gx * gx + gy * gy);
  }

  vec4 edgeExtendSample(vec2 uv, float edgeStrength) {
    vec4 center = texture2D(uTexture, uv);
    float offset = uTexelSize.x * edgeStrength * 3.0;
    vec4 sUp    = texture2D(uTexture, uv + vec2( 0.0,        offset));
    vec4 sDown  = texture2D(uTexture, uv + vec2( 0.0,       -offset));
    vec4 sLeft  = texture2D(uTexture, uv + vec2(-offset,     0.0));
    vec4 sRight = texture2D(uTexture, uv + vec2( offset,     0.0));
    float diagOffset = offset * 0.7071;
    vec4 sUL = texture2D(uTexture, uv + vec2(-diagOffset,  diagOffset));
    vec4 sUR = texture2D(uTexture, uv + vec2( diagOffset,  diagOffset));
    vec4 sLL = texture2D(uTexture, uv + vec2(-diagOffset, -diagOffset));
    vec4 sLR = texture2D(uTexture, uv + vec2( diagOffset, -diagOffset));
    vec4 blended = center * 0.4 + (sUp + sDown + sLeft + sRight) * 0.1 + (sUL + sUR + sLL + sLR) * 0.05;
    return mix(center, blended, edgeStrength);
  }

  vec4 holeFillSample(vec2 uv, float gradient) {
    vec4 center = texture2D(uTexture, uv);
    float maxDepth = vDepthValue;
    vec4 fillColor = center;
    for (int i = -2; i <= 2; i++) {
      for (int j = -2; j <= 2; j++) {
        if (i == 0 && j == 0) continue;
        vec2 sampleUv = uv + vec2(float(i), float(j)) * uTexelSize * 2.0;
        float sampleDepth = texture2D(uDepthTexture, sampleUv).r;
        if (sampleDepth > maxDepth) {
          maxDepth = sampleDepth;
          fillColor = texture2D(uTexture, sampleUv);
        }
      }
    }
    return fillColor;
  }

  void main() {
    float gradient = computeDepthGradient(vUv);
    float edgeStrength = smoothstep(uEdgeThreshold * 0.5, uEdgeThreshold * 1.5, gradient);
    bool isHole = gradient > uEdgeThreshold * 3.0;
    vec4 finalColor;
    if (isHole) {
      finalColor = holeFillSample(vUv, gradient);
    } else if (edgeStrength > 0.01) {
      finalColor = edgeExtendSample(vUv, edgeStrength);
    } else {
      finalColor = texture2D(uTexture, vUv);
    }
    gl_FragColor = finalColor;
  }
`

// ============ 视差网格组件 ============

function ShareDepthMesh({ sceneData }: { sceneData: ShareSceneData }) {
  const meshRef = useRef<THREE.Mesh>(null)
  const textureLoader = useMemo(() => new THREE.TextureLoader(), [])
  const animTypeMap: Record<string, number> = { swing: 1, zoom: 2, rotate: 3, parallax: 4, dolly: 5 }

  const animParams = sceneData.animation_params || {}
  const animType = animTypeMap[animParams.type || 'swing'] ?? 1
  const amplitude = animParams.amplitude || 0.3
  const speed = animParams.speed || 1.0

  const colorTexture = useMemo(() => {
    const url = sceneData.texture_url
    if (!url) return null
    const tex = textureLoader.load(url)
    tex.colorSpace = THREE.SRGBColorSpace
    tex.minFilter = THREE.LinearFilter
    tex.magFilter = THREE.LinearFilter
    return tex
  }, [sceneData.texture_url, textureLoader])

  const depthTexture = useMemo(() => {
    const url = sceneData.depth_map_url
    if (!url) return null
    const tex = textureLoader.load(url)
    tex.minFilter = THREE.LinearFilter
    tex.magFilter = THREE.LinearFilter
    return tex
  }, [sceneData.depth_map_url, textureLoader])

  const geometry = useMemo(() => new THREE.PlaneGeometry(4, 3, 256, 256), [])

  const shaderMaterial = useMemo(() => new THREE.ShaderMaterial({
    uniforms: {
      uTexture: { value: null },
      uDepthTexture: { value: null },
      disparityScale: { value: 0.3 },
      uTexelSize: { value: new THREE.Vector2(1 / 1024, 1 / 1024) },
      uEdgeThreshold: { value: 0.15 },
      uTime: { value: 0 },
      uAnimType: { value: animType },
      uAmplitude: { value: amplitude },
      uSpeed: { value: speed },
    },
    vertexShader: VERTEX_SHADER,
    fragmentShader: FRAGMENT_SHADER,
  }), [])

  useEffect(() => {
    if (colorTexture) {
      shaderMaterial.uniforms.uTexture.value = colorTexture
      const updateTexelSize = () => {
        if (colorTexture.image) {
          const w = colorTexture.image.width || 1024
          const h = colorTexture.image.height || 1024
          shaderMaterial.uniforms.uTexelSize.value.set(1 / w, 1 / h)
        }
      }
      if (colorTexture.image) updateTexelSize()
      else colorTexture.addEventListener('load', updateTexelSize)
    }
    if (depthTexture) shaderMaterial.uniforms.uDepthTexture.value = depthTexture
  }, [colorTexture, depthTexture, shaderMaterial])

  useFrame((state) => {
    if (!meshRef.current) return
    const mat = meshRef.current.material as THREE.ShaderMaterial
    mat.uniforms.uTime.value = state.clock.elapsedTime
  })

  if (!colorTexture) return null
  return <mesh ref={meshRef} geometry={geometry} material={shaderMaterial} />
}

// ============ 分享页面主组件 ============

export function SharePage() {
  const { id } = useParams<{ id: string }>()
  const [shareData, setShareData] = useState<ShareResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    setLoading(true)
    getShare(id)
      .then((data) => {
        setShareData(data)
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message || '加载失败')
        setLoading(false)
      })
  }, [id])

  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(label)
      setTimeout(() => setCopied(null), 2000)
    })
  }

  // 加载中
  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-8 h-8 text-violet-400 animate-spin mx-auto mb-4" />
          <p className="text-white/50 text-sm">加载 3D 场景中...</p>
        </div>
      </div>
    )
  }

  // 加载失败
  if (error || !shareData) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center">
        <div className="text-center max-w-md">
          <AlertCircle className="w-10 h-10 text-red-400 mx-auto mb-4" />
          <h2 className="text-lg font-medium text-white/90 mb-2">无法加载</h2>
          <p className="text-[13px] text-white/40">{error || '分享不存在或已过期'}</p>
        </div>
      </div>
    )
  }

  const sceneData = shareData.scene_data

  return (
    <div className="min-h-screen bg-[#0a0a0f] flex flex-col">
      {/* 3D 渲染区域 */}
      <div className="flex-1 relative">
        {sceneData && sceneData.depth_map_url ? (
          <Suspense fallback={
            <div className="absolute inset-0 flex items-center justify-center">
              <Loader2 className="w-6 h-6 text-violet-400/60 animate-spin" />
            </div>
          }>
            <Canvas
              gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: 1.0 }}
              style={{ width: '100%', height: '100%' }}
            >
              <PerspectiveCamera makeDefault fov={60} near={0.1} far={100} position={[0, 0, 2.5]} />
              <ambientLight intensity={1.0} />
              <directionalLight position={[5, 5, 5]} intensity={0.5} />
              <ShareDepthMesh sceneData={sceneData} />
              <OrbitControls
                enableDamping dampingFactor={0.05} enablePan={false}
                minDistance={1.0} maxDistance={5.0}
                minPolarAngle={Math.PI * 0.2} maxPolarAngle={Math.PI * 0.8}
                minAzimuthAngle={-Math.PI * 0.3} maxAzimuthAngle={Math.PI * 0.3}
                rotateSpeed={0.5} zoomSpeed={0.8}
              />
              <color attach="background" args={['#0a0a0f']} />
            </Canvas>
          </Suspense>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <AlertCircle className="w-8 h-8 text-white/20 mx-auto mb-3" />
              <p className="text-white/30 text-sm">场景数据不可用</p>
            </div>
          </div>
        )}

        {/* 标题覆盖层 */}
        <div className="absolute top-4 left-4 right-4 flex items-start justify-between pointer-events-none">
          <div>
            <h1 className="text-lg font-medium text-white/90 drop-shadow-lg">{shareData.title}</h1>
            <p className="text-[11px] text-white/30 mt-0.5 flex items-center gap-2">
              <Eye className="w-3 h-3" /> {shareData.view_count} 次浏览
            </p>
          </div>
          <a
            href="/"
            className="pointer-events-auto px-3 py-1.5 rounded-lg bg-white/[0.06] border border-white/[0.08] text-[12px] text-white/60 hover:text-white/90 hover:bg-white/[0.1] transition-colors flex items-center gap-1.5"
          >
            <ExternalLink className="w-3 h-3" /> LeiaPix AI
          </a>
        </div>

        {/* 底部操作栏 */}
        <div className="absolute bottom-4 left-4 right-4 flex items-center gap-2 pointer-events-none">
          {/* 分享链接 */}
          <button
            onClick={() => copyToClipboard(shareData.share_url, 'link')}
            className="pointer-events-auto px-3 py-2 rounded-lg bg-black/40 backdrop-blur-sm border border-white/[0.08] text-[12px] text-white/70 hover:text-white/90 hover:bg-black/50 transition-colors"
          >
            {copied === 'link' ? '已复制!' : '复制链接'}
          </button>

          {/* 嵌入代码 */}
          <button
            onClick={() => copyToClipboard(shareData.embed_code, 'embed')}
            className="pointer-events-auto px-3 py-2 rounded-lg bg-black/40 backdrop-blur-sm border border-white/[0.08] text-[12px] text-white/70 hover:text-white/90 hover:bg-black/50 transition-colors"
          >
            {copied === 'embed' ? '已复制!' : '嵌入代码'}
          </button>

          {/* 下载 */}
          {shareData.allow_download && sceneData?.texture_url && (
            <a
              href={sceneData.texture_url}
              target="_blank"
              rel="noopener noreferrer"
              className="pointer-events-auto px-3 py-2 rounded-lg bg-black/40 backdrop-blur-sm border border-white/[0.08] text-[12px] text-white/70 hover:text-white/90 hover:bg-black/50 transition-colors flex items-center gap-1.5"
            >
              <Download className="w-3 h-3" /> 下载原图
            </a>
          )}
        </div>
      </div>
    </div>
  )
}
