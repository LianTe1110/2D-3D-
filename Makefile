.PHONY: help dev dev-fe dev-be lint lint-fe lint-be test test-fe test-be

help: ## 显示帮助信息
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --------------- 开发 ---------------
dev: ## 启动前后端开发服务
	@echo "Starting development environment..."

dev-fe: ## 启动前端开发服务
	cd frontend && npm run dev

dev-be: ## 启动后端开发服务
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# --------------- 代码检查 ---------------
lint: lint-fe lint-be ## 运行所有代码检查

lint-fe: ## 前端代码检查
	cd frontend && npm run lint

lint-be: ## 后端代码检查
	cd backend && ruff check . && mypy app/

# --------------- 测试 ---------------
test: test-fe test-be ## 运行所有测试

test-fe: ## 前端测试
	cd frontend && npm run test

test-be: ## 后端测试
	cd backend && pytest tests/ -v

# --------------- 构建 ---------------
build-fe: ## 构建前端
	cd frontend && npm run build

build-be: ## 构建后端 Docker 镜像
	docker build -t leiapix-backend:latest ./backend
