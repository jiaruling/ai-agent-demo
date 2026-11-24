import os
import json
import uuid
from typing import Optional
from openai import OpenAI
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI()

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
        return {"count": 128, "range": date_range}
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
    "query_data":        lambda args: mock_query_data(args["query_type"], args["date_range"]),
    "navigate_to_page":  lambda args: navigate_to_page(args["page_id"], args.get("date_range")),
}

# ---------- 会话历史（demo 用内存，重启即清空） ----------
SESSIONS: dict[str, list] = {}

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

def run_agent(session_id: str, user_message: str):
    history = SESSIONS.setdefault(session_id, [])
    history.append({"role": "user", "content": user_message})

    navigation = None
    reply = ""

    for _ in range(5):  # 最多 5 轮，防止模型陷入循环
        response = client.chat.completions.create(
            model="deepseek-flash",
            messages=history,
            tools=tools,
            extra_body={"thinking": {"type": "disabled"}},
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            reply = msg.content or ""
            history.append({"role": "assistant", "content": reply})
            return {"reply": reply, "navigation": navigation}

        history.append(msg)
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
            history.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    return {"reply": "处理步骤过多，请换个问法试试。", "navigation": navigation}

@app.post("/api/chat")
def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    result = run_agent(session_id, req.message)
    return {"session_id": session_id, **result}

@app.get("/")
def index():
    return FileResponse("index.html")