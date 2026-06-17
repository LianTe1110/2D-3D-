"""LeiaPix AI - Stable Normal 推理引擎

对标 Immersity AI System ①: 法线估计模块
基于 StableNormal (Stable Diffusion 微调), 生成高质量法线图。
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


class StableNormalEngine(InferenceEngine):
    """Stable Normal 法线估计引擎

    输入: RGB 图像
    输出: 法线图 (H, W, 3), float32, XYZ 分量范围 [-1, 1]

    模型选择:
    - stable_normal_turbo: 速度快 (~0.5s), 适合实时预览
    - stable_normal_full: 质量高 (~2s), 适合最终输出
    """

    # 标准输入尺寸 (StableNormal 推荐 768x768)
    INPUT_SIZE = 768

    # 默认 Turbo 权重 (轻量, 先跑通)
    DEFAULT_TURBO_WEIGHT = "stable_normal_turbo.pt"

    def __init__(
        self,
        model_path: str | Path,
        device: str | None = None,
        input_size: int = 768,
    ):
        super().__init__(model_path, device)
        self.input_size = input_size

    def _load_model(self) -> torch.nn.Module:
        """加载 StableNormal 模型

        优先级:
        1. 尝试加载官方 StableNormal 权重 (diffusers pipeline)
        2. 如果权重不存在, 使用 Sobel 边缘检测 + 深度图梯度 → 近似法线 (fallback)
        """
        if self.model_path.exists():
            try:
                # 尝试加载 diffusers 格式的 StableNormal pipeline
                from diffusers import StableNormalPipeline

                logger.info("Loading StableNormal from diffusers pipeline...")
                pipe = StableNormalPipeline.from_pretrained(
                    self.model_path.parent,
                    torch_dtype=torch.float16 if self.device.type == "cuda" else torch.float32,
                )
                return pipe.to(self.device)
            except ImportError:
                logger.warning("diffusers not installed, using Sobel fallback")
            except Exception as e:
                logger.warning(f"StableNormal pipeline load failed: {e}, using Sobel fallback")

        # Fallback: 返回 None 标识用 _forward 中的 Sobel 近似
        logger.info("Using Sobel-based normal approximation (no StableNormal weights)")
        return None

    def _preprocess(self, image: Image.Image) -> torch.Tensor:
        """预处理: 缩放到 INPUT_SIZE, 归一化"""
        w, h = image.size
        scale = min(self.input_size / w, self.input_size / h)
        new_w, new_h = int(w * scale), int(h * scale)

        img = image.resize((new_w, new_h), Image.LANCZOS)
        img_array = np.array(img, dtype=np.float32) / 255.0

        # 简单归一化到 [-1, 1] (ImageNet 风格)
        img_array = (img_array - 0.5) * 2.0

        tensor = torch.from_numpy(img_array).permute(2, 0, 1).unsqueeze(0)
        return tensor.to(self.device)

    def _forward(self, tensor: torch.Tensor) -> torch.Tensor:
        """前向传播 (或 Sobel 近似)

        StableNormal pipeline 需要特殊处理 (diffusers), 这里封装。
        如果 model 是 None, 返回 None → _postprocess 用 Sobel 近似。
        """
        if self.model is None:
            return None

        # StableNormal diffusers pipeline
        if hasattr(self.model, '__call__'):
            # diffusers pipeline: 输入是 PIL Image 或 tensor
            # 转回 numpy 给 pipeline
            img_np = tensor.squeeze(0).permute(1, 2, 0).cpu().numpy()
            img_np = (img_np + 1.0) / 2.0  # [-1,1] → [0,1]
            img_np = np.clip(img_np * 255, 0, 255).astype(np.uint8)
            pil_img = Image.fromarray(img_np)

            with torch.no_grad():
                # StableNormal 返回 (H, W, 3) 的 numpy 法线图
                normal = self.model(pil_img)
                if isinstance(normal, Image.Image):
                    normal = np.array(normal, dtype=np.float32) / 255.0
                    normal = normal * 2.0 - 1.0  # [0,1] → [-1,1]
                return torch.from_numpy(normal).permute(2, 0, 1).unsqueeze(0).to(self.device)

        # 普通 torch 模型
        return self.model(tensor)

    def _postprocess(
        self,
        output: torch.Tensor | None,
        original_size: tuple[int, int],
    ) -> np.ndarray:
        """后处理: 缩放回原始尺寸, 输出 XYZ 法线图

        Returns:
            np.ndarray: (H, W, 3) float32, X/Y/Z 分量范围 [-1, 1]
        """
        if output is not None:
            # 模型输出 → (H, W, 3) numpy
            normal = output.squeeze(0).permute(1, 2, 0).cpu().numpy()
            # 缩放到原始尺寸
            if normal.shape[:2] != (original_size[1], original_size[0]):
                normal = cv2.resize(
                    normal,
                    (original_size[0], original_size[1]),
                    interpolation=cv2.INTER_LINEAR,
                )
            # 归一化 (确保每个像素是单位向量)
            norm = np.linalg.norm(normal, axis=-1, keepdims=True)
            norm = np.maximum(norm, 1e-8)
            normal = normal / norm
            return normal.astype(np.float32)

        # Fallback: 无模型时返回空法线图 (调用方用 Sobel 近似)
        logger.debug("No normal model output, returning empty normal map")
        return np.zeros(
            (original_size[1], original_size[0], 3),
            dtype=np.float32,
        )

    def estimate_normal_from_depth(
        self,
        depth_map: np.ndarray,
        original_size: tuple[int, int],
    ) -> np.ndarray:
        """Sobel 梯度 + 深度图 → 近似法线 (fallback)

        从深度图构建高度场, 用 Sobel 算子计算梯度, 构造法线。

        Args:
            depth_map: (H, W) float32 深度图 [0, 1]
            original_size: (W, H) 原始图像尺寸

        Returns:
            np.ndarray: (H, W, 3) float32 法线图 [-1, 1]
        """
        depth = depth_map.astype(np.float32)

        # Sobel 梯度 (dx, dy)
        grad_x = cv2.Sobel(depth, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(depth, cv2.CV_32F, 0, 1, ksize=3)

        # 梯度缩放系数 (控制法线陡峭程度)
        scale = 10.0

        # 法线 = normalize([-grad_x * scale, -grad_y * scale, 1.0])
        nx = -grad_x * scale
        ny = -grad_y * scale
        nz = np.ones_like(depth)

        norm = np.sqrt(nx**2 + ny**2 + nz**2)
        norm = np.maximum(norm, 1e-8)

        normal = np.stack([
            nx / norm,
            ny / norm,
            nz / norm,
        ], axis=-1)

        # 缩放到原始尺寸
        if normal.shape[:2] != (original_size[1], original_size[0]):
            normal = cv2.resize(
                normal,
                (original_size[0], original_size[1]),
                interpolation=cv2.INTER_LINEAR,
            )

        return normal.astype(np.float32)

    def predict_normal(
        self,
        image: Image.Image,
        depth_map: np.ndarray | None = None,
    ) -> dict:
        """法线估计 (带 fallback)

        Args:
            image: 输入 RGB 图像
            depth_map: 可选的深度图, 用于 fallback 近似

        Returns:
            dict: {
                "normal": np.ndarray,      # (H, W, 3) 法线图
                "method": str,             # "stable_normal" | "sobel_depth"
                "confidence": np.ndarray,  # (H, W) 法线置信度
            }
        """
        original_size = image.size

        if self.model is not None:
            try:
                normal = self.predict(image)
                method = "stable_normal"
            except Exception as e:
                logger.warning(f"StableNormal inference failed: {e}, falling back to Sobel")
                normal = self.estimate_normal_from_depth(
                    depth_map if depth_map is not None
                    else np.zeros((original_size[1], original_size[0]), dtype=np.float32),
                    original_size,
                )
                method = "sobel_depth"
        else:
            # 无模型: 直接用 Sobel 近似
            if depth_map is not None:
                normal = self.estimate_normal_from_depth(depth_map, original_size)
                method = "sobel_depth"
            else:
                logger.warning("No depth map for normal fallback, returning zeros")
                normal = np.zeros((original_size[1], original_size[0], 3), dtype=np.float32)
                method = "sobel_depth"

        # 置信度: 基于法线梯度 (边缘区域低置信度)
        if normal.shape[0] > 0 and normal.shape[1] > 0:
            grad_x = cv2.Sobel(normal[..., 0], cv2.CV_32F, 1, 0, ksize=3)
            grad_y = cv2.Sobel(normal[..., 0], cv2.CV_32F, 0, 1, ksize=3)
            gradient_mag = np.sqrt(grad_x**2 + grad_y**2)
            max_grad = gradient_mag.max() or 1.0
            confidence = 1.0 - np.clip(gradient_mag / (max_grad * 0.5), 0, 1)
            confidence = confidence.astype(np.float32)
        else:
            confidence = np.zeros((original_size[1], original_size[0]), dtype=np.float32)

        return {
            "normal": normal,
            "method": method,
            "confidence": confidence.astype(np.float32),
        }