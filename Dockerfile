FROM python:3.10-slim AS backend

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY pyproject.toml .
COPY src/ src/
COPY specs/ specs/

RUN pip install --no-cache-dir -e ".[all,dev]"

# 前端构建
FROM node:18-slim AS frontend
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
RUN npm run build

# 最终镜像
FROM python:3.10-slim

WORKDIR /app

# 复制后端
COPY --from=backend /app/src/ /app/src/
COPY --from=backend /app/pyproject.toml /app/
COPY --from=backend /app/specs/ /app/specs/
RUN pip install --no-cache-dir -e ".[all]"

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
