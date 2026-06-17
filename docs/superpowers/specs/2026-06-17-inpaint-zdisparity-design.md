# 深度空洞修复 (Inpainting) + Z-Disparity 曲线 - 设计文档

> **Date:** 2026-06-17
> **Status:** Approved
> **Scope:** 后端 engine.py `_postprocess()` 管线升级，新增 2 个处理步骤

## 问题背景

当前 LeiaPix AI 的 3D 渲染在动画/视差移动时出现**撕裂感**：
- 深度图存在未填充的空洞区域（深度估计模型在物体边缘/遮挡处产生不连续）
- 前端 `holeFillSample()` 仅做片元级像素扩散，无法修复深度数据本身的缺陷
- 视角/相机移动时，空洞暴露为裂缝、背景穿帮

同时，线性深度映射导致**空间塌缩感**：前景和背景的深度差距不够大，立体感不足。

## 解决方案

### 功能 1: Z-Disparity 非线性曲线

**公式**: `z = depth / (1 - depth + ε)`, ε = 0.001

**效果**: 将线性深度转换为非线性视差，前景被大幅"推出去"，背景保持稳定。

| depth 原始值 | 线性输出 | Z-Disparity 输出 | 放大倍率 |
|-------------|----------|------------------|---------|
| 0.0 (远景) | 0.0 | 0.0 | 1x |
| 0.3 (中景) | 0.3 | 0.428 | **1.43x** |
| 0.5 (中近景) | 0.5 | 1.0 | **2x** |
| 0.7 (近景) | 0.7 | 2.33 | **3.33x** |
| 0.9 (前景) | 0.9 | 9.0 | **10x** |

### 功能 2: OpenCV INPAINT_NS 深度空洞修复

**算法**: Navier-Stokes 基于偏微分方程的图像修复方法
- 从空洞边缘像素信息逐步向内传播，生成平滑过渡的填充值
- 比 Telea 方法质量更好，适合深度图的平滑连续性要求

## 架构设计

### 文件变更

| 文件 | 操作 | 变更范围 |
|------|------|----------|
| `ai-models/depth/depth_anything_v2/engine.py` | 修改 | `_postprocess()` 新增 Step 3.5 + Step 7 |
| `backend/app/tasks/depth_task.py` | 修改 | params 记录新增参数 |

### 更新后的后处理管线

```
原始深度 tensor (H, W)
    │
    ├─ Step 1: F.interpolate 双线性插值回原始尺寸          [已有]
    │
    ├─ Step 2: Min-max 归一化 → [0, 1]                     [已有]
    │
    ├─ Step 3: Gamma 非线性重映射 pow(depth, gamma=1.8)     [已有]
    │
    ├─ Step 3.5: Z-Disparity 曲线 ★新增★                    [NEW]
    │   └─ depth = depth / (1 - depth + ε), ε=0.001
    │   └─ clip 到 [0, 1]
    │
    ├─ Step 4: Otsu 自适应前景/背景分离与增强                [已有]
    │   └─ fg_boost=1.2, bg_suppress=0.75
    │
    ├─ Step 5: 映射到 [0, 255] → uint8                     [已有]
    │
    ├─ Step 6: bilateralFilter 边缘保持平滑                  [已有]
    │
    ├─ Step 7: 深度空洞检测 + INPAINT_NS 修复 ★新增★        [NEW]
    │   ├─ 7a: Sobel 边缘检测 → 梯度幅值图
    │   ├─ 7b: Otsu 自适应阈值 → 二值 mask
    │   ├─ 7c: 形态学膨胀 (kernel=5, iter=2)
    │   └─ 7d: cv2.inpaint(mask, radius=5, INPAINT_NS)
    │
    └─ 输出: 修复后的 uint8 深度图 PNG
```

## 详细模块设计

### Module A: Z-Disparity Curve

```python
# 在 _postprocess() 中, Step 3 之后插入:

# Step 3.5: Z-Disparity 非线性变换
# 效果: 拉开远近差距, 消除空间"塌缩感"
if getattr(self, 'z_disparity_enabled', True):
    epsilon = getattr(self, 'z_disparity_epsilon', 0.001)

    # 安全边界处理: 限制输入范围避免极端输出
    depth_normalized = np.clip(depth_normalized, 0.0, 0.99)  # 上限 0.99 防止趋近无穷

    # Z-Disparity 变换
    depth_normalized = depth_normalized / (1.0 - depth_normalized + epsilon)

    # 输出归一化到 [0, 1] (z-disparity 将 [0,0.99] 映射到 [0, ~99])
    depth_normalized = np.clip(depth_normalized, 0, 1)
```

**边界条件安全分析**:
- `depth = 0` → `z = 0 / (1 + ε) = 0` ✅ 安全
- `depth = 0.5` → `z = 0.5 / (0.5 + ε) ≈ 1.0` ✅ 合理
- `depth = 0.99` → `z = 0.99 / (0.01 + ε) ≈ 99` → clip 到 1.0 ✅ 受控
- **关键**: 先 clip 输入到 `[0, 0.99]`，再做除法，最后 clip 输出到 `[0, 1]`

**对后续 Otsu 的影响**:
- Z-Disparity 会拉大前景/背景的深度差距
- 这实际上**有助于** Otsu 更准确地区分前景和背景（双峰更分离）
- 但需注意: 如果前景区域被过度放大(clip 到 1.0)，可能造成信息损失
- 缓解措施: 输入上限用 0.99 而非 1.0，保留一定动态范围

**参数定义**:
```python
Z_DISPARITY_ENABLED = True      # 是否启用 Z-Disparity
Z_DISPARITY_EPSILON = 0.001     # 防除零小量
```

**数学特性**:
- 单调递增函数（不改变深度排序）
- 对低深度值(背景)几乎无影响
- 对高深度值(前景)指数级放大
- 配合后续 Otsu 分割，前景/背景差距进一步拉大

### Module B: Inpainting 深度空洞修复

```python
# 在 _postprocess() 中, bilateralFilter 之后、返回之前插入:

# Step 7: 深度空洞检测 + Inpainting
if getattr(self, 'inpaint_enabled', True):
    # 7a. Sobel 边缘检测
    grad_x = cv2.Sobel(depth_uint8, cv2.CV_64F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(depth_uint8, cv2.CV_64F, 0, 1, ksize=3)
    gradient_magnitude = np.sqrt(grad_x**2 + grad_y**2)

    # 7b. Otsu 自适应阈值 → 二值 mask (高梯度区域 = 空洞候选)
    _, mask = cv2.threshold(
        gradient_magnitude.astype(np.uint8),
        0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    # 7b-safety: 验证 mask 覆盖率 (防止过度修复)
    mask_ratio = np.count_nonzero(mask) / mask.size
    if mask_ratio > 0.4:
        logger.warning(f"Inpaint mask covers {mask_ratio:.1%} of image, "
                       f"skipping inpainting (threshold > 40%)")
    else:
        # 7c. 膨胀 mask 确保完全覆盖空洞及边缘
        dilate_k = getattr(self, 'inpaint_dilate_kernel', 5)
        dilate_iter = getattr(self, 'inpaint_dilate_iterations', 2)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_k, dilate_k))
        mask = cv2.dilate(mask, kernel, iterations=dilate_iter)

        # 7d. Navier-Stokes inpainting
        radius = getattr(self, 'inpaint_radius', 5)
        depth_inpainted = cv2.inpaint(depth_uint8, mask, radius, cv2.INPAINT_NS)

        # 7e. 结果验证: 检查 NaN / Inf / 异常值
        if np.any(np.isnan(depth_inpainted)) or np.any(np.isinf(depth_inpainted)):
            logger.warning("Inpainting produced NaN/Inf values, using original depth")
            # 保持原始深度图不变
        else:
            depth_uint8 = depth_inpainted.astype(np.uint8)

            logger.debug(f"Inpainting: mask pixels={np.count_nonzero(mask)}, "
                         f"mask_ratio={mask_ratio:.3f}, radius={radius}")
```

**参数定义**:
```python
INPAINT_ENABLED = True           # 是否启用 inpainting
INPAINT_RADIUS = 5               # INPAINT_NS 搜索半径 (3~15)
INPAINT_DILATE_KERNEL = 5        # 膨胀核大小
INPAINT_DILATE_ITERATIONS = 2    # 膨胀迭代次数
```

**参数调优指南**:
| 参数 | 过小的影响 | 过大的影响 | 推荐范围 |
|------|-----------|-----------|---------|
| radius | 空洞填充不完全 | 过度模糊细节 | 3~10 |
| dilate_kernel | 边缘空洞漏检 | 正常区域被误修 | 3~9 |
| dilate_iterations | mask 不够覆盖 | 处理变慢+过度修复 | 1~3 |

## 前端影响评估

| 组件 | 需要修改 | 说明 |
|------|---------|------|
| Scene3D.tsx VERTEX_SHADER | 否 | 深度已在后端修复 |
| Scene3D.tsx FRAGMENT_SHADER | 否 | `holeFillSample()` 作为安全兜底保留 |
| CameraParallaxController | 无影响 | — |
| depth_task.py params | 是 | 记录 z_disparity + inpaint 参数 |

## 性能预估

| 步骤 | 预估耗时 (1080p 图像) | 说明 |
|------|---------------------|------|
| Sobel 梯度 | ~5ms | 3x3 卷积，极快 |
| Otsu 阈值 | ~2ms | 直方图计算 |
| 形态学膨胀 | ~3ms | 5x5 核 x 2 迭代 |
| INPAINT_NS | **~20-40ms** | 主要开销（Navier-Stokes 迭代） |
| **总计新增** | **~30-50ms** | 相比原有管线增加约 15% |

## 后续升级路径 (不在本次范围内)

1. **MPI 多平面架构**: 将单 PlaneGeometry 替换为 N 个深度排序的独立平面，从根本上消除撕裂
2. **LaMa 模型替换**: 用 LaMa (Resolution-robust Large Mask Inpainting) 替换 OpenCV INPAINT_NS，提升修复质量（需额外 200MB 权重）
3. **前端实时 inpainting**: 在片元着色器中实现轻量级实时空洞修复（WebGL compute shader 或多 pass 渲染）
