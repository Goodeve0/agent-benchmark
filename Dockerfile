FROM python:3.11-slim AS backend

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 先安装依赖（利用 Docker 层缓存）
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[all]" || true
COPY src/ src/
RUN pip install --no-cache-dir -e ".[all]"

COPY specs/ specs/

# 前端构建
FROM node:18-slim AS frontend
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
RUN npm run build

# 最终镜像
FROM python:3.11-slim

WORKDIR /app

# 复制后端（含已安装的依赖）
COPY --from=backend /app/src/ /app/src/
COPY --from=backend /app/pyproject.toml /app/
COPY --from=backend /app/specs/ /app/specs/
COPY --from=backend /usr/local/lib/ /usr/local/lib/
COPY --from=backend /usr/local/bin/ /usr/local/bin/

# 复制前端构建产物
COPY --from=frontend /app/web/dist/ /app/web/dist/

# 复制示例数据
COPY data/ /app/data/

# 环境变量
ENV PYTHONUNBUFFERED=1
ENV AGENT_BENCH_DB_PATH=/app/data/sakila.db
ENV AGENT_BENCH_SPEC_DIR=/app/specs/tasks

EXPOSE 8000

CMD ["agent-bench-server"]
