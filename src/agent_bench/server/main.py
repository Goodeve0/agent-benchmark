"""FastAPI 服务器启动入口。

用法：
    python -m agent_bench.server.main [--spec-dir DIR] [--host HOST] [--port PORT]
"""

from __future__ import annotations

import argparse

import uvicorn

from agent_bench.server.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentBench Web API Server")
    parser.add_argument("--spec-dir", type=str, default=None, help="任务规范目录路径")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发模式（自动重载）")
    args = parser.parse_args()

    app = create_app(spec_dir=args.spec_dir)

    uvicorn.run(
        "agent_bench.server.app:create_app" if args.reload else app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        factory=args.reload,
    )


if __name__ == "__main__":
    main()
