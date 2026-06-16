"""LeiaPix AI - Real-ESRGAN 超分辨率推理引擎

基于 Real-ESRGAN x4plus 的图像超分辨率增强。
支持 4x 超分辨率放大，自动分块处理大图防止 OOM。
"""

import logging
import math
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from inference_engine import InferenceEngine

logger = logging.getLogger(__name__)

# 分块处理参数 (防止大图 OOM)
TILE_SIZE = 512       # 分块大小
TILE_PAD = 10         # 分块重叠像素
DEFAULT_SCALE = 4     # 默认 4x 超分


class RealESRGANEngine(InferenceEngine):
    """Real-ESRGAN x4plus 超分辨率引擎"""

    def __init__(
        self,
        model_path: str | Path,
        scale: int = DEFAULT_SCALE,
        tile_size: int = TILE_SIZE,
        tile_pad: int = TILE_PAD,
        device: str | None = None,
    ):
        self.scale = scale
        self.tile_size = tile_size
        self.tile_pad = tile_pad
        self.half = False  # FP16 推理 (仅 CUDA)
        super().__init__(model_path, device)

    def _load_model(self) -> torch.nn.Module:
        """加载 Real-ESRGAN 模型"""
        try:
            from basicsr.archs.rrdbnet_arch import RRDBNet
            from realesrgan import RealESRGANer
        except ImportError:
            logger.error(
                "realesrgan package not installed!\n"
                "Install: pip install realesrgan basicsr\n"
                "Or: pip install realesrgan-ncnn-vulkan"
            )
            raise ImportError(
                "realesrgan package required. "
                "Install: pip install realesrgan basicsr"
            )

        # Real-ESRGAN x4plus 模型结构
        model = RRDBNet(
            num_in_ch=3,
            num_out_ch=3,
            num_feat=64,
            num_block=23,
            num_grow_ch=32,
            scale=self.scale,
        )

        # 使用 RealESRGANer 包装器 (内置分块处理)
        netscale = self.scale

        # 加载权重
        state_dict = torch.load(
            str(self.model_path),
            map_location=self.device,
            weights_only=True,
        )

        # 兼容不同权重格式
        if "params_ema" in state_dict:
            state_dict = state_dict["params_ema"]
        elif "params" in state_dict:
            state_dict = state_dict["params"]

        model.load_state_dict(state_dict, strict=True)

        # 检测是否可使用 FP16
        if self.device.type == "cuda":
            self.half = True
            model = model.half()

        return model

    def _preprocess(self, image: Image.Image) -> torch.Tensor:
        """图像预处理: RGB → Tensor → 归一化 [0, 1]"""
        if image.mode != "RGB":
            image = image.convert("RGB")

        img_np = np.array(image).astype(np.float32) / 255.0
        img_tensor = torch.from_numpy(img_np).permute(2, 0, 1).unsqueeze(0)

        if self.half:
            img_tensor = img_tensor.half()

        return img_tensor.to(self.device)

    def _forward(self, tensor: torch.Tensor) -> torch.Tensor:
        """前向传播 (带分块处理)"""
        _, _, h, w = tensor.shape

        # 小图直接推理
        if h <= self.tile_size and w <= self.tile_size:
            return self.model(tensor)

        # 大图分块处理
        return self._tile_process(tensor)

    def _tile_process(self, tensor: torch.Tensor) -> torch.Tensor:
        """分块处理大图, 防止 OOM

        将大图分割为 tile_size × tile_size 的块,
        每块独立推理后拼接, 重叠区域取均值
        """
        batch, channel, height, width = tensor.shape
        output_height = height * self.scale
        output_width = width * self.scale
        output_shape = (batch, channel, output_height, output_width)

        # 初始化输出张量和权重图
        output = torch.zeros(output_shape, dtype=tensor.dtype, device=tensor.device)
        tiles_weight = torch.zeros((batch, 1, output_height, output_width), dtype=tensor.dtype, device=tensor.device)

        tiles = []

        # 生成分块坐标
        for h_idx in range(0, height, self.tile_size):
            for w_idx in range(0, width, self.tile_size):
                h_end = min(h_idx + self.tile_size, height)
                w_end = min(w_idx + self.tile_size, width)

                # 加上 padding
                h_start = max(0, h_idx - self.tile_pad)
                w_start = max(0, w_idx - self.tile_pad)
                h_end_pad = min(height, h_end + self.tile_pad)
                w_end_pad = min(width, w_end + self.tile_pad)

                tiles.append((h_idx, w_idx, h_end, w_end, h_start, w_start, h_end_pad, w_end_pad))

        # 逐块推理
        for h_idx, w_idx, h_end, w_end, h_start, w_start, h_end_pad, w_end_pad in tiles:
            tile_input = tensor[:, :, h_start:h_end_pad, w_start:w_end_pad]

            with torch.no_grad():
                tile_output = self.model(tile_input)

            # 计算输出坐标
            out_h_start = h_start * self.scale
            out_w_start = w_start * self.scale
            out_h_end = h_end_pad * self.scale
            out_w_end = w_end_pad * self.scale

            # 裁剪到实际区域
            out_h_idx = h_idx * self.scale
            out_w_idx = w_idx * self.scale
            out_h_end = h_end * self.scale
            out_w_end = w_end * self.scale

            # 计算输入裁剪偏移
            crop_h_start = (h_idx - h_start) * self.scale
            crop_w_start = (w_idx - w_start) * self.scale
            crop_h_end = crop_h_start + (h_end - h_idx) * self.scale
            crop_w_end = crop_w_start + (w_end - w_idx) * self.scale

            # 裁剪有效区域
            tile_output_cropped = tile_output[:, :, crop_h_start:crop_h_end, crop_w_start:crop_w_end]

            # 累加到输出
            output[:, :, out_h_idx:out_h_end, out_w_idx:out_w_end] += tile_output_cropped
            tiles_weight[:, :, out_h_idx:out_h_end, out_w_idx:out_w_end] += 1.0

        # 取均值
        output = output / tiles_weight

        return output

    def _postprocess(self, output: torch.Tensor, original_size: tuple[int, int]) -> np.ndarray:
        """后处理: Tensor → numpy [0, 255] uint8"""
        output = output.squeeze(0).permute(1, 2, 0).cpu()

        if self.half:
            output = output.float()

        output = output.numpy()
        output = np.clip(output * 255.0, 0, 255).astype(np.uint8)

        return output

    def enhance(self, image: Image.Image) -> Image.Image:
        """便捷方法: 超分辨率增强并返回 PIL Image"""
        result = self.predict(image)
        # result 是 (H*scale, W*scale, 3) 的 numpy 数组
        return Image.fromarray(result, mode="RGB")

    def enhance_with_timing(self, image: Image.Image) -> tuple[Image.Image, float]:
        """增强并返回耗时 (ms)"""
        start = __import__("time").time()
        enhanced = self.enhance(image)
        elapsed_ms = (__import__("time").time() - start) * 1000
        return enhanced, elapsed_ms
