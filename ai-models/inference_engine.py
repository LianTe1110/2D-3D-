"""LeiaPix AI - 通用推理引擎

提供模型加载、设备适配、图像预处理和前向传播的通用框架。
"""

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
import torch
from PIL import Image

logger = logging.getLogger(__name__)


class InferenceEngine(ABC):
    """通用推理引擎基类

    子类需实现:
        - _load_model(): 加载模型权重
        - _preprocess(image): 图像预处理
        - _forward(tensor): 前向传播
        - _postprocess(output): 后处理
    """

    def __init__(self, model_path: str | Path, device: str | None = None):
        self.model_path = Path(model_path)
        self.device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        self.model: torch.nn.Module | None = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded and self.model is not None

    def load(self) -> None:
        """加载模型权重"""
        if self.is_loaded:
            logger.info(f"Model already loaded: {self.model_path.name}")
            return

        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Model weight not found: {self.model_path}\n"
                f"Please download it first."
            )

        logger.info(f"Loading model from {self.model_path} to {self.device}")
        start = time.time()
        self.model = self._load_model()
        self.model.to(self.device)
        self.model.eval()
        self._loaded = True
        elapsed = time.time() - start
        logger.info(f"Model loaded in {elapsed:.2f}s")

    @abstractmethod
    def _load_model(self) -> torch.nn.Module:
        """加载模型权重，子类实现"""
        ...

    @abstractmethod
    def _preprocess(self, image: Image.Image) -> torch.Tensor:
        """图像预处理（缩放、归一化等），子类实现"""
        ...

    @abstractmethod
    def _forward(self, tensor: torch.Tensor) -> torch.Tensor:
        """前向传播，子类实现"""
        ...

    @abstractmethod
    def _postprocess(self, output: torch.Tensor, original_size: tuple[int, int]) -> np.ndarray:
        """后处理，子类实现"""
        ...

    def predict(self, image: Image.Image) -> np.ndarray:
        """完整推理流程: 预处理 → 前向传播 → 后处理

        Args:
            image: PIL 输入图像 (RGB)

        Returns:
            numpy 数组 (深度图 / 增强图等)
        """
        if not self.is_loaded:
            self.load()

        original_size = image.size  # (W, H)

        with torch.no_grad():
            tensor = self._preprocess(image)
            output = self._forward(tensor)
            result = self._postprocess(output, original_size)

        return result

    def predict_with_timing(self, image: Image.Image) -> tuple[np.ndarray, float]:
        """推理并返回耗时 (ms)"""
        start = time.time()
        result = self.predict(image)
        elapsed_ms = (time.time() - start) * 1000
        return result, elapsed_ms

    def unload(self) -> None:
        """卸载模型释放显存"""
        if self.model is not None:
            del self.model
            self.model = None
            self._loaded = False
            if self.device.type == "cuda":
                torch.cuda.empty_cache()
            logger.info("Model unloaded, GPU cache cleared")
