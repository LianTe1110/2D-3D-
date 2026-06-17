# Inpainting + Z-Disparity 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在后端深度处理管线中新增 Z-Disparity 非线性曲线（消除空间塌缩感）和 OpenCV INPAINT_NS 深度空洞修复（消除动画撕裂），前端无需改动

**Architecture:** 在 `engine.py` 的 `_postprocess()` 方法中插入两个新步骤：Step 3.5 (Z-Disparity, Gamma 之后/Otsu 之前) 和 Step 7 (Inpainting, bilateralFilter 之后/输出之前)。同时更新 `depth_task.py` 的 params 记录

**Tech Stack:** Python, NumPy, OpenCV (cv2.inpaint), PyTorch

**Spec 文档:** `docs/superpowers/specs/2026-06-17-inpaint-zdisparity-design.md`

---

## 文件变更总览

| 文件 | 操作 | 变更范围 |
|------|------|----------|
| `ai-models/depth/depth_anything_v2/engine.py` | 修改 | 新增常量 + `__init__` 参数 + `_postprocess()` Step 3.5 + Step 7 |
| `backend/app/tasks/depth_task.py` | 修改 | params dict 新增 5 个参数 |

---

### Task 1: Z-Disparity 非线性曲线

**Files:**
- Modify: `ai-models/depth/depth_anything_v2/engine.py`

- [ ] **Step 1: 在常量区域添加 Z-Disparity 参数**

在 `FG_BOOST / BG_SUPPRESS` 常量之后添加：

```python
# Z-Disparity 非线性曲线参数
Z_DISPARITY_ENABLED = True      # 是否启用 Z-Disparity
Z_DISPARITY_EPSILON = 0.001     # 防除零小量
```

- [ ] **Step 2: 在 `__init__()` 中接收 Z-Disparity 参数**

在现有 `fg_boost` / `bg_suppress` 参数之后添加：

```python
        self.fg_boost = fg_boost
        self.bg_suppress = bg_suppress
        self.z_disparity_enabled = z_disparity_enabled      # 新增
        self.z_disparity_epsilon = z_disparity_epsilon       # 新增
```

同时更新函数签名：

```python
    def __init__(
        self,
        model_path: str | Path,
        encoder: str = "vitl",
        max_resolution: int = MAX_RESOLUTION,
        device: str | None = None,
        gamma: float = DEFAULT_GAMMA,
        fg_boost: float = FG_BOOST,
        bg_suppress: float = BG_SUPPRESS,
        z_disparity_enabled: bool = Z_DISPARITY_ENABLED,         # 新增
        z_disparity_epsilon: float = Z_DISPARITY_EPSILON,        # 新增
    ):
```

- [ ] **Step 3: 在 `_postprocess()` 中插入 Step 3.5**

在 Step 3 (Gamma) 结束、Step 4 (Otsu) 开始之间，插入以下代码：

```python
        # Step 3: Gamma 非线性重映射 (已有代码)
        gamma = getattr(self, 'gamma', DEFAULT_GAMMA)
        depth_normalized = np.power(np.clip(depth_normalized, 0, 1), gamma)

        # ===== Step 3.5: Z-Disparity 非线性变换 (新增) =====
        if getattr(self, 'z_disparity_enabled', True):
            epsilon = getattr(self, 'z_disparity_epsilon', 0.001)
            # 安全边界: 限制输入到 [0, 0.99] 防止趋近无穷大
            depth_normalized = np.clip(depth_normalized, 0.0, 0.99)
            # Z-Disparity 变换: 前景指数级放大, 背景几乎不变
            depth_normalized = depth_normalized / (1.0 - depth_normalized + epsilon)
            # 归一化回 [0, 1]
            depth_normalized = np.clip(depth_normalized, 0, 1)

        # Step 4: Otsu 自适应前景/背景分离与增强 (已有代码)
```

- [ ] **Step 4: 验证 Python 语法**

Run:
```bash
cd d:\12\conversion && python -c "import py_compile; py_compile.compile('ai-models/depth/depth_anything_v2/engine.py', doraise=True); print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add ai-models/depth/depth_anything_v2/engine.py
git commit -m "feat(depth): add Z-Disparity non-linear curve for enhanced depth separation"
```

---

### Task 2: Inpainting 深度空洞修复

**Files:**
- Modify: `ai-models/depth/depth_anything_v2/engine.py`

- [ ] **Step 1: 在常量区域添加 Inpainting 参数**

在 Z-Disparity 常量之后添加：

```python
# Inpainting 深度空洞修复参数
INPAINT_ENABLED = True           # 是否启用 inpainting
INPAINT_RADIUS = 5               # INPAINT_NS 搜索半径 (3~15)
INPAINT_DILATE_KERNEL = 5        # 膨胀核大小 (3~9)
INPAINT_DILATE_ITERATIONS = 2    # 膨胀迭代次数 (1~3)
```

- [ ] **Step 2: 在 `__init__()` 中接收 Inpainting 参数**

在 Z-Disparity 参数之后添加：

```python
        self.z_disparity_enabled = z_disparity_enabled
        self.z_disparity_epsilon = z_disparity_epsilon
        self.inpaint_enabled = inpaint_enabled                    # 新增
        self.inpaint_radius = inpaint_radius                     # 新增
        self.inpaint_dilate_kernel = inpaint_dilate_kernel       # 新增
        self.inpaint_dilate_iterations = inpaint_dilate_iterations # 新增
```

更新函数签名：

```python
        z_disparity_epsilon: float = Z_DISPARITY_EPSILON,
        inpaint_enabled: bool = INPAINT_ENABLED,                 # 新增
        inpaint_radius: int = INPAINT_RADIUS,                    # 新增
        inpaint_dilate_kernel: int = INPAINT_DILATE_KERNEL,      # 新增
        inpaint_dilate_iterations: int = INPAINT_DILATE_ITERATIONS, # 新增
    ):
```

并在函数体中赋值。

- [ ] **Step 3: 在 `_postprocess()` 中插入 Step 7**

在 Step 6 (bilateralFilter) 之后、`return depth_filtered` 之前，插入：

```python
        # Step 6: 双边滤波 (已有代码)
        depth_filtered = cv2.bilateralFilter(
            depth_uint8,
            self.BILATERAL_D,
            self.BILATERAL_SIGMA_COLOR,
            self.BILATERAL_SIGMA_SPACE,
        )

        # ===== Step 7: 深度空洞检测 + INPAINT_NS 修复 (新增) =====
        if getattr(self, 'inpaint_enabled', True):
            # 7a. Sobel 边缘检测 → 梯度幅值图
            grad_x = cv2.Sobel(depth_filtered, cv2.CV_64F, 1, 0, ksize=3)
            grad_y = cv2.Sobel(depth_filtered, cv2.CV_64F, 0, 1, ksize=3)
            gradient_magnitude = np.sqrt(grad_x**2 + grad_y**2)

            # 7b. Otsu 自适应阈值 → 二值 mask (高梯度区域 = 空洞候选)
            _, mask = cv2.threshold(
                gradient_magnitude.astype(np.uint8),
                0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )

            # 7b-safety: 验证 mask 覆盖率 (防止过度修复导致整图模糊)
            mask_ratio = np.count_nonzero(mask) / mask.size
            if mask_ratio > 0.4:
                logger.warning(
                    f"Inpaint mask covers {mask_ratio:.1%} of image, "
                    f"skipping inpainting (>40% threshold)"
                )
            else:
                # 7c. 形态学膨胀 mask 确保完全覆盖空洞及边缘
                dilate_k = getattr(self, 'inpaint_dilate_kernel', 5)
                dilate_iter = getattr(self, 'inpaint_dilate_iterations', 2)
                kernel = cv2.getStructuringElement(
                    cv2.MORPH_ELLIPSE, (dilate_k, dilate_k)
                )
                mask = cv2.dilate(mask, kernel, iterations=dilate_iter)

                # 7d. Navier-Stokes inpainting 填充空洞
                radius = getattr(self, 'inpaint_radius', 5)
                depth_inpainted = cv2.inpaint(
                    depth_filtered, mask, radius, cv2.INPAINT_NS
                )

                # 7e. 结果验证: NaN / Inf 保护
                if (np.any(np.isnan(depth_inpainted)) or
                        np.any(np.isinf(depth_inpainted))):
                    logger.warning(
                        "Inpainting produced NaN/Inf values, "
                        "using pre-inpaint depth"
                    )
                else:
                    depth_filtered = depth_inpainted.astype(np.uint8)
                    logger.debug(
                        f"Inpainting done: mask_pixels="
                        f"{np.count_nonzero(mask)}, "
                        f"ratio={mask_ratio:.3f}"
                    )

        return depth_filtered  # 已有代码, 现在返回的是修复后的深度图
```

注意：需要将原来的 `return depth_filtered` 替换为上面的完整 Step 7 + return 块。

- [ ] **Step 4: 更新 `_postprocess()` docstring**

将 docstring 从：

```python
"""后处理: 插值 → Gamma重映射 → Otsu前景强化 → 双边滤波 → 8位灰度"""
```

更新为：

```python
"""后处理: 插值 → Gamma重映射 → Z-Disparity → Otsu → 双边滤波 → Inpainting → 8位灰度"""
```

- [ ] **Step 5: 验证 Python 语法**

Run:
```bash
cd d:\12\conversion && python -c "import py_compile; py_compile.compile('ai-models/depth/depth_anything_v2/engine.py', doraise=True); print('OK')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add ai-models/depth/depth_anything_v2/engine.py
git commit -m "feat(depth): add OpenCV INPAINT_NS deep hole repair for tear-free animation"
```

---

### Task 3: 更新 depth_task.py 参数记录

**Files:**
- Modify: `backend/app/tasks/depth_task.py`

- [ ] **Step 1: 在 params dict 中记录全部新参数**

找到现有的 `params={...}` 字典，更新为：

```python
params={
    "bilateral_filter": {"d": 9, "sigma_color": 75, "sigma_space": 75},
    "gamma": 1.8,
    "fg_boost": 1.2,
    "bg_suppress": 0.75,
    # Z-Disparity (Task 1 新增)
    "z_disparity_enabled": True,
    "z_disparity_epsilon": 0.001,
    # Inpainting (Task 2 新增)
    "inpaint_enabled": True,
    "inpaint_radius": 5,
    "inpaint_dilate_kernel": 5,
    "inpaint_dilate_iterations": 2,
},
```

- [ ] **Step 2: 验证语法**

Run:
```bash
cd d:\12\conversion && python -c "import py_compile; py_compile.compile('backend/app/tasks/depth_task.py', doraise=True); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/tasks/depth_task.py
git commit -m "chore(task): record Z-Disparity and Inpainting parameters in depth task"
```

---

### Task 4: 集成验证

**Files:**
- No new files (validation only)

- [ ] **Step 1: 重启 Celery Worker**

Stop existing worker terminal → Start new:

```bash
cd d:\12\conversion\backend && python -m celery -A app.core.celery_app worker --loglevel=info --queues=gpu_depth -c 1 --pool=solo
```

- [ ] **Step 2: 上传测试图片验证**

1. 打开 http://localhost:3000
2. 上传一张测试图片（有人物前景 + 背景的图片效果最佳）
3. 等待深度估算完成
4. 观察 3D 预览：
   - 移动鼠标触发视差：**不应出现裂缝/撕裂**
   - 播放动画：**前后景层次感应明显增强**
   - 人物轮廓边缘：**清晰不黏连**

- [ ] **Step 3: 检查 Worker 日志确认新步骤执行**

在 Celery Worker 终端中应能看到类似日志：
```
DEBUG Inpainting done: mask_pixels=XXXX, ratio=0.XXX
```
如果看到 `skipping inpainting (>40% threshold)` 说明该图片空洞较少（正常）

- [ ] **Step 4: Final Commit (如有微调)**

```bash
git add -A
git commit -m "feat: complete inpainting + z-disparity integration for tear-free 3D rendering"
```

---

## 实施依赖关系

```
Task 1 (Z-Disparity) ──┐
                       ├──→ Task 4 (集成验证)
Task 2 (Inpainting)  ──┤
                       │
Task 3 (params 记录) ──┘
```

Task 1 和 Task 2 都修改 engine.py 的不同位置（Step 3.5 vs Step 7），但共享 `__init__` 和常量区域。建议按顺序执行：Task 1 → Task 2 → Task 3 → Task 4。
