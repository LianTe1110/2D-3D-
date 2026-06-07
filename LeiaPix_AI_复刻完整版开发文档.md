# LeiaPix AI 复刻版 — 完整项目开发文档

> **版本**: v1.0.0
> **最后更新**: 2026-06-06
> **文档状态**: 开发基线
> **项目代号**: LeiaPix-3D

---

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 产品需求规格说明](#2-产品需求规格说明)
- [3. 系统架构设计](#3-系统架构设计)
- [4. 核心算法设计](#4-核心算法设计)
- [5. 前端设计](#5-前端设计)
- [6. 后端设计](#6-后端设计)
- [7. 数据库与存储设计](#7-数据库与存储设计)
- [8. 安全设计](#8-安全设计)
- [9. 性能设计](#9-性能设计)
- [10. 测试策略](#10-测试策略)
- [11. 部署架构](#11-部署架构)
- [12. CI/CD 与 DevOps](#12-cicd-与-devops)
- [13. 监控与运维](#13-监控与运维)
- [14. 开发规范](#14-开发规范)
- [15. 项目管理与排期](#15-项目管理与排期)
- [16. 扩展规划](#16-扩展规划)
- [附录](#附录)

---

## 1. 项目概述

### 1.1 项目背景

LeiaPix AI 是 Leia Inc. 推出的一项创新 AI 技术，它彻底改变了我们观看和分享照片的方式。这款工具的核心优势在于其强大的 AI 算法，能够模拟深度感知，将任何一张普通的 2D 照片瞬间赋予三维生命力。它通过 AI 驱动的深度映射软件智能识别图片中元素的空间距离，并在此基础上生成惊人的 3D 效果。用户不仅可以轻松地将平面图片转化为具有立体感的视觉体验，还能进一步调整视角、添加各种动画效果，让每一张照片都充满动态和沉浸感。

### 1.2 项目目标

复刻并实现一款完整的 2D → 3D 图片转换工具，具备以下核心能力：

| 序号 | 目标 | 优先级 | 说明 |
|------|------|--------|------|
| 1 | 单张图片深度估计 | P0 | 输入 2D 图片，AI 自动生成深度图 |
| 2 | 3D 重建与视差动画 | P0 | 基于深度图生成可交互 3D 场景 |
| 3 | 动态视角交互 | P0 | 用户可旋转、缩放、平移 3D 场景 |
| 4 | 动画效果系统 | P1 | 预设动画模板 + 自定义参数调节 |
| 5 | 图像增强 | P1 | 超分辨率、光照修正、去噪 |
| 6 | 导出与分享 | P1 | 视频/GIF 导出、链接分享 |
| 7 | 前端用户界面 | P0 | 完整的 Web 端交互体验 |

### 1.3 目标用户

| 用户类型 | 使用场景 | 核心需求 |
|----------|----------|----------|
| 摄影爱好者 | 将照片转为 3D 动态效果 | 操作简单、效果自然 |
| 社交媒体创作者 | 制作 3D 动态内容 | 快速生成、方便分享 |
| 设计师 | 创作沉浸式视觉内容 | 高质量输出、自定义参数 |
| 开发者 | 集成 3D 转换能力 | API 接口、批量处理 |

### 1.4 核心价值主张

- **零门槛**: 上传即得 3D，无需专业 3D 建模知识
- **高质量**: AI 深度估计精度高，3D 效果自然逼真
- **可交互**: 实时旋转、缩放、动画，沉浸式体验
- **可创作**: 丰富的动画模板和参数调节，激发创意
- **可分享**: 一键导出视频/GIF，链接即分享

---

## 2. 产品需求规格说明

### 2.1 功能需求矩阵

#### 2.1.1 图片上传模块

| 功能 ID | 功能名称 | 描述 | 输入 | 输出 | 优先级 |
|---------|----------|------|------|------|--------|
| F-UP-001 | 本地图片上传 | 用户从本地选择图片上传 | 图片文件 (JPG/PNG/WEBP) | image_id, 缩略图 URL | P0 |
| F-UP-002 | 拖拽上传 | 支持拖拽图片到指定区域 | 拖拽文件 | image_id, 缩略图 URL | P0 |
| F-UP-003 | 粘贴上传 | 支持剪贴板粘贴图片 | 剪贴板图片数据 | image_id, 缩略图 URL | P1 |
| F-UP-004 | URL 导入 | 通过图片 URL 远程导入 | 图片 URL | image_id, 缩略图 URL | P2 |
| F-UP-005 | 图片格式校验 | 校验上传文件格式与大小 | 文件元数据 | 校验结果 (pass/reject) | P0 |
| F-UP-006 | 图片预处理 | 自动旋转(EXIF)、压缩、缩放 | 原始图片 | 预处理后图片 | P0 |

**图片上传约束**:

| 约束项 | 限制值 | 说明 |
|--------|--------|------|
| 最大文件大小 | 20 MB | 超过提示压缩或裁剪 |
| 支持格式 | JPG, PNG, WEBP, BMP | 不支持 RAW/HEIC |
| 最小分辨率 | 256×256 | 低于此值提示质量不佳 |
| 最大分辨率 | 8192×8192 | 超过自动缩放 |
| 单用户并发上传 | 3 张 | 防止资源滥用 |

#### 2.1.2 深度估计模块

| 功能 ID | 功能名称 | 描述 | 输入 | 输出 | 优先级 |
|---------|----------|------|------|------|--------|
| F-DE-001 | 自动深度估计 | AI 模型自动生成深度图 | image_id | depth_map_id | P0 |
| F-DE-002 | 深度图预览 | 可视化展示生成的深度图 | depth_map_id | 灰度深度图 | P0 |
| F-DE-003 | 深度图手动编辑 | 用户可手动调整深度图局部区域 | 编辑指令 | 更新后的 depth_map | P1 |
| F-DE-004 | 深度图精细度调节 | 调节深度估计的精细程度 | 精细度参数 | 重新生成的 depth_map | P2 |
| F-DE-005 | 前景/背景分割 | 自动分割前景与背景区域 | image_id | 分割 mask | P1 |
| F-DE-006 | 多模型对比 | 展示不同深度估计模型的结果 | image_id | 多张 depth_map | P2 |

#### 2.1.3 3D 重建与渲染模块

| 功能 ID | 功能名称 | 描述 | 输入 | 输出 | 优先级 |
|---------|----------|------|------|------|--------|
| F-3D-001 | 自动 3D 重建 | 基于深度图生成 3D 场景 | image_id + depth_map_id | 3D scene_id | P0 |
| F-3D-002 | 实时旋转交互 | 用户拖拽旋转 3D 场景 | 鼠标/触控操作 | 实时渲染画面 | P0 |
| F-3D-003 | 缩放交互 | 滚轮/手势缩放 3D 场景 | 缩放指令 | 实时渲染画面 | P0 |
| F-3D-004 | 平移交互 | 拖拽平移 3D 场景视角 | 平移指令 | 实时渲染画面 | P1 |
| F-3D-005 | 景深模糊(DOF) | 模拟相机景深效果 | 焦点位置、光圈参数 | 带景深模糊的渲染 | P1 |
| F-3D-006 | 空洞填充 | 3D 视差移动后的空洞智能填充 | 原图 + depth_map | 填充后的纹理 | P0 |
| F-3D-007 | 点云渲染模式 | 以点云方式渲染 3D 场景 | 渲染模式参数 | 点云渲染画面 | P2 |
| F-3D-008 | 网格渲染模式 | 以三角网格方式渲染 3D 场景 | 渲染模式参数 | 网格渲染画面 | P2 |

#### 2.1.4 动画效果模块

| 功能 ID | 功能名称 | 描述 | 输入 | 输出 | 优先级 |
|---------|----------|------|------|------|--------|
| F-AN-001 | 预设动画模板 | 提供多种预设动画效果 | 模板选择 | 动画渲染 | P0 |
| F-AN-002 | 摇摆动画 | 相机轻微左右摇摆 | 摇摆幅度、速度 | 动画渲染 | P0 |
| F-AN-003 | 缩放动画 | 相机缓慢推进/拉远 | 缩放范围、速度 | 动画渲染 | P0 |
| F-AN-004 | 旋转动画 | 相机绕场景中心旋转 | 旋转角度、速度 | 动画渲染 | P1 |
| F-AN-005 | 视差平移动画 | 水平/垂直视差平移 | 方向、幅度、速度 | 动画渲染 | P1 |
| F-AN-006 | 粒子特效 | 添加粒子飘散/光效 | 粒子参数 | 动画渲染 | P2 |
| F-AN-007 | 动画参数调节 | 自定义动画各项参数 | 参数值 | 更新后的动画 | P0 |
| F-AN-008 | 动画时间线 | 可视化时间线编辑动画 | 时间线操作 | 更新后的动画 | P2 |

**预设动画模板列表**:

| 模板 ID | 模板名称 | 效果描述 | 适用场景 |
|---------|----------|----------|----------|
| TPL-001 | 微风轻拂 | 轻微水平视差 + 前景微动 | 风景、自然 |
| TPL-002 | 深度呼吸 | 缓慢缩放 + 景深变化 | 人像、静物 |
| TPL-003 | 环绕凝视 | 缓慢旋转环绕 | 建筑、产品 |
| TPL-004 | 平行世界 | 水平视差平移 | 街景、全景 |
| TPL-005 | 星光闪耀 | 缩放 + 粒子光效 | 夜景、星空 |
| TPL-006 | 沉浸穿越 | 前进推进 + 景深 | 风景、走廊 |

#### 2.1.5 图像增强模块

| 功能 ID | 功能名称 | 描述 | 输入 | 输出 | 优先级 |
|---------|----------|------|------|------|--------|
| F-EN-001 | 超分辨率 | 提升图片分辨率 | image_id, 倍率 | 增强后图片 | P1 |
| F-EN-002 | 光照修正 | 自动修正过暗/过亮区域 | image_id | 修正后图片 | P1 |
| F-EN-003 | 去噪处理 | 去除图片噪点 | image_id | 去噪后图片 | P1 |
| F-EN-004 | 色彩增强 | 增强图片色彩饱和度与对比度 | image_id, 参数 | 增强后图片 | P2 |
| F-EN-005 | 一键优化 | 自动选择最佳增强组合 | image_id | 优化后图片 | P1 |

#### 2.1.6 导出与分享模块

| 功能 ID | 功能名称 | 描述 | 输入 | 输出 | 优先级 |
|---------|----------|------|------|------|--------|
| F-EX-001 | 导出 MP4 视频 | 将 3D 动画导出为 MP4 | scene_id, 参数 | MP4 文件 | P0 |
| F-EX-002 | 导出 GIF | 将 3D 动画导出为 GIF | scene_id, 参数 | GIF 文件 | P0 |
| F-EX-003 | 导出深度图 | 导出灰度深度图 | depth_map_id | PNG 文件 | P1 |
| F-EX-004 | 生成分享链接 | 生成可分享的在线预览链接 | scene_id | 分享 URL | P1 |
| F-EX-005 | 嵌入代码 | 生成可嵌入网页的 HTML 代码 | scene_id | HTML 代码片段 | P2 |
| F-EX-006 | 批量导出 | 批量导出多个场景 | scene_id 列表 | 打包文件 | P2 |

**导出参数约束**:

| 参数 | 可选值 | 默认值 | 说明 |
|------|--------|--------|------|
| 视频分辨率 | 720p / 1080p / 4K | 1080p | 输出视频分辨率 |
| 视频帧率 | 24 / 30 / 60 fps | 30 fps | 输出视频帧率 |
| 视频时长 | 1-30 秒 | 5 秒 | 动画循环时长 |
| GIF 尺寸 | 320 / 480 / 640 px | 480 px | GIF 宽度 |
| GIF 帧率 | 10 / 15 / 24 fps | 15 fps | GIF 帧率 |

### 2.2 非功能需求

| 类别 | 需求 ID | 需求描述 | 指标 |
|------|---------|----------|------|
| 性能 | NFR-001 | 深度估计响应时间 | ≤ 10s (1024×1024 图片) |
| 性能 | NFR-002 | 3D 场景加载时间 | ≤ 3s |
| 性能 | NFR-003 | 实时渲染帧率 | ≥ 30 FPS (WebGL) |
| 性能 | NFR-004 | 视频导出时间 | ≤ 30s (5s 1080p 视频) |
| 可用性 | NFR-005 | 系统可用性 | ≥ 99.5% |
| 可用性 | NFR-006 | 并发用户支持 | ≥ 500 同时在线 |
| 安全 | NFR-007 | 数据传输加密 | TLS 1.3 |
| 安全 | NFR-008 | 用户数据隔离 | 租户级隔离 |
| 兼容性 | NFR-009 | 浏览器兼容 | Chrome 90+, Firefox 88+, Safari 15+, Edge 90+ |
| 兼容性 | NFR-010 | 移动端适配 | 响应式布局, iOS Safari / Android Chrome |
| 可扩展 | NFR-011 | 模型热替换 | 支持不停服更换 AI 模型 |
| 可扩展 | NFR-012 | 水平扩展 | 支持多 GPU 节点扩展 |

---

## 3. 系统架构设计

### 3.1 总体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                          用户终端 (Browser)                         │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌──────────────────┐ │
│  │  图片上传  │  │  3D 预览  │  │  动画编辑  │  │  导出/分享       │ │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └────────┬─────────┘ │
│        └───────────────┴──────────────┴─────────────────┘           │
│                              │ HTTPS / WSS                         │
└──────────────────────────────┼──────────────────────────────────────┘
                               │
┌──────────────────────────────┼──────────────────────────────────────┐
│                        CDN / Nginx                                  │
│                   (静态资源 + 反向代理 + 负载均衡)                    │
└──────────────────────────────┼──────────────────────────────────────┘
                               │
┌──────────────────────────────┼──────────────────────────────────────┐
│                     前端应用 (SPA)                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │  React   │ │ Three.js │ │  状态管理 │ │  动画引擎 │ │  导出引擎 │ │
│  │  UI 层   │ │ 渲染引擎 │ │  Zustand │ │  Tween.js│ │  FFmpeg  │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
└──────────────────────────────┼──────────────────────────────────────┘
                               │ REST API / WebSocket
┌──────────────────────────────┼──────────────────────────────────────┐
│                     后端服务 (FastAPI)                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ 上传服务 │ │ 深度估计 │ │ 3D 重建  │ │ 图像增强 │ │ 导出服务 │ │
│  │ /upload  │ │ /depth   │ │ /render  │ │ /enhance │ │ /export  │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                           │
│  │ 认证服务 │ │ 任务队列 │ │ 分享服务 │                           │
│  │ /auth    │ │ Celery   │ │ /share   │                           │
│  └──────────┘ └──────────┘ └──────────┘                           │
└──────────────────────────────┼──────────────────────────────────────┘
                               │
┌──────────────────────────────┼──────────────────────────────────────┐
│                     AI 推理层                                        │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐   │
│  │ Depth Anything V2│ │     MiDaS        │ │   Real-ESRGAN    │   │
│  │  (深度估计主模型) │ │  (深度估计备选)   │ │   (超分辨率)     │   │
│  └──────────────────┘ └──────────────────┘ └──────────────────┘   │
│  ┌──────────────────┐ ┌──────────────────┐                        │
│  │     LeReS        │ │   SAM / SegFormer│                        │
│  │  (深度估计备选)   │ │   (前景分割)     │                        │
│  └──────────────────┘ └──────────────────┘                        │
└──────────────────────────────┼──────────────────────────────────────┘
                               │
┌──────────────────────────────┼──────────────────────────────────────┐
│                     数据存储层                                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐             │
│  │ MinIO/S3 │ │PostgreSQL│ │  Redis   │ │ MongoDB  │             │
│  │ (文件存储)│ │(关系数据)│ │ (缓存)   │ │(分享数据)│             │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘             │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 技术栈选型

| 层级 | 技术 | 版本 | 选型理由 |
|------|------|------|----------|
| **前端框架** | React | 18+ | 组件化、生态丰富、TypeScript 支持好 |
| **前端 3D** | Three.js | r160+ | WebGL 标准库、社区活跃、性能优秀 |
| **前端状态** | Zustand | 4+ | 轻量、TypeScript 友好、无 boilerplate |
| **前端动画** | Tween.js | 25+ | 轻量级补间动画库 |
| **前端构建** | Vite | 5+ | 极速 HMR、ESM 原生支持 |
| **前端 UI** | Tailwind CSS + shadcn/ui | - | 高效样式开发、组件一致性好 |
| **后端框架** | FastAPI | 0.110+ | 异步、高性能、自动 API 文档 |
| **任务队列** | Celery + Redis | 5+ | 成熟的异步任务方案、GPU 任务调度 |
| **深度估计** | Depth Anything V2 | - | SOTA 精度、推理速度快 |
| **深度估计备选** | MiDaS / LeReS | - | 多模型融合、降级容灾 |
| **超分辨率** | Real-ESRGAN | - | 通用图像超分、效果好 |
| **前景分割** | SAM / SegFormer | - | 精确分割、辅助深度估计 |
| **关系数据库** | PostgreSQL | 16+ | 可靠、JSON 支持、扩展性好 |
| **文件存储** | MinIO | - | S3 兼容、私有部署、高性能 |
| **缓存** | Redis | 7+ | 高性能、丰富数据结构 |
| **文档数据库** | MongoDB | 7+ | 灵活 schema、适合分享数据 |
| **容器化** | Docker + K8s | - | 标准化部署、弹性伸缩 |
| **监控** | Prometheus + Grafana | - | 开源标准、可视化好 |

### 3.3 项目目录结构

```
leiapix-ai/
├── frontend/                      # 前端项目
│   ├── public/
│   ├── src/
│   │   ├── assets/                # 静态资源
│   │   ├── components/            # UI 组件
│   │   │   ├── common/            # 通用组件 (Button, Modal, Toast...)
│   │   │   ├── upload/            # 上传相关组件
│   │   │   ├── preview/           # 3D 预览组件
│   │   │   ├── editor/            # 编辑器组件
│   │   │   ├── animation/         # 动画控制组件
│   │   │   └── export/            # 导出/分享组件
│   │   ├── hooks/                 # 自定义 Hooks
│   │   ├── stores/                # Zustand 状态管理
│   │   ├── services/              # API 调用层
│   │   ├── three/                 # Three.js 相关
│   │   │   ├── scene/             # 场景管理
│   │   │   ├── camera/            # 相机控制
│   │   │   ├── renderer/          # 渲染器
│   │   │   ├── animation/         # 动画引擎
│   │   │   └── effects/           # 后处理效果
│   │   ├── utils/                 # 工具函数
│   │   ├── types/                 # TypeScript 类型定义
│   │   └── App.tsx
│   ├── index.html
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   └── package.json
├── backend/                       # 后端项目
│   ├── app/
│   │   ├── api/                   # API 路由
│   │   │   ├── v1/
│   │   │   │   ├── upload.py
│   │   │   │   ├── depth.py
│   │   │   │   ├── render.py
│   │   │   │   ├── enhance.py
│   │   │   │   ├── export.py
│   │   │   │   ├── share.py
│   │   │   │   └── auth.py
│   │   │   └── deps.py            # 依赖注入
│   │   ├── core/                  # 核心配置
│   │   │   ├── config.py
│   │   │   ├── security.py
│   │   │   └── events.py
│   │   ├── models/                # 数据库模型
│   │   ├── schemas/               # Pydantic 模型
│   │   ├── services/              # 业务逻辑
│   │   │   ├── depth_estimator.py
│   │   │   ├── renderer_3d.py
│   │   │   ├── image_enhancer.py
│   │   │   ├── video_exporter.py
│   │   │   └── share_manager.py
│   │   ├── tasks/                 # Celery 异步任务
│   │   │   ├── depth_task.py
│   │   │   ├── render_task.py
│   │   │   ├── enhance_task.py
│   │   │   └── export_task.py
│   │   └── main.py
│   ├── alembic/                   # 数据库迁移
│   ├── tests/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── pyproject.toml
├── ai-models/                     # AI 模型管理
│   ├── depth/                     # 深度估计模型
│   │   ├── depth_anything_v2/
│   │   ├── midas/
│   │   └── leres/
│   ├── enhance/                   # 增强模型
│   │   └── real_esrgan/
│   ├── segmentation/              # 分割模型
│   │   └── sam/
│   ├── model_manager.py           # 模型加载/切换/版本管理
│   └── inference_engine.py        # 推理引擎封装
├── deploy/                        # 部署配置
│   ├── docker/
│   │   ├── docker-compose.yml
│   │   ├── docker-compose.prod.yml
│   │   ├── nginx.conf
│   │   └── .env.example
│   ├── k8s/
│   │   ├── namespace.yaml
│   │   ├── frontend-deployment.yaml
│   │   ├── backend-deployment.yaml
│   │   ├── worker-deployment.yaml
│   │   ├── gpu-deployment.yaml
│   │   ├── ingress.yaml
│   │   └── configmap.yaml
│   └── scripts/
│       ├── init_db.sh
│       └── backup.sh
├── docs/                          # 文档
├── .github/                       # CI/CD
│   └── workflows/
│       ├── ci.yml
│       └── cd.yml
├── .gitignore
├── Makefile
└── README.md
```

---

## 4. 核心算法设计

### 4.1 深度估计

#### 4.1.1 算法选型与对比

| 模型 | 精度 (δ<1.25) | 推理速度 (1024×1024) | 显存占用 | 适用场景 |
|------|---------------|---------------------|----------|----------|
| Depth Anything V2 | 94.2% | ~2.5s (RTX 3090) | ~4 GB | 通用场景，主模型 |
| MiDaS v3.1 | 91.8% | ~3.0s | ~3.5 GB | 室内/户外，备选 |
| LeReS | 89.5% | ~3.5s | ~3 GB | 相对深度，备选 |

#### 4.1.2 深度估计流程

```
输入图片
    │
    ▼
┌──────────────┐
│  图片预处理    │  → 统一尺寸、归一化、格式转换
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  前景分割     │  → SAM/SegFormer 分离前景/背景
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  深度估计     │  → Depth Anything V2 推理
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  深度图优化   │  → 边缘保持滤波 + 前景深度增强
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  深度图归一化  │  → [0, 255] 灰度映射
└──────┬───────┘
       │
       ▼
  输出深度图
```

#### 4.1.3 深度图优化策略

1. **边缘保持滤波**: 使用双边滤波 (Bilateral Filter) 平滑深度图，保持物体边缘锐利
2. **前景深度增强**: 结合前景分割 mask，增强前景物体与背景的深度差异
3. **多模型融合**: 对多个深度估计模型结果取加权平均，降低单模型偏差
4. **梯度感知优化**: 在深度梯度大的区域（物体边缘）增加深度对比度

#### 4.1.4 深度图手动编辑

- **画笔工具**: 用户可涂抹调整局部深度值（加深/减浅）
- **区域选择**: 选择区域后批量调整深度
- **平滑工具**: 平滑过渡区域，消除深度突变
- **撤销/重做**: 支持编辑历史记录

### 4.2 3D 重建与视差映射

#### 4.2.1 核心流程

```
原图 + 深度图
    │
    ▼
┌──────────────┐
│  点云生成     │  → 将每个像素映射到 3D 空间坐标
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  网格构建     │  → Delaunay 三角化 / 规则网格
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  纹理映射     │  → 原图作为纹理贴到网格
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  空洞填充     │  → 视差移动后的遮挡区域内容补全
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  后处理效果   │  → 景深模糊、光照、环境映射
└──────┬───────┘
       │
       ▼
  3D 场景
```

#### 4.2.2 点云生成算法

```python
def generate_point_cloud(image, depth_map, fov=60):
    """
    将 2D 图片 + 深度图转换为 3D 点云

    Args:
        image: 原始图片 (H, W, 3)
        depth_map: 深度图 (H, W), 值域 [0, 1]
        fov: 视场角 (度)

    Returns:
        points: (N, 3) 3D 坐标
        colors: (N, 3) RGB 颜色
    """
    H, W = image.shape[:2]
    focal_length = W / (2 * np.tan(np.radians(fov / 2)))

    # 生成像素坐标网格
    u, v = np.meshgrid(np.arange(W), np.arange(H))

    # 反投影到 3D 空间
    z = depth_map
    x = (u - W / 2) * z / focal_length
    y = (v - H / 2) * z / focal_length

    points = np.stack([x, y, z], axis=-1).reshape(-1, 3)
    colors = image.reshape(-1, 3) / 255.0

    return points, colors
```

#### 4.2.3 空洞填充策略

视差移动后，原本被遮挡的区域会暴露出"空洞"。填充策略：

1. **边缘扩展**: 从空洞边缘像素向内扩展颜色
2. **深度感知填充**: 利用深度信息，从相近深度的邻近区域采样填充
3. **AI 填充**: 使用 Inpainting 模型（如 LaMa）智能填充大面积空洞
4. **多尺度填充**: 先填充低分辨率，再逐步细化

### 4.3 图像增强

#### 4.3.1 超分辨率 (Real-ESRGAN)

- **输入**: 低分辨率图片
- **输出**: 2×/4× 放大后的高分辨率图片
- **模型**: Real-ESRGAN x4plus
- **推理**: GPU 加速，1024×1024 → 4096×4096 约 3s

#### 4.3.2 光照修正 (Retinex 算法)

- **低光照增强**: 基于 Retinex 理论，分解反射分量与光照分量
- **过曝修正**: 压缩高光区域，恢复细节
- **自适应**: 自动检测光照条件，选择最佳修正策略

#### 4.3.3 去噪处理

- **模型**: SCUNet (SwinCNN-based UNet)
- **特点**: 保持纹理细节的同时去除噪点
- **适用**: 低光照拍摄、高 ISO 噪点图片

### 4.4 动态渲染与动画

#### 4.4.1 Three.js 渲染管线

```
┌─────────────┐
│  Scene 构建  │  → 添加 Mesh/Points + 纹理
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Camera 设置 │  → PerspectiveCamera, 视角参数
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  动画更新    │  → 每帧更新 Camera/Scene 参数
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  WebGL 渲染  │  → WebGLRenderer 渲染到 Canvas
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  后处理      │  → 景深模糊、色彩校正、抗锯齿
└─────────────┘
```

#### 4.4.2 动画系统设计

```typescript
// 动画参数接口
interface AnimationParams {
  type: 'swing' | 'zoom' | 'rotate' | 'parallax' | 'dolly' | 'custom';
  duration: number;        // 动画时长 (ms)
  amplitude: number;       // 振幅 (0-1)
  speed: number;           // 速度倍率 (0.1-5.0)
  easing: EasingFunction;  // 缓动函数
  loop: boolean;           // 是否循环
  direction: 'forward' | 'reverse' | 'alternate';
}

// 动画引擎核心
class AnimationEngine {
  private mixer: AnimationMixer;
  private timeline: Timeline;

  // 应用预设动画
  applyPreset(presetId: string): void;

  // 自定义动画参数
  setParams(params: Partial<AnimationParams>): void;

  // 播放控制
  play(): void;
  pause(): void;
  stop(): void;
  seek(time: number): void;

  // 实时预览
  preview(frameCallback: (frame: ImageData) => void): void;
}
```

---

## 5. 前端设计

### 5.1 页面结构

```
┌─────────────────────────────────────────────────────┐
│  Header: Logo | 导航 | 用户头像                       │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌─────────────────────┐  ┌───────────────────────┐ │
│  │                     │  │                       │ │
│  │   3D 预览区域       │  │   控制面板             │ │
│  │   (Three.js Canvas) │  │   ┌─────────────────┐ │ │
│  │                     │  │   │ 深度图预览      │ │ │
│  │                     │  │   ├─────────────────┤ │ │
│  │                     │  │   │ 动画控制        │ │ │
│  │                     │  │   │ - 模板选择      │ │ │
│  │                     │  │   │ - 参数调节      │ │ │
│  │                     │  │   │ - 时间线        │ │ │
│  │                     │  │   ├─────────────────┤ │ │
│  │                     │  │   │ 增强选项        │ │ │
│  │                     │  │   ├─────────────────┤ │ │
│  │                     │  │   │ 导出/分享       │ │ │
│  │                     │  │   └─────────────────┘ │ │
│  └─────────────────────┘  └───────────────────────┘ │
│                                                     │
├─────────────────────────────────────────────────────┤
│  Footer: 版权 | 帮助 | 反馈                          │
└─────────────────────────────────────────────────────┘
```

### 5.2 页面路由

| 路由 | 页面 | 描述 |
|------|------|------|
| `/` | 首页 | 产品介绍 + 上传入口 |
| `/upload` | 上传页 | 图片上传与预处理 |
| `/editor/:id` | 编辑器页 | 3D 预览 + 参数编辑 |
| `/share/:id` | 分享页 | 公开分享预览 |
| `/gallery` | 作品集 | 用户历史作品 |
| `/settings` | 设置页 | 用户偏好设置 |

### 5.3 核心组件设计

#### 5.3.1 Three.js 场景组件

```typescript
interface Scene3DProps {
  imageId: string;
  depthMapId: string;
  animationParams?: AnimationParams;
  onSceneReady?: (scene: THREE.Scene) => void;
  onRenderFrame?: (canvas: HTMLCanvasElement) => void;
}

const Scene3D: React.FC<Scene3DProps> = ({ imageId, depthMapId, ... }) => {
  // WebGL 渲染器初始化
  // 点云/网格生成
  // 相机控制器 (OrbitControls)
  // 动画循环
  // 后处理管线
  // 响应式适配
};
```

#### 5.3.2 状态管理 (Zustand)

```typescript
interface EditorStore {
  // 当前项目状态
  currentImage: ImageInfo | null;
  depthMap: DepthMapInfo | null;
  scene3D: SceneInfo | null;

  // 动画参数
  animation: AnimationParams;

  // 编辑状态
  isProcessing: boolean;
  processingStep: 'idle' | 'uploading' | 'estimating' | 'rendering' | 'exporting';
  progress: number;

  // 操作方法
  uploadImage: (file: File) => Promise<void>;
  estimateDepth: (imageId: string) => Promise<void>;
  updateAnimation: (params: Partial<AnimationParams>) => void;
  exportVideo: (options: ExportOptions) => Promise<Blob>;
  shareScene: () => Promise<string>;
}
```

### 5.4 前端性能优化

| 优化项 | 策略 | 说明 |
|--------|------|------|
| 首屏加载 | 路由懒加载 + 代码分割 | 减少初始 bundle 大小 |
| 3D 渲染 | requestAnimationFrame | 同步浏览器刷新率 |
| 纹理加载 | 渐进式加载 + mipmap | 先低后高、按需加载 |
| 深度图传输 | 压缩 + WebWorker | 后台解压不阻塞 UI |
| 内存管理 | 及时释放 Three.js 资源 | dispose() geometry/material/texture |
| 移动端 | 降低渲染分辨率 | devicePixelRatio 适配 |

---

## 6. 后端设计

### 6.1 API 接口详细设计

#### 6.1.1 图片上传

```
POST /api/v1/upload
Content-Type: multipart/form-data

Request:
  - file: 图片文件 (required)
  - quality_preset: "auto" | "high" | "ultra" (optional, default: "auto")

Response 200:
{
  "image_id": "img_abc123",
  "filename": "photo.jpg",
  "width": 1920,
  "height": 1080,
  "format": "jpeg",
  "size_bytes": 2048576,
  "thumbnail_url": "https://cdn.example.com/thumb/img_abc123.jpg",
  "status": "ready"
}

Response 400:
{
  "error_code": "INVALID_FORMAT",
  "message": "Unsupported image format. Supported: JPG, PNG, WEBP, BMP"
}
```

#### 6.1.2 深度估计

```
POST /api/v1/depth/estimate
Content-Type: application/json

Request:
{
  "image_id": "img_abc123",
  "model": "depth_anything_v2",       // 可选: "midas", "leres", "ensemble"
  "enhance_foreground": true,          // 是否增强前景深度
  "edge_preserve": true                // 是否启用边缘保持
}

Response 200:
{
  "task_id": "task_def456",
  "status": "processing",
  "estimated_time_seconds": 8
}

Response 200 (WebSocket 推送完成通知):
{
  "task_id": "task_def456",
  "status": "completed",
  "depth_map_id": "dmp_ghi789",
  "depth_map_url": "https://cdn.example.com/depth/dmp_ghi789.png",
  "processing_time_seconds": 6.2,
  "model_used": "depth_anything_v2"
}
```

#### 6.1.3 3D 渲染

```
POST /api/v1/render/3d
Content-Type: application/json

Request:
{
  "image_id": "img_abc123",
  "depth_map_id": "dmp_ghi789",
  "render_params": {
    "fov": 60,
    "disparity_scale": 1.0,
    "hole_fill_method": "edge_extend",
    "enable_dof": false,
    "dof_focus_point": [0.5, 0.5],
    "dof_aperture": 0.1
  }
}

Response 200:
{
  "scene_id": "scn_jkl012",
  "status": "ready",
  "scene_data_url": "https://cdn.example.com/scene/scn_jkl012.json",
  "texture_url": "https://cdn.example.com/texture/scn_jkl012.jpg"
}
```

#### 6.1.4 图像增强

```
POST /api/v1/enhance
Content-Type: application/json

Request:
{
  "image_id": "img_abc123",
  "operations": [
    { "type": "super_resolution", "scale": 2 },
    { "type": "denoise", "strength": 0.5 },
    { "type": "light_correction", "mode": "auto" }
  ]
}

Response 200:
{
  "task_id": "task_mno345",
  "status": "processing",
  "estimated_time_seconds": 12
}
```

#### 6.1.5 导出

```
POST /api/v1/export
Content-Type: application/json

Request:
{
  "scene_id": "scn_jkl012",
  "format": "mp4",                    // "mp4" | "gif" | "depth_png"
  "params": {
    "resolution": "1080p",
    "fps": 30,
    "duration_seconds": 5,
    "animation": {
      "type": "swing",
      "amplitude": 0.5,
      "speed": 1.0
    }
  }
}

Response 200:
{
  "task_id": "task_pqr678",
  "status": "processing",
  "estimated_time_seconds": 20
}

Response 200 (完成):
{
  "task_id": "task_pqr678",
  "status": "completed",
  "download_url": "https://cdn.example.com/export/video_stu901.mp4",
  "file_size_bytes": 5242880,
  "expires_at": "2026-06-07T00:00:00Z"
}
```

#### 6.1.6 分享

```
POST /api/v1/share
Content-Type: application/json

Request:
{
  "scene_id": "scn_jkl012",
  "title": "我的 3D 照片",
  "is_public": true,
  "allow_download": true,
  "expires_in_hours": 168            // 7 天
}

Response 200:
{
  "share_id": "shr_vwx234",
  "share_url": "https://leiapix.app/share/shr_vwx234",
  "embed_code": "<iframe src=\"https://leiapix.app/embed/shr_vwx234\" ...></iframe>",
  "expires_at": "2026-06-13T00:00:00Z"
}
```

#### 6.1.7 认证

```
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
GET  /api/v1/auth/me
```

### 6.2 异步任务设计

#### 6.2.1 任务状态机

```
  pending ──→ processing ──→ completed
     │            │
     │            ▼
     │         failed
     │            │
     ▼            ▼
  cancelled    retry ──→ processing (最多重试 3 次)
```

#### 6.2.2 Celery 任务配置

```python
# 任务优先级队列
CELERY_TASK_ROUTES = {
    "app.tasks.depth_task.estimate_depth": {"queue": "gpu_depth"},
    "app.tasks.render_task.render_3d": {"queue": "gpu_render"},
    "app.tasks.enhance_task.enhance_image": {"queue": "gpu_enhance"},
    "app.tasks.export_task.export_video": {"queue": "export"},
}

# GPU 任务并发控制
CELERY_WORKER_CONCURRENCY = {
    "gpu_depth": 2,      # 深度估计: 2 并发 (受 GPU 显存限制)
    "gpu_render": 2,     # 3D 渲染: 2 并发
    "gpu_enhance": 1,    # 图像增强: 1 并发
    "export": 4,         # 视频导出: 4 并发 (CPU 密集)
}

# 任务超时
CELERY_TASK_TIME_LIMIT = {
    "depth": 60,         # 深度估计: 60s 超时
    "render": 30,        # 3D 渲染: 30s 超时
    "enhance": 120,      # 图像增强: 120s 超时
    "export": 300,       # 视频导出: 300s 超时
}
```

### 6.3 WebSocket 实时通信

```python
# WebSocket 消息类型
class WSMessageType(str, Enum):
    TASK_PROGRESS = "task_progress"      # 任务进度更新
    TASK_COMPLETED = "task_completed"    # 任务完成
    TASK_FAILED = "task_failed"          # 任务失败
    SCENE_UPDATE = "scene_update"        # 场景数据更新

# 消息格式
{
    "type": "task_progress",
    "data": {
        "task_id": "task_def456",
        "progress": 0.65,
        "step": "depth_estimation",
        "message": "正在生成深度图..."
    }
}
```

---

## 7. 数据库与存储设计

### 7.1 PostgreSQL 表结构

#### 7.1.1 用户表 (users)

```sql
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        VARCHAR(50) UNIQUE NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    avatar_url      VARCHAR(512),
    plan            VARCHAR(20) DEFAULT 'free',  -- free / pro / enterprise
    storage_used_mb INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_username ON users(username);
```

#### 7.1.2 图片表 (images)

```sql
CREATE TABLE images (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename        VARCHAR(255) NOT NULL,
    original_url    VARCHAR(512) NOT NULL,
    thumbnail_url   VARCHAR(512),
    width           INTEGER NOT NULL,
    height          INTEGER NOT NULL,
    format          VARCHAR(10) NOT NULL,
    size_bytes      BIGINT NOT NULL,
    storage_key     VARCHAR(512) NOT NULL,
    status          VARCHAR(20) DEFAULT 'uploaded',  -- uploaded / processing / ready / failed
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_images_user_id ON images(user_id);
CREATE INDEX idx_images_status ON images(status);
CREATE INDEX idx_images_created_at ON images(created_at DESC);
```

#### 7.1.3 深度图表 (depth_maps)

```sql
CREATE TABLE depth_maps (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    image_id        UUID NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    model_used      VARCHAR(50) NOT NULL,       -- depth_anything_v2 / midas / leres / ensemble
    depth_map_url   VARCHAR(512) NOT NULL,
    storage_key     VARCHAR(512) NOT NULL,
    processing_time_ms INTEGER,
    params          JSONB,                       -- 模型参数
    status          VARCHAR(20) DEFAULT 'processing',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_depth_maps_image_id ON depth_maps(image_id);
```

#### 7.1.4 场景表 (scenes)

```sql
CREATE TABLE scenes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    image_id        UUID NOT NULL REFERENCES images(id),
    depth_map_id    UUID NOT NULL REFERENCES depth_maps(id),
    scene_data_url  VARCHAR(512),
    texture_url     VARCHAR(512),
    render_params   JSONB,
    animation_params JSONB,
    status          VARCHAR(20) DEFAULT 'processing',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_scenes_user_id ON scenes(user_id);
CREATE INDEX idx_scenes_image_id ON scenes(image_id);
```

#### 7.1.5 任务表 (tasks)

```sql
CREATE TABLE tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type            VARCHAR(30) NOT NULL,        -- depth / render / enhance / export
    status          VARCHAR(20) DEFAULT 'pending',  -- pending / processing / completed / failed / cancelled
    progress        DECIMAL(5,2) DEFAULT 0,
    input_params    JSONB,
    result          JSONB,
    error_message   TEXT,
    retry_count     INTEGER DEFAULT 0,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_tasks_user_id ON tasks(user_id);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_type_status ON tasks(type, status);
```

#### 7.1.6 导出记录表 (exports)

```sql
CREATE TABLE exports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scene_id        UUID NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    format          VARCHAR(10) NOT NULL,        -- mp4 / gif / depth_png
    resolution      VARCHAR(10),
    duration_seconds INTEGER,
    file_size_bytes BIGINT,
    download_url    VARCHAR(512),
    storage_key     VARCHAR(512),
    expires_at      TIMESTAMPTZ,
    status          VARCHAR(20) DEFAULT 'processing',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_exports_scene_id ON exports(scene_id);
CREATE INDEX idx_exports_user_id ON exports(user_id);
```

### 7.2 MongoDB 集合设计

#### 7.2.1 分享集合 (shares)

```json
{
  "_id": ObjectId,
  "share_id": "shr_vwx234",
  "scene_id": "scn_jkl012",
  "user_id": "usr_abc123",
  "title": "我的 3D 照片",
  "is_public": true,
  "allow_download": true,
  "view_count": 0,
  "download_count": 0,
  "expires_at": ISODate,
  "created_at": ISODate,
  "password_hash": null,
  "metadata": {
    "animation_type": "swing",
    "duration_seconds": 5
  }
}
```

### 7.3 Redis 缓存设计

| Key 模式 | 数据类型 | TTL | 说明 |
|----------|----------|-----|------|
| `task:{task_id}` | Hash | 1h | 任务状态与进度 |
| `user:{user_id}:quota` | Hash | - | 用户配额信息 |
| `depth:{image_id}:result` | String (JSON) | 24h | 深度估计结果缓存 |
| `scene:{scene_id}:data` | String (JSON) | 1h | 场景数据缓存 |
| `rate_limit:{user_id}:{endpoint}` | String (counter) | 60s | API 速率限制 |
| `ws:session:{session_id}` | Hash | 24h | WebSocket 会话 |

### 7.4 MinIO/S3 存储结构

```
bucket: leiapix-storage
├── images/
│   ├── original/{user_id}/{image_id}.jpg
│   ├── thumbnail/{user_id}/{image_id}_thumb.jpg
│   └── enhanced/{user_id}/{image_id}_enhanced.jpg
├── depth_maps/
│   └── {user_id}/{depth_map_id}.png
├── scenes/
│   └── {user_id}/{scene_id}.json
├── textures/
│   └── {user_id}/{scene_id}_texture.jpg
└── exports/
    └── {user_id}/{export_id}.mp4
```

---

## 8. 安全设计

### 8.1 认证与授权

| 机制 | 说明 |
|------|------|
| JWT Token | 访问令牌，有效期 15 分钟 |
| Refresh Token | 刷新令牌，有效期 7 天 |
| OAuth 2.0 | 支持 Google / GitHub 第三方登录 |
| RBAC | 基于角色的访问控制 (free/pro/admin) |

### 8.2 数据安全

| 措施 | 说明 |
|------|------|
| HTTPS | 全站 TLS 1.3 加密传输 |
| 密码存储 | bcrypt 哈希 + salt |
| 文件校验 | 上传文件 magic bytes 校验，防止恶意文件 |
| 数据隔离 | 用户数据严格隔离，不可跨租户访问 |
| 敏感数据 | 数据库敏感字段加密存储 (AES-256) |

### 8.3 防护策略

| 威胁 | 防护措施 |
|------|----------|
| DDoS | CDN + WAF + 速率限制 |
| SQL 注入 | ORM 参数化查询 |
| XSS | CSP 策略 + 输出编码 |
| CSRF | SameSite Cookie + CSRF Token |
| 文件上传攻击 | 文件类型校验 + 大小限制 + 沙箱扫描 |
| 暴力破解 | 登录频率限制 + 验证码 |
| API 滥用 | 速率限制 + 配额管理 |

### 8.4 速率限制

| 端点 | 免费用户 | Pro 用户 | 企业用户 |
|------|----------|----------|----------|
| /upload | 10 次/小时 | 50 次/小时 | 无限 |
| /depth/estimate | 5 次/小时 | 30 次/小时 | 无限 |
| /enhance | 3 次/小时 | 20 次/小时 | 无限 |
| /export | 5 次/小时 | 30 次/小时 | 无限 |
| /share | 10 次/小时 | 50 次/小时 | 无限 |

---

## 9. 性能设计

### 9.1 性能目标

| 指标 | 目标值 | 测量方法 |
|------|--------|----------|
| 深度估计延迟 | ≤ 10s (1024×1024) | 端到端计时 |
| 3D 场景加载 | ≤ 3s | 首帧渲染时间 |
| 实时渲染帧率 | ≥ 30 FPS | requestAnimationFrame 统计 |
| 视频导出 | ≤ 30s (5s 1080p) | 端到端计时 |
| API 响应时间 | ≤ 200ms (P95) | APM 监控 |
| 首屏加载 | ≤ 2s | Lighthouse |

### 9.2 性能优化策略

#### 9.2.1 前端优化

- **代码分割**: 路由级懒加载，Three.js 按需加载
- **资源优化**: 图片 WebP 格式、深度图压缩传输
- **渲染优化**: LOD (Level of Detail)、视锥裁剪、实例化渲染
- **内存优化**: 及时 dispose Three.js 资源、纹理压缩
- **移动端适配**: 动态降低渲染分辨率、简化后处理

#### 9.2.2 后端优化

- **异步处理**: GPU 推理任务全部异步化，WebSocket 推送结果
- **缓存策略**: Redis 缓存热点数据、CDN 缓存静态资源
- **连接池**: 数据库连接池、Redis 连接池
- **批处理**: 支持批量深度估计、批量导出
- **GPU 调度**: 多 GPU 任务调度、显存动态分配

#### 9.2.3 AI 推理优化

- **模型量化**: INT8 量化减少显存占用、加速推理
- **TensorRT**: 使用 TensorRT 加速模型推理
- **批处理推理**: 多张图片合并 batch 推理
- **模型缓存**: 预加载模型到 GPU，避免冷启动

---

## 10. 测试策略

### 10.1 测试层级

| 层级 | 工具 | 覆盖目标 | 说明 |
|------|------|----------|------|
| 单元测试 | Jest / pytest | ≥ 80% | 核心逻辑、工具函数 |
| 集成测试 | Testing Library / pytest | ≥ 70% | API 接口、组件交互 |
| E2E 测试 | Playwright | 核心流程 | 上传→深度→3D→导出 |
| 性能测试 | k6 / Lighthouse | 关键指标 | 响应时间、吞吐量 |
| 视觉回归 | Chromatic | UI 一致性 | 截图对比 |

### 10.2 核心测试用例

#### 10.2.1 深度估计测试

| 用例 ID | 测试场景 | 输入 | 预期输出 |
|---------|----------|------|----------|
| TC-DE-001 | 正常图片深度估计 | 标准 1024×768 JPG | 深度图生成成功，尺寸匹配 |
| TC-DE-002 | 大尺寸图片深度估计 | 4096×4096 PNG | 自动缩放后生成深度图 |
| TC-DE-003 | 低质量图片深度估计 | 模糊/低分辨率图片 | 生成深度图 + 质量提示 |
| TC-DE-004 | 非图片文件上传 | PDF 文件 | 返回格式错误 |
| TC-DE-005 | 超大文件上传 | 50MB 图片 | 返回大小超限错误 |

#### 10.2.2 3D 渲染测试

| 用例 ID | 测试场景 | 输入 | 预期输出 |
|---------|----------|------|----------|
| TC-3D-001 | 基础 3D 场景生成 | 原图 + 深度图 | 场景加载成功，可交互 |
| TC-3D-002 | 旋转交互 | 鼠标拖拽 | 场景跟随旋转，帧率 ≥ 30 FPS |
| TC-3D-003 | 缩放交互 | 滚轮缩放 | 场景跟随缩放，无闪烁 |
| TC-3D-004 | 动画播放 | 选择摇摆模板 | 动画流畅播放，可暂停 |
| TC-3D-005 | 景深模糊 | 启用 DOF | 模糊效果正确，焦点清晰 |

#### 10.2.3 导出测试

| 用例 ID | 测试场景 | 输入 | 预期输出 |
|---------|----------|------|----------|
| TC-EX-001 | MP4 导出 | 1080p, 30fps, 5s | 视频文件生成成功 |
| TC-EX-002 | GIF 导出 | 480px, 15fps | GIF 文件生成成功 |
| TC-EX-003 | 长视频导出 | 30s 视频 | 导出成功或提示限制 |
| TC-EX-004 | 4K 导出 | 4K 分辨率 | Pro 用户成功，免费用户提示升级 |

### 10.3 AI 模型测试

| 测试维度 | 指标 | 方法 |
|----------|------|------|
| 深度精度 | δ<1.25 准确率 | 标注数据集对比 |
| 边缘质量 | 边缘 F1 Score | 边缘检测对比 |
| 推理速度 | 平均推理时间 | 基准测试 |
| 显存占用 | 峰值显存 | nvidia-smi 监控 |
| 鲁棒性 | 极端场景成功率 | 暗光/模糊/遮挡测试 |

---

## 11. 部署架构

### 11.1 生产环境架构

```
                    ┌─────────────┐
                    │   CDN (OSS) │ ← 静态资源 + 导出文件
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │    Nginx    │ ← 反向代理 + SSL + 负载均衡
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────┴──────┐     │     ┌──────┴──────┐
       │  Frontend   │     │     │  Frontend   │
       │  Pod ×2     │     │     │  Pod ×2     │
       └─────────────┘     │     └─────────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────┴──────┐     │     ┌──────┴──────┐
       │  Backend    │     │     │  Backend    │
       │  Pod ×3     │     │     │  Pod ×3     │
       └─────────────┘     │     └─────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
  ┌──────┴──────┐  ┌──────┴──────┐  ┌──────┴──────┐
  │ GPU Worker  │  │ GPU Worker  │  │ CPU Worker  │
  │ Pod ×2      │  │ Pod ×2      │  │ Pod ×3      │
  │ (深度/增强)  │  │ (渲染)      │  │ (导出/通用)  │
  └─────────────┘  └─────────────┘  └─────────────┘
         │                 │                 │
    ┌────┴────┐      ┌────┴────┐      ┌─────┴─────┐
    │ NVIDIA  │      │ NVIDIA  │      │           │
    │ RTX     │      │ RTX     │      │           │
    │ 3090    │      │ 3090    │      │           │
    └─────────┘      └─────────┘      └───────────┘
```

### 11.2 Docker Compose 开发环境

```yaml
version: '3.8'
services:
  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    volumes: ["./frontend:/app"]
    environment:
      - VITE_API_URL=http://localhost:8000

  backend:
    build: ./backend
    ports: ["8000:8000"]
    volumes: ["./backend:/app"]
    environment:
      - DATABASE_URL=postgresql://leiapix:leiapix@db:5432/leiapix
      - REDIS_URL=redis://redis:6379/0
      - MINIO_ENDPOINT=minio:9000
      - GPU_ENABLED=true
    depends_on: [db, redis, minio]

  worker-depth:
    build: ./backend
    command: celery -A app.tasks.depth_task worker -Q gpu_depth -c 2
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=0
    depends_on: [redis]

  worker-export:
    build: ./backend
    command: celery -A app.tasks.export_task worker -Q export -c 4
    depends_on: [redis]

  db:
    image: postgres:16
    ports: ["5432:5432"]
    environment:
      POSTGRES_DB: leiapix
      POSTGRES_USER: leiapix
      POSTGRES_PASSWORD: leiapix
    volumes: ["pgdata:/var/lib/postgresql/data"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  minio:
    image: minio/minio
    ports: ["9000:9000", "9001:9001"]
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: leiapix
      MINIO_ROOT_PASSWORD: leiapix123
    volumes: ["minio_data:/data"]

  mongodb:
    image: mongo:7
    ports: ["27017:27017"]
    environment:
      MONGO_INITDB_ROOT_USERNAME: leiapix
      MONGO_INITDB_ROOT_PASSWORD: leiapix123
    volumes: ["mongo_data:/data/db"]

volumes:
  pgdata:
  minio_data:
  mongo_data:
```

### 11.3 环境变量配置

| 变量名 | 说明 | 开发默认值 | 生产值 |
|--------|------|-----------|--------|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql://leiapix:leiapix@localhost:5432/leiapix` | (密钥管理) |
| `REDIS_URL` | Redis 连接串 | `redis://localhost:6379/0` | (密钥管理) |
| `MINIO_ENDPOINT` | MinIO 地址 | `localhost:9000` | (内部地址) |
| `MINIO_ACCESS_KEY` | MinIO 访问密钥 | `leiapix` | (密钥管理) |
| `MINIO_SECRET_KEY` | MinIO 密钥 | `leiapix123` | (密钥管理) |
| `JWT_SECRET` | JWT 签名密钥 | `dev-secret` | (密钥管理) |
| `GPU_ENABLED` | 是否启用 GPU | `true` | `true` |
| `MODEL_PATH` | AI 模型存储路径 | `./ai-models` | `/models` |
| `MAX_UPLOAD_SIZE_MB` | 最大上传大小 | `20` | `20` |
| `CORS_ORIGINS` | 允许的跨域来源 | `http://localhost:3000` | (生产域名) |

---

## 12. CI/CD 与 DevOps

### 12.1 CI 流水线

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]

jobs:
  frontend-ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: cd frontend && npm ci
      - run: cd frontend && npm run lint
      - run: cd frontend && npm run typecheck
      - run: cd frontend && npm run test
      - run: cd frontend && npm run build

  backend-ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: cd backend && pip install -r requirements.txt
      - run: cd backend && ruff check .
      - run: cd backend && mypy app/
      - run: cd backend && pytest tests/ -v

  docker-build:
    runs-on: ubuntu-latest
    needs: [frontend-ci, backend-ci]
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t leiapix-frontend ./frontend
      - run: docker build -t leiapix-backend ./backend
```

### 12.2 CD 流水线

```yaml
# .github/workflows/cd.yml
name: CD
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build & Push Docker Images
        run: |
          docker build -t leiapix-frontend:latest ./frontend
          docker build -t leiapix-backend:latest ./backend
          docker push registry.example.com/leiapix-frontend:latest
          docker push registry.example.com/leiapix-backend:latest
      - name: Deploy to K8s
        run: |
          kubectl set image deployment/frontend frontend=registry.example.com/leiapix-frontend:latest
          kubectl set image deployment/backend backend=registry.example.com/leiapix-backend:latest
          kubectl rollout status deployment/frontend
          kubectl rollout status deployment/backend
```

---

## 13. 监控与运维

### 13.1 监控指标

| 类别 | 指标 | 告警阈值 |
|------|------|----------|
| 系统 | CPU 使用率 | > 80% 持续 5 分钟 |
| 系统 | 内存使用率 | > 85% |
| 系统 | GPU 显存使用率 | > 90% |
| 系统 | 磁盘使用率 | > 85% |
| 应用 | API 响应时间 P95 | > 500ms |
| 应用 | API 错误率 | > 1% |
| 应用 | 任务队列积压 | > 100 待处理 |
| 业务 | 深度估计成功率 | < 95% |
| 业务 | 导出成功率 | < 98% |

### 13.2 日志规范

```python
# 日志格式
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(service)s | %(request_id)s | %(message)s"

# 日志级别使用规范
# DEBUG: 开发调试信息
# INFO:  正常业务流程 (任务开始/完成、用户操作)
# WARN:  可恢复异常 (重试成功、降级处理)
# ERROR: 需要关注的错误 (任务失败、外部服务异常)
# CRITICAL: 系统级故障 (数据库不可用、GPU 故障)
```

### 13.3 备份策略

| 数据 | 备份频率 | 保留时长 | 存储位置 |
|------|----------|----------|----------|
| PostgreSQL | 每日全量 + 实时 WAL | 30 天 | 异地 OSS |
| MongoDB | 每日全量 | 30 天 | 异地 OSS |
| MinIO 文件 | 每日增量 | 90 天 | 异地 OSS |
| Redis | 不备份 (可重建) | - | - |
| AI 模型文件 | 版本变更时 | 永久 | 模型仓库 |

---

## 14. 开发规范

### 14.1 代码规范

| 规范项 | 前端 | 后端 |
|--------|------|------|
| 语言 | TypeScript (strict) | Python 3.11+ |
| Linter | ESLint + Prettier | Ruff |
| 类型检查 | tsc --strict | mypy --strict |
| 命名风格 | camelCase (变量/函数), PascalCase (组件/类) | snake_case (变量/函数), PascalCase (类) |
| 注释 | JSDoc (公共 API) | Docstring (公共函数/类) |
| 提交信息 | Conventional Commits | Conventional Commits |

### 14.2 Git 工作流

```
main (生产)
  │
  ├── develop (开发主线)
  │     │
  │     ├── feature/depth-edit      (功能分支)
  │     ├── feature/animation-timeline
  │     └── feature/batch-export
  │
  ├── release/v1.0.0 (发布分支)
  │
  └── hotfix/fix-depth-crash (热修复分支)
```

**提交信息规范**:

```
<type>(<scope>): <subject>

type: feat | fix | docs | style | refactor | perf | test | chore
scope: depth | render | enhance | export | share | ui | api | infra

示例:
feat(depth): add manual depth map editing tool
fix(render): resolve hole-filling artifact on edges
perf(export): optimize video encoding with hardware acceleration
```

### 14.3 Code Review 规范

- 所有代码合并前必须经过至少 1 人 Review
- Review 关注: 功能正确性、性能影响、安全风险、代码可读性
- AI 推理相关变更需额外检查: 模型兼容性、显存影响、精度回归

---

## 15. 项目管理与排期

### 15.1 里程碑规划

| 里程碑 | 阶段 | 核心交付物 | 验收标准 |
|--------|------|-----------|----------|
| M1 | 基础架构搭建 | 项目脚手架、数据库、CI/CD | 本地开发环境可运行 |
| M2 | 深度估计核心 | 图片上传 + 深度估计 API | 上传图片可生成深度图 |
| M3 | 3D 渲染核心 | Three.js 场景 + 交互 | 可旋转/缩放 3D 场景 |
| M4 | 动画系统 | 预设动画 + 参数调节 | 动画播放流畅 |
| M5 | 图像增强 | 超分辨率 + 光照修正 | 增强效果可验证 |
| M6 | 导出分享 | MP4/GIF 导出 + 链接分享 | 导出文件可正常播放 |
| M7 | 集成测试 | 全流程 E2E 测试 | 核心流程通过率 100% |
| M8 | 部署上线 | 生产环境部署 | 系统稳定运行 72h |

### 15.2 MVP 功能范围

MVP 版本包含以下核心功能：

- [x] 图片上传 (本地 + 拖拽)
- [x] 深度估计 (Depth Anything V2)
- [x] 深度图预览
- [x] 3D 场景生成与交互 (旋转/缩放)
- [x] 基础动画模板 (3 个)
- [x] MP4/GIF 导出
- [x] 用户认证 (注册/登录)

### 15.3 迭代优化范围

- [ ] 深度图手动编辑
- [ ] 更多动画模板 (6+)
- [ ] 动画时间线编辑
- [ ] 景深模糊 (DOF)
- [ ] 图像增强 (超分辨率/去噪/光照)
- [ ] 分享链接 + 嵌入代码
- [ ] 批量处理
- [ ] 多模型对比

---

## 16. 扩展规划

### 16.1 短期扩展 (v1.x)

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 视频转 3D | 2D 视频逐帧生成 3D 动态场景 | 高 |
| AI 背景替换 | 自动分割并替换背景 | 高 |
| 多风格渲染 | 卡通/油画/赛博朋克风格化 | 中 |
| 深度图导入 | 支持导入外部深度图 | 中 |
| 批量处理 API | 批量上传/深度估计/导出 | 中 |

### 16.2 中期扩展 (v2.x)

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 社区互动 | 作品广场、点赞/评论/收藏 | 高 |
| 模板市场 | 用户创建/分享动画模板 | 中 |
| 移动端 App | React Native 移动应用 | 高 |
| AR 预览 | ARKit/ARCore 实景预览 | 中 |
| 实时协作 | 多人同时编辑 3D 场景 | 低 |

### 16.3 长期愿景 (v3.x)

| 功能 | 描述 |
|------|------|
| 全息显示适配 | 支持 Leia 全息显示器输出 |
| AI 时间胶囊 | 照片 + AI 生成时间维度变化 |
| 宇宙星图系统 | 3D 照片在虚拟宇宙中展示 |
| NeRF 集成 | 多角度照片生成完整 3D 场景 |
| 3D 打印适配 | 导出可 3D 打印的模型文件 |

---

## 附录

### 附录 A: 错误码定义

| 错误码 | HTTP 状态码 | 描述 | 处理建议 |
|--------|------------|------|----------|
| `INVALID_FORMAT` | 400 | 不支持的图片格式 | 检查文件格式 |
| `FILE_TOO_LARGE` | 400 | 文件大小超限 | 压缩或裁剪图片 |
| `IMAGE_TOO_SMALL` | 400 | 图片分辨率过低 | 使用更高分辨率图片 |
| `DEPTH_ESTIMATION_FAILED` | 500 | 深度估计失败 | 重试或更换图片 |
| `RENDER_FAILED` | 500 | 3D 渲染失败 | 检查深度图质量 |
| `EXPORT_FAILED` | 500 | 导出失败 | 重试或降低参数 |
| `QUOTA_EXCEEDED` | 429 | 配额已用尽 | 升级套餐或等待重置 |
| `RATE_LIMITED` | 429 | 请求频率过高 | 降低请求频率 |
| `UNAUTHORIZED` | 401 | 未认证 | 重新登录 |
| `FORBIDDEN` | 403 | 无权限 | 检查访问权限 |
| `NOT_FOUND` | 404 | 资源不存在 | 检查资源 ID |
| `MODEL_UNAVAILABLE` | 503 | AI 模型不可用 | 稍后重试 |

### 附录 B: 第三方依赖清单

#### 前端依赖

| 包名 | 版本 | 用途 | 许可证 |
|------|------|------|--------|
| react | 18+ | UI 框架 | MIT |
| three | r160+ | 3D 渲染 | MIT |
| @react-three/fiber | 8+ | React Three.js 绑定 | MIT |
| @react-three/drei | 9+ | Three.js 辅助工具 | MIT |
| zustand | 4+ | 状态管理 | MIT |
| @tweenjs/tween.js | 25+ | 补间动画 | MIT |
| axios | 1+ | HTTP 客户端 | MIT |
| tailwindcss | 3+ | CSS 框架 | MIT |
| ffmpeg.wasm | 0.12+ | 浏览器端视频编码 | MIT |

#### 后端依赖

| 包名 | 版本 | 用途 | 许可证 |
|------|------|------|--------|
| fastapi | 0.110+ | Web 框架 | MIT |
| uvicorn | 0.29+ | ASGI 服务器 | BSD |
| sqlalchemy | 2+ | ORM | MIT |
| alembic | 1+ | 数据库迁移 | MIT |
| celery | 5+ | 任务队列 | BSD |
| redis | 5+ | Redis 客户端 | MIT |
| minio | 7+ | MinIO 客户端 | Apache |
| python-jose | 3+ | JWT 处理 | MIT |
| passlib | 1+ | 密码哈希 | BSD |
| torch | 2+ | PyTorch 深度学习 | BSD |
| torchvision | 0.17+ | 视觉模型工具 | BSD |
| opencv-python | 4+ | 图像处理 | Apache |
| pillow | 10+ | 图片处理 | HPND |
| numpy | 1.26+ | 数值计算 | BSD |

### 附录 C: AI 模型清单

| 模型 | 版本 | 大小 | 用途 | 来源 |
|------|------|------|------|------|
| Depth Anything V2 | v2.0 | ~350MB | 深度估计 (主) | [TikHub](https://github.com/DepthAnything/Depth-Anything-V2) |
| MiDaS | v3.1 | ~400MB | 深度估计 (备) | [Intel ISL](https://github.com/isl-org/MiDaS) |
| LeReS | - | ~300MB | 深度估计 (备) | [SVIP-Lab](https://github.com/fra31/auto-ting) |
| Real-ESRGAN | x4plus | ~17MB | 超分辨率 | [XPixelGroup](https://github.com/xinntao/Real-ESRGAN) |
| SAM | vit_h | ~2.4GB | 前景分割 | [Meta](https://github.com/facebookresearch/segment-anything) |
| LaMa | big | ~50MB | 图像修复/空洞填充 | [advimman](https://github.com/advimman/lama) |

### 附录 D: 术语表

| 术语 | 英文 | 解释 |
|------|------|------|
| 深度图 | Depth Map | 灰度图，每个像素值表示该点到相机的距离 |
| 视差 | Parallax | 不同深度的物体在视角变化时产生的位移差异 |
| 点云 | Point Cloud | 3D 空间中的离散点集合 |
| 景深模糊 | Depth of Field (DOF) | 模拟相机焦点外区域的模糊效果 |
| 空洞填充 | Hole Filling | 3D 视差移动后遮挡区域的内容补全 |
| 超分辨率 | Super Resolution | 从低分辨率图像重建高分辨率图像 |
| 视差映射 | Disparity Mapping | 基于深度图生成视差位移效果 |
| 三角化 | Triangulation | 将点云连接为三角网格 |
| 边缘保持 | Edge-Preserving | 滤波时保持物体边缘锐利 |
| 前景分割 | Foreground Segmentation | 将图片分为前景和背景区域 |

---

> **文档维护说明**: 本文档随项目开发持续更新，所有重大变更需经技术评审后更新对应章节，并记录变更日志。
