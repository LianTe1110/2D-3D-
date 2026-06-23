import { useRef, useMemo, useEffect, useCallback } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, PerspectiveCamera } from '@react-three/drei'
import * as THREE from 'three'
import { useEditorStore } from '@/stores/editor-store'
import { AnimationEngine } from '@/lib/animation-engine'
import { CameraPathEngine, PRESET_PATHS } from '@/lib/camera-path-engine'
import { getOrLoadTexture } from '@/lib/performance-cache'
import type { MPILayer } from '@/types'

// ============ Phase 1.2: 改进 UV clamp (每层 Shader) ============

const LAYER_VERTEX_SHADER = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const LAYER_FRAGMENT_SHADER = /* glsl */ `
  uniform sampler2D uTexture;
  uniform sampler2D uSoftMask;
  uniform float uMotionScale;
  uniform vec2 uCameraOffset;
  uniform int uArtStyle;
  uniform vec2 uTexelSize;
  uniform float uEdgeFreezeStrength;
  uniform float uZPosition;     // Level 3: z-position for depth-aware motion
  varying vec2 vUv;

  // === 画风后处理函数 (保留原有) ===

  vec3 animeStyle(vec3 color, vec2 uv) {
    float levels = 6.0;
    vec3 quantized = floor(color * levels + 0.5) / levels;
    float l = dot(color, vec3(0.299, 0.587, 0.114));
    float lLeft  = dot(texture2D(uTexture, uv - vec2(uTexelSize.x, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lRight = dot(texture2D(uTexture, uv + vec2(uTexelSize.x, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lUp    = dot(texture2D(uTexture, uv - vec2(0.0, uTexelSize.y)).rgb, vec3(0.299, 0.587, 0.114));
    float lDown  = dot(texture2D(uTexture, uv + vec2(0.0, uTexelSize.y)).rgb, vec3(0.299, 0.587, 0.114));
    float edge = abs(lLeft - lRight) + abs(lUp - lDown);
    float outline = smoothstep(0.05, 0.15, edge);
    return mix(quantized, vec3(0.05), outline * 0.7);
  }

  vec3 oilPaintingStyle(vec3 color, vec2 uv) {
    vec3 sum = vec3(0.0);
    float totalWeight = 0.0;
    float radius = 3.0;
    for (float dy = -radius; dy <= radius; dy += 1.0) {
      for (float dx = -radius; dx <= radius; dx += 1.0) {
        vec2 offset = vec2(dx, dy) * uTexelSize * 2.0;
        vec3 s = texture2D(uTexture, uv + offset).rgb;
        float w = 1.0 / (1.0 + length(vec2(dx, dy)));
        sum += s * w;
        totalWeight += w;
      }
    }
    vec3 smoothed = sum / totalWeight;
    float gray = dot(smoothed, vec3(0.299, 0.587, 0.114));
    vec3 saturated = mix(vec3(gray), smoothed, 1.4);
    return saturated * vec3(1.05, 1.0, 0.92);
  }

  vec3 watercolorStyle(vec3 color, vec2 uv) {
    vec3 sum = vec3(0.0);
    float r = 2.0;
    for (float dy = -r; dy <= r; dy += 1.0) {
      for (float dx = -r; dx <= r; dx += 1.0) {
        sum += texture2D(uTexture, uv + vec2(dx, dy) * uTexelSize * 1.5).rgb;
      }
    }
    vec3 blurred = sum / ((2.0*r+1.0) * (2.0*r+1.0));
    vec3 brightened = (blurred + 0.15) / 1.15;
    float gray = dot(brightened, vec3(0.299, 0.587, 0.114));
    vec3 desaturated = mix(vec3(gray), brightened, 0.75);
    float noise = fract(sin(dot(uv * 500.0, vec2(12.9898, 78.233))) * 43758.5453);
    desaturated += (noise - 0.5) * 0.03;
    return desaturated;
  }

  vec3 sketchStyle(vec3 color, vec2 uv) {
    float l = dot(color, vec3(0.299, 0.587, 0.114));
    float edge = 0.0;
    for (float angle = 0.0; angle < 3.14159; angle += 0.3927) {
      vec2 dir = vec2(cos(angle), sin(angle)) * uTexelSize * 2.0;
      float l1 = dot(texture2D(uTexture, uv + dir).rgb, vec3(0.299, 0.587, 0.114));
      float l2 = dot(texture2D(uTexture, uv - dir).rgb, vec3(0.299, 0.587, 0.114));
      edge += abs(l1 - l2);
    }
    edge /= 8.0;
    return vec3(1.0 - smoothstep(0.02, 0.12, edge));
  }

  vec3 cyberpunkStyle(vec3 color, vec2 uv) {
    float gray = dot(color, vec3(0.299, 0.587, 0.114));
    vec3 highContrast = mix(vec3(gray), color, 1.6);
    highContrast = pow(highContrast, vec3(0.85));
    highContrast.r *= 1.1;
    highContrast.g *= 0.9;
    highContrast.b *= 1.3;
    float scanline = 0.95 + 0.05 * sin(uv.y * 800.0);
    highContrast *= scanline;
    return highContrast;
  }

  vec3 vintageStyle(vec3 color, vec2 uv) {
    float gray = dot(color, vec3(0.299, 0.587, 0.114));
    vec3 desaturated = mix(vec3(gray), color, 0.6);
    desaturated.r *= 1.15;
    desaturated.g *= 1.05;
    desaturated.b *= 0.85;
    float dist = distance(uv, vec2(0.5));
    float vignette = 1.0 - smoothstep(0.4, 0.9, dist);
    desaturated *= mix(0.6, 1.0, vignette);
    float noise = fract(sin(dot(uv * 300.0, vec2(12.9898, 78.233))) * 43758.5453);
    desaturated += (noise - 0.5) * 0.06;
    return desaturated;
  }

  vec3 applyArtStyle(vec3 color, vec2 uv, int style) {
    if (style == 1) return animeStyle(color, uv);
    if (style == 2) return oilPaintingStyle(color, uv);
    if (style == 3) return watercolorStyle(color, uv);
    if (style == 4) return sketchStyle(color, uv);
    if (style == 5) return cyberpunkStyle(color, uv);
    if (style == 6) return vintageStyle(color, uv);
    return color;
  }

  // === Level 3: UV clamp → 边缘镜像采样 (防撕裂) ===
  vec2 clampMirrorUV(vec2 uv) {
    return vec2(
      abs(fract(uv.x * 0.5 + 0.5) * 2.0 - 1.0),
      abs(fract(uv.y * 0.5 + 0.5) * 2.0 - 1.0)
    );
  }

  // === Level 3: Soft mask edge detection (替代 depth texture) ===
  float computeSoftMaskEdge(vec2 uv) {
    float m = texture2D(uSoftMask, uv).r;
    float mL = texture2D(uSoftMask, uv - vec2(uTexelSize.x, 0.0)).r;
    float mR = texture2D(uSoftMask, uv + vec2(uTexelSize.x, 0.0)).r;
    float mU = texture2D(uSoftMask, uv - vec2(0.0, uTexelSize.y)).r;
    float mD = texture2D(uSoftMask, uv + vec2(0.0, uTexelSize.y)).r;
    float gx = mL - mR;
    float gy = mU - mD;
    return sqrt(gx * gx + gy * gy);
  }

  // === Level 3: MPI 层边缘瑕疵遮罩（仅极端区域，不影响正常轮廓） ===
  float layerEdgeArtifactMask(vec2 uv) {
    // 只在极高 soft-mask 梯度处淡出（真正分层边界瑕疵）
    float maskEdge = computeSoftMaskEdge(uv);
    float extremeFade = 1.0 - smoothstep(0.20, 0.45, maskEdge);

    // UV 边界极窄淡出
    float margin = 0.02;
    float edgeX = smoothstep(0.0, margin, uv.x) * smoothstep(0.0, margin, 1.0 - uv.x);
    float edgeY = smoothstep(0.0, margin, uv.y) * smoothstep(0.0, margin, 1.0 - uv.y);

    return max(extremeFade, edgeX * edgeY);
  }

  void main() {
    float softMask = texture2D(uSoftMask, vUv).r;

    // Level 3: Z-position driven parallax (FG z>0 → move more, BG z<0 → move less)
    float zFactor = uZPosition * 0.5 + 0.5; // map [-2.5, 2.0] → [0, 1.5]
    float depthDriven = softMask * zFactor;

    vec2 offset = uCameraOffset * uMotionScale * 0.06 * depthDriven;

    // Edge freeze: reduce motion at soft mask discontinuities (防撕裂)
    float maskEdge = computeSoftMaskEdge(vUv);
    float edgeFreeze = smoothstep(0.0, 0.25, maskEdge) * uEdgeFreezeStrength;
    offset *= (1.0 - edgeFreeze);

    vec2 sampleUv = vUv + offset;
    sampleUv = clampMirrorUV(sampleUv);

    vec4 color = texture2D(uTexture, sampleUv);

    // Level 3: Soft mask blending (0~1 alpha)
    color.a *= softMask;

    // Border feather + 边缘瑕疵遮罩：防止露出底层建模
    float borderDist = min(
      min(sampleUv.x, 1.0 - sampleUv.x),
      min(sampleUv.y, 1.0 - sampleUv.y)
    );
    float borderFeather = smoothstep(0.0, 0.03, borderDist);
    float artifactFade = layerEdgeArtifactMask(vUv);
    color.a *= borderFeather * artifactFade;

    if (color.a < 0.005) discard;

    color.rgb = applyArtStyle(color.rgb, vUv, uArtStyle);

    // Premultiplied alpha output
    gl_FragColor = vec4(color.rgb * color.a, color.a);
  }
`

// ============ Phase 1.5: 单层 MPI Mesh (Level 3 z-spacing) ============

// Level 3: 扩大 z 间距 — 人物真实漂浮 + 背景空间延展
const DEFAULT_Z_POSITIONS = [-2.5, 0.0, 2.0]
const DEFAULT_MOTION_SCALES = [0.2, 0.7, 1.5]

interface LayerMeshProps {
  layer: MPILayer
  index: number
  cameraOffset: React.MutableRefObject<THREE.Vector2>
  artStyle: number
}

function LayerMesh({ layer, index, cameraOffset, artStyle }: LayerMeshProps) {
  const meshRef = useRef<THREE.Mesh>(null)
  const { uploadedImage } = useEditorStore()

  // ⚡ Texture Pool: 复用纹理, 避免重复加载
  const texture = useMemo(() => getOrLoadTexture(layer.textureUrl), [layer.textureUrl])

  // ⚡ Level 3: Soft mask texture (复用 texture pool)
  const softMaskTexture = useMemo(() => {
    if (layer.normalUrl) return getOrLoadTexture(layer.normalUrl)
    return texture // fallback to main texture
  }, [layer.normalUrl, texture])

  const geometry = useMemo(() => {
    const imgW = uploadedImage?.width || 4
    const imgH = uploadedImage?.height || 3
    const aspect = imgW / imgH
    return new THREE.PlaneGeometry(2.0 * aspect, 2.0, 64, 64)
  }, [uploadedImage])

  const material = useMemo(() => {
    const zPos = layer.zIndex ?? DEFAULT_Z_POSITIONS[index] ?? 0
    return new THREE.ShaderMaterial({
      uniforms: {
        uTexture: { value: texture },
        uSoftMask: { value: softMaskTexture },
        uMotionScale: { value: layer.motionScale ?? DEFAULT_MOTION_SCALES[index] ?? 1.0 },
        uCameraOffset: { value: new THREE.Vector2(0, 0) },
        uArtStyle: { value: artStyle },
        uTexelSize: { value: new THREE.Vector2(1 / 1024, 1 / 1024) },
        uEdgeFreezeStrength: { value: 0.8 },
        uZPosition: { value: zPos },
      },
      vertexShader: LAYER_VERTEX_SHADER,
      fragmentShader: LAYER_FRAGMENT_SHADER,
      transparent: true,
      depthTest: true,
      depthWrite: true,  // Level 3: 所有层写深度 → 正确遮挡，无错层
      blending: THREE.CustomBlending,
      blendSrc: THREE.OneFactor,
      blendDst: THREE.OneMinusSrcAlphaFactor,
      toneMapped: false,
    })
  }, [texture, softMaskTexture, layer.motionScale, layer.zIndex, artStyle, index])

  useEffect(() => {
    if (texture.image) {
      const w = texture.image.width || 1024
      const h = texture.image.height || 1024
      material.uniforms.uTexelSize.value.set(1.0 / w, 1.0 / h)
    }
  }, [texture, material])

  useFrame(() => {
    if (!meshRef.current) return
    const mat = meshRef.current.material as THREE.ShaderMaterial
    mat.uniforms.uCameraOffset.value.copy(cameraOffset.current)
  })

  return (
    <mesh
      ref={meshRef}
      geometry={geometry}
      material={material}
      position={[0, 0, layer.zIndex ?? DEFAULT_Z_POSITIONS[index] ?? 0]}
      renderOrder={index}
    />
  )
}

// ============ Phase 1.5: MPI 层容器 ============

function MPIScene() {
  const { mpiLayerUrls, uploadedImage, styleQuality, animation, isPlaying } = useEditorStore()
  const cameraOffsetRef = useRef(new THREE.Vector2(0, 0))
  const pathEngineRef = useRef<CameraPathEngine | null>(null)
  const { camera } = useThree()

  // Initialize CameraPathEngine
  useEffect(() => {
    if (camera && !pathEngineRef.current) {
      pathEngineRef.current = new CameraPathEngine(camera as THREE.PerspectiveCamera)
    }
  }, [camera])

  // Switch camera path when animation type changes
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

  const artStyleMap: Record<string, number> = {
    original: 0, anime: 1, oil_painting: 2, watercolor: 3,
    sketch: 4, cyberpunk: 5, vintage: 6,
  }

  // Level 3: Camera-driven parallax (NOT mouse-driven UV warp)
  useFrame((state) => {
    if (pathEngineRef.current && isPlaying) {
      pathEngineRef.current.update()
      // Derive camera offset from camera position
      const cam = camera as THREE.PerspectiveCamera
      cameraOffsetRef.current.set(
        cam.position.x * 0.5,
        cam.position.y * 0.5
      )
      return
    }

    // Fallback: sine animation
    if (animation.type !== 'none' && isPlaying) {
      const t = state.clock.elapsedTime * animation.speed
      if (animation.type === 'swing') {
        cameraOffsetRef.current.set(
          Math.sin(t) * animation.amplitude * 0.15,
          Math.cos(t * 0.7) * animation.amplitude * 0.05
        )
      } else if (animation.type === 'parallax') {
        cameraOffsetRef.current.set(
          Math.sin(t * 0.6) * animation.amplitude * 0.2,
          Math.cos(t * 0.4) * animation.amplitude * 0.1
        )
      } else if (animation.type === 'dolly') {
        cameraOffsetRef.current.set(
          Math.sin(t * 0.5) * animation.amplitude * 0.1,
          Math.cos(t * 0.3) * animation.amplitude * 0.05
        )
      }
    }
  })

  if (!mpiLayerUrls || mpiLayerUrls.length === 0) return null

  return (
    <>
      {mpiLayerUrls.map((layer, i) => (
        <LayerMesh
          key={layer.id || i}
          layer={layer}
          index={i}
          cameraOffset={cameraOffsetRef}
          artStyle={artStyleMap[styleQuality.artStyle] ?? 0}
        />
      ))}
    </>
  )
}

// ============ 旧 DepthMesh (保留作为 fallback) ============

const VERTEX_SHADER = /* glsl */ `
  uniform sampler2D uDepthTexture;
  uniform float uTime;
  uniform int uAnimType;
  uniform float uAmplitude;
  uniform float uSpeed;
  uniform int uLayerCount;
  uniform float uLayerScale0;
  uniform float uLayerScale1;
  uniform float uLayerScale2;
  uniform float uLayerScale3;
  uniform float uLayerScale4;
  varying vec2 vUv;
  varying float vDepthValue;
  varying float vLayeredDepth;

  float getLayerScale(int idx) {
    if (idx == 0) return uLayerScale0;
    else if (idx == 1) return uLayerScale1;
    else if (idx == 2) return uLayerScale2;
    else if (idx == 3) return uLayerScale3;
    else return uLayerScale4;
  }

  float computeVertDepthGradient(vec2 uv) {
    float ts = 1.0 / 512.0;
    float d00 = texture2D(uDepthTexture, uv + vec2(-ts, -ts)).r;
    float d10 = texture2D(uDepthTexture, uv + vec2( 0.0, -ts)).r;
    float d20 = texture2D(uDepthTexture, uv + vec2( ts, -ts)).r;
    float d01 = texture2D(uDepthTexture, uv + vec2(-ts,  0.0)).r;
    float d21 = texture2D(uDepthTexture, uv + vec2( ts,  0.0)).r;
    float d02 = texture2D(uDepthTexture, uv + vec2(-ts,  ts)).r;
    float d12 = texture2D(uDepthTexture, uv + vec2( 0.0,  ts)).r;
    float d22 = texture2D(uDepthTexture, uv + vec2( ts,  ts)).r;
    float gx = -d00 - 2.0*d01 - d02 + d20 + 2.0*d21 + d22;
    float gy = -d00 - 2.0*d10 - d20 + d02 + 2.0*d12 + d22;
    return sqrt(gx * gx + gy * gy);
  }

  void main() {
    vUv = uv;
    float depthValue = texture2D(uDepthTexture, uv).r;
    vDepthValue = depthValue;

    // === 边缘位移衰减：必须在分层缩放之前判断，确保轮廓处整体位移都降低 ===
    float vertGrad = computeVertDepthGradient(uv);
    float displacementFalloff = 1.0 - smoothstep(0.03, 0.18, vertGrad);

    float effectiveDepth = depthValue;
    if (uLayerCount > 1) {
      float layerStep = 1.0 / float(uLayerCount);
      float layerIndex = floor(depthValue / layerStep);
      layerIndex = clamp(layerIndex, 0.0, float(uLayerCount) - 1.0);
      int iLayer = int(layerIndex);
      float layerScale = getLayerScale(iLayer);
      effectiveDepth = depthValue * layerScale;
      float layerFract = fract(depthValue / layerStep);
      float blendWidth = 0.15;
      if (layerFract < blendWidth && iLayer > 0) {
        float prevScale = getLayerScale(iLayer - 1);
        float mixFactor = smoothstep(0.0, blendWidth, layerFract);
        effectiveDepth = mix(depthValue * prevScale, effectiveDepth, mixFactor);
      }
    }

    // 轮廓处整体深度缩放降低 → 所有方向位移都降低
    effectiveDepth *= displacementFalloff;

    vLayeredDepth = effectiveDepth;
    vec3 transformed = position;
    float t = uTime * uSpeed;
    if (uAnimType == 1) {
      transformed.x += sin(t) * uAmplitude * effectiveDepth * 0.15;
      transformed.z += cos(t * 0.7) * uAmplitude * effectiveDepth * 0.05;
    } else if (uAnimType == 2) {
      float scale = 1.0 + sin(t * 0.5) * uAmplitude * 0.08;
      transformed.xy *= scale;
      transformed.z += sin(t * 0.3) * uAmplitude * effectiveDepth * 0.1;
    } else if (uAnimType == 3) {
      float angle = sin(t * 0.4) * uAmplitude * 0.15;
      float c = cos(angle);
      float s = sin(angle);
      transformed.xz = mat2(c, -s, s, c) * transformed.xz;
    } else if (uAnimType == 4) {
      transformed.x += sin(t * 0.6) * uAmplitude * effectiveDepth * 0.2;
    } else if (uAnimType == 5) {
      transformed.z += sin(t * 0.5) * uAmplitude * effectiveDepth * 0.15;
    }
    gl_Position = projectionMatrix * modelViewMatrix * vec4(transformed, 1.0);
  }
`

const FRAGMENT_SHADER = /* glsl */ `
  uniform sampler2D uTexture;
  uniform sampler2D uDepthTexture;
  uniform vec2 uTexelSize;
  uniform float uEdgeThreshold;
  uniform int uArtStyle;
  varying vec2 vUv;
  varying float vDepthValue;
  varying float vLayeredDepth;
  uniform float uEdgeFreezeStrength;

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
    vec4 blended = center * 0.4
                 + (sUp + sDown + sLeft + sRight) * 0.1
                 + (sUL + sUR + sLL + sLR) * 0.05;
    return mix(center, blended, edgeStrength);
  }

  // 画风函数 (精简, 与 MPI 层一致)
  vec3 animeStyle(vec3 color, vec2 uv) {
    float levels = 6.0;
    vec3 quantized = floor(color * levels + 0.5) / levels;
    float l = dot(color, vec3(0.299, 0.587, 0.114));
    float lLeft  = dot(texture2D(uTexture, uv - vec2(uTexelSize.x, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lRight = dot(texture2D(uTexture, uv + vec2(uTexelSize.x, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lUp    = dot(texture2D(uTexture, uv - vec2(0.0, uTexelSize.y)).rgb, vec3(0.299, 0.587, 0.114));
    float lDown  = dot(texture2D(uTexture, uv + vec2(0.0, uTexelSize.y)).rgb, vec3(0.299, 0.587, 0.114));
    float edge = abs(lLeft - lRight) + abs(lUp - lDown);
    float outline = smoothstep(0.05, 0.15, edge);
    return mix(quantized, vec3(0.05), outline * 0.7);
  }

  vec3 oilPaintingStyle(vec3 color, vec2 uv) {
    vec3 sum = vec3(0.0);
    float totalWeight = 0.0;
    float radius = 3.0;
    for (float dy = -radius; dy <= radius; dy += 1.0) {
      for (float dx = -radius; dx <= radius; dx += 1.0) {
        vec2 offset = vec2(dx, dy) * uTexelSize * 2.0;
        vec3 s = texture2D(uTexture, uv + offset).rgb;
        float w = 1.0 / (1.0 + length(vec2(dx, dy)));
        sum += s * w;
        totalWeight += w;
      }
    }
    vec3 smoothed = sum / totalWeight;
    float gray = dot(smoothed, vec3(0.299, 0.587, 0.114));
    vec3 saturated = mix(vec3(gray), smoothed, 1.4);
    return saturated * vec3(1.05, 1.0, 0.92);
  }

  vec3 watercolorStyle(vec3 color, vec2 uv) {
    vec3 sum = vec3(0.0);
    float r = 2.0;
    for (float dy = -r; dy <= r; dy += 1.0) {
      for (float dx = -r; dx <= r; dx += 1.0) {
        sum += texture2D(uTexture, uv + vec2(dx, dy) * uTexelSize * 1.5).rgb;
      }
    }
    vec3 blurred = sum / ((2.0*r+1.0) * (2.0*r+1.0));
    vec3 brightened = (blurred + 0.15) / 1.15;
    float gray = dot(brightened, vec3(0.299, 0.587, 0.114));
    vec3 desaturated = mix(vec3(gray), brightened, 0.75);
    return desaturated;
  }

  vec3 sketchStyle(vec3 color, vec2 uv) {
    float l = dot(color, vec3(0.299, 0.587, 0.114));
    float edge = 0.0;
    for (float angle = 0.0; angle < 3.14159; angle += 0.3927) {
      vec2 dir = vec2(cos(angle), sin(angle)) * uTexelSize * 2.0;
      float l1 = dot(texture2D(uTexture, uv + dir).rgb, vec3(0.299, 0.587, 0.114));
      float l2 = dot(texture2D(uTexture, uv - dir).rgb, vec3(0.299, 0.587, 0.114));
      edge += abs(l1 - l2);
    }
    edge /= 8.0;
    return vec3(1.0 - smoothstep(0.02, 0.12, edge));
  }

  vec3 cyberpunkStyle(vec3 color, vec2 uv) {
    float gray = dot(color, vec3(0.299, 0.587, 0.114));
    vec3 highContrast = mix(vec3(gray), color, 1.6);
    highContrast = pow(highContrast, vec3(0.85));
    highContrast.r *= 1.1;
    highContrast.g *= 0.9;
    highContrast.b *= 1.3;
    float scanline = 0.95 + 0.05 * sin(uv.y * 800.0);
    highContrast *= scanline;
    return highContrast;
  }

  vec3 vintageStyle(vec3 color, vec2 uv) {
    float gray = dot(color, vec3(0.299, 0.587, 0.114));
    vec3 desaturated = mix(vec3(gray), color, 0.6);
    desaturated.r *= 1.15;
    desaturated.g *= 1.05;
    desaturated.b *= 0.85;
    float dist = distance(uv, vec2(0.5));
    float vignette = 1.0 - smoothstep(0.4, 0.9, dist);
    desaturated *= mix(0.6, 1.0, vignette);
    float noise = fract(sin(dot(uv * 300.0, vec2(12.9898, 78.233))) * 43758.5453);
    desaturated += (noise - 0.5) * 0.06;
    return desaturated;
  }

  vec3 applyArtStyle(vec3 color, vec2 uv, int style) {
    if (style == 1) return animeStyle(color, uv);
    if (style == 2) return oilPaintingStyle(color, uv);
    if (style == 3) return watercolorStyle(color, uv);
    if (style == 4) return sketchStyle(color, uv);
    if (style == 5) return cyberpunkStyle(color, uv);
    if (style == 6) return vintageStyle(color, uv);
    return color;
  }

  void main() {
    float gradient = computeDepthGradient(vUv);
    float lumCenter = dot(texture2D(uTexture, vUv).rgb, vec3(0.299, 0.587, 0.114));
    float lLeft  = dot(texture2D(uTexture, vUv + vec2(-uTexelSize.x, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lRight = dot(texture2D(uTexture, vUv + vec2( uTexelSize.x, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lUp    = dot(texture2D(uTexture, vUv + vec2(0.0, -uTexelSize.y)).rgb, vec3(0.299, 0.587, 0.114));
    float lDown  = dot(texture2D(uTexture, vUv + vec2(0.0,  uTexelSize.y)).rgb, vec3(0.299, 0.587, 0.114));
    float imgEdgeGrad = abs(lLeft - lRight) + abs(lUp - lDown);
    float edgeFreezeStrength = smoothstep(0.05, 0.20, imgEdgeGrad) * uEdgeFreezeStrength;
    bool isHole = gradient > uEdgeThreshold * 3.0 && edgeFreezeStrength < 0.3;

    // 人物/物体锐利边缘直接取原色，不做任何混合（避免边缘白边/黑边）
    vec4 finalColor;
    if (edgeFreezeStrength > 0.5 || gradient > uEdgeThreshold * 2.0) {
      finalColor = texture2D(uTexture, vUv);
    } else if (isHole) {
      finalColor = holeFillSample(vUv, gradient);
    } else {
      finalColor = texture2D(uTexture, vUv);
    }
    finalColor.rgb = applyArtStyle(finalColor.rgb, vUv, uArtStyle);

    // 始终不透明，不丢弃像素
    finalColor.a = 1.0;
    gl_FragColor = finalColor;
  }
`

function DepthMesh() {
  const meshRef = useRef<THREE.Mesh>(null)
  const { originalPreview, depthMapUrl, animation, isPlaying, sceneData, styleQuality, uploadedImage } = useEditorStore()
  const textureLoader = useMemo(() => new THREE.TextureLoader(), [])

  const colorTexture = useMemo(() => {
    if (!originalPreview) return null
    const tex = textureLoader.load(originalPreview)
    tex.colorSpace = THREE.NoColorSpace
    tex.minFilter = THREE.LinearFilter
    tex.magFilter = THREE.LinearFilter
    return tex
  }, [originalPreview, textureLoader])

  const depthTexture = useMemo(() => {
    if (!depthMapUrl) return null
    const tex = textureLoader.load(depthMapUrl)
    tex.minFilter = THREE.LinearFilter
    tex.magFilter = THREE.LinearFilter
    return tex
  }, [depthMapUrl, textureLoader])

  const geometry = useMemo(() => {
    const imgW = uploadedImage?.width || 4
    const imgH = uploadedImage?.height || 3
    const aspect = imgW / imgH
    return new THREE.PlaneGeometry(2.0 * aspect, 2.0, 256, 256)
  }, [uploadedImage?.width, uploadedImage?.height])

  const shaderMaterial = useMemo(() => {
    const rp = sceneData?.render_params
    return new THREE.ShaderMaterial({
      uniforms: {
        uTexture:        { value: null },
        uDepthTexture:   { value: null },
        uTexelSize:      { value: new THREE.Vector2(1.0 / 1024, 1.0 / 1024) },
        uEdgeThreshold:  { value: 0.15 },
        uTime:           { value: 0 },
        uAnimType:       { value: 0 },
        uAmplitude:      { value: 0.3 },
        uSpeed:          { value: 1.0 },
        uArtStyle:       { value: 0 },
        uLayerCount:     { value: rp?.layer_count ?? 3 },
        uLayerScale0:    { value: rp?.layer_scales?.[0] ?? 0.15 },
        uLayerScale1:    { value: rp?.layer_scales?.[1] ?? 0.6 },
        uLayerScale2:    { value: rp?.layer_scales?.[2] ?? 1.3 },
        uLayerScale3:    { value: rp?.layer_scales?.[3] ?? 1.8 },
        uLayerScale4:    { value: rp?.layer_scales?.[4] ?? 2.5 },
        uEdgeFreezeStrength: { value: rp?.edge_freeze_strength ?? 0.8 },
      },
      vertexShader: VERTEX_SHADER,
      fragmentShader: FRAGMENT_SHADER,
      transparent: true,
      depthTest: true,
      depthWrite: true,
      side: THREE.DoubleSide,
      toneMapped: false,
    })
  }, [sceneData?.render_params])

  useEffect(() => {
    if (colorTexture) {
      shaderMaterial.uniforms.uTexture.value = colorTexture
      const updateTexelSize = () => {
        if (colorTexture.image) {
          const w = colorTexture.image.width || 1024
          const h = colorTexture.image.height || 1024
          shaderMaterial.uniforms.uTexelSize.value.set(1.0 / w, 1.0 / h)
        }
      }
      if (colorTexture.image) {
        updateTexelSize()
      } else {
        colorTexture.addEventListener('load', updateTexelSize)
      }
    }
    if (depthTexture) shaderMaterial.uniforms.uDepthTexture.value = depthTexture
  }, [colorTexture, depthTexture, shaderMaterial])

  const animTypeMap: Record<string, number> = {
    swing: 1, zoom: 2, rotate: 3, parallax: 4, dolly: 5,
  }
  const artStyleMap: Record<string, number> = {
    original: 0, anime: 1, oil_painting: 2, watercolor: 3, sketch: 4, cyberpunk: 5, vintage: 6,
  }

  useFrame((state) => {
    if (!meshRef.current) return
    const mat = meshRef.current.material as THREE.ShaderMaterial
    mat.uniforms.uTime.value = isPlaying ? state.clock.elapsedTime : 0
    mat.uniforms.uAnimType.value = animTypeMap[animation.type] ?? 0
    mat.uniforms.uAmplitude.value = animation.amplitude
    mat.uniforms.uSpeed.value = animation.speed
    mat.uniforms.uArtStyle.value = artStyleMap[styleQuality.artStyle] ?? 0
  })

  if (!colorTexture) return null

  return <mesh ref={meshRef} geometry={geometry} material={shaderMaterial} />
}

// ============ 相机自适应 ============

function CameraFitter() {
  const { camera } = useThree()
  const { uploadedImage } = useEditorStore()

  useEffect(() => {
    const imgW = uploadedImage?.width || 4
    const imgH = uploadedImage?.height || 3
    const imageAspect = imgW / imgH
    const planeH = 2.0
    const planeW = planeH * imageAspect
    const canvas = document.querySelector('canvas') as HTMLCanvasElement | null
    if (!canvas) return
    const canvasAspect = canvas.clientWidth / canvas.clientHeight
    const perspCamera = camera as THREE.PerspectiveCamera
    const fov = perspCamera.fov * (Math.PI / 180)
    const distByHeight = (planeH / 2) / Math.tan(fov / 2)
    const distByWidth = (planeW / 2) / (Math.tan(fov / 2) * canvasAspect)
    const distance = Math.max(distByHeight, distByWidth)
    camera.position.set(0, 0, distance)
    camera.lookAt(0, 0, 0)
  }, [uploadedImage?.width, uploadedImage?.height, camera])

  return null
}

// ============ 相机动画控制器 ============

function CameraAnimator() {
  const { camera } = useThree()
  const { animation, isPlaying } = useEditorStore()
  const engineRef = useRef<AnimationEngine | null>(null)

  if (!engineRef.current) {
    engineRef.current = new AnimationEngine(camera as THREE.PerspectiveCamera)
  }

  useEffect(() => {
    const engine = engineRef.current!
    if (isPlaying) {
      engine.play(animation.type, animation)
    } else {
      engine.stop()
    }
  }, [animation.type, animation.amplitude, animation.speed, animation.duration, animation.loop, isPlaying])

  useFrame((state) => {
    if (isPlaying) {
      engineRef.current?.update(state.clock.elapsedTime * 1000)
    }
  })

  useEffect(() => {
    return () => { engineRef.current?.dispose() }
  }, [])

  return null
}

// ============ 相机视差控制器 ============

function CameraParallaxController() {
  const { camera } = useThree()
  const { animation, isPlaying, sceneData } = useEditorStore()
  const mouseRef = useRef({ x: 0, y: 0 })
  const basePosition = useRef(new THREE.Vector3(0, 0, 5))
  const isInitialized = useRef(false)

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      mouseRef.current.x = (e.clientX / window.innerWidth) * 2 - 1
      mouseRef.current.y = -(e.clientY / window.innerHeight) * 2 + 1
    }
    window.addEventListener('mousemove', handleMouseMove)
    return () => window.removeEventListener('mousemove', handleMouseMove)
  }, [])

  useEffect(() => {
    if (!isInitialized.current && camera.position.z > 0 && camera.position.z < 50) {
      basePosition.current.copy(camera.position)
      isInitialized.current = true
    }
  }, [camera.position.z])

  useFrame(() => {
    const rp = sceneData?.render_params
    const intensity = rp?.parallax_scale ?? 0.3
    const enableMouseParallax = rp?.camera_parallax !== false
    if (!enableMouseParallax || !isInitialized.current) return
    if (isPlaying && animation.type !== 'none') return
    const targetX = basePosition.current.x + mouseRef.current.x * intensity
    const targetY = basePosition.current.y + mouseRef.current.y * intensity * 0.6
    const smoothing = 0.08
    camera.position.x += (targetX - camera.position.x) * smoothing
    camera.position.y += (targetY - camera.position.y) * smoothing
  })

  return null
}

// ============ 场景主组件 (MPI 优先, fallback 到旧 DepthMesh) ============

export function Scene3D() {
  const { step, originalPreview, depthMapUrl, mpiLayerUrls, sceneData } = useEditorStore()

  if (step !== 'completed' || !originalPreview) {
    return null
  }

  const rp = sceneData?.render_params
  const hasMPI = mpiLayerUrls && mpiLayerUrls.length > 0

  return (
    <Canvas
      gl={{
        antialias: true,
        toneMapping: THREE.NoToneMapping,
        preserveDrawingBuffer: false,
      }}
      frameloop="always"
      dpr={[1, 2]}
      style={{ width: '100%', height: '100%' }}
    >
      <PerspectiveCamera
        makeDefault
        fov={rp?.fov ?? 60}
        near={rp?.near_plane ?? 0.1}
        far={rp?.far_plane ?? 100}
        position={[0, 0, 5]}
      />

      {/* 深度图渲染: 单层 Mesh + 深度驱动视差 (旧版效果) */}
      {depthMapUrl ? (
        <DepthMesh />
      ) : null}

      <CameraFitter />
      <CameraAnimator />
      <CameraParallaxController />

      <OrbitControls
        enableDamping
        dampingFactor={0.05}
        enablePan={false}
        minDistance={1.5}
        maxDistance={10.0}
        minPolarAngle={Math.PI * 0.15}
        maxPolarAngle={Math.PI * 0.85}
        minAzimuthAngle={-Math.PI * 0.4}
        maxAzimuthAngle={Math.PI * 0.4}
        rotateSpeed={0.5}
        zoomSpeed={0.8}
        enableRotate={true}
      />

      <color attach="background" args={['#1a1a24']} />
    </Canvas>
  )
}