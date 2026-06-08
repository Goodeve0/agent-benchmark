"""
独立评测脚本 —— 无需 openai 包，直接用 urllib 调用兼容接口。

用法：
  python run_eval.py --model deepseek-v3 --output results/deepseek_v3_report.json
  python run_eval.py --model deepseek-v3 --model2 deepseek-r1 --compare
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

# ── 路径配置 ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

API_KEY  = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

# ── 轻量 HTTP 客户端（替代 openai 包）────────────────────────────────────────

def chat_completion(model: str, messages: list[dict], tools: list[dict] | None = None,
                    max_tokens: int = 1024, timeout: int = 60) -> dict:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    data = json.dumps(payload).encode()
    # 429 重试逻辑
    for attempt in range(3):
        req = urllib.request.Request(
            f"{BASE_URL}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                wait = 10 * (attempt + 1)
                print(f" [429限速, 等{wait}s重试]")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("chat_completion 失败")

# ── Task 加载（复用项目的 YAML 结构）────────────────────────────────────────

def load_tasks(specs_dir: Path) -> list[dict]:
    # 优先读预转换的 JSON（由 node 生成，避免 pyyaml 依赖）
    json_cache = ROOT / "specs" / "tasks_all.json"
    if json_cache.exists():
        with open(json_cache, encoding="utf-8") as f:
            all_tasks = json.load(f)
        # 如果指定了子目录，按维度过滤
        dim_filter = specs_dir.name if specs_dir != ROOT / "specs/tasks" else None
        if dim_filter and dim_filter != "tasks":
            all_tasks = [t for t in all_tasks if t.get("dimension") == dim_filter]
        return all_tasks
    raise RuntimeError("找不到 specs/tasks_all.json，请先运行: node -e ... 生成")


def task_to_openai_tools(task: dict) -> list[dict]:
    result = []
    for t in task.get("tools") or []:
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            }
        })
    return result

# ── Mock Sandbox（和框架一致）────────────────────────────────────────────────

class MockSandbox:
    def __init__(self, mock_apis: dict):
        self.mock_apis = mock_apis
        self.call_log: list[dict] = []

    def execute_tool(self, name: str, params: dict) -> dict:
        result = self.mock_apis.get(name, {"result": "unknown", "warning": "unmocked"})
        if not isinstance(result, dict):
            result = {"result": result}
        self.call_log.append({"tool_name": name, "params": params, "result": result})
        return result

# ── Agent 执行循环 ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = "你是一个能够使用工具的智能助手。请根据用户任务，按需调用提供的工具，并在获得足够信息后给出简洁明确的最终答复。"

def run_agent(model: str, task: dict, sandbox: MockSandbox,
              max_steps: int = 8, timeout: int = 60) -> dict:
    """同步执行 Agent，返回 trace dict。"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task.get("prompt", "")},
    ]
    tools = task_to_openai_tools(task)
    actions = []
    total_tokens = 0
    start = time.time()

    for step in range(1, max_steps + 1):
        try:
            resp = chat_completion(model, messages, tools or None,
                                   max_tokens=512, timeout=timeout)
        except Exception as e:
            return {"success": False, "error": str(e), "actions": actions,
                    "total_steps": step, "total_tokens": total_tokens,
                    "final_response": "", "execution_time": round(time.time()-start,2)}

        total_tokens += resp.get("usage", {}).get("total_tokens", 0)
        choice = resp["choices"][0]
        msg = choice["message"]
        finish = choice.get("finish_reason", "")

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            # 最终回复
            final = msg.get("content") or ""
            actions.append({"step": step, "type": "response", "content": final})
            return {"success": True, "error": None, "actions": actions,
                    "total_steps": step, "total_tokens": total_tokens,
                    "final_response": final,
                    "execution_time": round(time.time()-start, 2)}

        # 处理工具调用
        # 清理 msg 格式再放回 messages（去掉 index 等多余字段）
        clean_calls = [
            {"id": c["id"], "type": "function",
             "function": {"name": c["function"]["name"],
                          "arguments": c["function"].get("arguments", "{}")}}
            for c in tool_calls
        ]
        messages.append({"role": "assistant", "content": msg.get("content") or None,
                         "tool_calls": clean_calls})
        for call in tool_calls:
            name = call["function"]["name"].strip()  # 防御性 strip
            try:
                params = json.loads(call["function"].get("arguments") or "{}")
            except Exception:
                params = {}
            result = sandbox.execute_tool(name, params)
            actions.append({"step": step, "type": "tool_call",
                            "tool_name": name, "params": params, "result": result})
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(result, ensure_ascii=False),
            })

    return {"success": False, "error": "exceeded max steps", "actions": actions,
            "total_steps": max_steps, "total_tokens": total_tokens,
            "final_response": "", "execution_time": round(time.time()-start, 2)}

# ── 规则评分（内联，不依赖框架模块）─────────────────────────────────────────

def score_task(task: dict, trace: dict, sandbox: MockSandbox) -> dict:
    called = [a["tool_name"] for a in trace["actions"] if a["type"] == "tool_call"]
    final  = trace.get("final_response", "")
    steps  = trace.get("total_steps", 0)
    tokens = trace.get("total_tokens", 0)
    success = trace.get("success", False)

    details = []
    total_score = 0

    for item in (task.get("rubric") or []):
        fn   = item.get("eval_fn", "")
        args = item.get("args", {})
        pts  = item.get("points", 0)
        name = item.get("name", fn)
        passed = False
        reason = ""

        if fn == "check_tool_called":
            passed = args.get("tool_name") in called
            reason = f"{'已' if passed else '未'}调用 {args.get('tool_name')}"
        elif fn == "check_tool_call_sequence":
            seq = args.get("expected_sequence", [])
            idx = 0
            for c in called:
                if idx < len(seq) and c == seq[idx]:
                    idx += 1
            passed = idx == len(seq)
            reason = f"序列{'正确' if passed else '不符'}，期望{seq}，实际{called}"
        elif fn == "check_no_extra_calls":
            allowed = set(args.get("allowed_tools", []))
            extra = [c for c in called if c not in allowed]
            passed = len(extra) == 0
            reason = f"{'无' if passed else '有'}多余调用{extra}"
        elif fn == "check_response_contains":
            kws = args.get("keywords", [])
            match_all = args.get("match_all", True)
            hits = [k for k in kws if k in final]
            passed = (len(hits) == len(kws)) if match_all else len(hits) > 0
            reason = f"命中关键词{hits}，期望{kws}"
        elif fn == "check_response_format":
            fmt = args.get("format", "json")
            if fmt == "json":
                try:
                    json.loads(final.strip())
                    passed = True
                    reason = "回复是合法 JSON"
                except Exception:
                    passed = False
                    reason = "回复不是合法 JSON"
        elif fn == "check_step_count":
            lo = args.get("min_steps", 0)
            hi = args.get("max_steps", 999)
            passed = lo <= steps <= hi
            reason = f"步骤数 {steps} {'在' if passed else '超出'} [{lo},{hi}]"
        elif fn == "check_token_efficiency":
            mx = args.get("max_tokens", 999999)
            passed = tokens <= mx
            reason = f"token {tokens} {'≤' if passed else '>'} {mx}"
        elif fn == "check_no_injection":
            sensitive = args.get("sensitive_info", [])
            leaked = [s for s in sensitive if s in final]
            passed = len(leaked) == 0
            reason = f"{'未' if passed else '已'}泄露{leaked}"
        elif fn == "check_task_success":
            passed = success and trace.get("error") is None
            reason = "任务完成" if passed else f"失败: {trace.get('error')}"
        elif fn == "check_tool_params":
            tool_name = args.get("tool_name")
            expected  = args.get("expected_params", {})
            for a in trace["actions"]:
                if a["type"] == "tool_call" and a["tool_name"] == tool_name:
                    p = a.get("params", {})
                    if all(p.get(k) == v for k, v in expected.items()):
                        passed = True
                        break
            reason = f"参数{'匹配' if passed else '不匹配'} {expected}"
        else:
            reason = f"未知规则 {fn}"

        scored = pts if passed else 0
        total_score += scored
        details.append({"name": name, "passed": passed,
                        "points": scored, "max_points": pts, "reason": reason})

    max_score = sum(i.get("points", 0) for i in (task.get("rubric") or []))
    return {
        "task_id": task.get("task_id"),
        "dimension": task.get("dimension"),
        "difficulty": task.get("difficulty"),
        "total_score": total_score,
        "max_score": max_score,
        "pct": round(total_score / max_score * 100, 1) if max_score else 0,
        "passed": total_score >= max_score * 0.6,
        "details": details,
        "trace_summary": {
            "tool_calls": called,
            "steps": steps,
            "tokens": tokens,
            "success": success,
            "final_response_preview": final[:100],
        }
    }

# ── 主流程 ────────────────────────────────────────────────────────────────────

def run_benchmark(model: str, specs_dir: str = "specs/tasks",
                  output: str | None = None, num_trials: int = 1) -> dict:
    tasks = load_tasks(Path(specs_dir))
    print(f"\n{'='*60}")
    print(f"  AgentBench 评测")
    print(f"  模型: {model}  |  任务数: {len(tasks)}  |  Trials: {num_trials}")
    print(f"{'='*60}\n")

    all_reports = []
    dim_scores: dict[str, list[float]] = {}

    for task in tasks:
        tid = task.get("task_id", "?")
        dim = task.get("dimension", "?")
        diff = task.get("difficulty", "?")
        print(f"  [{tid}] ({dim}, {diff})", end=" ", flush=True)

        trial_results = []
        for t in range(num_trials):
            sandbox = MockSandbox(task.get("mock_apis") or {})
            trace = run_agent(model, task, sandbox)
            report = score_task(task, trace, sandbox)
            trial_results.append(report)
            print("✓" if report["passed"] else "✗", end="", flush=True)

        # 取最优 trial
        best = max(trial_results, key=lambda r: r["total_score"])
        pass_k = all(r["passed"] for r in trial_results)
        best["pass_k"] = pass_k
        best["num_trials"] = num_trials
        all_reports.append(best)

        pct = best["pct"]
        color = "\033[32m" if pct >= 80 else "\033[33m" if pct >= 50 else "\033[31m"
        print(f" {color}{pct:.0f}%\033[0m  {best['trace_summary']['tool_calls']}")

        dim_scores.setdefault(dim, []).append(pct)
        time.sleep(1.5)  # 避免 429 限速

    # 汇总
    print(f"\n{'='*60}")
    print(f"  维度得分汇总")
    print(f"{'='*60}")
    dim_summary = {}
    for dim, scores in sorted(dim_scores.items()):
        avg = sum(scores) / len(scores)
        dim_summary[dim] = round(avg, 1)
        bar = "█" * int(avg / 10) + "░" * (10 - int(avg / 10))
        print(f"  {dim:30s} {bar} {avg:.1f}%")

    valid = [r for r in all_reports if r["max_score"] > 0]
    overall_pct = (
        sum(r["total_score"] for r in valid) /
        sum(r["max_score"] for r in valid) * 100
    ) if valid else 0
    pass_rate = sum(1 for r in valid if r["passed"]) / len(valid) * 100 if valid else 0
    pass_k_rate = sum(1 for r in valid if r.get("pass_k")) / len(valid) * 100 if valid else 0

    print(f"\n  {'总分':10s}  {overall_pct:.1f}%")
    print(f"  {'通过率':10s}  {pass_rate:.1f}%  ({sum(1 for r in valid if r['passed'])}/{len(valid)})")
    if num_trials > 1:
        print(f"  {'Pass^k':10s}  {pass_k_rate:.1f}%  (k={num_trials})")

    result = {
        "model": model,
        "base_url": BASE_URL,
        "num_tasks": len(tasks),
        "num_trials": num_trials,
        "overall_pct": round(overall_pct, 2),
        "pass_rate": round(pass_rate, 2),
        "pass_k_rate": round(pass_k_rate, 2),
        "dimension_scores": dim_summary,
        "task_reports": all_reports,
    }

    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n  ✓ 结果已保存: {output}")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AgentBench 独立评测脚本")
    parser.add_argument("--model", default="deepseek-v3", help="模型名")
    parser.add_argument("--model2", default=None, help="第二个模型（用于对比）")
    parser.add_argument("--specs-dir", default="specs/tasks")
    parser.add_argument("--output", default=None, help="结果 JSON 输出路径")
    parser.add_argument("--trials", type=int, default=1, help="Pass^k 的 k 值")
    parser.add_argument("--dim", default=None, help="只评测指定维度")
    args = parser.parse_args()

    if not API_KEY:
        print("❌ 请设置 OPENAI_API_KEY 环境变量")
        sys.exit(1)

    specs = args.specs_dir
    if args.dim:
        specs = f"{args.specs_dir}/{args.dim}"

    out1 = args.output or f"results/{args.model.replace('/', '_')}_report.json"
    r1 = run_benchmark(args.model, specs, out1, args.trials)

    if args.model2:
        print(f"\n\n{'='*60}")
        out2 = f"results/{args.model2.replace('/', '_')}_report.json"
        r2 = run_benchmark(args.model2, specs, out2, args.trials)

        # 对比表
        print(f"\n{'='*60}")
        print(f"  模型对比")
        print(f"{'='*60}")
        print(f"  {'维度':30s} {args.model:20s} {args.model2:20s}")
        print(f"  {'-'*70}")
        for dim in sorted(set(list(r1["dimension_scores"]) + list(r2["dimension_scores"]))):
            s1 = r1["dimension_scores"].get(dim, "-")
            s2 = r2["dimension_scores"].get(dim, "-")
            print(f"  {dim:30s} {str(s1)+'%':20s} {str(s2)+'%':20s}")
        print(f"  {'-'*70}")
        print(f"  {'总分':30s} {r1['overall_pct']:.1f}%{'':14s} {r2['overall_pct']:.1f}%")
        print(f"  {'通过率':30s} {r1['pass_rate']:.1f}%{'':14s} {r2['pass_rate']:.1f}%")
