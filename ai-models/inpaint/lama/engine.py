"""LaMa (Large Mask Inpainting) 引擎 - 遮挡区域补全 (Phase 2 / Level 3)

Level 3 增强:
    - depth-aware inpainting: 利用深度图引导补全方向
    - soft mask 支持: 接受 0~1 float 掩码
    - 多策略 fallback: LaMa → OpenCV Navier-Stokes → OpenCV Telea
"""

import logging
import numpy as np
import torch
from PIL import Image
from inference_engine import InferenceEngine

logger = logging.getLogger(__name__)


class LaMaInpaintEngine(InferenceEngine):
    """LaMa Resolution-Independent Inpainting

    特点:
        - Fast Fourier Convolution (FFC) 感受野无限大
        - 分辨率无关 (任意尺寸直接推理)
        - 推理速度 ~100ms (1080p on RTX 3090)
    """

    def _load_model(self):
        """加载 LaMa 模型"""
        try:
            from lama_models import build_lama_model
            model = build_lama_model(self.model_path)
            return model
        except ImportError:
            # Fallback: 尝试简单的 U-Net 架构
            logger.warning(
                "lama_models not installed, using OpenCV fallback. "
                "Install: pip install lama-cleaner"
            )
            return None

    def _preprocess(self, image: Image.Image, mask: np.ndarray):
        """预处理: image + mask -> model input

        Args:
            image: 原始 RGB 图像
            mask: 二值遮罩 (H, W), 255=inpaint 区域
        """
        image_np = np.array(image.convert("RGB"))
        image_tensor = torch.from_numpy(image_np).float() / 255.0
        image_tensor = image_tensor.permute(2, 0, 1).unsqueeze(0)  # (1,3,H,W)

        mask_tensor = torch.from_numpy(mask.astype(np.float32)) / 255.0
        mask_tensor = mask_tensor.unsqueeze(0).unsqueeze(0)  # (1,1,H,W)

        return {
            "image": image_tensor.to(self.device),
            "mask": mask_tensor.to(self.device),
        }

    def _forward(self, inputs: dict):
        """LaMa 前向推理"""
        image = inputs["image"]
        mask = inputs["mask"]
        masked_image = image * (1 - mask)

        with torch.no_grad():
            if self.model is not None:
                output = self.model(masked_image, mask)
            else:
                # Fallback: 返回原图 (no-op)
                output = image
        return output

    def _postprocess(self, output: torch.Tensor, original_size: tuple) -> np.ndarray:
        """后处理: tensor -> numpy RGB"""
        result = output.squeeze().permute(1, 2, 0).cpu().numpy()
        result = (result * 255).clip(0, 255).astype(np.uint8)
        return result

    def inpaint_layer(
        self,
        layer_texture: Image.Image,
        occlusion_mask: np.ndarray,
        original_image: Image.Image,
        depth_map: np.ndarray | None = None,
        depth_aware: bool = True,
    ) -> Image.Image:
        """对单层执行 inpainting (Level 3: depth-aware)

        Args:
            layer_texture: 该层 RGBA 纹理
            occlusion_mask: 遮挡掩码 (需要补全的区域, uint8 或 float32)
            original_image: 原始完整图像 (作为 inpainting 参照)
            depth_map: 深度图 (H, W) float32 [0,1] (可选, depth-aware 引导)
            depth_aware: 是否启用深度引导 inpainting

        Returns:
            inpainted RGBA Image
        """
        # 统一掩码格式: 支持 soft mask (0~1 float) 和 binary mask (0/255 uint8)
        if occlusion_mask.dtype in (np.float32, np.float64):
            valid_mask = (occlusion_mask > 0.1).astype(np.uint8) * 255
        else:
            valid_mask = (occlusion_mask > 128).astype(np.uint8) * 255

        if valid_mask.sum() < 100:
            return layer_texture

        # Depth-aware: 扩展遮挡掩码到深度连续区域
        if depth_aware and depth_map is not None:
            valid_mask = self._expand_mask_by_depth(valid_mask, depth_map)

        if self.model is not None:
            inputs = self._preprocess(original_image, valid_mask)
            output = self._forward(inputs)
            inpainted_rgb = self._postprocess(output, original_image.size)
        else:
            # OpenCV fallback: Navier-Stokes (效果更好) → Telea
            import cv2
            original_np = np.array(original_image.convert("RGB"))
            try:
                inpainted_rgb = cv2.inpaint(
                    original_np, valid_mask, inpaintRadius=5,
                    flags=cv2.INPAINT_NS
                )
            except Exception:
                inpainted_rgb = cv2.inpaint(
                    original_np, valid_mask, inpaintRadius=3,
                    flags=cv2.INPAINT_TELEA
                )

        layer_np = np.array(layer_texture.convert("RGBA"))
        mask_binary = valid_mask > 128
        replace_region = mask_binary & (layer_np[:, :, 3] > 0)
        layer_np[replace_region, :3] = inpainted_rgb[replace_region]

        return Image.fromarray(layer_np)

    def _expand_mask_by_depth(
        self,
        mask: np.ndarray,
        depth_map: np.ndarray,
        depth_threshold: float = 0.05,
    ) -> np.ndarray:
        """Depth-aware: 沿深度连续方向扩展掩码

        当相机移动时, 遮挡区域通常与前景深度连续。
        此方法将掩码扩展到深度相近的邻域, 确保补全区域覆盖完整。

        Args:
            mask: 二值掩码 (H, W) uint8 {0, 255}
            depth_map: 深度图 (H, W) float32 [0, 1]
            depth_threshold: 深度差异阈值

        Returns:
            扩展后的掩码 (H, W) uint8 {0, 255}
        """
        import cv2

        mask_binary = (mask > 128).astype(np.uint8)
        if mask_binary.sum() == 0:
            return mask

        # 获取掩码区域的平均深度
        masked_depth = depth_map[mask_binary > 0]
        if len(masked_depth) == 0:
            return mask

        mean_depth = np.mean(masked_depth)
        std_depth = np.std(masked_depth) or 0.01

        # 扩展到深度相近的区域
        depth_nearby = np.abs(depth_map - mean_depth) < (std_depth * 3 + depth_threshold)
        expanded = np.logical_or(mask_binary, depth_nearby).astype(np.uint8) * 255

        # 形态学闭运算 (填充小孔洞)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        expanded = cv2.morphologyEx(expanded, cv2.MORPH_CLOSE, kernel)

        return expanded