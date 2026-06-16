"""LeiaPix AI - 结构化日志配置

提供统一的日志格式、颜色终端输出、文件输出和请求追踪。
日志文件写入 backend/logs/ 目录，按天轮转。
"""

import logging
import sys
import time
from pathlib import Path

from fastapi import Request, Response
from logging.handlers import TimedRotatingFileHandler

# 日志文件目录
LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


class ColorFormatter(logging.Formatter):
    """带颜色的终端日志格式器"""

    COLORS = {
        "DEBUG": "\033[36m",     # 青色
        "INFO": "\033[32m",      # 绿色
        "WARNING": "\033[33m",   # 黄色
        "ERROR": "\033[31m",     # 红色
        "CRITICAL": "\033[1;31m" # 粗红
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        # 保存原始 levelname，格式化后恢复
        original = record.levelname
        color = self.COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname:<8}{self.RESET}"
        result = super().format(record)
        record.levelname = original  # 恢复，避免污染文件 handler
        return result


def setup_logging(debug: bool = False) -> None:
    """配置全局日志：终端 + 文件双输出"""
    level = logging.DEBUG if debug else logging.INFO

    # 确保日志目录存在
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # ---- 终端 Handler (带颜色) ----
    console_fmt = ColorFormatter(
        fmt="%(levelname)s │ %(asctime)s │ %(name)s │ %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_fmt)
    console_handler.setLevel(level)

    # ---- 文件 Handler (全部日志，按天轮转) ----
    file_fmt = logging.Formatter(
        fmt="%(levelname)-8s │ %(asctime)s │ %(name)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    all_log_file = LOG_DIR / "leiapix.log"
    file_handler = TimedRotatingFileHandler(
        filename=str(all_log_file),
        when="midnight",
        interval=1,
        backupCount=30,  # 保留 30 天
        encoding="utf-8",
    )
    file_handler.setFormatter(file_fmt)
    file_handler.setLevel(logging.DEBUG)  # 文件始终记录 DEBUG

    # ---- 错误日志单独文件 ----
    error_log_file = LOG_DIR / "error.log"
    error_handler = TimedRotatingFileHandler(
        filename=str(error_log_file),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    error_handler.setFormatter(file_fmt)
    error_handler.setLevel(logging.ERROR)

    # ---- 配置根 logger ----
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(console_handler)
    root.addHandler(file_handler)
    root.addHandler(error_handler)

    # 降低第三方库日志级别
    for name in ["uvicorn.access", "sqlalchemy.engine", "httpx", "httpcore", "PIL", "motor"]:
        logging.getLogger(name).setLevel(logging.WARNING)

    # 提升项目日志级别
    logging.getLogger("app").setLevel(level)

    # 记录日志文件位置
    root.info(f"Log files: {LOG_DIR}/")


async def log_request_response(request: Request, call_next) -> Response:
    """FastAPI 中间件: 记录请求/响应日志 + 耗时"""
    logger = logging.getLogger("app.api")

    # 跳过健康检查和文档
    path = request.url.path
    if path in ("/health", "/docs", "/redoc", "/openapi.json") or path.startswith("/docs/"):
        return await call_next(request)

    start = time.perf_counter()
    method = request.method
    query = str(request.query_params) if request.query_params else ""

    # 请求日志
    log_line = f"→ {method} {path}"
    if query:
        log_line += f"?{query}"
    logger.info(log_line)

    # 处理请求
    try:
        response = await call_next(request)
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        logger.error(f"← {method} {path} │ 500 │ {elapsed:.0f}ms │ {e}")
        raise

    # 响应日志
    elapsed = (time.perf_counter() - start) * 1000
    status = response.status_code

    if status >= 500:
        log_method = logger.error
    elif status >= 400:
        log_method = logger.warning
    else:
        log_method = logger.info

    log_method(f"← {method} {path} │ {status} │ {elapsed:.0f}ms")

    return response
