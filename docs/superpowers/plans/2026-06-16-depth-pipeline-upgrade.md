# 深度处理管线升级 - 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 升级 LeiaPix AI 的深度图后处理管线和前端 3D 渲染，实现电影级 2.5D 效果（Gamma 重映射、分层视差、边缘冻结、前景强化、相机视差）

**Architecture:** 后端 engine.py 的 `_postprocess()` 增加 Gamma 曲线和 Otsu 自适应前景强化；前端 Scene3D.tsx 顶点/片元着色器重写，从"顶点 Z 偏移"改为"相机位移 + 分层深度 + 边缘保护"

**Tech Stack:** Python (NumPy, OpenCV, PyTorch), GLSL (WebGL 着色器), React Three Fiber, Three.js

---

## 文件变更总览

| 文件 | 操作 | 职责 |
|------|------|------|
| `ai-models/depth/depth_anything_v2/engine.py` | 修改 | `_postprocess()` 增加 Gamma + Otsu 前景强化 |
| `frontend/src/components/preview/Scene3D.tsx` | 修改 | 着色器重写：分层 + 边缘冻结 + 相机视差 |

---

### Task 1: 后端 Gamma 非线性深度重映射

**Files:**
- Modify: `ai-models/depth/depth_anything_v2/engine.py:114-155`

- [ ] **Step 1: 在 `_postprocess()` 中添加 Gamma 非线性重映射**

在现有线性归一化之后、双边滤波之前，插入 Gamma 曲线处理：

```python
def _postprocess(
    self, output: torch.Tensor, original_size: tuple[int, int]
) -> np.ndarray:
    """后处理: 插值 → Gamma重映射 → Otsu前景强化 → 双边滤波 → 8位灰度

    Steps:
        1. 双线性插值回原始尺寸
        2. 线性归一化到 [0, 1]
        3. Gamma 非线性重映射 (前景更凸, 背景更平)
        4. Otsu 自适应前景/背景分离与增强
        5. cv2.bilateralFilter 边缘保持平滑
        6. 转为 uint8 单通道灰度图
    """
    depth = output.squeeze().unsqueeze(0).unsqueeze(0)  # (1, 1, H, W)

    # Step 1: 双线性插值回原始尺寸
    depth = F.interpolate(
        depth,
        size=(original_size[1], original_size[0]),  # (H, W)
        mode="bilinear",
        align_corners=False,
    )

    depth_np = depth.squeeze().cpu().numpy()

    # Step 2: 等比例线性映射到 [0, 1]
    depth_min = depth_np.min()
    depth_max = depth_np.max()
    if depth_max - depth_min > 0:
        depth_normalized = (depth_np - depth_min) / (depth_max - depth_min)
    else:
        depth_normalized = np.zeros_like(depth_np)

    # Step 3: Gamma 非线性重映射
    # 效果: 压缩背景深度范围, 扩展前景深度范围, 层次感立刻增强
    gamma = getattr(self, 'gamma', 1.8)  # 默认 1.8, 可配范围 1.5~2.2
    depth_normalized = np.power(np.clip(depth_normalized, 0, 1), gamma)

    # Step 4: Otsu 自适应前景/背景分离与增强 (见 Task 2)

    # Step 5: 映射到 [0, 255] 并转 uint8
    depth_uint8 = (np.clip(depth_normalized, 0, 1) * 255.0).astype(np.uint8)

    # Step 6: 双边滤波 — 边缘保持平滑, 消除网格化噪点
    depth_filtered = cv2.bilateralFilter(
        depth_uint8,
        self.BILATERAL_D,
        self.BILATERAL_SIGMA_COLOR,
        self.BILATERAL_SIGMA_SPACE,
    )

    return depth_filtered
```

- [ ] **Step 2: 在类中添加 gamma 配置属性**

在 `DepthAnythingV2Engine.__init__` 中添加：

```python
def __init__(
    self,
    model_path: str | Path,
    encoder: str = "vitl",
    max_resolution: int = MAX_RESOLUTION,
    device: str | None = None,
    gamma: float = 1.8,          # 新增: Gamma 曲线指数
):
    self.encoder = encoder
    self.max_resolution = max_resolution
    self.gamma = gamma             # 新增
    super().__init__(model_path, device)
```

同时在 `MODEL_CONFIGS` 旁边添加：

```python
# Gamma 默认值 (非线性深度重映射)
DEFAULT_GAMMA = 1.8

# 前景/背景增强系数
FG_BOOST = 1.2     # 前景深度乘数 (>1.0 让前景更突出)
BG_SUPPRESS = 0.75 # 背景深度乘数 (<1.0 让背景更扁平)
```

- [ ] **Step 3: 更新 depth_task.py 中的 params 记录**

修改 `backend/app/tasks/depth_task.py:248` 附近，在 params 中记录新参数：

```python
params={
    "bilateral_filter": {"d": 9, "sigma_color": 75, "sigma_space": 75},
    "gamma": 1.8,                    # 新增
    "fg_boost": 1.2,                 # 新增 (Task 2)
    "bg_suppress": 0.75,             # 新增 (Task 2)
},
```

- [ ] **Step 4: 手动验证 — 重启 Worker 并上传测试图片**

Run: 重启 Celery Worker (`StopCommand` 旧 worker → `RunCommand` 新 worker)
Expected: 深度图生成成功，前景区域更亮（更凸），背景区域更暗（更平）

- [ ] **Step 5: Commit**

```bash
git add ai-models/depth/depth_anything_v2/engine.py backend/app/tasks/depth_task.py
git commit -m "feat(depth): add gamma non-linear remapping for enhanced depth contrast"
```

---

### Task 2: 后端 Otsu 自适应前景强化

**Files:**
- Modify: `ai-models/depth/depth_anything_v2/engine.py` (在 Task 1 的 Step 4 位置填充)

- [ ] **Step 1: 实现 Otsu 自适应阈值分割 + 前景增强逻辑**

在 `_postprocess()` 的 Step 4 位置（Gamma 之后、uint8 转换之前）添加：

```python
    # Step 4: Otsu 自适应前景/背景分离与增强
    # 无需 SAM 等分割模型, 利用深度直方图自动找到前景/背景分界线
    fg_boost = getattr(self, 'fg_boost', FG_BOOST)
    bg_suppress = getattr(self, 'bg_suppress', BG_SUPPRESS)

    if fg_boost != 1.0 or bg_suppress != 1.0:
        # 计算归一化后的深度直方图
        hist, bin_edges = np.histogram(
            depth_normalized.flatten(), bins=256, range=(0, 1)
        )
        total = depth_normalized.size

        # Otsu 方法寻找最佳分割阈值
        best_threshold = 0.5  # 回退默认值
        best_variance = 0
        sum_all = np.sum(np.arange(256) * hist)

        for t in range(10, 245):  # 排除极端值
            w0 = np.sum(hist[:t]) / total       # 背景权重
            w1 = np.sum(hist[t:]) / total       # 前景权重
            if w0 < 0.01 or w1 < 0.01:
                continue

            sum0 = np.sum(np.arange(t) * hist[:t])
            sum1 = np.sum(np.arange(t, 256) * hist[t:])
            mu0 = sum0 / (w0 * total)
            mu1 = sum1 / (w1 * total)

            variance = w0 * w1 * (mu0 - mu1) ** 2
            if variance > best_variance:
                best_variance = variance
                best_threshold = t / 256.0

        logger.debug(f"Otsu threshold: {best_threshold:.3f}, "
                     f"fg_boost={fg_boost}, bg_suppress={bg_suppress}")

        # 应用前景增强 / 背景抑制
        fg_mask = depth_normalized > best_threshold
        depth_normalized = np.where(
            fg_mask,
            np.clip(depth_normalized * fg_boost, 0, 1),
            np.clip(depth_normalized * bg_suppress, 0, 1),
        )
```

- [ ] **Step 2: 在 `__init__` 中接收前景增强参数**

```python
def __init__(
    self,
    model_path: str | Path,
    encoder: str = "vitl",
    max_resolution: int = MAX_RESOLUTION,
    device: str | None = None,
    gamma: float = DEFAULT_GAMMA,
    fg_boost: float = FG_BOOST,      # 新增
    bg_suppress: float = BG_SUPPRESS, # 新增
):
    self.encoder = encoder
    self.max_resolution = max_resolution
    self.gamma = gamma
    self.fg_boost = fg_boost         # 新增
    self.bg_suppress = bg_suppress   # 新增
    super().__init__(model_path, device)
```

- [ ] **Step 3: Commit**

```bash
git add ai-models/depth/depth_anything_v2/engine.py
git commit -m "feat(depth): add Otsu adaptive foreground boost and background suppression"
```

---

### Task 3: 前端着色器 — 深度分层（Layering）+ 边缘冻结

**Files:**
- Modify: `frontend/src/components/preview/Scene3D.tsx`

这是改动最大的任务，需要重写顶点着色器和部分片元着色器。

- [ ] **Step 1: 重写顶点着色器 — 移除 Z 偏移，改为传递深度值 + 分层**

替换整个 `VERTEX_SHADER` 常量：

```glsl
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
```

- [ ] **Step 2: 在片元着色器中添加完整的边缘冻结逻辑**

**修改 `FRAGMENT_SHADER` 的 `varying` 区域：**

新增 varying：
```glsl
  varying float vDepthValue;    // 已有
  varying float vLayeredDepth;  // 新增: 分层后深度
```

新增 uniform：
```glsl
  uniform float uEdgeFreezeStrength;  // 边缘冻结强度 0~1, 0=不冻结
```

**重写 `FRAGMENT_SHADER` 的 `main()` 函数**（替换从 `void main()` 到 `gl_FragColor` 的全部内容）：

```glsl
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

    gl_FragColor = finalColor;
  }
```

**关键设计决策说明：**
- `edgeFreezeStrength > 0.5` 作为边缘冻结阈值：只有强边缘才完全冻结
- 边缘冻结区域直接 `texture2D(uTexture, vUv)` 而不走 `edgeExtendSample`
- 空洞判断增加 `edgeFreezeStrength < 0.3` 条件

- [ ] **Step 3: 更新 ShaderMaterial uniforms**

在 `DepthMesh` 组件的 `shaderMaterial` useMemo 中更新 uniforms：

```typescript
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
      toneMapped: false,
    })
  }, [sceneData?.render_params])
```

注意：`uLayerCount=1` 表示不分层（向后兼容），`uLayerCount=3` 为默认分层模式。WebGL 1.0 不支持 uniform 数组动态索引，因此使用 `uLayerScale0`~`uLayerScale4` 独立变量 + `getLayerScale()` if-else 函数。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/preview/Scene3D.tsx
git commit -m "feat(render): add depth layering and edge freezing to 3D shader"
```

---

### Task 4: 前端相机视差（Camera Parallax）

**Files:**
- Modify: `frontend/src/components/preview/Scene3D.tsx`

- [ ] **Step 1: 创建 CameraParallaxController 组件**

在 Scene3D.tsx 文件中，`CameraAnimator` 组件之后添加新组件：

```tsx
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
```

- [ ] **Step 2: 在 Scene3D 主组件中挂载 CameraParallaxController**

在 `<CameraAnimator />` 之后添加：

```tsx
export function Scene3D() {
  // ... 现有代码 ...

  return (
    <Canvas ...>
      <PerspectiveCamera ... />
      {depthMapUrl && <DepthMesh />}
      <CameraFitter />
      <CameraAnimator />
      <CameraParallaxController />   {/* 新增 */}
      <OrbitControls ... />
      <color attach="background" args={['#1a1a24']} />
    </Canvas>
  )
}
```

- [ ] **Step 3: 更新 OrbitControls 配置以兼容相机视差**

当启用了鼠标驱动的相机视差时，OrbitControls 可能会冲突。调整配置：

```tsx
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
  enableRotate={true}   // 允许用户手动旋转查看
/>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/preview/Scene3D.tsx
git commit -m "feat(render): add camera parallax controller replacing vertex Z-displacement"
```

---

### Task 5: 集成验证与参数调优

**Files:**
- No new files (validation only)

- [ ] **Step 1: 重启全部服务并端到端测试**

1. Stop existing backend and worker terminals
2. Start backend: `cd d:\12\conversion\backend && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
3. Start worker: `cd d:\12\conversion\backend && python -m celery -A app.core.celery_app worker --loglevel=info --queues=gpu_depth -c 1 --pool=solo`
4. Open frontend at http://localhost:3000
5. Upload test image
6. Verify depth estimation completes without errors
7. Verify 3D preview shows layered parallax effect

- [ ] **Step 2: 验证清单逐项确认**

| # | 功能 | 验证方法 | 预期结果 |
|---|------|----------|----------|
| 1 | Gamma 重映射 | 对比新旧深度图 PNG | 前景更亮(凸)，背景更暗(平) |
| 2 | 分层视差 | 移动鼠标观察 3D 预览 | 前景/中景/背景明显分层移动 |
| 3 | 边缘冻结 | 观察人物轮廓边缘 | 轮廓清晰，不与背景黏连 |
| 4 | 前景强化 | 观察人物 vs 背景立体感 | 人物"跳出来"，背景"压回去" |
| 5 | 相机视差 | 左右移动鼠标 | 场景随视角自然偏移 |

- [ ] **Step 3: Final Commit (如有微调)**

```bash
git add -A
git commit -m "feat: complete depth pipeline upgrade with 5 cinematic improvements"
```

---

## 实施顺序依赖关系

```
Task 1 (Gamma) ──→ Task 2 (Otsu前景强化) ──┐
                                           ├──→ Task 5 (集成验证)
Task 3 (分层+边缘冻结) ──→ Task 4 (相机视差) ┘
```

Task 1+2 是后端，可并行。Task 3+4 是前端，可并行。但前后端都完成后才能做 Task 5 的端到端验证。
