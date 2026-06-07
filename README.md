# LeiaPix AI

2D → 3D 图片转换工具，基于 AI 深度估计与 Three.js 3D 渲染。

## 项目结构

- `frontend/` - 前端项目 (React + TypeScript + Vite + Three.js)
- `backend/` - 后端项目 (FastAPI + Python 3.11+)
- `ai-models/` - AI 模型管理 (Depth Anything V2 / MiDaS / LeReS)
- `deploy/` - 部署配置 (Docker / Kubernetes)
- `docs/` - 项目文档

## 开发环境

### 前端

```bash
cd frontend
npm install
npm run dev
```

### 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## 代码规范

- 前端: ESLint + Prettier (`npm run lint`)
- 后端: Ruff + mypy (`ruff check .` / `mypy app/`)
- 提交信息: Conventional Commits
