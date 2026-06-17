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
    "sam2": {
        "name": "SAM2 Segmentation",
        "version": "v2.0",
        "weight_file": "sam2_hiera_large.pt",
        "path": "segmentation/sam",
        "engine_class": None,
    },
    "lama_inpaint": {
        "name": "LaMa Inpainting",
        "version": "v1.0",
        "weight_file": "lama_large.pt",
        "path": "inpaint/lama",
        "engine_class": None,
    },
    "stable_normal": {
        "name": "Stable Normal",
        "version": "v1.0",
        "weight_file": "stable_normal_turbo.pt",
        "path": "normal/stable_normal",
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
        if model_name == "sam2":
            from segmentation.sam.engine import SAM2Engine
            return SAM2Engine(weight_path)
        if model_name == "lama_inpaint":
            from inpaint.lama.engine import LaMaInpaintEngine
            return LaMaInpaintEngine(weight_path)
        if model_name == "stable_normal":
            from normal.stable_normal.engine import StableNormalEngine
            return StableNormalEngine(weight_path)
        raise ValueError(f"No engine class for model: {model_name}")

    async def run_full_pipeline(self, image: Any) -> dict:
        """运行完整的场景理解流水线 (Phase 2)

        并行运行 Depth + SAM2 分割 + Stable Normal, 然后四路融合。

        Returns:
            dict: 融合后的场景数据, 含 fused_depth, seg_mask, normal_map, num_detected_layers
        """
        import asyncio

        depth_engine = self.get_engine("depth_anything_v2")
        has_seg = "sam2" in _MODEL_REGISTRY
        has_normal = "stable_normal" in _MODEL_REGISTRY

        # 并行运行深度估计和分割
        tasks = [
            asyncio.to_thread(depth_engine.predict_with_confidence, image),
        ]
        task_names = ["depth"]

        if has_seg:
            try:
                seg_engine = self.get_engine("sam2")
                tasks.append(asyncio.to_thread(seg_engine.predict, image))
                task_names.append("seg")
            except Exception:
                logger.warning("SAM2 engine unavailable, using depth-only pipeline")

        if has_normal:
            try:
                normal_engine = self.get_engine("stable_normal")
                tasks.append(
                    asyncio.to_thread(normal_engine.predict_normal, image, None)
                )
                task_names.append("normal")
            except Exception:
                logger.debug("StableNormal unavailable, skipping normal estimation")

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 解析结果
        depth_result = results[0] if not isinstance(results[0], Exception) else None
        seg_result = None
        normal_result = None

        idx = 1
        for name in task_names[1:]:
            if idx < len(results):
                if isinstance(results[idx], Exception):
                    logger.warning(f"Task '{name}' failed: {results[idx]}")
                elif name == "seg":
                    seg_result = results[idx]
                elif name == "normal":
                    normal_result = results[idx]
            idx += 1

        if depth_result is None:
            raise RuntimeError("Depth estimation failed — pipeline cannot continue")

        if seg_result is None:
            seg_result = {"seg_mask": None, "num_layers": 3}
        if normal_result is None:
            normal_result = {"normal": None, "method": "none", "confidence": None}

        return depth_engine.fuse_multi_modal(depth_result, seg_result, normal_result)

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
