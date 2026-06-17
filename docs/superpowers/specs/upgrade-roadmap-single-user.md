# 个人升级路线：单图 Depth+UV Parallax → Neural Scene Reconstruction System

> **定位**: 仅个人使用，无需多用户、SaaS、队列等基础设施
> **起点**: 当前代码已完成的 Phase 1 基础改动
> **目标**: 商业级 Immersity-like 3D 运动效果
> **日期**: 2026-06-17

---

## 一、当前状态盘点

### ✅ 已完成 (Phase 1 基础)

| 模块 | 文件 | 状态 |
|------|------|------|
| Edge-aware 深度平滑 | `ai-models/depth/depth_anything_v2/engine.py` | ✅ 已实现 |
| Otsu 分层阈值 | `engine.py` | ✅ 已实现 |
| MPI 层纹理生成 | `engine.py` `generate_mpi_layers()` | ✅ 已实现 |
| Depth+Seg 融合 | `engine.py` `fuse_with_segmentation()` | ✅ 已实现 |
| Scene Decomposition | `engine.py` `decompose_scene()` | ✅ 已实现 |
| 带置信度深度估计 | `engine.py` `predict_with_confidence()` | ✅ 已实现 |
| 前端 MPI 渲染器 | `frontend/src/components/preview/Scene3D.tsx` | ✅ 已实现 (LayerMesh + MPIScene) |
| UV clamp 改进 | `Scene3D.tsx` `clampMirrorUV()` | ✅ 已实现 |
| 相机视差替代 UV warp | `Scene3D.tsx` | ✅ 已实现 |
| 相机轨迹引擎 | `frontend/src/lib/camera-path-engine.ts` | ✅ 已实现 (4 种预设) |
| Types / Store | `frontend/src/types/index.ts` + `editor-store.ts` | ✅ 已扩展 |
| Model Manager | `ai-models/model_manager.py` | ✅ 已扩展 (SAM2/LaMa 注册 + `run_full_pipeline`) |
| SAM2 分割引擎 | `ai-models/segmentation/sam/engine.py` | ✅ 已实现 (占位) |
| LaMa Inpainting | `ai-models/inpaint/lama/engine.py` | ✅ 已实现 (含 OpenCV fallback) |
| Scene DB 模型 | `backend/app/models/scene.py` | ✅ 已扩展 |
| depth_task MPI 集成 | `backend/app/tasks/depth_task.py` | ✅ 已扩展 |

### ⚠️ 未实际联调 (代码已写但未跑通)

| 模块 | 阻塞原因 |
|------|---------|
| MPI 层纹理上传 MinIO | `depth_task.py` 中生成了但没上传和保存 URL |
| SAM2 实际推理 | 需要安装 `segment-anything-2` 包和权重 |
| LaMa 实际推理 | 需要安装模型权重 (OpenCV fallback 可用) |
| 前端 `mpiLayerUrls` 数据流 | 后端返回了但前端还没接上 |
| Camera Path Engine 集成到 Scene3D | 创建了但还没在组件中使用 |

---

## 二、升级路线（按优先级排列）

### 🟢 第 1 步：让现有 MPI 跑起来 (最关键)

**目标**: 一张图片 → 深度估计 → 3 层 MPI 纹理 → 前端能看到分层效果

这是**最重要的一步**。完成后，你的系统从"单图 shader warp"正式变成"多层 3D proxy scene"。

#### 1.1 修改 `depth_task.py` — 上传 MPI 层纹理

当前代码已经生成了 `layers` (list of PIL.Image)，但没有保存到 MinIO 也没有返回 URL。

需要改 `depth_task.py` 的 `estimate_depth` 函数:

```python
# 在 "layers = engine.generate_mpi_layers(...)" 之后加:

# 上传每层纹理到 MinIO
layer_urls = []
for i, layer_img in enumerate(layers):
    layer_key = f"mpi_layers/{user_id}/{image_id}/layer_{i}.png"
    upload_image(layer_img, layer_key)  # 复用现有上传逻辑
    layer_url = get_presigned_url(layer_key)
    layer_urls.append({
        "id": f"layer_{i}",
        "textureUrl": layer_url,
        "zIndex": [-1.0, 0.0, 1.2][i],
        "motionScale": [0.3, 0.8, 1.5][i],
        "parallaxDirection": "both",
        "blendMode": "premultiplied",
    })

# 把 layer_urls 存入 result_data
result_data["mpi_layers"] = layer_urls
```

#### 1.2 修改 `editor-store.ts` — 接上 MPI 数据

在 `triggerDepthEstimation` 或 WebSocket 消息处理中，把 `mpi_layers` 数据存到 store:

```typescript
// 在收到 task completed 消息时:
if (result.mpi_layers) {
  set({ mpiLayerUrls: result.mpi_layers })
}
```

#### 1.3 测试

- 上传一张图 → 深度估计 → 前端预览
- 应该看到 3 层独立的 PNG 纹理以不同 Z 位置排列
- 用 OrbitControls 拖拽相机，验证视差效果

---

### 🟢 第 2 步：修复后端 Python import 问题

**目标**: 所有新增模块能正常 import 运行

#### 2.1 修复 `_postprocess` 中的 `None` seg_mask

`engine.py` 第 395 行 `seg_mask = seg_result.get("seg_mask")`，但 `fuse_with_segmentation` 在没有 SAM 时 `seg_mask` 为 `None`，后续 `np.unique(seg_mask)` 会报错。

已修复 — 代码已加了 `if seg_mask is None: return` 保护。

#### 2.2 修复 `model_manager.py` 缺少的 import

`run_full_pipeline` 方法第 109 行用了 `Image.Image` 但没有 import `PIL.Image`。

已在代码中加了 `from PIL import Image as PILImage`，但类型注解应改为:

```python
async def run_full_pipeline(self, image: Any) -> dict:
```

或者在文件顶部加:

```python
from PIL import Image
```

#### 2.3 测试 Python 全链路

```bash
cd ai-models
python -c "
from depth.depth_anything_v2.engine import DepthAnythingV2Engine
from PIL import Image
import numpy as np

# 测试: 加载模型 → 深度估计 → 分层
engine = DepthAnythingV2Engine('weights/depth_anything_v2_vitl.pth')
engine.load()
img = Image.open('test.jpg')
depth = engine.predict_depth_as_array(img)
depth_uint8 = (depth * 255).astype(np.uint8)
layers = engine.generate_mpi_layers(depth_uint8, img, n_layers=3)
print(f'✅ 生成 {len(layers)} 层 MPI 纹理')
for i, layer in enumerate(layers):
    layer.save(f'layer_{i}.png')
    print(f'  Layer {i}: {layer.size}, alpha 非零像素: {np.sum(np.array(layer)[:,:,3] > 0)}')
"
```

---

### 🟡 第 3 步：集成 Camera Path Engine 到 Scene3D

**目标**: 不再只用正弦函数动画，改用预定义相机轨迹

当前 `CameraPathEngine` 已经写好，但还没在 `Scene3D.tsx` 中实际使用。

#### 3.1 在 Scene3D 中使用轨迹引擎

在 `Scene3D.tsx` 中添加:

```tsx
import { CameraPathEngine, PRESET_PATHS } from '@/lib/camera-path-engine'

function MPIScene() {
  const { camera } = useThree()
  const engineRef = useRef<CameraPathEngine | null>(null)

  useEffect(() => {
    engineRef.current = new CameraPathEngine(camera as THREE.PerspectiveCamera)
  }, [camera])

  // 自动播放电影摇摄
  useEffect(() => {
    engineRef.current?.play('cinematic_pan')
    return () => engineRef.current?.stop()
  }, [])

  useFrame(() => {
    engineRef.current?.update()
  })

  // ... 渲染层
}
```

#### 3.2 添加 UI 切换轨迹

在预览面板加一个下拉框:

```
动画类型: [电影摇摄 ▼] [缓慢环绕] [推进穿越] [上下巡视]
```

选择后调用 `engine.play(selectedPathId)`。

---

### 🟡 第 4 步：安装 SAM2 并跑通分割

**目标**: Depth + Seg 融合生效 → 分层更精准

#### 4.1 安装 SAM2

```bash
pip install segment-anything-2
```

下载权重:
```bash
# 推荐用轻量版，显存占用小
wget https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_small.pt
# 放到 ai-models/segmentation/sam/weights/
```

#### 4.2 测试 SAM2 推理

```bash
cd ai-models
python -c "
from segmentation.sam.engine import SAM2Engine
from PIL import Image

engine = SAM2Engine('segmentation/sam/weights/sam2_hiera_small.pt')
engine.load()
img = Image.open('test.jpg')
result = engine.predict(img)
print(f'✅ 检测到 {result[\"num_layers\"]} 个分割层')
print(f'  分割类别: {np.unique(result[\"seg_mask\"])}')
print(f'  置信度: {result[\"confidence\"]}')
"
```

#### 4.3 验证融合效果

```python
# 完整流水线测试
depth_result = engine.predict_with_confidence(img)
seg_result = sam_engine.predict(img)
fused = engine.fuse_with_segmentation(depth_result, seg_result)
layers = engine.decompose_scene(fused, img, n_layers=3)
print(f'✅ 分层后: {len(layers)} 层')
for i, l in enumerate(layers):
    print(f'  Layer {i}: z={l["z_position"]}, motion={l["motion_scale"]}, '
          f'occlusion={l["occlusion_mask"].sum()}px')
```

---

### 🟡 第 5 步：LaMa Inpainting (先 OpenCV fallback，后 LaMa)

**目标**: 移动视角时遮挡区域不露黑洞

#### 5.1 先用 OpenCV fallback (零依赖)

`LaMaInpaintEngine` 已写了 OpenCV fallback。当前代码在 `model is None` 时自动用 `cv2.inpaint`。

测试:
```python
from inpaint.lama.engine import LaMaInpaintEngine
from PIL import Image
import numpy as np

engine = LaMaInpaintEngine(None)  # 不加载模型, 用 fallback
img = Image.open('test.jpg')
mask = np.zeros((img.height, img.width), dtype=np.uint8)
mask[100:200, 100:200] = 255  # 模拟遮挡区域
result = engine.inpaint_layer(img, mask, img)
result.save('inpainted.png')
```

#### 5.2 安装 LaMa (可选, 效果更好)

```bash
pip install lama-cleaner
# 下载权重
wget https://huggingface.co/akhaliq/lama/resolve/main/big-lama.pt
```

---

### 🔴 第 6 步：后端 Scene API (个人使用可简化)

**目标**: 保存/加载 MPI 场景数据

因为是个人使用，可以**跳过 Celery + 复杂队列**，改用同步调用:

#### 6.1 简化方案: 直接在 `depth_task.py` 中同步返回

```python
# 新增端点: POST /api/v1/depth/estimate-mpi
@router.post("/estimate-mpi")
async def estimate_depth_mpi(file: UploadFile):
    """同步: 上传 → 深度+分割+分层 → 返回 MPI 数据"""
    image = Image.open(file.file)
    manager = ModelManager()

    # 1. 完整场景分析
    fused = await manager.run_full_pipeline(image)

    # 2. 分解为层
    engine = manager.get_engine("depth_anything_v2")
    layers = engine.decompose_scene(fused, image, n_layers=3)

    # 3. Inpainting (如果可用)
    # ... (同 depth_task.py 中的逻辑)

    # 4. 保存层纹理到本地 (不用 MinIO, 直接写磁盘)
    os.makedirs("data/mpi", exist_ok=True)
    layer_urls = []
    for i, layer_data in enumerate(layers):
        path = f"data/mpi/layer_{i}.png"
        layer_data["texture"].save(path)
        layer_urls.append({
            "id": f"layer_{i}",
            "textureUrl": f"/api/v1/files/mpi/layer_{i}.png",
            "zIndex": layer_data["z_position"],
            "motionScale": layer_data["motion_scale"],
        })

    return {"mpi_layers": layer_urls, "metadata": {...}}
```

#### 6.2 文件服务

```python
@router.get("/files/mpi/{filename}")
async def serve_mpi_file(filename: str):
    return FileResponse(f"data/mpi/{filename}")
```

---

### 🔴 第 7 步：完整集成测试

**目标**: 端到端跑通

```
1. 前端上传图片
     ↓
2. 调用 /depth/estimate-mpi (同步或异步)
     ↓
3. 后端:
   - Depth Anything V2 → 深度图
   - SAM2 → 分割掩码
   - fuse_with_segmentation → 融合深度
   - decompose_scene → 3 层数据
   - LaMa (或 OpenCV) → 每层 inpainting
   - 保存层纹理到磁盘
     ↓
4. 返回 {mpi_layers: [...], metadata: {...}}
     ↓
5. 前端 store 存入 mpiLayerUrls
     ↓
6. Scene3D 自动切换到 <MPIScene />
     ↓
7. CameraPathEngine 播放预设轨迹
     ↓
8. 用户看到分层视差效果 ✅
```

---

### 🟢 第 8 步：优化体验 (锦上添花)

#### 8.1 鼠标拖拽视差 (Phase 1.3 已完成，验证即可)

当前 `CameraParallaxController` 已经实现，确保在 `Scene3D` 中使用:

```tsx
{!isPlaying && <CameraParallaxController />}
```

#### 8.2 层数自适应

简单规则:
```python
# 在 decompose_scene 中:
# 场景简单 (分割类别少) → 3 层
# 场景复杂 (人物+多物体) → 5 层
n_layers = min(seg_result.get("num_layers", 3), 5)
```

#### 8.3 性能监控

加一个简单的计时器:
```python
import time
start = time.time()
# ... 处理流程
elapsed = time.time() - start
print(f"总耗时: {elapsed:.1f}s")
print(f"  深度估计: {depth_time:.2f}s")
print(f"  分割: {seg_time:.2f}s")
print(f"  分层+Inpainting: {layer_time:.2f}s")
```

---

## 三、执行顺序 (推荐)

| 优先级 | 步骤 | 预计效果 | 风险 |
|--------|------|---------|------|
| **P0** | 第 1 步: MPI 跑起来 | 分层视差生效 | 低 |
| **P0** | 第 2 步: Python import 修复 | 全链路无报错 | 低 |
| **P1** | 第 3 步: Camera Path 集成 | 电影级动画 | 低 |
| **P1** | 第 4 步: SAM2 分割 | 分层更精准 | 中 (显存) |
| **P2** | 第 5 步: Inpainting | 遮挡不露黑洞 | 低 (fallback 可用) |
| **P2** | 第 6 步: Scene API | 场景可保存/加载 | 低 |
| **P3** | 第 7 步: 端到端测试 | 完整验证 | 中 |
| **P3** | 第 8 步: 体验优化 | 锦上添花 | 低 |

**建议**: 先跑通 1→2→3 (不依赖新模型，只用现有 Depth Anything V2)，看到分层视差效果后，再逐步加 SAM2 → Inpainting。

---

## 四、最小可用路径 (最快看到效果)

如果只想快速看到效果，只做这 3 步:

```
第 1 步: depth_task.py 上传 MPI 层纹理 (5 分钟改代码)
第 2 步: editor-store.ts 接上数据 (2 分钟)
第 3 步: 刷新前端预览 (10 秒)
```

改完这 3 处，上传一张图，你应该就能看到 **3 层独立 PNG 以不同 Z 位置排列 + OrbitControls 拖拽视差**。

---

## 五、模型权重清单 (按需下载)

| 模型 | 权重文件 | 大小 | 用途 | 必须? |
|------|---------|------|------|-------|
| Depth Anything V2 | `depth_anything_v2_vitl.pth` | ~1.2GB | 深度估计 | ✅ 已有 |
| SAM2 (轻量版) | `sam2_hiera_small.pt` | ~120MB | 分割 | 🟡 推荐 |
| SAM2 (完整版) | `sam2_hiera_large.pt` | ~320MB | 分割 | 🔴 可选 |
| LaMa | `big-lama.pt` | ~200MB | Inpainting | 🔴 可选 (OpenCV fallback) |

---

*文档结束。按 P0 → P1 → P2 顺序执行即可。*
