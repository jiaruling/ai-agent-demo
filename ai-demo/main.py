import os
import json
import uuid
from typing import Optional
from openai import OpenAI
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

# 初始化fastapi web服务
app = FastAPI()

# 初始化大模型客户端
client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

# ---------- 页面注册表 ----------
PAGE_REGISTRY = {
    "order_list":   {"title": "订单列表", "path": "/orders?range={date_range}"},
    "user_profile": {"title": "个人中心", "path": "/profile"},
    "dashboard":    {"title": "数据看板", "path": "/dashboard"},
}
BASE_URL = "http://localhost:3000"  # demo 用假域名，接入真实系统时改掉

# ---------- 工具定义 ----------
tools = [
    {
        "type": "function",
        "function": {
            "name": "query_data",
            "description": "查询业务数据，支持按时间范围查询订单数量或订单列表。只在用户需要查询数据时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_type": {"type": "string", "enum": ["order_count", "order_list"],
                                   "description": "order_count 返回数量，order_list 返回列表"},
                    "date_range": {"type": "string", "description": "时间范围，如 '2025-01'"},
                },
                "required": ["query_type", "date_range"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate_to_page",
            "description": "跳转到内部系统指定页面。只在用户明确要求打开、跳转、进入某个页面时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "string",
                                "enum": ["order_list", "user_profile", "dashboard"],
                                "description": "order_list=订单列表, user_profile=个人中心, dashboard=数据看板"},
                    "date_range": {"type": "string", "description": "可选，跳订单列表时可带时间范围"},
                },
                "required": ["page_id"],
            },
        },
    },
]

# ---------- 工具执行函数（mock） ----------
def mock_query_data(query_type, date_range):
    if query_type == "order_count":
        return {"count": 99, "range": date_range}
    return {"orders": [
        {"id": "ORD-001", "status": "待处理"},
        {"id": "ORD-002", "status": "已完成"},
    ], "range": date_range}

def navigate_to_page(page_id, date_range=None):
    page = PAGE_REGISTRY.get(page_id)
    if not page:
        return {"error": f"页面不存在：{page_id}"}
    path = page["path"].format(date_range=date_range or "")
    return {"type": "navigation", "label": page["title"], "url": f"{BASE_URL}{path}"}

TOOL_HANDLERS = {
    "query_data":       lambda args: mock_query_data(args["query_type"], args["date_range"]),
    "navigate_to_page": lambda args: navigate_to_page(args["page_id"], args.get("date_range")),
}

# ---------- 会话历史 ----------
SESSIONS: dict[str, list] = {}

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


# ============================================================
# 新增：规划阶段
# ============================================================

# PLANNER_SYSTEM = "xqswqdqdqfdewcdeedqqw sqdqwdcq145d5wqd" # 乱码测试
PLANNER_SYSTEM = """你是一个任务规划器。请把用户的请求拆解成 1-3 个简单步骤。

规则：
- 每个步骤只描述一个明确动作，例如"查询 2025 年 1 月的订单数量"或"跳转到订单列表页面"
- 不要过度拆分，能一步完成就一步
- 步骤之间有依赖关系时，按顺序排列
- 只输出 JSON，不要输出任何解释或 Markdown

输出格式：
{"steps": ["步骤1的描述", "步骤2的描述"]}
"""

def _clean_history_for_planner(history: list) -> list:
    """只保留 user / assistant 的文本消息，丢掉 tool 消息，避免传给规划器时结构不合法"""
    cleaned = []
    for m in history:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        if role in ("user", "assistant"):
            content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
            if content:
                cleaned.append({"role": role, "content": content})
    return cleaned[-4:]  # 只取最近 2 轮，够用且省 token

def plan_task(history: list) -> list[str]:
    """阶段 1：让模型输出步骤列表。失败时退化为单步执行原请求。"""
    recent = _clean_history_for_planner(history)
    messages = [{"role": "system", "content": PLANNER_SYSTEM}] + recent
    content = ""

    # 优先用 JSON mode
    try:
        resp = client.chat.completions.create(
            model="deepseek-flash",
            messages=messages,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
        )
        content = resp.choices[0].message.content or ""
    except Exception as e:
        # 执行失败执行普通模式
        print(f"[plan] JSON mode 调用失败，退化普通调用：{e}")
        try:
            resp = client.chat.completions.create(
                model="deepseek-flash",
                messages=messages,
                extra_body={"thinking": {"type": "disabled"}},
            )
            content = resp.choices[0].message.content or ""
        except Exception as e2:
            print(f"[plan] 规划调用彻底失败：{e2}")
            return [history[-1]["content"]]

    # 解析 JSON，失败则兜底
    try:
        # 兼容模型偶尔在 JSON 外面包 ```json ... ``` 的情况
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        # 加载数据
        data = json.loads(text)
        steps = data.get("steps", [])
        if isinstance(steps, list):
            steps = [str(s).strip() for s in steps if str(s).strip()]
        else:
            steps = []
        # 只取最近3步骤，如果步骤列表为空，则退化为单步执行
        return steps[:3] if steps else [history[-1]["content"]]
    except Exception as e:
        print(f"[plan] JSON 解析失败，退化单步：{e} | 原始内容：{content[:200]}")
        return [history[-1]["content"]]


# ============================================================
# 执行阶段：单个步骤的 Agent 循环
# ============================================================

AGENT_SYSTEM = """你是一个内部系统的智能助手，可以调用工具查询数据或跳转页面。
- 查询数据用 query_data
- 跳转页面用 navigate_to_page
只完成当前任务，不要发散，不要重复前面已完成的操作。
"""

def _agent_loop(messages: list, max_rounds: int = 5) -> tuple[str, dict | None]:
    """核心 Agent 循环：决策 → 调工具 → 再决策，直到模型不再请求工具"""
    navigation = None
    for _ in range(max_rounds):
        resp = client.chat.completions.create(
            model="deepseek-flash",
            messages=messages,
            tools=tools,
            extra_body={"thinking": {"type": "disabled"}},
        )
        msg = resp.choices[0].message

        if not msg.tool_calls:
            return msg.content or "", navigation

        messages.append(msg)
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            handler = TOOL_HANDLERS.get(name)
            result = handler(args) if handler else {"error": f"未知工具：{name}"}
            if isinstance(result, dict) and result.get("type") == "navigation":
                navigation = result
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    return "（达到最大轮次，任务未完全结束）", navigation


def _execute_step(step: str, index: int, total: int, prior_results: list[str]) -> tuple[str, dict | None]:
    """阶段 2：执行单个步骤。前序步骤的结果作为背景注入。"""
    context = ""
    if prior_results:
        context = "之前步骤的执行结果：\n" + "\n".join(f"- {r}" for r in prior_results) + "\n\n"

    messages = [
        {"role": "system", "content": AGENT_SYSTEM},
        {
            "role": "user",
            "content": f"{context}【当前步骤 {index}/{total}】{step}\n（请专注执行这一步，不要重复前面的操作）",
        },
    ]
    return _agent_loop(messages)


def _summarize(steps: list[str], replies: list[str]) -> str:
    """把多步骤结果拼成 Markdown 汇总"""
    parts = []
    for i, (step, reply) in enumerate(zip(steps, replies), 1):
        body = reply.strip() if reply and reply.strip() else "（无输出）"
        parts.append(f"**{i}. {step}**\n{body}")
    return "\n\n".join(parts)


# ============================================================
# 主入口：规划 → 逐步执行 → 汇总
# ============================================================

def run_agent(session_id: str, user_message: str):
    history = SESSIONS.setdefault(session_id, [])
    history.append({"role": "user", "content": user_message})

    # 阶段 1：规划
    steps = plan_task(history)
    print(f"[plan] 步骤：{steps}")

    # 阶段 2：逐步执行
    navigation = None # 存储前端跳转
    prior_results: list[str] = [] # 之前的结果
    replies: list[str] = [] # 大模型的回复

    for i, step in enumerate(steps, 1): # 计数器从1开始，遍历从列表第一项(0号下标)开始
        reply, nav = _execute_step(step, i, len(steps), prior_results)
        replies.append(reply)
        prior_results.append(f"步骤{i}「{step}」→ {reply}")
        if nav:
            navigation = nav

    # 汇总
    if len(steps) <= 1:
        final_reply = replies[0] if replies else "（无回复）"
    else:
        final_reply = _summarize(steps, replies)

    history.append({"role": "assistant", "content": final_reply})

    return {
        "reply": final_reply,
        "navigation": navigation,
        "steps": steps,   # 新增字段，前端可以选择展示
    }


# ---------- HTTP 接口 ----------
@app.post("/api/chat")
def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4()) # 获取session_id如果没有就新建
    result = run_agent(session_id, req.message)
    return {"session_id": session_id, **result} # 返回session_id和agent的回复

@app.get("/")
def index():
    return FileResponse("index.html")