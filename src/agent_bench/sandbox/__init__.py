"""沙箱统一导出。"""

from agent_bench.sandbox.sandbox import AuditEntry, AuditLog, Sandbox

__all__ = ["AuditEntry", "AuditLog", "Sandbox", "RealSandbox"]


def __getattr__(name: str):
    if name == "RealSandbox":
        from agent_bench.sandbox.real_sandbox import RealSandbox
        return RealSandbox
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
