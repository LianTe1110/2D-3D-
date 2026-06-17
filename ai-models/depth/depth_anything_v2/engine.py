"""LeiaPix AI - Depth Anything V2 推理引擎

基于 Depth Anything V2 的深度估计推理封装。
"""

import logging
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from inference_engine import InferenceEngine

logger = logging.getLogger(__name__)

# Depth Anything V2 支持的模型尺寸与对应配置
MODEL_CONFIGS = {
    "vitl": {"encoder": "vitl", "features": 256, "out_channels": [256, 512, 1024, 1024]},
    "vitb": {"encoder": "vitb", "features": 128, "out_channels": [128, 256, 512, 1024]},
    "vits": {"encoder": "vits", "features": 64, "out_channels": [64, 128, 256, 512]},
}

# 最大输入分辨率 (避免 OOM)
MAX_RESOLUTION = 518

# Level 3: 统一推理分辨率 (所有 AI 模型输出对齐到同一尺寸)
UNIFIED_RESOLUTION = 768  # 768x768 or 1024x1024

# Gamma 默认值 (非线性深度重映射)
DEFAULT_GAMMA = 1.8

# 前景/背景增强系数
FG_BOOST = 1.2     # 前景深度乘数 (>1.0 让前景更突出)
BG_SUPPRESS = 0.75 # 背景深度乘数 (<1.0 让背景更扁平)


class DepthAnythingV2Engine(InferenceEngine):
    """Depth Anything V2 深度估计引擎"""

    def __init__(
        self,
        model_path: str | Path,
        encoder: str = "vitl",
        max_resolution: int = MAX_RESOLUTION,
        device: str | None = None,
        gamma: float = DEFAULT_GAMMA,
        fg_boost: float = FG_BOOST,
        bg_suppress: float = BG_SUPPRESS,
    ):
        self.encoder = encoder
        self.max_resolution = max_resolution
        self.gamma = gamma
        self.fg_boost = fg_boost
        self.bg_suppress = bg_suppress
        super().__init__(model_path, device)

    def _load_model(self) -> torch.nn.Module:
        """加载 Depth Anything V2 模型"""
        try:
            from depth_anything_v2.dpt import DepthAnythingV2
        except ImportError:
            logger.warning(
                "depth_anything_v2 package not installed, "
                "using placeholder model loader"
            )
            return self._load_model_fallback()

        config = MODEL_CONFIGS.get(self.encoder, MODEL_CONFIGS["vitl"])
        model = DepthAnythingV2(**config)
        state_dict = torch.load(str(self.model_path), map_location=self.device, weights_only=True)
        model.load_state_dict(state_dict)
        return model

    def _load_model_fallback(self) -> torch.nn.Module:
        """当 depth_anything_v2 包未安装时的占位加载"""
        logger.error(
            "depth_anything_v2 package is not installed!\n"
            "Install it with: pip install depth-anything-v2\n"
            "Or clone from: https://github.com/DepthAnything/Depth-Anything-V2"
        )
        raise ImportError(
            "depth_anything_v2 package required. "
            "Install: pip install depth-anything-v2"
        )

    def _preprocess(self, image: Image.Image) -> torch.Tensor:
        """图像预处理: 缩放 + 归一化

        Depth Anything V2 要求:
        - 输入尺寸为 14 的倍数
        - 归一化: ImageNet mean/std
        """
        # 确保 RGB
        if image.mode != "RGB":
            image = image.convert("RGB")

        # 计算目标尺寸 (保持宽高比, 最长边 <= max_resolution, 且为 14 的倍数)
        w, h = image.size
        scale = min(self.max_resolution / max(w, h), 1.0)
        new_w = int(w * scale) // 14 * 14
        new_h = int(h * scale) // 14 * 14
        new_w = max(new_w, 14)
        new_h = max(new_h, 14)

        image_resized = image.resize((new_w, new_h), Image.LANCZOS)

        # 转为 tensor 并归一化
        img_np = np.array(image_resized).astype(np.float32) / 255.0
        img_tensor = torch.from_numpy(img_np).permute(2, 0, 1).unsqueeze(0)

        # ImageNet 归一化
        mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
        img_tensor = (img_tensor - mean) / std

        return img_tensor.to(self.device)

    def _forward(self, tensor: torch.Tensor) -> torch.Tensor:
        """前向传播"""
        return self.model(tensor)  # type: ignore[misc]

    # 双边滤波默认参数
    BILATERAL_D = 9          # 邻域直径
    BILATERAL_SIGMA_COLOR = 75  # 颜色空间标准差
    BILATERAL_SIGMA_SPACE = 75  # 坐标空间标准差

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
        gamma = getattr(self, 'gamma', DEFAULT_GAMMA)
        depth_normalized = np.power(np.clip(depth_normalized, 0, 1), gamma)

        # Step 4: Otsu 自适应前景/背景分离与增强
        # 无需 SAM 等分割模型, 利用深度直方图自动找到前景/背景分界线
        fg_boost = getattr(self, 'fg_boost', FG_BOOST)
        bg_suppress = getattr(self, 'bg_suppress', BG_SUPPRESS)

        if fg_boost != 1.0 or bg_suppress != 1.0:
            # 计算归一化后的深度直方图
            hist, _ = np.histogram(
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

    def predict_depth(self, image: Image.Image) -> np.ndarray:
        """便捷方法: 预测深度图"""
        return self.predict(image)

    def predict_depth_as_image(self, image: Image.Image) -> Image.Image:
        """便捷方法: 预测深度图并返回单通道 8 位灰度 PIL Image (PNG)"""
        depth = self.predict_depth(image)
        return Image.fromarray(depth, mode="L")

    def predict_depth_as_array(self, image: Image.Image) -> np.ndarray:
        """便捷方法: 预测深度图并返回 float32 numpy 数组 (H, W), 值域 [0, 1]"""
        depth = self.predict_depth(image)
        return depth.astype(np.float32) / 255.0

    # ========== Phase 1.1: Edge-aware depth smoothing ==========

    def edge_aware_smooth(self, depth_uint8: np.ndarray) -> np.ndarray:
        """边缘感知深度平滑: 双边滤波 + 引导滤波

        策略:
            - 双边滤波: 平滑但保留边缘 (BILATERAL_D=9, sigma=75)
            - 引导滤波: 用原深度图作为引导图, 细化边缘
            - 两步接力: 双边 → 引导, 消除网格噪点同时保持锐利边缘
        """
        # Step 1: 双边滤波 (已有, 加强参数)
        smoothed = cv2.bilateralFilter(
            depth_uint8,
            self.BILATERAL_D,
            self.BILATERAL_SIGMA_COLOR,
            self.BILATERAL_SIGMA_SPACE,
        )

        # Step 2: 引导滤波 (用平滑后的深度图作为引导图)
        # 引导滤波比双边滤波更擅长消除"梯度反转"伪影
        try:
            smoothed_float = smoothed.astype(np.float32) / 255.0
            guide = smoothed_float  # 自引导
            radius = 4
            eps = 0.01 ** 2
            guided = cv2.ximgproc.guidedFilter(
                guide, smoothed_float, radius, eps, -1
            )
            guided = (guided * 255).clip(0, 255).astype(np.uint8)
            return guided
        except (AttributeError, cv2.error):
            # cv2.ximgproc 可能不可用, 回退到仅双边滤波
            logger.debug("cv2.ximgproc.guidedFilter not available, using bilateral only")
            return smoothed

    # ========== Phase 1.4: 基础分层 Otsu ==========

    def _compute_layer_thresholds(
        self, depth_uint8: np.ndarray, n_layers: int
    ) -> list[int]:
        """计算层边界阈值 (Otsu 自适应)

        3层: 两级 Otsu → [0, t1, t2, 255]
        其他: 等间距 → [0, step, 2*step, ..., 255]

        Args:
            depth_uint8: uint8 深度图 (H, W), 值域 [0, 255]
            n_layers: 目标层数

        Returns:
            阈值列表, 长度 = n_layers + 1
        """
        if n_layers == 3:
            # 两级 Otsu: 先找全局阈值, 再在两个子区域分别找阈值
            _, binary1 = cv2.threshold(
                depth_uint8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )
            dark_region = depth_uint8[binary1 == 0]
            if dark_region.size > 10:
                t1, _ = cv2.threshold(
                    dark_region, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
                )
                t1 = int(t1)
            else:
                t1 = 85
            bright_region = depth_uint8[binary1 == 255]
            if bright_region.size > 10:
                t2, _ = cv2.threshold(
                    bright_region, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
                )
                t2 = int(t2)
            else:
                t2 = 170
            if t1 >= t2:
                t1, t2 = min(t1, t2) // 2, max(t1, t2)
            return [0, t1, t2, 255]
        else:
            step = 256 // n_layers
            return [i * step for i in range(n_layers)] + [255]

    def generate_mpi_layers(
        self, depth_uint8: np.ndarray, original_image: Image.Image,
        n_layers: int = 3
    ) -> list[Image.Image]:
        """将原图按深度切分为 N 层 RGBA 纹理 (Phase 1.4 基础分层)

        Args:
            depth_uint8: 后处理完成的 uint8 深度图 (H, W)
            original_image: 原始 RGB 图像
            n_layers: 层数 (默认 3)

        Returns:
            list of RGBA PIL Image, 按深度从远到近排序
        """
        thresholds = self._compute_layer_thresholds(depth_uint8, n_layers)
        original_rgba = np.array(original_image.convert("RGBA"))

        layers = []
        for i in range(n_layers):
            if i < n_layers - 1:
                mask = (
                    (depth_uint8 >= thresholds[i])
                    & (depth_uint8 < thresholds[i + 1])
                ).astype(np.uint8) * 255
            else:
                mask = (depth_uint8 >= thresholds[i]).astype(np.uint8) * 255

            # 边缘膨胀: 7x7 椭圆核 x 5 次, 确保视差移动时不露缝
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
            mask = cv2.dilate(mask, kernel, iterations=5)

            layer = original_rgba.copy()
            layer[:, :, 3] = mask
            layers.append(Image.fromarray(layer))

        return layers

    # ========== Phase 2: 带置信度的深度估计 ==========

    def predict_with_confidence(self, image: Image.Image) -> dict:
        """带置信度的深度估计

        Returns:
            dict: {
                "depth": np.ndarray,        # 深度图 (H, W), float32 [0,1]
                "confidence": np.ndarray,   # 置信度图 (H, W)
                "uncertainty": np.ndarray,  # 不确定区域
            }
        """
        depth = self.predict_depth_as_array(image)

        # 基于深度梯度的启发式置信度
        grad_x = cv2.Sobel(depth, cv2.CV_64F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(depth, cv2.CV_64F, 0, 1, ksize=3)
        gradient_magnitude = np.sqrt(grad_x**2 + grad_y**2)

        # 高梯度 = 低置信度 (边缘区域不可靠)
        max_grad = gradient_magnitude.max() or 1.0
        confidence = 1.0 - np.clip(gradient_magnitude / max_grad, 0, 1)
        uncertainty = 1.0 - confidence

        return {
            "depth": depth,
            "confidence": confidence,
            "uncertainty": uncertainty,
        }

    def predict_unified(self, image: Image.Image, target_size: int = 768) -> dict:
        """Level 3: 统一分辨率的多模态场景理解

        所有 AI 模型输出对齐到同一尺寸, 避免 GPU 对齐问题。

        Returns:
            dict: {
                "depth": np.ndarray,        # (H, W) float32 [0,1]
                "confidence": np.ndarray,   # (H, W) float32
                "uncertainty": np.ndarray,  # (H, W) float32
                "original_size": tuple,     # (W, H) 原始尺寸
                "unified_size": tuple,      # (W, H) 统一尺寸
            }
        """
        original_size = image.size  # (W, H)

        # 统一 resize 到 target_size
        w, h = image.size
        scale = min(target_size / w, target_size / h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = image.resize((new_w, new_h), Image.LANCZOS)

        # 深度估计 (在统一分辨率上)
        result = self.predict_with_confidence(resized)

        result["original_size"] = original_size
        result["unified_size"] = (new_w, new_h)
        return result

    # ========== Phase 2: Depth + Seg 融合 ==========

    def fuse_with_segmentation(
        self, depth_result: dict, seg_result: dict
    ) -> dict:
        """融合深度图与分割掩码

        策略:
            - 在分割边界处信任分割结果 (覆盖深度噪声)
            - 在分割内部使用深度信息细化层级
        """
        depth = depth_result["depth"]
        seg_mask = seg_result.get("seg_mask")
        if seg_mask is None:
            return {**depth_result, "fused_depth": depth, "num_detected_layers": 3}

        fused_depth = depth.copy()
        for layer_id in np.unique(seg_mask):
            if layer_id == 0:
                continue
            region_mask = seg_mask == layer_id
            if not region_mask.any():
                continue
            region_depth = depth[region_mask]
            median_depth = np.median(region_depth)
            std_depth = np.std(region_depth) or 0.01

            # 仅对异常值 (偏离中位数 > 2sigma) 做修正
            outliers = np.abs(depth - median_depth) > 2 * std_depth
            correction = np.where(region_mask & outliers, median_depth, depth)
            fused_depth = np.where(region_mask & outliers, correction, fused_depth)

        return {
            **depth_result,
            "fused_depth": fused_depth,
            "seg_mask": seg_mask,
            "num_detected_layers": seg_result.get("num_layers", 3),
        }

    # ========== Phase 2: Depth + Seg + Normal + Confidence 四路融合 ==========

    def fuse_multi_modal(
        self,
        depth_result: dict,
        seg_result: dict,
        normal_result: dict,
    ) -> dict:
        """四路融合: Depth + Segmentation + Normal + Confidence

        对标 Immersity AI System ① 多模态融合策略:

        深度 (Depth)        → 提供基础几何结构
        分割 (Segmentation) → 修正语义边界, 区分物体层级
        法线 (Normal)       → 细化表面朝向, 增强微几何细节
        置信度 (Confidence) → 加权融合, 低置信度区域降权

        融合权重:
            - 平坦区域: 深度占主导 (w_depth=0.6)
            - 分割边界: 分割占主导 (w_seg=0.5)
            - 细节区域: 法线占主导 (w_normal=0.4)
            - 全局: 置信度加权调和

        Returns:
            dict: {
                "fused_depth": np.ndarray,        # 融合后深度图 (H, W)
                "seg_mask": np.ndarray | None,    # 分割掩码
                "normal_map": np.ndarray | None,  # 法线图 (H, W, 3)
                "confidence": np.ndarray,         # 融合置信度 (H, W)
                "num_detected_layers": int,       # 检测到的层数
                "depth": np.ndarray,              # 原始深度图
                "normal_method": str,             # 法线估计方法
            }
        """
        depth = depth_result["depth"]
        depth_confidence = depth_result.get("confidence")
        seg_mask = seg_result.get("seg_mask")
        normal_map = normal_result.get("normal")
        normal_method = normal_result.get("method", "none")
        normal_confidence = normal_result.get("confidence")

        H, W = depth.shape
        fused_depth = depth.copy()

        # ========== 1. 分割修正 (保留原有逻辑) ==========
        if seg_mask is not None:
            for layer_id in np.unique(seg_mask):
                if layer_id == 0:
                    continue
                region_mask = seg_mask == layer_id
                if not region_mask.any():
                    continue
                region_depth = depth[region_mask]
                median_depth = np.median(region_depth)
                std_depth = np.std(region_depth) or 0.01

                outliers = np.abs(depth - median_depth) > 2 * std_depth
                correction = np.where(region_mask & outliers, median_depth, depth)
                fused_depth = np.where(region_mask & outliers, correction, fused_depth)

        # ========== 2. 法线引导的深度细化 ==========
        if normal_map is not None and normal_map.shape[:2] == (H, W):
            normal_z = np.abs(normal_map[..., 2])  # |nz| ∈ [0, 1]
            # 法线 Z 分量接近 0 → 表面陡峭 → 需要细化
            # 法线 Z 分量接近 1 → 表面平坦 → 信任深度

            steepness = 1.0 - normal_z  # 陡峭度 ∈ [0, 1]

            # 对陡峭区域做边缘保持滤波 (Bilateral Filter)
            steep_mask = steepness > 0.5
            if steep_mask.any():
                filtered = cv2.bilateralFilter(
                    fused_depth.astype(np.float32), d=9, sigmaColor=0.1, sigmaSpace=0.1,
                )
                # 混合: 陡峭区域用滤波结果, 平坦区域用原始深度
                alpha = np.clip(steepness * 0.6, 0, 0.6)  # 法线引导权重上限 0.6
                fused_depth = fused_depth * (1.0 - alpha) + filtered * alpha

        # ========== 3. 置信度加权融合 ==========
        # 构建融合置信度: 深度置信度 + 法线置信度
        if depth_confidence is not None:
            base_confidence = depth_confidence.copy()
        else:
            base_confidence = np.ones((H, W), dtype=np.float32)

        if normal_confidence is not None and normal_confidence.shape == (H, W):
            # 深度置信度 70% + 法线置信度 30%
            fused_confidence = base_confidence * 0.7 + normal_confidence * 0.3
        else:
            fused_confidence = base_confidence

        # 置信度裁剪到 [0.1, 1.0] (避免零权重)
        fused_confidence = np.clip(fused_confidence, 0.1, 1.0)

        return {
            **depth_result,
            "fused_depth": fused_depth.astype(np.float32),
            "seg_mask": seg_mask,
            "normal_map": normal_map,
            "normal_method": normal_method,
            "confidence": fused_confidence.astype(np.float32),
            "num_detected_layers": seg_result.get("num_layers", 3),
        }

    # ========== Phase 2: Scene Decomposition ==========

    def decompose_scene(
        self,
        fused_result: dict,
        original_image: Image.Image,
        n_layers: int = 3,
    ) -> list[dict]:
        """Level 3: 将融合后的场景数据分解为多层 (soft mask)

        关键改进:
            - 使用 soft mask (0~1 alpha) 替代 binary mask
            - 边缘羽化 (feathering) 消除硬边
            - FG/MG/BG 语义分层

        Args:
            fused_result: fuse_multi_modal() 或 fuse_with_segmentation() 的输出
            original_image: 原始 RGB 图像
            n_layers: 目标层数

        Returns:
            list[dict]: 每层数据
            [{
                "texture": PIL.Image,           # RGBA 纹理 (soft alpha)
                "depth_map": np.ndarray,        # 该层深度图
                "soft_mask": np.ndarray,        # (H, W) float32 [0,1] soft mask
                "occlusion_mask": np.ndarray,   # 遮挡掩码
                "z_position": float,            # Z 轴位置
                "motion_scale": float,          # 运动缩放
                "layer_index": int,
                "layer_type": str,              # "fg" | "mid" | "bg"
            }]
        """
        fused_depth = fused_result["fused_depth"]
        seg_mask = fused_result.get("seg_mask")
        confidence = fused_result.get("confidence")
        original_rgba = np.array(original_image.convert("RGBA"))

        depth_uint8 = (fused_depth * 255).astype(np.uint8)
        thresholds = self._compute_layer_thresholds(depth_uint8, n_layers)

        # 层类型映射 (Level 3: 扩大间距 → 人物漂浮 + 空间延展)
        layer_types = ["bg", "mid", "fg"]
        z_positions = [-2.5, 0.0, 2.0]
        motion_scales = [0.2, 0.7, 1.5]

        layers = []
        for i in range(n_layers):
            # 深度范围掩码
            if i < n_layers - 1:
                layer_pixel_mask = (
                    (fused_depth >= thresholds[i] / 255.0)
                    & (fused_depth < thresholds[i + 1] / 255.0)
                )
            else:
                layer_pixel_mask = fused_depth >= thresholds[i] / 255.0

            # SAM 分割修正
            if seg_mask is not None:
                sam_foreground = seg_mask > 0
                if i == n_layers - 1:
                    layer_pixel_mask = layer_pixel_mask & sam_foreground
                elif i == 0:
                    layer_pixel_mask = layer_pixel_mask & (~sam_foreground)

            # ★ Level 3 核心: soft mask (0~1 alpha) 替代 binary mask
            soft_mask = self._compute_soft_mask(
                layer_pixel_mask.astype(np.float32),
                confidence,
                feather_radius=15,
            )

            # 应用 soft mask 到 RGBA
            layer_rgba = original_rgba.copy()
            layer_rgba[:, :, 3] = (soft_mask * 255).astype(np.uint8)

            # 该层深度 (soft mask 加权)
            layer_depth = fused_depth * soft_mask

            # 遮挡掩码 (被前方层遮挡的区域)
            occlusion_mask = np.zeros_like(soft_mask)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
            for j in range(i + 1, n_layers):
                if j < n_layers - 1:
                    front_mask = (
                        (fused_depth >= thresholds[j] / 255.0)
                        & (fused_depth < thresholds[j + 1] / 255.0)
                    ).astype(np.float32)
                else:
                    front_mask = (fused_depth >= thresholds[j] / 255.0).astype(np.float32)
                front_soft = self._compute_soft_mask(front_mask, None, feather_radius=5)
                occlusion_mask = np.maximum(occlusion_mask, front_soft)

            layers.append({
                "texture": Image.fromarray(layer_rgba),
                "depth_map": layer_depth,
                "soft_mask": soft_mask,
                "occlusion_mask": (occlusion_mask * 255).astype(np.uint8),
                "z_position": z_positions[i] if i < len(z_positions) else i,
                "motion_scale": motion_scales[i] if i < len(motion_scales) else 1.0,
                "layer_index": i,
                "layer_type": layer_types[i] if i < len(layer_types) else "mid",
            })

        return layers

    def decompose_per_object(
        self,
        fused_result: dict,
        original_image: Image.Image,
        seg_result: dict,
    ) -> list[dict]:
        """Level 3: 逐物体分解 — 每个 SAM2 识别到的物体独立为一层

        BG 由 seg_mask==0 的像素组成, 每个物体 (seg_mask==1,2,...N) 各自一层。
        每层拥有独立的 z_position 和 motion_scale, 基于该物体的平均深度。

        Args:
            fused_result: fuse_multi_modal() 或 fuse_with_segmentation() 的输出
            original_image: 原始 RGB 图像
            seg_result: SAM2 分割结果 {"seg_mask": np.ndarray, "num_layers": int}

        Returns:
            list[dict]: 每层数据 (1 BG + N objects)
        """
        fused_depth = fused_result["fused_depth"]
        seg_mask = seg_result.get("seg_mask")
        confidence = fused_result.get("confidence")
        original_rgba = np.array(original_image.convert("RGBA"))

        if seg_mask is None:
            # Fallback: 没有 SAM2, 用深度分层
            return self.decompose_scene(fused_result, original_image, n_layers=3)

        num_objects = seg_result.get("num_layers", 1) - 1
        if num_objects <= 0:
            return self.decompose_scene(fused_result, original_image, n_layers=3)

        layers = []

        # ============ BG 层 (seg_mask == 0) ============
        bg_mask = (seg_mask == 0).astype(np.float32)
        bg_depth = fused_depth.copy()
        bg_depth[seg_mask > 0] = 0  # 移除物体区域
        bg_soft = self._compute_soft_mask(bg_mask, confidence, feather_radius=10)

        bg_rgba = original_rgba.copy()
        bg_rgba[:, :, 3] = (bg_soft * 255).astype(np.uint8)

        layers.append({
            "texture": Image.fromarray(bg_rgba),
            "depth_map": bg_depth * bg_soft,
            "soft_mask": bg_soft,
            "occlusion_mask": np.zeros_like(bg_soft),
            "z_position": -2.5,
            "motion_scale": 0.2,
            "layer_index": 0,
            "layer_type": "bg",
            "object_id": None,
            "label": "背景",
        })

        # ============ 每物体层 (seg_mask == 1,2,...,N) ============
        for obj_id in range(1, num_objects + 1):
            obj_mask = (seg_mask == obj_id).astype(np.float32)

            # 计算该物体的平均深度 (用于 z 和 motion)
            obj_depth_values = fused_depth[obj_mask > 0.5]
            if len(obj_depth_values) == 0:
                continue
            mean_depth = float(np.mean(obj_depth_values))

            # 深度 → z_position: near → z>0, far → z<0
            z_pos = (mean_depth - 0.5) * 5.0
            # 深度 → motion_scale: near → 大运动, far → 小运动
            motion_scale = 0.4 + mean_depth * 1.6

            # 物体深度图
            obj_depth = fused_depth * obj_mask

            # Soft mask
            obj_soft = self._compute_soft_mask(
                obj_mask, confidence, feather_radius=8
            )

            # 物体 RGBA
            obj_rgba = original_rgba.copy()
            obj_rgba[:, :, 3] = (obj_soft * 255).astype(np.uint8)

            # 遮挡掩码: 前方物体区域
            occlusion_mask = np.zeros_like(obj_soft, dtype=np.float32)
            for other_id in range(1, num_objects + 1):
                if other_id == obj_id:
                    continue
                other_mask = (seg_mask == other_id).astype(np.float32)
                other_depth = np.mean(fused_depth[other_mask > 0.5]) if np.any(other_mask > 0.5) else 0.5
                # 仅在 other 在前方时遮挡
                if other_depth > mean_depth:
                    front_soft = self._compute_soft_mask(other_mask, None, feather_radius=5)
                    occlusion_mask = np.maximum(occlusion_mask, front_soft)

            label = f"物体{obj_id}"

            layers.append({
                "texture": Image.fromarray(obj_rgba),
                "depth_map": obj_depth,
                "soft_mask": obj_soft,
                "occlusion_mask": (occlusion_mask * 255).astype(np.uint8),
                "z_position": z_pos,
                "motion_scale": motion_scale,
                "layer_index": obj_id,
                "layer_type": "object",
                "object_id": obj_id,
                "label": label,
            })

        # 按 z_position 排序 (BG → 远 → 近)
        layers.sort(key=lambda l: l["z_position"])

        return layers

    def _compute_soft_mask(
        self,
        binary_mask: np.ndarray,
        confidence: np.ndarray | None = None,
        feather_radius: int = 15,
    ) -> np.ndarray:
        """Level 3: 计算软掩码 (0~1 alpha)

        策略:
            1. Gaussian blur 羽化边缘
            2. 置信度加权 (低置信度 → alpha 更透明)
            3. 归一化到 [0, 1]

        Args:
            binary_mask: (H, W) float32 二值掩码
            confidence: (H, W) float32 置信度图 (可选)
            feather_radius: 羽化半径 (像素)

        Returns:
            np.ndarray: (H, W) float32 soft mask [0, 1]
        """
        # Gaussian 羽化
        ksize = feather_radius * 2 + 1
        soft = cv2.GaussianBlur(binary_mask, (ksize, ksize), feather_radius / 3.0)

        # 置信度加权
        if confidence is not None and confidence.shape == binary_mask.shape:
            soft = soft * (0.5 + 0.5 * confidence)

        # 归一化到 [0, 1]
        max_val = soft.max()
        if max_val > 0:
            soft = soft / max_val

        return np.clip(soft, 0.0, 1.0).astype(np.float32)
