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
// - 分层参数:       uLayerCount + uLayerScale0~4 (WebGL 1.0 兼容)
// - 边缘冻结:       uEdgeFreezeStrength (基于原图亮度梯度的边缘保护)
//
// 顶点着色器: 根据 UV 采样深度图 → 分层量化 → 每层独立视差倍率 → 动画效果
//   不再做 Z 轴偏移 (disparityScale 已移除), 视差由 CameraParallaxController 驱动
//
// 片元着色器: 边缘冻结 → 空洞填充 → 边缘扩展 → 画风后处理
//   - 边缘冻结: 检测原图亮度梯度, 强边缘直接采样 (防止人物/背景黏连)
//   - 空洞区域: 前景像素扩散填充
//   - 深度边缘: 多重采样混合
//   - 保证实时渲染 ≥ 30 FPS

const VERTEX_SHADER = /* glsl */ `
  uniform sampler2D uDepthTexture;
  uniform float uTime;
  uniform int uAnimType;
  uniform float uAmplitude;
  uniform float uSpeed;

  // 分层参数 (WebGL 1.0 兼容: 独立 uniform 变量, 不用数组)
  uniform int uLayerCount;           // 层数 (3~5), 1=不分层
  uniform float uLayerScale0;
  uniform float uLayerScale1;
  uniform float uLayerScale2;
  uniform float uLayerScale3;
  uniform float uLayerScale4;

  varying vec2 vUv;
  varying float vDepthValue;         // 原始深度值 (用于边缘冻结)
  varying float vLayeredDepth;       // 分层后的有效深度值

  // 获取指定层的视差倍率 (if-else 展开, 兼容 WebGL 1.0)
  float getLayerScale(int idx) {
    if (idx == 0) return uLayerScale0;
    else if (idx == 1) return uLayerScale1;
    else if (idx == 2) return uLayerScale2;
    else if (idx == 3) return uLayerScale3;
    else return uLayerScale4;
  }

  void main() {
    vUv = uv;

    // 1. 采样原始深度图
    float depthValue = texture2D(uDepthTexture, uv).r;
    vDepthValue = depthValue;

    // 2. 分层量化 (当 layerCount > 1 时启用)
    float effectiveDepth = depthValue;
    if (uLayerCount > 1) {
      float layerStep = 1.0 / float(uLayerCount);
      float layerIndex = floor(depthValue / layerStep);
      layerIndex = clamp(layerIndex, 0.0, float(uLayerCount) - 1.0);
      int iLayer = int(layerIndex);

      // 使用该层的视差倍率 (通过 getLayerScale 避免动态索引)
      float layerScale = getLayerScale(iLayer);
      effectiveDepth = depthValue * layerScale;

      // 平滑过渡: 层边界处做混合避免硬切边
      float layerFract = fract(depthValue / layerStep);
      float blendWidth = 0.15;  // 过渡带宽度
      if (layerFract < blendWidth && iLayer > 0) {
        float prevScale = getLayerScale(iLayer - 1);
        float mixFactor = smoothstep(0.0, blendWidth, layerFract);
        effectiveDepth = mix(depthValue * prevScale, effectiveDepth, mixFactor);
      }
    }

    vLayeredDepth = effectiveDepth;

    // 3. 动画效果 (基于分层深度)
    vec3 transformed = position;
    float t = uTime * uSpeed;

    if (uAnimType == 1) {
      // swing: 水平摆动 + 前景微动
      transformed.x += sin(t) * uAmplitude * effectiveDepth * 0.15;
      transformed.z += cos(t * 0.7) * uAmplitude * effectiveDepth * 0.05;
    } else if (uAnimType == 2) {
      // zoom: 缩放 + 景深
      float scale = 1.0 + sin(t * 0.5) * uAmplitude * 0.08;
      transformed.xy *= scale;
      transformed.z += sin(t * 0.3) * uAmplitude * effectiveDepth * 0.1;
    } else if (uAnimType == 3) {
      // rotate: 缓慢旋转
      float angle = sin(t * 0.4) * uAmplitude * 0.15;
      float c = cos(angle);
      float s = sin(angle);
      transformed.xz = mat2(c, -s, s, c) * transformed.xz;
    } else if (uAnimType == 4) {
      // parallax: 水平视差平移
      transformed.x += sin(t * 0.6) * uAmplitude * effectiveDepth * 0.2;
    } else if (uAnimType == 5) {
      // dolly: 前进推进
      transformed.z += sin(t * 0.5) * uAmplitude * effectiveDepth * 0.15;
    }
    // uAnimType == 0: none, 不做动画

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
  varying float vLayeredDepth;  // 分层后深度
  uniform float uEdgeFreezeStrength;  // 边缘冻结强度 0~1, 0=不冻结

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
    // === 1. 计算深度梯度 (用于空洞检测) ===
    float gradient = computeDepthGradient(vUv);
    float depthEdgeStrength = smoothstep(uEdgeThreshold * 0.5, uEdgeThreshold * 1.5, gradient);

    // === 2. 边缘冻结检测 (基于原图亮度梯度, 非深度梯度) ===
    float lumCenter = dot(texture2D(uTexture, vUv).rgb, vec3(0.299, 0.587, 0.114));
    float lLeft  = dot(texture2D(uTexture, vUv + vec2(-uTexelSize.x, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lRight = dot(texture2D(uTexture, vUv + vec2( uTexelSize.x, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lUp    = dot(texture2D(uTexture, vUv + vec2(0.0, -uTexelSize.y)).rgb, vec3(0.299, 0.587, 0.114));
    float lDown  = dot(texture2D(uTexture, vUv + vec2(0.0,  uTexelSize.y)).rgb, vec3(0.299, 0.587, 0.114));

    float imgEdgeGrad = abs(lLeft - lRight) + abs(lUp - lDown);
    float edgeFreezeStrength = smoothstep(0.05, 0.20, imgEdgeGrad) * uEdgeFreezeStrength;

    // === 3. 判断空洞 (边缘区域跳过空洞填充) ===
    bool isHole = gradient > uEdgeThreshold * 3.0 && edgeFreezeStrength < 0.3;

    // === 4. 选择颜色采样策略 (完整分支) ===
    vec4 finalColor;

    if (edgeFreezeStrength > 0.5) {
      // 边缘冻结区域: 直接采样原图, 不做任何混合模糊
      finalColor = texture2D(uTexture, vUv);
    } else if (isHole) {
      // 空洞区域: 前景像素扩散填充
      finalColor = holeFillSample(vUv, gradient);
    } else if (depthEdgeStrength > 0.01) {
      // 深度边缘非冻结区: 多重采样混合
      finalColor = edgeExtendSample(vUv, depthEdgeStrength);
    } else {
      // 正常区域: 直接采样
      finalColor = texture2D(uTexture, vUv);
    }

    // === 5. 应用画风后处理 (保持不变) ===
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
        uTexelSize:      { value: new THREE.Vector2(1.0 / 1024, 1.0 / 1024) }, // 纹素尺寸, 纹理加载后更新
        uEdgeThreshold:  { value: 0.15 },   // 边缘梯度阈值
        uTime:           { value: 0 },
        uAnimType:       { value: 0 },      // 0=none, 1=swing, 2=zoom, 3=rotate, 4=parallax, 5=dolly
        uAmplitude:      { value: 0.3 },
        uSpeed:          { value: 1.0 },
        uArtStyle:       { value: 0 },      // 0=original, 1=anime, 2=oil_painting, 3=watercolor, 4=sketch, 5=cyberpunk, 6=vintage
        // ===== 分层 uniforms (独立变量, 兼容 WebGL 1.0) =====
        uLayerCount:     { value: rp?.layer_count ?? 3 },
        uLayerScale0:    { value: rp?.layer_scales?.[0] ?? 0.15 },
        uLayerScale1:    { value: rp?.layer_scales?.[1] ?? 0.6 },
        uLayerScale2:    { value: rp?.layer_scales?.[2] ?? 1.3 },
        uLayerScale3:    { value: rp?.layer_scales?.[3] ?? 1.8 },
        uLayerScale4:    { value: rp?.layer_scales?.[4] ?? 2.5 },
        // ===== 边缘冻结 uniform =====
        uEdgeFreezeStrength: { value: rp?.edge_freeze_strength ?? 0.8 },
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
  // 注意: 顶点着色器已处理所有动画类型的视差效果 (swing/zoom/rotate/parallax/dolly)
  // CameraAnimator 仅在需要相机轨迹动画时启用，避免与着色器 uTime 动画冲突导致撕裂
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

// ============ 相机视差控制器 (鼠标驱动相机位移) ============
//
// 电影级 2.5D 标准做法: 相机移动 + 深度图驱动视差
// 冲突规避:
//   - 动画播放时自动禁用鼠标视差 (避免与 CameraAnimator 冲突)
//   - 不调用 lookAt() (让 OrbitControls 管理朝向)
//   - 使用 isInitialized 标志确保 basePosition 在 CameraFitter 之后记录
//
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

  // 仅在 CameraFitter 设置完成后记录一次 basePosition
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
    // 不调用 lookAt! 让 OrbitControls 管理朝向
  })

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
        preserveDrawingBuffer: false,
      }}
      frameloop="always"
      dpr={[1, 2]}
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
