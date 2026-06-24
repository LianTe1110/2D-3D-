# 2D → 3D 图片转换工具

> 基于 AI 深度估计 + Three.js 的图片 3D 化工具

[![React](https://img.shields.io/badge/React-19-61dafb?logo=react)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-6-3178c6?logo=typescript)](https://www.typescriptlang.org)
[![Three.js](https://img.shields.io/badge/Three.js-0.184-black?logo=three.js)](https://threejs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.137-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.7-ee4c2c?logo=pytorch)](https://pytorch.org)

把任意 2D 图片扔进去，AI 自动生成深度图，在浏览器里实时渲染出可以**视差摆动 / 环绕旋转 / 推进穿越**的 3D 效果，一键导出 MP4 / GIF / 深度图。

---
## 首页和工作台
![Uploading 屏幕截图 2026-06-24 103318.png…]()

![Uploading 屏幕截图 2026-06-24 103216.png…]()



## 效果展示

### 1. 视差摆动动画（GIF）

![3D 视差效果](leiapix_3d_1a97fd82.gif)![3D 视差效果](leiapix_3d_4efd139a.gif)
![3D 视差效果](leiapix_3d_c25cf8c3.gif)![3D 视差效果](leiapix_3d_c71c5e92.gif)

> 单层深度 + GLSL 视差位移着色器
> 前景猫咪 → 中景石墙 → 远景天空，鼠标拖拽可自由旋转视角

### 2. 3D 动画视频（MP4 1080p · 浏览器内 ffmpeg.wasm 编码）

**视频一 · 微风轻拂 (swing)**

<video src="leiapix_3d_eecf0693.mp4" controls width="100%"></video>

**视频二 · 深度呼吸 (zoom)**

<video src="leiapix_3d_3acdba41.mp4" controls width="100%"></video>

**视频三 · 沉浸穿越 (dolly)**

<video src="leiapix_3d_940e8b12.mp4" controls width="100%"></video>

### 3. 多格式导出

| 格式 | 分辨率 | 帧率 | 引擎 | 文件 |
|------|--------|------|------|------|
| MP4 | 1080p | 30fps | 前端 ffmpeg.wasm (libx264 / CRF 23 / yuv420p / faststart) | [eecf0693](leiapix_3d_eecf0693.mp4) · [3acdba41](leiapix_3d_3acdba41.mp4) · [940e8b12](leiapix_3d_940e8b12.mp4) |
| GIF | 480px | 15fps | 前端 ffmpeg.wasm (调色板优化 + Bayer 抖动) | [1a97fd82](leiapix_3d_1a97fd82.gif) |
| 深度图 PNG | 原分辨率 | - | 直接下载 | 编辑器内一键导出 |

### 4. 5 种动画预设

| 预设 | 中文 | 效果 |
|------|------|------|
| `swing` | 微风轻拂 | 水平视差 + 前景微动 |
| `zoom` | 深度呼吸 | 缓慢缩放 + 景深变化 |
| `rotate` | 环绕凝视 | 缓慢旋转环绕 |
| `parallax` | 平行世界 | 水平视差平移 |
| `dolly` | 沉浸穿越 | 前进推进 + 景深 |

---

## 核心特性

- **AI 深度估计** — 集成 [Depth Anything V2](https://github.com/DepthAnything/Depth-Anything-V2) (ViT-L)，可选 SAM2 语义分割、Stable Normal 法线估计、LaMa Inpainting
- **多模态融合** — Depth + Segmentation + Normal + Confidence 四路加权融合，深度图更准
- **MPI 多层渲染** — Otsu 自适应分层 + Soft Mask 羽化 + 边缘膨胀，解决 3D 视差撕裂和孔洞问题
- **浏览器内编码** — ffmpeg.wasm 在前端直接出 MP4 / GIF，无需后端算力
- **WebSocket 实时进度** — 任务状态秒级推送，WS 断开自动降级为 HTTP 轮询
- **公开分享** — 生成短链接 + iframe 嵌入代码，支持第三方网站直接嵌入 3D 预览
- **零配置部署** — Docker Compose 一键拉起 PostgreSQL / Redis / MinIO / MongoDB / 4 个 Worker

---

## 技术栈

**前端** — React 19 · TypeScript 6 · Vite · Three.js 0.184 · @react-three/fiber · Framer Motion · Zustand · Tailwind CSS v4 · ffmpeg.wasm

**后端** — FastAPI 0.137 · SQLAlchemy 2.0 (asyncpg) · Celery 5.6 · Redis · PostgreSQL 16 · MongoDB 7 · MinIO · JWT (python-jose) · Pydantic v2

**AI** — PyTorch 2.7 (CPU/GPU) · HuggingFace Transformers · OpenCV · Pillow · NumPy

---

## 项目结构

```
conversion/
├── frontend/                    # React 前端 (Vite + TypeScript)
│   ├── src/
│   │   ├── components/preview/  # Scene3D (Three.js 3D 渲染) · InstancedMPILayers
│   │   ├── pages/               # HomePage · EditorPage · SharePage
│   │   ├── services/            # api.ts · ws.ts · export-engine.ts (ffmpeg.wasm)
│   │   ├── stores/              # editor-store.ts (Zustand 全局状态)
│   │   ├── types/               # 全局 TypeScript 类型
│   │   └── lib/                 # logger · performance-cache · animation-engine
│   └── package.json
│
├── backend/                     # FastAPI 后端
│   ├── app/
│   │   ├── api/v1/              # upload · depth · render · export · enhance · share · auth · ws
│   │   ├── models/              # user · image · depth_map · scene · task · export · share (Mongo)
│   │   ├── core/                # config · database · redis · security · celery_app · logging
│   │   ├── services/            # storage_service (MinIO) · share_service
│   │   ├── tasks/               # Celery 异步任务 (深度/增强/渲染/导出)
│   │   └── main.py              # FastAPI 入口
│   └── requirements.txt
│
├── ai-models/                   # AI 推理引擎 (独立于后端框架)
│   ├── inference_engine.py      # 推理引擎基类
│   ├── model_manager.py         # 模型管理器 (单例懒加载)
│   ├── depth/depth_anything_v2/ # DAV2 引擎 (融合/分层/Inpainting)
│   ├── segmentation/sam/        # SAM2 语义分割
│   ├── enhance/real_esrgan/     # Real-ESRGAN 超分辨率
│   ├── inpaint/lama/            # LaMa 遮挡修复
│   └── normal/stable_normal/    # 法线估计
│
├── deploy/docker/               # Docker Compose 编排
│   ├── docker-compose.yml       # 8 个服务 (PostgreSQL/Redis/MinIO/MongoDB/3 Worker)
│   └── Dockerfile.*
│
├── Makefile                     # 快捷开发命令
└── PROJECT_DOCUMENTATION.md     # 完整技术文档
```

---

## 快速开始

### 0. 环境要求

- Node.js ≥ 20
- Python ≥ 3.11
- Docker + Docker Compose
- 模型权重: 见 [ai-models/weights/](ai-models/weights/) 目录 (需自行下载 DAV2 / SAM2 / LaMa 等权重)

### 1. 启动中间件

```bash
docker compose -f deploy/docker/docker-compose.yml up -d postgres redis minio mongodb
docker compose -f deploy/docker/docker-compose.yml up -d minio-init   # 初始化 Bucket
```

### 2. 启动后端 API

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate              # Windows
pip install -r requirements.txt

# 数据库迁移
alembic upgrade head                  # 或 alembic stamp head (已建表时)

# 启动 API
uvicorn app.main:app --reload --port 8000
```

### 3. 启动 Celery Worker

```bash
cd backend
# CPU 模式 (无 GPU)
set GPU_ENABLED=false && python -m celery -A app.core.celery_app:celery_app worker --loglevel=info --pool=solo -Q gpu_depth
```

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev                          # 默认 http://localhost:3001
```

打开浏览器访问 **http://localhost:3001**，上传一张 2D 图片，等 AI 生成深度图（~20 秒），即可在 3D 场景中自由旋转 / 切换动画 / 导出视频。

---

## 完整 AI 处理流水线

```
用户上传 2D 图片
    ↓
[10%] MinIO 下载原图
    ↓
[30%] 加载 Depth Anything V2 (ViT-L)
    ↓
[50%] 深度估计推理 (~2s @ CPU)
    ↓
[80%] 上传深度图 PNG
    ↓
[85%] MPI 分层 (可选 SAM2 + Stable Normal + LaMa Inpainting)
    ↓
[90%] 入库 PostgreSQL
    ↓
[100%] WebSocket 推送完成 → 前端 3D 渲染
```

---

## 数据库结构 (PostgreSQL)

| 表 | 用途 |
|----|------|
| `users` | 用户账号 (bcrypt + JWT) |
| `images` | 原图元数据 (含 MinIO 存储键) |
| `depth_maps` | 深度图记录 (关联图片) |
| `scenes` | 3D 场景元数据 (渲染/动画参数) |
| `tasks` | 异步任务统一表 (深度/增强/导出) |
| `exports` | 导出文件记录 (下载链接 + 过期时间) |
| `shares` (MongoDB) | 分享数据 (浏览/下载计数 + 嵌入代码) |

---

## 任务队列 (Celery)

| 任务 | 队列 | Worker | 并发 |
|------|------|--------|------|
| `estimate_depth` | `gpu_depth` | GPU | 2 (24G) / 1 (12G) |
| `enhance_image` | `gpu_enhance` | GPU | 1 |
| `export_video` | `export` | CPU | 4 |
| `render_3d` | `gpu_render` | GPU | 2 |

---

## 代码规范

- **前端** — ESLint + Prettier (`npm run lint`)
- **后端** — Ruff + mypy (`ruff check .` / `mypy app/`)
- **提交信息** — Conventional Commits

---

## 路线图

- [x] 基础深度估计 + 视差渲染
- [x] 5 种动画预设
- [x] MP4 / GIF / 深度图导出
- [x] WebSocket 实时进度 + 降级轮询
- [x] 公开分享链接 + iframe 嵌入
- [x] SAM2 语义分割 + LaMa Inpainting
- [ ] Stable Diffusion 画风迁移 (anime / oil_painting / cyberpunk)
- [ ] 视频深度估计 (时序一致性)
- [ ] 移动端 App (React Native + Expo)
- [ ] 多用户协作编辑

---

## 致谢

- [Depth Anything V2](https://github.com/DepthAnything/Depth-Anything-V2) — 深度估计
- [SAM2](https://github.com/facebookresearch/segment-anything-2) — 语义分割
- [LaMa](https://github.com/advimman/lama) — Inpainting
- [Three.js](https://threejs.org) — WebGL 3D 渲染
- [ffmpeg.wasm](https://github.com/ffmpegwasm/ffmpeg.wasm) — 浏览器内视频编码
- [LeiaPix / Immersity AI](https://www.immersity.ai/) — 产品灵感来源

---

## License

MIT
