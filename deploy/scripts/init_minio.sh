#!/bin/bash
# ============================================
# LeiaPix AI - MinIO 存储桶初始化脚本
# ============================================
# 用法:
#   方式1: docker compose up minio-init (自动执行)
#   方式2: 手动执行本脚本
#     docker compose exec minio sh /scripts/init_minio.sh
# ============================================

set -e

MC_ALIAS="leiapix"
BUCKET="leiapix-storage"

# MinIO 连接配置 (从环境变量读取，提供默认值)
MINIO_HOST="${MINIO_HOST:-minio}"
MINIO_PORT="${MINIO_API_PORT:-9000}"
MINIO_USER="${MINIO_ROOT_USER:-leiapix}"
MINIO_PASS="${MINIO_ROOT_PASSWORD:-leiapix123}"

echo "=== MinIO 初始化开始 ==="

# 配置 mc 客户端别名
mc alias set ${MC_ALIAS} http://${MINIO_HOST}:${MINIO_PORT} ${MINIO_USER} ${MINIO_PASS}

# 创建主存储桶 (如果不存在)
mc mb --ignore-existing ${MC_ALIAS}/${BUCKET}
echo "[OK] Bucket '${BUCKET}' 已就绪"

# MinIO 是对象存储，不存在真正的空目录
# 通过上传 .keep 占位文件来创建目录结构
DIRECTORIES=(
  "images/original"
  "images/thumbnail"
  "images/enhanced"
  "depth_maps"
  "scenes"
  "textures"
  "exports"
)

for dir in "${DIRECTORIES[@]}"; do
  echo -n ".keep" | mc pipe ${MC_ALIAS}/${BUCKET}/${dir}/.keep
  echo "[OK] 目录 '${dir}/' 已创建"
done

# 设置 thumbnail 目录为公开可读 (方便前端直接访问缩略图)
mc anonymous set download ${MC_ALIAS}/${BUCKET}/images/thumbnail
echo "[OK] 'images/thumbnail/' 已设置为公开可读"

echo "=== MinIO 初始化完成 ==="
