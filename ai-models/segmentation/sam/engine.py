"""SAM2 分割引擎 - 场景语义理解 (Phase 2)"""

import logging
import numpy as np
from PIL import Image
from inference_engine import InferenceEngine

logger = logging.getLogger(__name__)


class SAM2Engine(InferenceEngine):
    """SAM2 自动分割引擎

    输出:
        - seg_mask: 分割掩码 (0=background, 1=foreground, 2=object)
        - class_map: 类别映射
        - confidence: 置信度图
    """

    def __init__(self, model_path, device=None):
        self._model_path = model_path
        super().__init__(model_path, device)

    def _load_model(self):
        """加载 SAM2 模型"""
        try:
            from sam2.build_sam import build_sam2
            return build_sam2(self.model_path)
        except ImportError:
            logger.warning(
                "sam2 package not installed. "
                "Install: pip install segment-anything-2"
            )
            raise ImportError(
                "sam2 package required. "
                "Install: pip install segment-anything-2"
            )

    def _preprocess(self, image: Image.Image):
        """SAM2 标准预处理"""
        import torch
        import torchvision.transforms as T

        if image.mode != "RGB":
            image = image.convert("RGB")

        transform = T.Compose([
            T.Resize((1024, 1024)),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        return transform(image).unsqueeze(0).to(self.device)

    def _forward(self, tensor):
        """SAM2 前向推理"""
        import torch
        with torch.no_grad():
            masks, scores, logits = self.model(tensor)
        return {"masks": masks, "scores": scores, "logits": logits}

    def _postprocess(self, output, original_size):
        """后处理: 生成 N 层分割掩码

        Args:
            output: _forward() 的输出
            original_size: (width, height)

        Returns:
            dict: {
                "seg_mask": np.ndarray (H, W), 0=bg, 1~N=objects
                "num_layers": int,
                "confidence": list[float],
            }
        """
        masks = output["masks"]
        scores = output["scores"]

        if isinstance(masks, list):
            masks = np.array(masks)
        if isinstance(scores, list):
            scores = np.array(scores)

        # 按置信度排序，取 Top-K 掩码
        sorted_indices = np.argsort(scores)[::-1]
        top_masks = masks[sorted_indices[:5]]  # 最多 5 个物体

        seg_map = np.zeros(original_size[::-1], dtype=np.uint8)
        for i, mask in enumerate(top_masks):
            mask_resized = np.array(Image.fromarray(
                (mask.squeeze() * 255).astype(np.uint8)
            ).resize(original_size, Image.NEAREST))
            seg_map[mask_resized > 128] = i + 1

        return {
            "seg_mask": seg_map,
            "num_layers": len(top_masks) + 1,
            "confidence": scores[sorted_indices[:5]].tolist(),
        }

    def predict(self, image: Image.Image) -> dict:
        """便捷方法: 运行分割"""
        tensor = self._preprocess(image)
        output = self._forward(tensor)
        return self._postprocess(output, image.size)