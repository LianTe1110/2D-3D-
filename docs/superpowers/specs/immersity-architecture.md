# 对标 Immersity AI（Immersive Motion）— 完整技术架构文档

> **目标**: 从单图 Depth+UV Parallax 升级为 Neural Scene Reconstruction System
> **日期**: 2026-06-17
> **当前基线**: LeiaPix AI 复刻版 v1 (Depth Anything V2 + 单平面 Shader Warp)

---

## 一、差距分析：我们 vs Immersity AI

### 1.1 本质区别

| 维度 | 当前实现 | Immersity AI |
|------|---------|-------------|
| **核心范式** | Depth Map + UV Parallax | Neural Scene Reconstruction |
| **AI 理解** | 单深度图 (Depth Anything V2) | Depth + Segmentation + Normal + Confidence 融合 |
| **场景表示** | 单张平面 + 顶点位移 | Multi-Plane Image (MPI) / Layered Depth Image (LDI) |
| **渲染方式** | UV Warp Shader | 相机路径驱动的多层 3D Proxy 渲染 |
| **遮挡处理** | 边缘冻结 + 空洞填充 (启发式) | AI Inpainting + View Synthesis |
| **动画驱动** | 正弦函数顶点位移 / Tween.js 相机 | 连续相机轨迹引擎 + 视角合成 |
| **输出质量** | 有撕裂风险，小角度可用 | 商业级无瑕疵沉浸体验 |

### 1.2 当前代码的致命问题

#### 问题 1: 单 Depth Map 天生不稳定

**位置**: `frontend/src/components/preview/Scene3D.tsx` 第 25-114 行

```glsl
// 当前: 仅依赖一张深度图的灰度值
float depthValue = texture2D(uDepthTexture, uv).r;  // 单一信号源
```

**后果**: 深度图在边缘处不准确 → 视差偏移量错误 → 前景背景黏连或撕裂

#### 问题 2: UV Warp 必然撕裂

**位置**: `frontend/src/components/preview/Scene3D.tsx` 第 85-109 行

```glsl
// 当前: 直接修改顶点位置做视差
transformed.x += sin(t) * uAmplitude * effectiveDepth * 0.15;
```

**后果**: 大幅度移动时 UV 拉伸超出纹理边界 → 出现黑洞/重复纹理

#### 问题 3: 无遮挡建模必穿帮

**位置**: `frontend/src/components/preview/Scene3D.tsx` 第 169-189 行

```glsl
// 当前: 启发式空洞填充 (前景像素扩散)
vec4 holeFillSample(vec2 uv, float gradient) {
    // 遍历邻域找最大深度像素填充  ← 不是真正的 inpainting
}
```

**后果**: 移动视角后被遮挡区域露出 → 显示错误内容

---

## 二、五大核心系统架构

### 系统总览

```
┌─────────────────────────────────────────────────────────────────┐
│                    INPUT: 单张 RGB 图片                          │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              ① AI Scene Understanding Layer                     │
│         Depth + Segmentation + Normal + Confidence              │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              ② Scene Decomposition & Layering                   │
│     Foreground / Midground / Background 多层分离                │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              ③ Occlusion Inpainting Pipeline                    │
│          LaMa / Stable Diffusion Inpainting 补全                │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              ④ Multi-Plane 3D Scene (MPI/LDI)                   │
│      每层独立 texture + depth + occlusion + motion             │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              ⑤ Camera Motion Path Engine                        │
│     Pan / Tilt / Dolly / Orbit 连续轨迹 + 视角合成              │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│           WebGL / Three.js Renderer → 沉浸式输出                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、系统① — AI Scene Understanding Layer

### 3.1 模型组合策略

```
输入图片 (RGB)
    ├──→ [Depth Anything V2] ──→ depth_map (HxW, float32)
    ├──→ [SAM2]               ──→ seg_mask (HxW, uint8)       ← 新增
    ├──→ [Stable Normal]      ──→ normal_map (HxWx3)          ← 新增 (可选)
    └──→ [Depth Confidence]   ──→ confidence_map (HxW)         ← 新增
                    ↓
            多模型融合 → unified_scene_tensor
```

### 3.2 后端实现方案

**新增文件**: `ai-models/segmentation/sam/engine.py`

```python
"""SAM2 分割引擎 - 场景语义理解"""

import numpy as np
from PIL import Image
from inference_engine import InferenceEngine


class SAM2Engine(InferenceEngine):
    """SAM2 自动分割引擎

    输出:
        - seg_mask: 分割掩码 (0=background, 1=foreground, 2=object)
        - class_map: 类别映射
        - confidence: 置信度图
    """

    def _load_model(self):
        from sam2.build_sam import build_sam2
        return build_sam2(self.model_path)

    def _preprocess(self, image: Image.Image) -> torch.Tensor:
        # SAM2 标准预处理
        import torchvision.transforms as T
        transform = T.Compose([
            T.Resize((1024, 1024)),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        return transform(image).unsqueeze(0).to(self.device)

    def _forward(self, tensor: torch.Tensor) -> torch.Tensor:
        with torch.no_grad():
            masks, scores, logits = self.model.predict(tensor)
        return {"masks": masks, "scores": scores, "logits": logits}

    def _postprocess(self, output, original_size):
        # 后处理: 生成 N 层分割掩码
        masks = output["masks"]
        scores = output["scores"]

        # 按置信度排序，取 Top-K 掩码
        sorted_indices = np.argsort(scores)[::-1]
        top_masks = masks[sorted_indices[:5]]  # 最多 5 个物体

        # 合并为统一分割图: 0=bg, 1~N=objects
        seg_map = np.zeros(original_size[::-1], dtype=np.uint8)
        for i, mask in enumerate(top_masks):
            mask_resized = np.array(Image.fromarray(mask.squeeze()).resize(
                original_size, Image.NEAREST
            ))
            seg_map[mask_resized > 0.5] = i + 1

        return {
            "seg_mask": seg_map,
            "num_layers": len(top_masks) + 1,  # +1 for background
            "confidence": scores[sorted_indices[:5]],
        }
```

**修改文件**: `ai-models/depth/depth_anything_v2/engine.py` 扩展

在现有 `DepthAnythingV2Engine` 中新增方法:

```python
def predict_with_confidence(self, image: Image.Image) -> dict:
    """带置信度的深度估计

    Returns:
        dict: {
            "depth": np.ndarray,        # 深度图 (H, W)
            "confidence": np.ndarray,   # 置信度图 (H, W), 高=可信
            "uncertainty": np.ndarray,  # 不确定区域 (边缘/遮挡)
        }
    """
    depth = self.predict_depth_as_array(image)

    # 基于深度梯度的启发式置信度
    grad_x = cv2.Sobel(depth, cv2.CV_64F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(depth, cv2.CV_64F, 0, 1, ksize=3)
    gradient_magnitude = np.sqrt(grad_x**2 + grad_y**2)

    # 高梯度 = 低置信度 (边缘区域不可靠)
    confidence = 1.0 - np.clip(gradient_magnitude / gradient_magnitude.max(), 0, 1)
    uncertainty = 1.0 - confidence

    return {
        "depth": depth,
        "confidence": confidence,
        "uncertainty": uncertainty,
    }


def fuse_with_segmentation(
    self, depth_result: dict, seg_result: dict
) -> dict:
    """融合深度图与分割掩码

    策略:
        - 在分割边界处信任分割结果 (覆盖深度噪声)
        - 在分割内部使用深度信息细化层级
    """
    depth = depth_result["depth"]
    seg_mask = seg_result["seg_mask"]

    # 为每个分割区域计算独立深度统计
    fused_depth = depth.copy()
    for layer_id in np.unique(seg_mask):
        if layer_id == 0:
            continue  # background
        region_mask = seg_mask == layer_id
        region_depth = depth[region_mask]

        # 用该区域的深度中位数平滑 (去除异常值)
        median_depth = np.median(region_depth)
        std_depth = np.std(region_depth)

        # 仅对异常值 (偏离中位数 > 2sigma) 做修正
        outliers = np.abs(depth - median_depth) > 2 * std_depth
        correction = np.where(region_mask & outliers, median_depth, depth)
        fused_depth = np.where(region_mask & outliers, correction, fused_depth)

    return {
        **depth_result,
        "fused_depth": fused_depth,
        "seg_mask": seg_mask,
        "num_detected_layers": seg_result["num_layers"],
    }
```

### 3.3 模型管理器扩展

**修改文件**: `ai-models/model_manager.py`

```python
class ModelManager:
    """统一模型管理器 - 支持多模型协同推理"""

    def __init__(self):
        self._engines: dict[str, InferenceEngine] = {}
        self._model_configs = {
            "depth_anything_v2": {
                "class": "DepthAnythingV2Engine",
                "path": "weights/depth_anything_v2",
                "device": "cuda:0",
            },
            "sam2": {                                    # 新增
                "class": "SAM2Engine",
                "path": "weights/sam2_hiera_large.pt",
                "device": "cuda:0",
            },
            "stable_normal": {                           # 可选
                "class": "StableNormalEngine",
                "path": "weights/stable_normal",
                "device": "cuda:0",
            },
        }

    def get_engine(self, name: str) -> InferenceEngine:
        if name not in self._engines:
            config = self._model_configs[name]
            engine_class = self._import_class(config["class"])
            self._engines[name] = engine_class(config["path"], config["device"])
            self._engines[name].load()
        return self._engines[name]

    async def run_full_pipeline(self, image: Image.Image) -> dict:
        """运行完整的场景理解流水线

        Returns:
            dict: 融合后的场景数据
        """
        import asyncio

        # 并行运行多个模型 (GPU 利用率最大化)
        depth_task = asyncio.to_thread(
            self.get_engine("depth_anything_v2").predict_with_confidence, image
        )
        seg_task = asyncio.to_thread(
            self.get_engine("sam2")._postprocess,
            self.get_engine("sam2")._forward(
                self.get_engine("sam2")._preprocess(image)
            ),
            image.size,
        )

        depth_result, seg_result = await asyncio.gather(depth_task, seg_task)

        # 融合结果
        return self.get_engine("depth_anything_v2").fuse_with_segmentation(
            depth_result, seg_result
        )
```

---

## 四、系统② — Scene Decomposition & Layering

### 4.1 分层结构定义

```
Layer 0: Background (最远层)
    ├── RGBA texture (含 alpha 遮罩)
    ├── depth offset map
    ├── occlusion mask (被前层遮挡的区域)
    └── motion scale factor (默认 0.3)

Layer 1: Midground (中间层)
    ├── RGBA texture
    ├── depth offset map
    ├── occlusion mask
    └── motion scale factor (默认 0.8)

Layer 2: Foreground (最近层)
    ├── RGBA texture
    ├── depth offset map
    ├── occlusion mask (通常为空 - 最前面没东西挡它)
    └── motion scale factor (默认 1.5)
```

### 4.2 后端分层生成

**修改文件**: `ai-models/depth/depth_anything_v2/engine.py`

```python
def decompose_scene(
    self,
    fused_result: dict,
    original_image: Image.Image,
    n_layers: int = 3,
) -> list[dict]:
    """将融合后的场景数据分解为多层

    Args:
        fused_result: fuse_with_segmentation() 的输出
        original_image: 原始 RGB 图像
        n_layers: 目标层数 (推荐 3)

    Returns:
        list[dict]: 每层的完整数据
        [
            {
                "texture": PIL.Image,      # RGBA 纹理
                "depth_map": np.ndarray,    # 该层深度图
                "occlusion_mask": np.ndarray,  # 遮挡掩码
                "z_position": float,        # Z 轴位置
                "motion_scale": float,      # 运动缩放
            },
            ...
        ]
    """
    fused_depth = fused_result["fused_depth"]
    seg_mask = fused_result["seg_mask"]
    original_rgba = np.array(original_image.convert("RGBA"))

    # 计算层深度阈值 (Otsu 自适应)
    thresholds = self._compute_layer_thresholds(
        (fused_depth * 255).astype(np.uint8), n_layers
    )

    layers = []
    z_positions = [-1.0, 0.0, 1.2]  # 从远到近
    motion_scales = [0.3, 0.8, 1.5]  # 远景慢、近景快

    for i in range(n_layers):
        # 构建该层的分割掩码
        if i < n_layers - 1:
            layer_pixel_mask = (
                (fused_depth >= thresholds[i] / 255.0) &
                (fused_depth < thresholds[i + 1] / 255.0)
            )
        else:
            layer_pixel_mask = fused_depth >= thresholds[i] / 255.0

        # 与 SAM 分割结果取交集 (更精确的边界)
        if seg_mask is not None:
            # 将 SAM 的多类掩码转为二值 (该深度范围的前景)
            sam_foreground = seg_mask > 0
            if i == n_layers - 1:  # 前景层: 取 SAM 前景 AND 深度前景
                layer_pixel_mask = layer_pixel_mask & sam_foreground
            elif i == 0:  # 背景层: 取 SAM 背景
                layer_pixel_mask = layer_pixel_mask & (~sam_foreground)

        # 生成 RGBA 纹理
        layer_rgba = original_rgba.copy()
        alpha_mask = layer_pixel_mask.astype(np.uint8) * 255

        # 边缘膨胀 (防止视差移动时露缝)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        alpha_mask = cv2.dilate(alpha_mask, kernel, iterations=5)
        layer_rgba[:, :, 3] = alpha_mask

        # 生成该层的独立深度图
        layer_depth = np.where(layer_pixel_mask, fused_depth, 0)

        # 计算遮挡掩码 (该层被更靠近相机的层遮挡的区域)
        occlusion_mask = np.zeros_like(alpha_mask)
        for j in range(i + 1, n_layers):
            if j < n_layers - 1:
                front_mask = (
                    (fused_depth >= thresholds[j] / 255.0) &
                    (fused_depth < thresholds[j + 1] / 255.0)
                ).astype(np.uint8) * 255
            else:
                front_mask = (fused_depth >= thresholds[j] / 255.0).astype(np.uint8) * 255
            front_mask = cv2.dilate(front_mask, kernel, iterations=3)
            occlusion_mask = np.maximum(occlusion_mask, front_mask)

        layers.append({
            "texture": Image.fromarray(layer_rgba),
            "depth_map": layer_depth,
            "occlusion_mask": occlusion_mask,
            "z_position": z_positions[i],
            "motion_scale": motion_scales[i],
            "layer_index": i,
        })

    return layers
```

---

## 五、系统③ — Occlusion Inpainting Pipeline

### 5.1 为什么必须 Inpainting

当相机移动时，原来被前景遮挡的背景区域会暴露出来：

```
原始视角:     [====前景====]
              [====背景====]

相机右移后:   [  前景  ]  <-- 新暴露区域!
              [====背景====][??]  <-- 这里需要 inpainting
```

没有 inpainting → 黑洞 / 拉伸 / 重复纹理

### 5.2 技术选型

| 方案 | 质量 | 速度 | 显存 | 推荐场景 |
|------|------|------|------|---------|
| **LaMa** | 高 | 快 (~100ms) | 低 (~2GB) | **生产首选** |
| Stable Diffusion Inpainting | 最高 | 慢 (~2-5s) | 高 (~8GB) | 高质量模式 |
| OpenCV Navier-Stokes | 中 | 极快 (<50ms) | 无 | Fallback |

### 5.3 LaMa Inpainting 实现

**新增文件**: `ai-models/inpaint/lama/engine.py`

```python
"""LaMa (Large Mask Inpainting) 引擎 - 遮挡区域补全"""

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from inference_engine import InferenceEngine


class LaMaInpaintEngine(InferenceEngine):
    """LaMa Resolution-Independent Inpainting

    特点:
        - Fast Fourier Convolution (FFC) 感受野无限大
        - 分辨率无关 (任意尺寸直接推理)
        - 推理速度 ~100ms (1080p on RTX 3090)
    """

    def _load_model(self) -> torch.nn.Module:
        from lama_models import build_lama_model
        model = build_lama_model(self.model_path)
        return model

    def _preprocess(self, image: Image.Image, mask: np.ndarray) -> torch.Tensor:
        """预处理: image + mask --> model input

        Args:
            image: 原始 RGB 图像
            mask: 二值遮罩 (H, W), 255=inpaint 区域
        """
        image_np = np.array(image.convert("RGB"))
        image_tensor = torch.from_numpy(image_np).float() / 255.0
        image_tensor = image_tensor.permute(2, 0, 1).unsqueeze(0)  # (1,3,H,W)

        mask_tensor = torch.from_numpy(mask.astype(np.float32)) / 255.0
        mask_tensor = mask_tensor.unsqueeze(0).unsqueeze(0)  # (1,1,H,W)

        return {"image": image_tensor.to(self.device), "mask": mask_tensor.to(self.device)}

    def _forward(self, inputs: dict) -> torch.Tensor:
        image = inputs["image"]
        mask = inputs["mask"]

        # masked 输入 (LaMa 用 mask 占位)
        masked_image = image * (1 - mask)

        with torch.no_grad():
            output = self.model(masked_image, mask)

        return output

    def _postprocess(self, output: torch.Tensor, original_size: tuple) -> np.ndarray:
        result = output.squeeze().permute(1, 2, 0).cpu().numpy()
        result = (result * 255).clip(0, 255).astype(np.uint8)
        return result

    def inpaint_layer(
        self,
        layer_texture: Image.Image,
        occlusion_mask: np.ndarray,
        original_image: Image.Image,
    ) -> Image.Image:
        """对单层执行 inpainting

        Args:
            layer_texture: 该层 RGBA 纹理
            occlusion_mask: 该层的遮挡掩码 (需要补全的区域)
            original_image: 原始完整图像 (作为 inpainting 参照)

        Returns:
            inpainted RGBA Image
        """
        # 只对有效遮挡区域 inpaint (mask > 128)
        valid_mask = (occlusion_mask > 128).astype(np.uint8) * 255

        if valid_mask.sum() < 100:  # 遮挡面积太小，跳过
            return layer_texture

        # 使用原图作为 inpainting 参考
        inputs = self._preprocess(original_image, valid_mask)
        output = self._forward(inputs)
        inpainted_rgb = self._postprocess(output, original_image.size)

        # 将 inpainted 结果合并到层纹理的遮挡区域
        layer_np = np.array(layer_texture.convert("RGBA"))
        mask_binary = valid_mask > 128

        # 仅替换 alpha > 0 且被遮挡的像素
        replace_region = mask_binary & (layer_np[:, :, 3] > 0)
        layer_np[replace_region, :3] = inpainted_rgb[replace_region]

        return Image.fromarray(layer_np)
```

### 5.4 完整 Inpainting 流程集成

**修改文件**: `backend/app/tasks/depth_task.py`

在现有 `estimate_depth` 任务中增加 inpainting 步骤:

```python
# ========== 5.5 Occlusion Inpainting (新增) ==========
await redis_client.set_task_progress(
    task_id=task_id, status="processing", progress=85,
    task_type="depth", user_id=user_id,
)

from ai_models.inpaint.lama.engine import LaMaInpaintEngine
inpaint_engine = LaMaInpaintEngine("weights/lama_large")

for i, layer in enumerate(layers):
    if layer["occlusion_mask"].sum() > 1000:  # 有显著遮挡
        layer["texture"] = inpaint_engine.inpaint_layer(
            layer_texture=layer["texture"],
            occlusion_mask=layer["occlusion_mask"],
            original_image=image,
        )
        logger.info(f"Layer {i} inpainting completed")
```

---

## 六、系统④ — Multi-Plane 3D Scene (MPI/LDI)

### 6.1 MPI 数据结构

```typescript
// frontend/src/types/index.ts 新增

export interface MPILayer {
  id: string                    // 层唯一标识
  textureUrl: string            // RGBA 纹理 URL (MinIO/S3)
  depthMapUrl?: string          // 该层深度图 URL (可选, 用于精细视差)
  zIndex: number                // Z 轴位置 (从远到近递增)
  motionScale: number           // 视差运动倍率
  parallaxDirection: 'horizontal' | 'vertical' | 'both'
  blendMode: 'normal' | 'additive' | 'premultiplied'
}

export interface MPIScene {
  layers: MPILayer[]
  cameraConfig: {
    fov: number
    nearPlane: number
    farPlane: number
    baseDistance: number
  }
  metadata: {
    width: number
    height: number
    layerCount: number
    modelUsed: string
    processingTimeMs: number
  }
}
```

### 6.2 前端 MPI 渲染器 (重写 Scene3D)

这是最大的改动 — 将现有的单平面 `DepthMesh` 替换为多层 MPI 架构。

```tsx
// frontend/src/components/preview/Scene3D.tsx
// ===== 新版 MPI 架构 =====

const LAYER_VERTEX_SHADER = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const LAYER_FRAGMENT_SHADER = /* glsl */ `
  uniform sampler2D uTexture;
  uniform sampler2D uDepthTexture;      // 该层独立深度图 (可选)
  uniform float uMotionScale;           // 该层运动倍率
  uniform vec2 uCameraOffset;           // 相机偏移 (-1~1)
  uniform int uArtStyle;
  uniform vec2 uTexelSize;
  varying vec2 vUv;

  // === 视差偏移计算 ===
  vec2 parallaxOffset(vec2 uv, vec2 camOffset, float scale) {
    if (uDepthTexture != NULL) {
      float d = texture2D(uDepthTexture, uv).r;
      return camOffset * d * scale;
    }
    // 无深度图时用均匀偏移
    return camOffset * scale * 0.5;
  }

  void main() {
    vec2 offset = parallaxOffset(vUv, uCameraOffset, uMotionScale);
    vec4 color = texture2D(uTexture, vUv + offset);

    if (color.a < 0.02) discard;

    // 画风后处理 (保留原有 anime/oil_painting 等)
    color.rgb = applyArtStyle(color.rgb, vUv, uArtStyle);

    // 预乘 Alpha 输出 (正确的透明混合)
    gl_FragColor = vec4(color.rgb * color.a, color.a);
  }
`

// ===== 单层 Mesh 组件 =====

const DEFAULT_Z_POSITIONS = [-1.0, 0.0, 1.2]
const DEFAULT_MOTION_SCALES = [0.3, 0.8, 1.5]

interface LayerMeshProps {
  layer: MPILayer
  index: number
  cameraOffset: React.MutableRefObject<THREE.Vector2>
  artStyle: number
}

function LayerMesh({ layer, index, cameraOffset, artStyle }: LayerMeshProps) {
  const meshRef = useRef<THREE.Mesh>(null)
  const { uploadedImage } = useEditorStore()

  const texture = useMemo(() => {
    const tex = new THREE.TextureLoader().load(layer.textureUrl)
    tex.colorSpace = THREE.NoColorSpace
    tex.minFilter = THREE.LinearFilter
    tex.magFilter = THREE.LinearFilter
    tex.anisotropy = 16  // 各向异性过滤 (斜视角防模糊)
    return tex
  }, [layer.textureUrl])

  const geometry = useMemo(() => {
    const imgW = uploadedImage?.width || 4
    const imgH = uploadedImage?.height || 3
    const aspect = imgW / imgH
    return new THREE.PlaneGeometry(2.0 * aspect, 2.0, 64, 64)  // 细分降低 (每层独立)
  }, [uploadedImage])

  const material = useMemo(() => {
    const isForeground = index === DEFAULT_Z_POSITIONS.length - 1
    return new THREE.ShaderMaterial({
      uniforms: {
        uTexture: { value: texture },
        uDepthTexture: { value: null },  // 可选加载
        uMotionScale: { value: layer.motionScale ?? DEFAULT_MOTION_SCALES[index] },
        uCameraOffset: { value: new THREE.Vector2(0, 0) },
        uArtStyle: { value: artStyle },
        uTexelSize: { value: new THREE.Vector2(1/1024, 1/1024) },
      },
      vertexShader: LAYER_VERTEX_SHADER,
      fragmentShader: LAYER_FRAGMENT_SHADER,
      transparent: true,
      depthTest: true,
      depthWrite: isForeground,       // 只有最前层写入深度缓冲
      blending: THREE.CustomBlending,
      blendSrc: THREE.OneFactor,
      blendDst: THREE.OneMinusSrcAlphaFactor,
      toneMapped: false,
    })
  }, [texture, layer.motionScale, artStyle])

  // 每帧更新相机偏移
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
      position={[0, 0, layer.zIndex ?? DEFAULT_Z_POSITIONS[index]]}
      renderOrder={index}  // 从后往前渲染顺序
    />
  )
}

// ===== MPI 层容器 =====

function MPIScene() {
  const { mpiLayers, uploadedImage, styleQuality, animation, isPlaying } = useEditorStore()
  const cameraOffsetRef = useRef(new THREE.Vector2(0, 0))

  // 全局相机偏移 (鼠标/动画驱动)
  useFrame((state) => {
    if (animation.type !== 'none' && isPlaying) {
      // 动画驱动的正弦偏移
      const t = state.clock.elapsedTime * animation.speed
      cameraOffsetRef.current.set(
        Math.sin(t) * animation.amplitude * 0.15,
        Math.cos(t * 0.7) * animation.amplitude * 0.05
      )
    }
  })

  if (!mpiLayers || mpiLayers.length === 0) return null

  const artStyleMap: Record<string, number> = {
    original: 0, anime: 1, oil_painting: 2, watercolor: 3,
    sketch: 4, cyberpunk: 5, vintage: 6,
  }

  return (
    <>
      {mpiLayers.map((layer, i) => (
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

// ===== 主 Scene 组件 (更新) =====

export function Scene3D() {
  const { step, originalPreview, mpiLayers, sceneData } = useEditorStore()

  if (step !== 'completed' || !originalPreview) return null

  const rp = sceneData?.render_params
  const hasMPI = mpiLayers && mpiLayers.length > 0

  return (
    <Canvas gl={{ antialias: true, toneMapping: THREE.NoToneMapping }}>
      <PerspectiveCamera
        makeDefault
        fov={rp?.fov ?? 60}
        near={rp?.near_plane ?? 0.1}
        far={rp?.far_plane ?? 100}
        position={[0, 0, hasMPI ? 5 : 5]}  // MPI 时考虑 Z 范围
      />

      {/* MPI 渲染 (优先) 或 fallback 到旧 DepthMesh */}
      {hasMPI ? <MPIScene /> : (originalPreview && <DepthMesh />)}

      <CameraFitter />
      <OrbitControls enableDamping dampingFactor={0.05} ... />

      <color attach="background" args={['#1a1a24']} />
    </Canvas>
  )
}
```

### 6.3 关键渲染差异对比

| 特性 | 旧架构 (当前) | 新架构 (MPI) |
|------|-------------|-------------|
| **几何体** | 1 个 PlaneGeometry (256x256) | N 个 PlaneGeometry (64x64 each) |
| **Shader** | 单个复杂 Shader (400+ 行) | 每层轻量 Shader (~60 行) |
| **深度处理** | 顶点位移 UV warp | 片元采样 parallax offset |
| **透明处理** | 无 (不透明平面) | Alpha test + premultiplied |
| **遮挡关系** | 启发式空洞填充 | Z-buffer 硬件深度测试 |
| **性能** | 1 次 draw call, 重 shader | N 次 draw call, 轻 shader |

---

## 七、系统⑤ — Camera Motion Path Engine

### 7.1 相机轨迹类型定义

```typescript
// frontend/src/lib/camera-path-engine.ts (新增)

export interface CameraKeyframe {
  time: number          // 时间点 (秒)
  position: [number, number, number]  // [x, y, z]
  target: [number, number, number]    // lookAt 目标
  fov?: number         // 可选 FOV 变化
  easing?: 'linear' | 'ease-in' | 'ease-out' | 'ease-in-out' | 'sinusoidal'
}

export interface CameraPath {
  id: string
  name: string                  // "cinematic_pan", "gentle_orbit", ...
  duration: number              // 总时长 (秒)
  loop: boolean
  keyframes: CameraKeyframe[]
}

// === 预设轨迹模板 ===

export const PRESET_PATHS: Record<string, CameraPath> = {
  // 水平电影摇摄 (Immersity 默认效果)
  cinematic_pan: {
    id: 'cinematic_pan',
    name: '电影摇摄',
    duration: 6.0,
    loop: true,
    keyframes: [
      { time: 0.0, position: [-1.5, 0.1, 5],   target: [0, 0, 0], easing: 'sinusoidal' },
      { time: 1.5, position: [0, 0, 5],         target: [0, 0, 0], easing: 'sinusoidal' },
      { time: 3.0, position: [1.5, -0.1, 5],    target: [0, 0, 0], easing: 'sinusoidal' },
      { time: 4.5, position: [0, 0, 5],         target: [0, 0, 0], easing: 'sinusoidal' },
      { time: 6.0, position: [-1.5, 0.1, 5],    target: [0, 0, 0], easing: 'sinusoidal' },
    ],
  },

  // 缓慢环绕
  gentle_orbit: {
    id: 'gentle_orbit',
    name: '缓慢环绕',
    duration: 8.0,
    loop: true,
    keyframes: [
      { time: 0.0, position: [1.5, 0.3, 4.5],   target: [0, 0, 0] },
      { time: 2.0, position: [0, 0.5, 4.2],      target: [0, 0, 0] },
      { time: 4.0, position: [-1.5, 0.3, 4.5],   target: [0, 0, 0] },
      { time: 6.0, position: [0, 0.1, 4.2],      target: [0, 0, 0] },
      { time: 8.0, position: [1.5, 0.3, 4.5],    target: [0, 0, 0] },
    ],
  },

  // 推进穿越
  push_in: {
    id: 'push_in',
    name: '推进穿越',
    duration: 4.0,
    loop: true,
    keyframes: [
      { time: 0.0, position: [0, 0, 6],    target: [0, 0, 0], fov: 50 },
      { time: 2.0, position: [0, 0, 3.5],  target: [0, 0, 0], fov: 55 },
      { time: 4.0, position: [0, 0, 6],    target: [0, 0, 0], fov: 50 },
    ],
  },

  // 上下巡视
  vertical_survey: {
    id: 'vertical_survey',
    name: '上下巡视',
    duration: 5.0,
    loop: true,
    keyframes: [
      { time: 0.0, position: [0, -1.0, 5],  target: [0, 0, 0] },
      { time: 1.25, position: [0, -0.3, 5], target: [0, 0, 0] },
      { time: 2.5, position: [0, 0.5, 5],   target: [0, 0, 0] },
      { time: 3.75, position: [0, -0.3, 5], target: [0, 0, 0] },
      { time: 5.0, position: [0, -1.0, 5],  target: [0, 0, 0] },
    ],
  },
}
```

### 7.2 轨迹插值引擎

```typescript
export class CameraPathEngine {
  private camera: THREE.PerspectiveCamera
  private currentPath: CameraPath | null = null
  private _isPlaying = false
  private _startTime = 0

  constructor(camera: THREE.PerspectiveCamera) {
    this.camera = camera
  }

  play(pathId: string): void {
    this.currentPath = PRESET_PATHS[pathId]
    if (!this.currentPath) return
    this._isPlaying = true
    this._startTime = performance.now() / 1000
  }

  stop(): void {
    this._isPlaying = false
  }

  update(): void {
    if (!this._isPlaying || !this.currentPath) return

    const elapsed = (performance.now() / 1000) - this._startTime
    const duration = this.currentPath.duration
    const t = this.currentPath.loop ? (elapsed % duration) / duration : Math.min(elapsed / duration, 1)

    const kf = this.interpolateKeyframes(this.currentPath.keyframes, t)

    this.camera.position.set(...kf.position)
    this.camera.lookAt(new THREE.Vector3(...kf.target))
    if (kf.fov) this.camera.fov = kf.fov
    this.camera.updateProjectionMatrix()
  }

  private interpolateKeyframes(
    keyframes: CameraKeyframe[], t: number
  ): Omit<CameraKeyframe, 'time' | 'easing'> {
    if (keyframes.length === 1) return keyframes[0]

    // 找到 t 所在的两个关键帧
    let prevKf = keyframes[0]
    let nextKf = keyframes[keyframes.length - 1]

    for (let i = 0; i < keyframes.length - 1; i++) {
      const k1 = keyframes[i]
      const k2 = keyframes[i + 1]
      const segmentStart = k1.time / this.currentPath!.duration
      const segmentEnd = k2.time / this.currentPath!.duration

      if (t >= segmentStart && t <= segmentEnd) {
        prevKf = k1
        nextKf = k2
        break
      }
    }

    // 归一化局部 t
    const localT = (t - prevKf.time / this.currentPath!.duration) /
                   ((nextKf.time - prevKf.time) / this.currentPath!.duration)

    // 应用缓动函数
    const easedT = this.applyEasing(localT, nextKf.easing ?? 'linear')

    return {
      position: this.lerpArray(prevKf.position, nextKf.position, easedT),
      target: this.lerpArray(prevKf.target, nextKf.target, easedT),
      fov: prevKf.fov && nextKf.fov
        ? prevKf.fov + (nextKf.fov - prevKf.fov) * easedT
        : undefined,
    }
  }

  private applyEasing(t: number, type: string): number {
    switch (type) {
      case 'ease-in': return t * t
      case 'ease-out': return t * (2 - t)
      case 'ease-in-out': return t < 0.5 ? 2*t*t : -1+(4-2*t)*t
      case 'sinusoidal': return (1 - Math.cos(t * Math.PI)) / 2
      default: return t
    }
  }

  private lerpArray(a: number[], b: number[], t: number): number[] {
    return a.map((v, i) => v + (b[i] - v) * t)
  }

  get isPlaying(): boolean { return this._isPlaying }
}
```

---

## 八、后端 API 扩展

### 8.1 新增端点

**修改文件**: `backend/app/api/v1/depth.py`

```python
@router.post("/scene/analyze", summary="完整场景分析 (Depth+Seg+Normal)")
async def analyze_scene(req: SceneAnalyzeRequest):
    """触发完整场景分析流水线

    比 /depth/estimate 多返回:
        - segmentation mask
        - MPI layer textures
        - occlusion inpainting results
    """
    pass


@router.get("/scene/{scene_id}", summary="获取场景数据")
async def get_scene(scene_id: str):
    """返回完整的 MPI 场景数据"""
    pass


@router.post("/scene/{scene_id}/export/video", summary="导出视频")
async def export_scene_video(scene_id: str, req: VideoExportRequest):
    """将 MPI 场景 + 相机轨迹渲染为 MP4 视频"""
    pass
```

### 8.2 数据库 Schema 扩展

**新增文件**: `backend/app/models/scene.py`

```python
"""Scene (MPI 场景) 数据模型"""

from .base import Base
from sqlalchemy import Column, String, JSON, Float, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime


class Scene(Base):
    __tablename__ = "scenes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(UUID(as_uuid=True), ForeignKey("images.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # MPI 数据
    layer_count = Column(Integer, default=3)
    layers = Column(JSON, default=list)  # MPILayer 列表

    # 分析参数
    models_used = Column(JSON, default=dict)  # {"depth": "dav2", "seg": "sam2"}
    processing_time_ms = Column(Float)

    # 相机配置
    camera_config = Column(JSON, default=dict)

    # 元数据
    metadata = Column(JSON, default=dict)

    status = Column(String, default="pending")  # pending --> processing --> ready
    created_at = Column(DateTime, default=datetime.utcnow)
```

---

## 九、三阶段实施路线图

### Phase 1: 修复现有 (Level 1) — 预计工作量: 3-5 天

**目标**: 不撕裂、可用的 2.5D 效果

| 序号 | 任务 | 文件 | 说明 |
|------|------|------|------|
| 1.1 | Edge-aware depth smoothing | `engine.py` | 双边滤波 + 引导滤波 |
| 1.2 | UV clamp 改进 | `Scene3D.tsx` | `clamp to edge` + `border mirroring` |
| 1.3 | 相机视差替代 UV warp | `Scene3D.tsx` | 移除顶点位移，改用相机移动 |
| 1.4 | 基础分层 (Otsu) | `engine.py` | 已有 MPI plan 基础 |
| 1.5 | 3 层 Plane 渲染 | `Scene3D.tsx` | 替换 DepthMesh --> MPILayers |

**验收标准**:
- [ ] 左右摆动 30 度无明显撕裂
- [ ] 前景人物不与背景黏连
- [ ] FPS >= 30 (1080p)

### Phase 2: 可用产品 (Level 2) — 预计工作量: 1-2 周

**目标**: 达到 LeiaPix Converter / Luma AI 水平

| 序号 | 任务 | 文件 | 说明 |
|------|------|------|------|
| 2.1 | SAM2 分割集成 | `sam/engine.py` 新增 | 前景/背景分离 |
| 2.2 | Depth + Seg 融合 | `engine.py` | 分割边界处深度修正 |
| 2.3 | LaMa Inpainting | `lama/engine.py` 新增 | 遮挡区域补全 |
| 2.4 | MPI 层纹理生成+上传 | `depth_task.py` | MinIO 存储 |
| 2.5 | 前端 MPI 渲染器 | `Scene3D.tsx` 重写 | 多层独立 mesh |
| 2.6 | 相机轨迹预设 | `camera-path-engine.ts` 新增 | 5 种预设动画 |
| 2.7 | Scene API | `depth.py` 扩展 | 场景 CRUD |
| 2.8 | 视频导出 | `export_task.py` | FFmpeg 渲染 MP4 |

**验收标准**:
- [ ] 左右摆动 60 度无撕裂
- [ ] 人物边缘清晰不模糊
- [ ] 遮挡区域自然过渡
- [ ] 支持 MP4 导出 (1080p, 30fps)

### Phase 3: 商业级对标 (Level 3) — 预计工作量: 3-4 周

**目标**: 接近 Immersity AI 体验

| 序号 | 任务 | 说明 |
|------|------|------|
| 3.1 | Normal Map 增强 | Stable Normal 法线估计 --> 更好立体感 |
| 3.2 | Diffusion Inpainting | SDXL Inpainting 替代 LaMa (高质量模式) |
| 3.3 | 自适应层数 | 根据场景复杂度动态调整 3~7 层 |
| 3.4 | View Synthesis Fallback | 大角度时用 NeRF/3DGS 生成新视角 |
| 3.5 | 用户自定义轨迹 | 贝塞尔曲线编辑器 |
| 3.6 | 实时预览优化 | WASM 推理 (浏览器端 Depth) |
| 3.7 | 批量处理 API | 企业级 SaaS 功能 |

**验收标准**:
- [ ] 全方向 +/-90 度无明显伪影
- [ ] 接近照片级真实感
- [ ] 支持自定义相机轨迹
- [ ] API 响应 < 10s (不含排队)

---

## 十、性能指标与优化策略

### 10.1 各阶段性能目标

| 指标 | Phase 1 | Phase 2 | Phase 3 |
|------|---------|---------|---------|
| **推理延迟** | ~2s (仅 Depth) | ~5s (Depth+Seg+Inpaint) | ~8s (+Normal+ViewSynth) |
| **渲染 FPS** | >=30 (1080p) | >=30 (1080p) | >=24 (4K) |
| **最大视差角度** | +/-15 度 | +/-45 度 | +/-80 度 |
| **显存占用** | ~4GB | ~8GB | ~16GB |
| **视频导出速度** | 不支持 | 1x 实时 | 0.5x 实时 |

### 10.2 GPU 优化策略

```python
# 1. 模型共享显存 (Depth + Seg 共享 backbone)
class SharedBackbone(nn.Module):
    """ViT Backbone 共享: Depth Anything V2 和 SAM2 都基于 ViT"""

    def __init__(self):
        self.encoder = ViTEncoder()  # 只加载一次
        self.depth_head = DepthHead()
        self.seg_head = SegHead()

    def forward(self, x):
        features = self.encoder(x)
        depth_out = self.depth_head(features)
        seg_out = self.seg_head(features)
        return depth_out, seg_out  # 一次前向传播，两个输出


# 2. FP16 推理 (显存减半)
with torch.cuda.amp.autocast(dtype=torch.float16):
    output = model(input_tensor)


# 3. Torch Compile (PyTorch 2.0+, 加速 20-40%)
model = torch.compile(model)


# 4. 异步推理流水线 (CPU/GPU 重叠)
async def pipeline(image):
    depth_task = run_in_executor(depth_model.predict, image)
    preprocess_next = cpu_preprocess(next_image)
    depth_result = await depth_task
    # GPU 计算 depth 的同时 CPU 准备下一张
```

---

## 十一、目录结构 (升级后完整)

```
conversion/
├── ai-models/
│   ├── depth/
│   │   └── depth_anything_v2/
│   │       └── engine.py          # <-- 扩展: fuse_with_segmentation, decompose_scene
│   ├── segmentation/
│   │   └── sam/
│   │       └── engine.py          # <-- 新增: SAM2 分割引擎
│   ├── normal/
│   │   └── stable_normal/
│   │       └── engine.py          # <-- 新增 (Phase 3): 法线估计
│   ├── inpaint/
│   │   └── lama/
│   │       └── engine.py          # <-- 新增: LaMa 遮挡补全
│   ├── inference_engine.py        # (已有)
│   └── model_manager.py            # <-- 扩展: run_full_pipeline
│
├── backend/
│   ├── app/
│   │   ├── api/v1/
│   │   │   ├── depth.py           # <-- 扩展: /scene/analyze, /scene/{id}
│   │   │   └── scene.py           # <-- 新增: 场景 CRUD API
│   │   ├── models/
│   │   │   └── scene.py           # <-- 新增: Scene DB Model
│   │   └── tasks/
│   │       ├── depth_task.py      # <-- 扩展: MPI 生成 + Inpainting
│   │       └── render_task.py     # <-- 扩展: 视频渲染任务
│   └── ...
│
├── frontend/
│   └── src/
│       ├── components/preview/
│       │   └── Scene3D.tsx        # <-- 重写: MPI 架构
│       ├── lib/
│       │   ├── animation-engine.ts  # (已有, 保留兼容)
│       │   └── camera-path-engine.ts  # <-- 新增: 轨迹引擎
│       ├── stores/
│       │   └── editor-store.ts    # <-- 扩展: mpiLayers, sceneData
│       └── types/
│           └── index.ts           # <-- 扩展: MPILayer, MPIScene
│
├── weights/                       # <-- 新增目录
│   ├── depth_anything_v2/
│   ├── sam2_hiera_large.pt
│   ├── lama_large/
│   └── stable_normal/
│
└── docs/
    └── superpowers/
        └── specs/
            └── immersity-architecture.md  # <-- 本文档
```

---

## 十二、关键技术决策记录 (ADR)

### ADR-001: 为什么选择 MPI 而非 NeRF/3DGS?

| 维度 | MPI | NeRF | 3D Gaussian Splatting |
|------|-----|------|---------------------|
| **推理速度** | 快 (~100ms) | 慢 (~5min训练) | 中 (~30s训练) |
| **单图输入** | 支持 | 差 (需多图) | 差 (需多图) |
| **可控性** | 高 (每层独立调参) | 低 (黑盒) | 中 |
| **浏览器实时** | WebGL 原生支持 | 不可能 | 困难 |
| **工业成熟度** | LeiaPix/Luma 已验证 | 学术为主 | 快速发展中 |
| **部署成本** | 低 (CPU/GPU均可) | 高 (必须GPU) | 高 (必须GPU) |

**结论**: MPI 是当前单图转 3D 的最佳工程选择。NeRF/3DGS 作为 Phase 3 的 View Synthesis Fallback 补充。

### ADR-002: 为什么选择 LaMa 而非 SD Inpainting?

- **速度**: LaMa ~100ms vs SD ~2000-5000ms (20-50x 差距)
- **质量**: 对自然图像遮挡补全足够好 (Immersity 也类似方案)
- **部署**: LaMa 模型 ~200MB vs SD ~4-7GB
- **策略**: LaMa 作为主力 + SD Inpainting 作为高质量可选模式

### ADR-003: 为什么分层用 Otsu 而非 K-Means?

- **Otsu**: 无需指定聚类数，自适应找最优阈值，计算 O(N)
- **K-Means**: 需要预设 K 值，对初始化敏感，迭代计算
- **结合使用**: Otsu 做粗分层 + SAM 分割做精细边界

---

## 十三、风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| SAM2 显存不足 (需要 >16GB) | 无法分割 | 中 | 使用 SAM-H (轻量版) 或 U^2-Net 替代 |
| LaMa 效果不佳 (复杂纹理) | 补全区域假影 | 中 | 多模型集成 (LaMa + OpenCV Fallback) |
| MPI 层数过多导致性能下降 | FPS < 30 | 低 | 动态层数 (简单场景 3 层，复杂 5 层) |
| 大角度视差仍撕裂 | 用户体验差 | 中 | Phase 3 View Synthesis 兜底 |
| 模型加载时间过长 | 首次等待久 | 高 | 模型预热 + 缓存 + 进度提示 |

---

## 十四、与现有代码的迁移路径

### 当前代码 → Phase 1 迁移清单

```
现有文件                          变更类型    说明
----------------------------------------------------------------------
Scene3D.tsx (DepthMesh)           重写        → MPILayers + LayerMesh
Scene3D.tsx (VERTEX_SHADER)       废弃        → LAYER_VERTEX_SHADER
Scene3D.tsx (FRAGMENT_SHADER)     拆分        → LAYER_FRAGMENT_SHADER (简化)
animation-engine.ts               保留        → 兼容旧 API，新功能用 CameraPathEngine
editor-store.ts                   扩展        → +mpiLayers, +sceneData
depth_task.py                     扩展        → +MPI 层纹理生成逻辑
engine.py (DAV2)                  扩展        → +decompose_scene, +fuse_with_segmentation
model_manager.py                  扩展        → +run_full_pipeline
```

### 向后兼容策略

```typescript
// Scene3D.tsx: 自动检测并切换渲染模式
{mpiLayers && mpiLayers.length > 0 ? (
  <MPIScene />           // 新 MPI 架构
) : (
  depthMapUrl && <DepthMesh />  // 旧架构 (fallback)
)}
```

---

*文档结束。下一步: 按 Phase 1 Task 列表开始实施。*
