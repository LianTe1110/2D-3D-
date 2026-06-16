"""LeiaPix AI - 模型管理器

统一管理所有 AI 模型的加载、切换和版本管理。
"""

import logging
from pathlib import Path
from typing import Any

from inference_engine import InferenceEngine

logger = logging.getLogger(__name__)

# 模型注册表
_MODEL_REGISTRY: dict[str, dict[str, Any]] = {
    "depth_anything_v2": {
        "name": "Depth Anything V2",
        "version": "v2.0",
        "weight_file": "depth_anything_v2_vitl.pth",
        "path": "depth/depth_anything_v2",
        "engine_class": None,
    },
    "real_esrgan_x4plus": {
        "name": "Real-ESRGAN x4plus",
        "version": "v1.0",
        "weight_file": "RealESRGAN_x4plus.pth",
        "path": "enhance/real_esrgan",
        "engine_class": None,
    },
}


class ModelManager:
    """AI 模型管理器 — 单例模式"""

    _instance: "ModelManager | None" = None
    _engines: dict[str, InferenceEngine]

    def __new__(cls) -> "ModelManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._engines = {}
        return cls._instance

    @property
    def model_base_path(self) -> Path:
        return Path(__file__).parent

    def get_engine(self, model_name: str) -> InferenceEngine:
        """获取推理引擎（懒加载）"""
        if model_name in self._engines:
            return self._engines[model_name]

        if model_name not in _MODEL_REGISTRY:
            raise ValueError(
                f"Unknown model: {model_name}. "
                f"Available: {list(_MODEL_REGISTRY.keys())}"
            )

        config = _MODEL_REGISTRY[model_name]
        weight_path = self.model_base_path / config["path"] / config["weight_file"]

        # 延迟导入具体引擎类
        engine = self._create_engine(model_name, weight_path)
        engine.load()
        self._engines[model_name] = engine
        logger.info(f"Model '{model_name}' loaded and cached")
        return engine

    def _create_engine(self, model_name: str, weight_path: Path) -> InferenceEngine:
        """创建具体推理引擎实例"""
        if model_name == "depth_anything_v2":
            from depth.depth_anything_v2.engine import DepthAnythingV2Engine
            return DepthAnythingV2Engine(weight_path)
        if model_name == "real_esrgan_x4plus":
            from enhance.real_esrgan.engine import RealESRGANEngine
            return RealESRGANEngine(weight_path, scale=4)
        raise ValueError(f"No engine class for model: {model_name}")

    def unload(self, model_name: str) -> None:
        """卸载指定模型释放显存"""
        if model_name in self._engines:
            self._engines[model_name].unload()
            del self._engines[model_name]

    def unload_all(self) -> None:
        """卸载所有模型"""
        for name in list(self._engines.keys()):
            self.unload(name)

    def list_available(self) -> list[dict[str, Any]]:
        """列出所有可用模型"""
        result = []
        for name, config in _MODEL_REGISTRY.items():
            weight_path = self.model_base_path / config["path"] / config["weight_file"]
            result.append({
                "name": name,
                "display_name": config["name"],
                "version": config["version"],
                "loaded": name in self._engines,
                "weight_exists": weight_path.exists(),
            })
        return result
