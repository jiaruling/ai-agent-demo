import os
import json
import uuid
import re
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from openai import OpenAI
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from tools import TOOLS, BASE_URL_BACKEND, TOOL_API_ROUTES
from page import PAGE_REGISTRY,BASE_URL_FRONT

# 初始化fastapi web服务
app = FastAPI()

# 初始化大模型客户端
client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)


# ---------- 工具执行函数 ----------
def navigate_to_page(page_id):
    page = PAGE_REGISTRY.get(page_id)
    if not page:
        return {"error": f"页面不存在：{page_id}"}
    path = page["path"]
    return {"type": "navigation", "label": page["title"], "url": f"{BASE_URL_FRONT}{path}"}

# JWTs are kept per chat session so different users cannot share an API login.
SESSION_TOKENS: dict[str, dict[str, str]] = {}


def _decode_api_response(body: bytes, charset: str | None = None) -> Any:
    if not body:
        return None
    text = body.decode(charset or "utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _call_backend_tool(name: str, args: dict, session_id: str) -> Any:
    route = TOOL_API_ROUTES.get(name)
    if route is None:
        return {"error": f"未知工具：{name}"}

    method, path_template = route
    path_params = re.findall(r":([A-Za-z][A-Za-z0-9_]*)", path_template)
    for param in path_params:
        if param not in args:
            return {"error": f"工具 {name} 缺少路径参数：{param}"}
        path_template = path_template.replace(
            f":{param}", quote(str(args[param]), safe="")
        )

    headers = {"Accept": "application/json"}
    session_tokens = SESSION_TOKENS.get(session_id, {})
    token = session_tokens.get("accessToken")
    if token:
        # The backend, like the frontend service, expects the raw token value.
        headers["Authorization"] = token

    body = None
    if name == "login":
        body = json.dumps(args, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    query = (
        {
            key: value
            for key, value in args.items()
            if key not in path_params and value is not None
        }
        if method == "GET"
        else {}
    )
    query_string = urlencode(query, doseq=True)
    url = f"{BASE_URL_BACKEND.rstrip('/')}{path_template}"
    if query_string:
        url = f"{url}?{query_string}"

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            result = _decode_api_response(
                response.read(), response.headers.get_content_charset()
            )
    except HTTPError as error:
        with error:
            details = _decode_api_response(
                error.read(), error.headers.get_content_charset()
            )
        message = details
        if isinstance(details, dict):
            message = details.get("msg") or details.get("message") or details
        return {"error": str(message), "status_code": error.code, "details": details}
    except (URLError, TimeoutError) as error:
        return {"error": f"请求后端接口失败：{error}"}

    if name == "login":
        login_result = result
        if isinstance(result, dict) and "code" in result and "data" in result:
            if result["code"] not in (0, "0"):
                return {"error": result.get("msg") or "登录失败"}
            login_result = result["data"]

        if not isinstance(login_result, dict):
            return {"error": "登录接口返回的数据格式无效"}
        access_token = login_result.get("accessToken")
        refresh_token = login_result.get("refreshToken")
        if not isinstance(access_token, str) or not access_token:
            return {"error": "登录接口未返回有效 accessToken"}
        if not isinstance(refresh_token, str) or not refresh_token:
            return {"error": "登录接口未返回有效 refreshToken"}

        SESSION_TOKENS[session_id] = {
            "accessToken": access_token,
            "refreshToken": refresh_token,
        }
        # Do not pass access/refresh tokens back into the model conversation.
        return {
            key: value for key, value in login_result.items()
            if key not in ("accessToken", "refreshToken")
        }

    if name == "logout" and not (
        isinstance(result, dict) and result.get("error")
    ):
        SESSION_TOKENS.pop(session_id, None)

    return result


def _execute_tool(name: str, args: Any, session_id: str) -> Any:
    if not isinstance(args, dict):
        return {"error": f"工具 {name} 的参数必须是 JSON 对象"}
    if name == "navigate_to_page":
        page_id = args.get("page_id")
        if not isinstance(page_id, str):
            return {"error": "工具 navigate_to_page 缺少有效参数：page_id"}
        return navigate_to_page(page_id)
    return _call_backend_tool(name, args, session_id)


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

AGENT_SYSTEM = """你是一个内部系统的智能助手，可以调用已定义的工具查询系统数据或跳转页面。
- 需要账号认证的接口，在调用前先使用 login 登录
- 跳转页面使用 navigate_to_page
只完成当前任务，不要发散，不要重复前面已完成的操作。
"""

def _agent_loop(
    messages: list, session_id: str, max_rounds: int = 5
) -> tuple[str, dict | None]:
    """核心 Agent 循环：决策 → 调工具 → 再决策，直到模型不再请求工具"""
    navigation = None
    for _ in range(max_rounds):
        resp = client.chat.completions.create(
            model="deepseek-flash",
            messages=messages,
            tools=TOOLS,
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
                result = {"error": f"工具 {name} 的参数不是有效 JSON"}
            else:
                result = _execute_tool(name, args, session_id)
            if isinstance(result, dict) and result.get("type") == "navigation":
                navigation = result
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    return "（达到最大轮次，任务未完全结束）", navigation


def _execute_step(
    step: str,
    index: int,
    total: int,
    prior_results: list[str],
    session_id: str,
) -> tuple[str, dict | None]:
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
    return _agent_loop(messages, session_id)


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
        reply, nav = _execute_step(
            step, i, len(steps), prior_results, session_id
        )
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