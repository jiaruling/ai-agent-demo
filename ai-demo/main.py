import os
import json
import uuid
import re
import tempfile
import random
from pathlib import Path
from threading import Lock
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from openai import OpenAI
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from tools import TOOLS, BASE_URL_BACKEND, TOOL_API_ROUTES
from page import PAGE_REGISTRY,BASE_URL_FRONT
from session_history import SessionHistory, SessionNotFound

# 初始化fastapi web服务
app = FastAPI()

# 初始化大模型客户端
client = OpenAI(
    # api_key=os.environ.get("DEEPSEEK_API_KEY"), # deepseek的api密钥
    api_key=os.environ.get("LITELLM_MASTER_KEY"), # 代理的访问密钥
    # base_url="https://api.deepseek.com",    # deepseek的地址 
    base_url="http://192.168.11.100:4000/v1", # 代码的访问地址
)


# ---------- 工具执行函数 ----------
def navigate_to_page(page_id):
    page = PAGE_REGISTRY.get(page_id)
    if not page:
        return {"error": f"页面不存在：{page_id}"}
    path = page["path"]
    return {"type": "navigation", "label": page["title"], "url": f"{BASE_URL_FRONT}{path}"}

TOKEN_FILE = Path(__file__).resolve().parent / ".env.agent-tokens.json"
TOKEN_LOCK = Lock()


def _load_session_tokens() -> dict[str, dict[str, str]]:
    try:
        with TOKEN_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"无法加载本地 Token 文件：{TOKEN_FILE}") from error

    if not isinstance(data, dict) or any(
        not isinstance(session_id, str)
        or not isinstance(token, str)
        or not token
        for session_id, token in data.items()
    ):
        raise ValueError(f"本地 Token 文件格式无效：{TOKEN_FILE}")
    return {
        session_id: {"accessToken": token}
        for session_id, token in data.items()
    }


SESSION_TOKENS: dict[str, dict[str, str]] = _load_session_tokens()


def _update_session_tokens(session_id: str, tokens: dict[str, str] | None) -> None:
    with TOKEN_LOCK:
        updated = SESSION_TOKENS.copy()
        if tokens is None:
            updated.pop(session_id, None)
        else:
            updated[session_id] = tokens

        persisted = {
            key: value["accessToken"] for key, value in updated.items()
        }
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=TOKEN_FILE.parent,
                prefix=".env.agent-tokens-", delete=False,
            ) as file:
                temp_path = Path(file.name)
                json.dump(persisted, file, ensure_ascii=False)
            os.replace(temp_path, TOKEN_FILE)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
        SESSION_TOKENS.clear()
        SESSION_TOKENS.update(updated)


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
    with TOKEN_LOCK:
        token = SESSION_TOKENS.get(session_id, {}).get("accessToken")
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

        try:
            _update_session_tokens(session_id, {
                "accessToken": access_token,
                "refreshToken": refresh_token,
            })
        except OSError as error:
            return {"error": f"登录成功，但保存本地 Token 失败：{error}"}
        # Do not pass access/refresh tokens back into the model conversation.
        return {
            key: value for key, value in login_result.items()
            if key not in ("accessToken", "refreshToken")
        }

    if name == "logout" and not (
        isinstance(result, dict)
        and (result.get("error") or result.get("code", 0) not in (0, "0"))
    ):
        try:
            _update_session_tokens(session_id, None)
        except OSError as error:
            with TOKEN_LOCK:
                SESSION_TOKENS.pop(session_id, None)
            return {"error": f"已退出登录，但删除本地 Token 失败：{error}"}

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
HISTORY = SessionHistory(Path(__file__).resolve().parent / ".env.agent-history.json")

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

def run_agent(session_id: str, user_message: str, owner_id: str = "legacy"):
    with HISTORY.session_lock(session_id):
        return _run_agent(session_id, user_message, owner_id)


def _run_agent(session_id: str, user_message: str, owner_id: str):
    history = HISTORY.add_user_message(session_id, owner_id, user_message)

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

    HISTORY.add_assistant_message(session_id, owner_id, final_reply, navigation)

    return {
        "reply": final_reply,
        "navigation": navigation,
        "steps": steps,   # 新增字段，前端可以选择展示
    }


# ---------- HTTP 接口 ----------
def _owner_id(client_id: str | None) -> str:
    if client_id is None:
        return "legacy"
    if not re.fullmatch(r"[a-f0-9]{64}", client_id):
        raise HTTPException(status_code=400, detail="无效的客户端标识")
    return client_id


@app.post("/api/chat")
def chat(req: ChatRequest, x_client_id: Optional[str] = Header(default=None)):
    session_id = req.session_id or str(uuid.uuid4()) # 获取session_id如果没有就新建
    try:
        result = run_agent(session_id, req.message, _owner_id(x_client_id))
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, **result} # 返回session_id和agent的回复

@app.get("/api/sessions")
def list_sessions(x_client_id: str = Header()):
    return {"sessions": HISTORY.list_sessions(_owner_id(x_client_id))}

@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, x_client_id: str = Header()):
    try:
        messages = HISTORY.get_messages(session_id, _owner_id(x_client_id))
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "messages": messages}

@app.get("/api/suggestions")
def suggestions():
    examples = [
        f"打开{page['title']}"
        for page_id, page in PAGE_REGISTRY.items()
        if page_id != "login"
    ]
    examples.extend(
        tool["function"]["description"].split("。", 1)[0]
        for tool in TOOLS
        if tool["function"]["name"] in ("list_devices", "list_users", "list_departments", "list_roles", "health")
    )
    return {"suggestions": random.sample(examples, min(len(examples), random.randint(6, 8)))}

@app.get("/")
def index():
    return FileResponse(Path(__file__).resolve().parent / "index.html")