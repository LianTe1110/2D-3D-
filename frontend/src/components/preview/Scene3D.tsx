import { useRef, useMemo, useEffect, useCallback } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, PerspectiveCamera } from '@react-three/drei'
import * as THREE from 'three'
import { useEditorStore } from '@/stores/editor-store'
import { AnimationEngine } from '@/lib/animation-engine'

// ============ 视差位移着色器 ============
//
// 算法: PlaneGeometry + 自定义 ShaderMaterial
// - uTexture:       原图采样器
// - uDepthTexture:  深度图灰度 PNG 采样器
// - disparityScale: 视差缩放倍率
//
// 顶点着色器: 根据 UV 采样深度图 Z ∈ [0,1]，沿 Z 轴偏移顶点
//   transformed.z += (depthValue * disparityScale);
//
// 片元着色器: 边缘扩展 (Edge Extend) + 空洞填充
//   - 计算深度梯度, 检测边缘断层
//   - 边缘区域: 多重采样混合 (4 方向 + 8 邻域加权)
//   - 空洞区域: 前景像素扩散填充
//   - 保证实时渲染 ≥ 30 FPS

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

    // 1. 根据 UV 坐标采样深度图灰度值, Z ∈ [0, 1]
    float depthValue = texture2D(uDepthTexture, uv).r;
    vDepthValue = depthValue;

    // 2. 顶点沿 Z 轴偏移: transformed.z += (depthValue * disparityScale)
    vec3 transformed = position;
    transformed.z += (depthValue * disparityScale);

    // 3. 动画位移 (可选, 由 uAnimType 控制)
    float t = uTime * uSpeed;

    if (uAnimType == 1) {
      // swing: 水平视差 + 前景微动
      transformed.x += sin(t) * uAmplitude * depthValue * 0.15;
      transformed.z += cos(t * 0.7) * uAmplitude * depthValue * 0.05;
    } else if (uAnimType == 2) {
      // zoom: 缓慢缩放 + 景深
      float scale = 1.0 + sin(t * 0.5) * uAmplitude * 0.08;
      transformed.xy *= scale;
      transformed.z += sin(t * 0.3) * uAmplitude * depthValue * 0.1;
    } else if (uAnimType == 3) {
      // rotate: 缓慢旋转
      float angle = sin(t * 0.4) * uAmplitude * 0.15;
      float c = cos(angle);
      float s = sin(angle);
      transformed.xz = mat2(c, -s, s, c) * transformed.xz;
    } else if (uAnimType == 4) {
      // parallax: 水平视差平移
      transformed.x += sin(t * 0.6) * uAmplitude * depthValue * 0.2;
    } else if (uAnimType == 5) {
      // dolly: 前进推进
      transformed.z += sin(t * 0.5) * uAmplitude * depthValue * 0.15;
    }

    gl_Position = projectionMatrix * modelViewMatrix * vec4(transformed, 1.0);
  }
`

const FRAGMENT_SHADER = /* glsl */ `
  uniform sampler2D uTexture;
  uniform sampler2D uDepthTexture;
  uniform vec2 uTexelSize;       // 1.0 / textureSize, 用于采样偏移
  uniform float uEdgeThreshold;  // 边缘梯度阈值
  uniform int uArtStyle;         // 0=original, 1=anime, 2=oil_painting, 3=watercolor, 4=sketch, 5=cyberpunk, 6=vintage

  varying vec2 vUv;
  varying float vDepthValue;

  // ---- 深度梯度计算 (Sobel) ----
  float computeDepthGradient(vec2 uv) {
    float d00 = texture2D(uDepthTexture, uv + vec2(-uTexelSize.x, -uTexelSize.y)).r;
    float d10 = texture2D(uDepthTexture, uv + vec2( 0.0,          -uTexelSize.y)).r;
    float d20 = texture2D(uDepthTexture, uv + vec2( uTexelSize.x, -uTexelSize.y)).r;
    float d01 = texture2D(uDepthTexture, uv + vec2(-uTexelSize.x,  0.0)).r;
    float d21 = texture2D(uDepthTexture, uv + vec2( uTexelSize.x,  0.0)).r;
    float d02 = texture2D(uDepthTexture, uv + vec2(-uTexelSize.x,  uTexelSize.y)).r;
    float d12 = texture2D(uDepthTexture, uv + vec2( 0.0,           uTexelSize.y)).r;
    float d22 = texture2D(uDepthTexture, uv + vec2( uTexelSize.x,  uTexelSize.y)).r;

    // Sobel 水平/垂直梯度
    float gx = -d00 - 2.0*d01 - d02 + d20 + 2.0*d21 + d22;
    float gy = -d00 - 2.0*d10 - d20 + d02 + 2.0*d12 + d22;

    return sqrt(gx * gx + gy * gy);
  }

  // ---- Edge Extend: 边缘像素多重采样混合 ----
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

  // ---- 空洞填充: 前景像素扩散 ----
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

  // ---- 画风后处理 ----

  // 动漫风格: 色阶量化 + 边缘描线
  vec3 animeStyle(vec3 color, vec2 uv) {
    // 色阶量化 (posterization): 将连续色阶分成少量离散色阶
    float levels = 6.0;
    vec3 quantized = floor(color * levels + 0.5) / levels;

    // 边缘检测 (Sobel on luminance)
    float l = dot(color, vec3(0.299, 0.587, 0.114));
    float lLeft  = dot(texture2D(uTexture, uv - vec2(uTexelSize.x, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lRight = dot(texture2D(uTexture, uv + vec2(uTexelSize.x, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lUp    = dot(texture2D(uTexture, uv - vec2(0.0, uTexelSize.y)).rgb, vec3(0.299, 0.587, 0.114));
    float lDown  = dot(texture2D(uTexture, uv + vec2(0.0, uTexelSize.y)).rgb, vec3(0.299, 0.587, 0.114));
    float edge = abs(lLeft - lRight) + abs(lUp - lDown);
    float outline = smoothstep(0.05, 0.15, edge);

    // 混合: 量化色 + 描线
    return mix(quantized, vec3(0.05), outline * 0.7);
  }

  // 油画风格: 多方向 Kuwahara 滤波 (简化版)
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

    // 增强饱和度
    float gray = dot(smoothed, vec3(0.299, 0.587, 0.114));
    vec3 saturated = mix(vec3(gray), smoothed, 1.4);

    // 轻微暖色调
    return saturated * vec3(1.05, 1.0, 0.92);
  }

  // 水彩风格: 模糊 + 亮度提升 + 低饱和度
  vec3 watercolorStyle(vec3 color, vec2 uv) {
    vec3 sum = vec3(0.0);
    float r = 2.0;
    for (float dy = -r; dy <= r; dy += 1.0) {
      for (float dx = -r; dx <= r; dx += 1.0) {
        sum += texture2D(uTexture, uv + vec2(dx, dy) * uTexelSize * 1.5).rgb;
      }
    }
    vec3 blurred = sum / ((2.0*r+1.0) * (2.0*r+1.0));

    // 水彩: 提亮 + 降低对比度 + 略降饱和度
    vec3 brightened = (blurred + 0.15) / 1.15;
    float gray = dot(brightened, vec3(0.299, 0.587, 0.114));
    vec3 desaturated = mix(vec3(gray), brightened, 0.75);

    // 纸张纹理 (微弱噪声)
    float noise = fract(sin(dot(uv * 500.0, vec2(12.9898, 78.233))) * 43758.5453);
    desaturated += (noise - 0.5) * 0.03;

    return desaturated;
  }

  // 素描风格: 灰度 + 边缘检测反色
  vec3 sketchStyle(vec3 color, vec2 uv) {
    float l = dot(color, vec3(0.299, 0.587, 0.114));

    // 多方向边缘检测
    float edge = 0.0;
    for (float angle = 0.0; angle < 3.14159; angle += 0.3927) {
      vec2 dir = vec2(cos(angle), sin(angle)) * uTexelSize * 2.0;
      float l1 = dot(texture2D(uTexture, uv + dir).rgb, vec3(0.299, 0.587, 0.114));
      float l2 = dot(texture2D(uTexture, uv - dir).rgb, vec3(0.299, 0.587, 0.114));
      edge += abs(l1 - l2);
    }
    edge /= 8.0;

    // 素描: 白底黑线
    float sketch = 1.0 - smoothstep(0.02, 0.12, edge);
    return vec3(sketch);
  }

  // 赛博朋克风格: 高对比度 + 霓虹色调
  vec3 cyberpunkStyle(vec3 color, vec2 uv) {
    // 高对比度
    float gray = dot(color, vec3(0.299, 0.587, 0.114));
    vec3 highContrast = mix(vec3(gray), color, 1.6);
    highContrast = pow(highContrast, vec3(0.85));

    // 霓虹色调: 偏青色 + 品红高光
    highContrast.r *= 1.1;
    highContrast.g *= 0.9;
    highContrast.b *= 1.3;

    // 扫描线效果
    float scanline = 0.95 + 0.05 * sin(uv.y * 800.0);
    highContrast *= scanline;

    return highContrast;
  }

  // 复古风格: 暖色调 + 降饱和度 + 暗角
  vec3 vintageStyle(vec3 color, vec2 uv) {
    float gray = dot(color, vec3(0.299, 0.587, 0.114));
    vec3 desaturated = mix(vec3(gray), color, 0.6);

    // 暖色调偏移 (sepia-like)
    desaturated.r *= 1.15;
    desaturated.g *= 1.05;
    desaturated.b *= 0.85;

    // 暗角
    float dist = distance(uv, vec2(0.5));
    float vignette = 1.0 - smoothstep(0.4, 0.9, dist);
    desaturated *= mix(0.6, 1.0, vignette);

    // 轻微颗粒感
    float noise = fract(sin(dot(uv * 300.0, vec2(12.9898, 78.233))) * 43758.5453);
    desaturated += (noise - 0.5) * 0.06;

    return desaturated;
  }

  void main() {
    // 1. 计算深度梯度
    float gradient = computeDepthGradient(vUv);

    // 2. 边缘强度: 梯度超过阈值时为边缘
    float edgeStrength = smoothstep(uEdgeThreshold * 0.5, uEdgeThreshold * 1.5, gradient);

    // 3. 判断是否为深度断层 (空洞)
    bool isHole = gradient > uEdgeThreshold * 3.0;

    vec4 finalColor;

    if (isHole) {
      finalColor = holeFillSample(vUv, gradient);
    } else if (edgeStrength > 0.01) {
      finalColor = edgeExtendSample(vUv, edgeStrength);
    } else {
      finalColor = texture2D(uTexture, vUv);
    }

    // 4. 应用画风后处理
    if (uArtStyle == 1) {
      finalColor.rgb = animeStyle(finalColor.rgb, vUv);
    } else if (uArtStyle == 2) {
      finalColor.rgb = oilPaintingStyle(finalColor.rgb, vUv);
    } else if (uArtStyle == 3) {
      finalColor.rgb = watercolorStyle(finalColor.rgb, vUv);
    } else if (uArtStyle == 4) {
      finalColor.rgb = sketchStyle(finalColor.rgb, vUv);
    } else if (uArtStyle == 5) {
      finalColor.rgb = cyberpunkStyle(finalColor.rgb, vUv);
    } else if (uArtStyle == 6) {
      finalColor.rgb = vintageStyle(finalColor.rgb, vUv);
    }
    // uArtStyle == 0: original, 不做后处理

    gl_FragColor = finalColor;
  }
`

// ============ 视差网格组件 ============

function DepthMesh() {
  const meshRef = useRef<THREE.Mesh>(null)
  const { originalPreview, depthMapUrl, animation, isPlaying, sceneData, styleQuality, uploadedImage } = useEditorStore()
  const textureLoader = useMemo(() => new THREE.TextureLoader(), [])

  // 加载原图纹理 (uTexture)
  // NoColorSpace: 不做 sRGB→linear 转换，保持原图像素值直接输出，避免颜色偏灰
  const colorTexture = useMemo(() => {
    if (!originalPreview) return null
    const tex = textureLoader.load(originalPreview)
    tex.colorSpace = THREE.NoColorSpace
    tex.minFilter = THREE.LinearFilter
    tex.magFilter = THREE.LinearFilter
    return tex
  }, [originalPreview, textureLoader])

  // 加载深度图纹理 (uDepthTexture)
  const depthTexture = useMemo(() => {
    if (!depthMapUrl) return null
    const tex = textureLoader.load(depthMapUrl)
    tex.minFilter = THREE.LinearFilter
    tex.magFilter = THREE.LinearFilter
    return tex
  }, [depthMapUrl, textureLoader])

  // 平面几何体: 根据图片实际比例动态创建，256×256 细分保证平滑视差效果
  const geometry = useMemo(() => {
    const imgW = uploadedImage?.width || 4
    const imgH = uploadedImage?.height || 3
    const aspect = imgW / imgH
    // 固定高度为 2 单位，宽度按比例缩放
    const planeH = 2.0
    const planeW = planeH * aspect
    return new THREE.PlaneGeometry(planeW, planeH, 256, 256)
  }, [uploadedImage?.width, uploadedImage?.height])

  // 自定义 ShaderMaterial
  const shaderMaterial = useMemo(() => {
    // 从 scene 数据中读取 render_params，若无则使用默认值
    const rp = sceneData?.render_params
    return new THREE.ShaderMaterial({
      uniforms: {
        uTexture:        { value: null },   // 原图采样器
        uDepthTexture:   { value: null },   // 深度图采样器
        disparityScale:  { value: rp?.parallax_scale ?? 0.3 },    // 视差缩放倍率
        uTexelSize:      { value: new THREE.Vector2(1.0 / 1024, 1.0 / 1024) }, // 纹素尺寸, 纹理加载后更新
        uEdgeThreshold:  { value: 0.15 },   // 边缘梯度阈值
        uTime:           { value: 0 },
        uAnimType:       { value: 0 },      // 0=none, 1=swing, 2=zoom, 3=rotate, 4=parallax, 5=dolly
        uAmplitude:      { value: 0.3 },
        uSpeed:          { value: 1.0 },
        uArtStyle:       { value: 0 },      // 0=original, 1=anime, 2=oil_painting, 3=watercolor, 4=sketch, 5=cyberpunk, 6=vintage
      },
      vertexShader: VERTEX_SHADER,
      fragmentShader: FRAGMENT_SHADER,
      toneMapped: false,  // 禁用色调映射，保持原图颜色
    })
  }, [sceneData?.render_params])

  // 绑定纹理到 uniforms + 更新纹素尺寸
  useEffect(() => {
    if (colorTexture) {
      shaderMaterial.uniforms.uTexture.value = colorTexture
      // 纹理加载后更新纹素尺寸
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

  // 动画类型映射
  const animTypeMap: Record<string, number> = {
    swing: 1, zoom: 2, rotate: 3, parallax: 4, dolly: 5,
  }

  // 画风映射
  const artStyleMap: Record<string, number> = {
    original: 0, anime: 1, oil_painting: 2, watercolor: 3, sketch: 4, cyberpunk: 5, vintage: 6,
  }

  // 每帧更新 uniforms
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

  return (
    <mesh ref={meshRef} geometry={geometry} material={shaderMaterial} />
  )
}

// ============ 相机自适应组件 — 动态调整相机距离使图片完整显示在视口中 ============

function CameraFitter() {
  const { camera } = useThree()
  const { uploadedImage } = useEditorStore()

  useEffect(() => {
    const imgW = uploadedImage?.width || 4
    const imgH = uploadedImage?.height || 3
    const imageAspect = imgW / imgH

    // 与 DepthMesh 几何体一致的尺寸: 固定高度 2，宽度按比例
    const planeH = 2.0
    const planeW = planeH * imageAspect

    // 获取画布实际尺寸（需要等 Canvas 渲染后才有值）
    const canvas = document.querySelector('canvas') as HTMLCanvasElement | null
    if (!canvas) return

    const canvasAspect = canvas.clientWidth / canvas.clientHeight

    const perspCamera = camera as THREE.PerspectiveCamera
    const fov = perspCamera.fov * (Math.PI / 180)

    // contain 模式: 取较大距离，确保图片完全显示在视口内不被裁剪
    const distByHeight = (planeH / 2) / Math.tan(fov / 2)
    const distByWidth = (planeW / 2) / (Math.tan(fov / 2) * canvasAspect)
    const distance = Math.max(distByHeight, distByWidth)

    camera.position.set(0, 0, distance)
    camera.lookAt(0, 0, 0)
  }, [uploadedImage?.width, uploadedImage?.height, camera])

  return null
}

// ============ 相机动画控制器 (基于 Tween.js AnimationEngine) ============

function CameraAnimator() {
  const { camera } = useThree()
  const { animation, isPlaying } = useEditorStore()
  const engineRef = useRef<AnimationEngine | null>(null)

  // 初始化引擎
  if (!engineRef.current) {
    engineRef.current = new AnimationEngine(camera as THREE.PerspectiveCamera)
  }

  // 监听动画参数变化
  useEffect(() => {
    const engine = engineRef.current!
    if (isPlaying) {
      engine.play(animation.type, animation)
    } else {
      engine.stop()
    }
  }, [animation.type, animation.amplitude, animation.speed, animation.duration, animation.loop, isPlaying])

  // 每帧更新 Tween
  useFrame((state) => {
    if (isPlaying) {
      engineRef.current?.update(state.clock.elapsedTime * 1000)
    }
  })

  // 组件卸载时清理
  useEffect(() => {
    return () => {
      engineRef.current?.dispose()
    }
  }, [])

  return null
}

// ============ 场景主组件 ============

export function Scene3D() {
  const { step, originalPreview, depthMapUrl, sceneData } = useEditorStore()

  if (step !== 'completed' || !originalPreview) {
    return null
  }

  // 从 scene 数据中读取 render_params
  const rp = sceneData?.render_params
  const fov = rp?.fov ?? 60

  return (
    <Canvas
      gl={{
        antialias: true,
        toneMapping: THREE.NoToneMapping,
        preserveDrawingBuffer: true,  // 导出时 canvas.toBlob() 需要保留缓冲区
      }}
      style={{ width: '100%', height: '100%' }}
    >
      <PerspectiveCamera
        makeDefault
        fov={fov}
        near={rp?.near_plane ?? 0.1}
        far={rp?.far_plane ?? 100}
        position={[0, 0, 5]}  // 初始位置，由 CameraFitter 动态调整
      />

      {depthMapUrl && <DepthMesh />}

      <CameraFitter />
      <CameraAnimator />

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
      />

      <color attach="background" args={['#1a1a24']} />
    </Canvas>
  )
}
