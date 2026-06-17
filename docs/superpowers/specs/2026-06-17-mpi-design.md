# MPI 多平面图像架构 - 设计文档

> **Date:** 2026-06-17
> **Status:** Approved
> **Scope:** 渲染架构从单平面顶点位移升级为 MPI 多平面, 彻底解决撕裂和遮挡问题

## 问题背景

当前单 PlaneGeometry + 顶点位移架构存在 3 个根本性缺陷:

1. **UV 拉伸撕裂**: 顶点 `transformed.x += sin(t) * effectiveDepth` — 邻近顶点 depth 不同导致位移不一致, 纹理被拉伸撕裂
2. **深度断层无约束**: `texture2D(uDepthTexture, uv).r` 直接采样, 0.45→0.98 的跳变无平滑处理
3. **无遮挡处理**: 单平面无法实现遮挡 — 前景移动后背景"穿出来"

## 解决方案: MPI (Multi-Plane Image)

将单平面替换为 N 个独立平面, 按深度 Z 排序渲染, 利用 WebGL 深度测试实现天然遮挡。

```
当前: 1 个 PlaneGeometry(256x256) + 顶点位移 → 撕裂 + 无遮挡
MPI:  N 个 PlaneGeometry(1x1) 按 Z 排序 → 天然遮挡 + 无撕裂
```

## 架构设计

### 数据流

```
后端 engine.py:
  深度图 → Otsu 双阈值切分 3 层 → 每层 mask
  原图 × mask → 3 张 RGBA PNG (透明背景)
  上传 MinIO → 返回 3 个 URL

前端 Scene3D.tsx:
  加载 3 张层纹理
  每层创建 mesh, position.z = layerDepth
  相机视差/动画 → 整层平移 (无顶点位移)
  WebGL depthTest 自动处理遮挡
```

### 文件变更总览

| 文件 | 操作 | 变更 |
|------|------|------|
| `ai-models/depth/depth_anything_v2/engine.py` | 新增方法 | `_generate_mpi_layers()` + `_compute_layer_thresholds()` |
| `backend/app/tasks/depth_task.py` | 修改 | 生成层纹理 + 上传 MinIO + DB 记录 |
| `frontend/src/components/preview/Scene3D.tsx` | 重写 | `DepthMesh` → `MPILayers` + `LayerMesh` |
| `frontend/src/stores/editor-store.ts` | 修改 | 新增 `mpiLayerUrls` 状态 |

## 详细模块设计

### Module A: 后端层纹理生成 (engine.py)

**新增方法**: `_generate_mpi_layers()`

```python
def _generate_mpi_layers(
    self, depth_uint8: np.ndarray, original_image: Image.Image, n_layers: int = 3
) -> list[Image.Image]:
    """将原图按深度切分为 N 层 RGBA 纹理

    Args:
        depth_uint8: 后处理完成的 uint8 深度图
        original_image: 原始 RGB 图像
        n_layers: 层数 (默认 3)

    Returns:
        list of RGBA PIL Image, 按深度从远到近排序
    """
    # 1. 计算层边界阈值
    thresholds = self._compute_layer_thresholds(depth_uint8, n_layers)

    # 2. 原图转 RGBA
    original_rgba = np.array(original_image.convert("RGBA"))

    layers = []
    for i in range(n_layers):
        # 3. 创建 mask: depth 在 [thresholds[i], thresholds[i+1]) 的像素
        if i < n_layers - 1:
            mask = ((depth_uint8 >= thresholds[i]) &
                    (depth_uint8 < thresholds[i + 1])).astype(np.uint8) * 255
        else:
            mask = (depth_uint8 >= thresholds[i]).astype(np.uint8) * 255

        # 4. 边缘膨胀 (避免层间透明缝)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask = cv2.dilate(mask, kernel, iterations=1)

        # 5. 原图 × mask → RGBA 层纹理
        layer = original_rgba.copy()
        layer[:, :, 3] = mask  # alpha = mask
        layers.append(Image.fromarray(layer))

    return layers


def _compute_layer_thresholds(
    self, depth_uint8: np.ndarray, n_layers: int
) -> list[int]:
    """计算层边界阈值

    3层: 用 Otsu 找两个分界点 → [0, t1, t2, 255]
    其他: 等间距切分
    """
    if n_layers == 3:
        # 两级 Otsu: 先整体 Otsu 分两半, 再对每半做 Otsu
        _, binary1 = cv2.threshold(
            depth_uint8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        t1 = int(np.median(depth_uint8[binary1 == 0])) if np.any(binary1 == 0) else 85
        t2 = int(np.median(depth_uint8[binary1 == 255])) if np.any(binary1 == 255) else 170
        return [0, t1, t2]
    else:
        # 等间距
        step = 256 // n_layers
        return [i * step for i in range(n_layers)]
```

**层间边缘处理**: 每层 mask 膨胀 1px (3x3 椭圆核), 相邻层有 1px 重叠 → 消除透明缝

### Module B: 后端存储层纹理 (depth_task.py)

在 `estimate_depth` 任务中, 深度图生成完成后新增:

```python
# 生成 MPI 层纹理
n_layers = 3
mpi_layers = engine._generate_mpi_layers(depth_result, original_image, n_layers)

# 上传每层到 MinIO
layer_urls = []
for i, layer_img in enumerate(mpi_layers):
    layer_key = f"depth/{image_id}/mpi_layer_{i}.png"
    layer_buf = io.BytesIO()
    layer_img.save(layer_buf, format="PNG")
    layer_buf.seek(0)
    await minio_client.put_object(layer_key, layer_buf, content_type="image/png")
    layer_urls.append(get_url(layer_key))
```

**DB params 新增**:
```python
params={
    ...,
    "mpi_layers": n_layers,
    "mpi_layer_urls": layer_urls,  # [url_bg, url_mid, url_fg]
}
```

### Module C: 前端 MPI 渲染 (Scene3D.tsx)

**替换** `DepthMesh` 组件为 `MPILayers`:

```tsx
// MPI 层 Z 位置 (非线性, 近大远小)
const LAYER_Z_POSITIONS = [-1.0, 0.0, 1.2]  // 背景/中景/前景

function MPILayers() {
  const { mpiLayerUrls, uploadedImage, animation, isPlaying, sceneData, styleQuality } = useEditorStore()

  if (!mpiLayerUrls || mpiLayerUrls.length === 0) return null

  return (
    <>
      {mpiLayerUrls.map((url, i) => (
        <LayerMesh
          key={i}
          textureUrl={url}
          zPosition={LAYER_Z_POSITIONS[i] ?? 0}
          layerIndex={i}
          artStyle={styleQuality.artStyle}
        />
      ))}
    </>
  )
}
```

**LayerMesh 组件** (每层一个简单平面):

```tsx
function LayerMesh({ textureUrl, zPosition, layerIndex, artStyle }: Props) {
  const meshRef = useRef<THREE.Mesh>(null)
  const texture = useMemo(() => {
    const tex = new THREE.TextureLoader().load(textureUrl)
    tex.colorSpace = THREE.NoColorSpace
    tex.minFilter = THREE.LinearFilter
    tex.magFilter = THREE.LinearFilter
    tex.premultiplyAlpha = true  // 预乘 alpha 避免边缘黑边
    return tex
  }, [textureUrl])

  const geometry = useMemo(() => {
    const imgW = uploadedImage?.width || 4
    const imgH = uploadedImage?.height || 3
    const aspect = imgW / imgH
    return new THREE.PlaneGeometry(2.0 * aspect, 2.0, 1, 1)  // 1x1 细分足够
  }, [uploadedImage])

  const material = useMemo(() => {
    return new THREE.ShaderMaterial({
      uniforms: {
        uTexture: { value: texture },
        uArtStyle: { value: artStyleMap[artStyle] ?? 0 },
        uTexelSize: { value: new THREE.Vector2(1/1024, 1/1024) },
      },
      vertexShader: LAYER_VERTEX_SHADER,  // 简单: position + uv pass-through
      fragmentShader: LAYER_FRAGMENT_SHADER,  // 透明丢弃 + 画风
      transparent: true,
      depthTest: true,      // ★ 启用深度测试
      depthWrite: true,     // ★ 写入深度缓冲
      toneMapped: false,
    })
  }, [texture, artStyle])

  return (
    <mesh
      ref={meshRef}
      geometry={geometry}
      material={material}
      position={[0, 0, zPosition]}
    />
  )
}
```

**LAYER_VERTEX_SHADER** (极简, 无顶点位移):
```glsl
varying vec2 vUv;
void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
```

**LAYER_FRAGMENT_SHADER** (透明丢弃 + 画风):
```glsl
uniform sampler2D uTexture;
uniform int uArtStyle;
uniform vec2 uTexelSize;
varying vec2 vUv;

// ... 画风函数 (animeStyle, oilPaintingStyle 等, 从现有代码迁移) ...

void main() {
    vec4 color = texture2D(uTexture, vUv);
    if (color.a < 0.01) discard;  // 透明像素丢弃, 不写入深度

    // 应用画风
    if (uArtStyle == 1) color.rgb = animeStyle(color.rgb, vUv);
    else if (uArtStyle == 2) color.rgb = oilPaintingStyle(color.rgb, vUv);
    // ... 其他画风 ...

    gl_FragColor = color;
}
```

### Module D: 动画兼容性

| 组件 | 变化 | 说明 |
|------|------|------|
| CameraAnimator | **无变化** | 相机移动天然产生层间视差 |
| CameraParallaxController | **无变化** | 鼠标驱动相机位移 |
| 顶点着色器动画 | **移除** | 不再需要顶点位移, 整层跟随相机 |
| CameraFitter | **微调** | 需考虑最前景层的 Z 偏移 |

**关键**: 动画完全由相机驱动, 每层 mesh 静止不动。相机移动时, 不同 Z 位置的层产生不同视差 → 自然立体感, 无撕裂。

### Module E: editor-store.ts 变更

```typescript
interface EditorState {
  // ... 现有字段 ...
  mpiLayerUrls: string[] | null  // 新增: MPI 层纹理 URL 数组
}
```

在 `estimateDepth` 完成后, 从 API 响应中解析 `mpi_layer_urls` 并设置到 store。

## 渲染顺序保证

Three.js 默认按 `renderOrder` (默认 0) + 距相机距离排序透明物体。为确保正确遮挡:

```tsx
// 在 LayerMesh 中设置 renderOrder (远→近 = 0,1,2)
<mesh renderOrder={layerIndex} ... />
```

配合 `depthTest: true` + `depthWrite: true`, 即使渲染顺序不完美, 深度缓冲也能保证正确遮挡。

## 性能预估

| 指标 | 当前 (单平面 256x256) | MPI (3层 1x1) | 变化 |
|------|---------------------|---------------|------|
| 顶点数 | 65,536 | 4 × 3 = 12 | -99.9% |
| 片元数 | ~1M (全屏) | ~1M (3层覆盖) | 持平 |
| Draw Call | 1 | 3 | +2 |
| 纹理内存 | 2 张 (原图+深度) | 3 张 (层纹理) | +1 张 |
| **总体** | — | — | **GPU 负载降低** |

顶点数大幅减少 (65K → 12), GPU 负载实际降低。

## 向后兼容

- 保留原有 `DepthMesh` 组件作为 fallback
- `Scene3D` 主组件根据 `mpiLayerUrls` 是否存在切换渲染:
  ```tsx
  {mpiLayerUrls && mpiLayerUrls.length > 0 ? <MPILayers /> : depthMapUrl && <DepthMesh />}
  ```
- 后端层纹理生成是可选的, 不影响现有深度图生成流程
- `editor-store.ts` 新增 `mpiLayerUrls: string[] | null` 字段, 默认 null

## 后续升级路径

1. **5 层 MPI**: 从 3 层扩展到 5 层, 更细腻的深度分层
2. **层间 inpainting**: 对每层边缘做 inpainting 填充, 进一步消除层间缝隙
3. **动态层数**: 根据深度图复杂度自适应选择 3~5 层
