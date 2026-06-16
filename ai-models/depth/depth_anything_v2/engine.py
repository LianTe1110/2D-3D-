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


class DepthAnythingV2Engine(InferenceEngine):
    """Depth Anything V2 深度估计引擎"""

    def __init__(
        self,
        model_path: str | Path,
        encoder: str = "vitl",
        max_resolution: int = MAX_RESOLUTION,
        device: str | None = None,
    ):
        self.encoder = encoder
        self.max_resolution = max_resolution
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
        """后处理: 插值 → 双边滤波(边缘保持平滑) → 线性归一化 → 8位灰度

        Steps:
            1. 双线性插值回原始尺寸
            2. 等比例线性映射到 [0, 255]
            3. cv2.bilateralFilter 边缘保持平滑, 消除网格化噪点
            4. 转为 uint8 单通道灰度图
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

        # Step 2: 等比例线性映射到 [0, 255]
        depth_min = depth_np.min()
        depth_max = depth_np.max()
        if depth_max - depth_min > 0:
            depth_normalized = (depth_np - depth_min) / (depth_max - depth_min) * 255.0
        else:
            depth_normalized = np.zeros_like(depth_np)

        depth_uint8 = depth_normalized.astype(np.uint8)

        # Step 3: 双边滤波 — 边缘保持平滑, 消除网格化噪点
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
