# 流程

> 基本环境: Ubuntu linux & python 3.10.12

## 一、环境准备

### 1. 确认 Python 版本
首先确认 Python 版本确实是 3.10.12

```bash
python3.10 --version
# 预期输出: Python 3.10.12
```
如果系统默认 python3 就是 3.10.12，后续步骤中的 python3.10 也可以用 python3 代替。

### 2. 安装 venv 模块（如尚未安装）
Ubuntu 的 Python 包通常不会自动包含 venv 模块，需要单独安装。对于 Python 3.10，对应的包是 python3.10-venv。

```bash
sudo apt update
sudo apt install python3.10-venv
```

### 3. 创建虚拟环境
进入项目目录，然后使用 python3.10 -m venv 命令创建环境。建议将环境命名为 .venv，这是社区的一种惯例。

```bash
cd /path/to/your/project  # 替换为实际项目路径
python3.10 -m venv .venv
```

执行后，当前目录下会生成一个 .venv 文件夹，其中包含了独立的 Python 解释器和包管理工具。

### 4. 激活虚拟环境
创建完成后，需要“激活”它才能开始使用。

```bash
source .venv/bin/activate
```
激活后，命令行提示符前会出现 (.venv) 字样，表示已进入该虚拟环境。

### 5. 验证环境的“纯净性”
这是关键一步。激活后，可以运行以下命令查看环境中已安装的包。

```bash
pip list
```
一个全新的纯净环境通常只包含 pip 和 setuptools（或仅 pip）这两个基础包。它不会包含系统全局 Python 环境中安装的任何第三方库（如 numpy、requests 等），从而实现了与系统环境的完全隔离。

### 6. 退出与删除环境

退出：当完成工作后，运行 `deactivate` 命令即可退出虚拟环境，回到系统的全局 Python 环境。

删除：虚拟环境被视为“可丢弃的”。如果不再需要，直接删除整个 .venv 文件夹即可，不会影响系统。

```bash
rm -rf .venv
```

### 7. 安装 `openai` 库
DeepSeek 官方推荐的 Python 接入方式，是直接使用 openai 这个包，通过修改 base_url 指向 DeepSeek，而不是安装一个叫 deepseek-sdk 的第三方包。
```bash
python3 -m pip install --upgrade openai
```
安装完成后验证一下：

```bash
python3 -c "import openai; print(openai.__version__)"
```
能打印出版本号就说明安装成功。

### 8. 设置API Key（不要写死在代码里）
设为环境变量，代码从环境变量读取，这样 Key 不会跟着代码泄露
推荐写入 ~/.bashrc，让它在每次打开终端时自动生效：

```bash
echo 'export DEEPSEEK_API_KEY="你的key"' >> ~/.bashrc
source ~/.bashrc
```
验证环境变量是否生效：

```bash
echo $DEEPSEEK_API_KEY
```

### 9. 第一个测试脚本
写并运行第一个测试脚本，新建一个文件 hello_deepseek.py，内容如下：

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

response = client.chat.completions.create(
    model="deepseek-flash",
    messages=[
        {"role": "user", "content": "用一句话告诉我，你已经准备好协助我完成数据查询和页面跳转了。"}
    ],
)


print(response.choices[0].message.content)
```
这里的关键点：`base_url` 指向 `https://api.deepseek.com`，`model` 使用 `deepseek-flash`，这是 DeepSeek 官方当前推荐的模型别名。后面做“模拟本地大模型”时，只需要把这个 `base_url` 改成 `http://127.0.0.1:8787/v1`（本地代理的地址），代码其余部分基本不用动。

运行：

```bash
python3 hello_deepseek.py
```
如果终端打印出一句类似“我已经准备好协助你……”的回复，第一步就完成了

## 二、工具调用（Function Calling）

### 1. 关键概念
> 模型不执行代码，只“请求”调用

DeepSeek 的 Tool Calls 流程中，**模型本身不执行任何函数**，它只做一件事：当判断需要外部数据时，返回一个结构化的 tool_calls 请求，告诉你的代码“我想调用 query_data，参数是这些”。真正执行查询、访问数据库的，是你自己的 Python 代码。官方文档把这个流程拆得很清楚：

> 用户提问 → 模型返回 tool_calls（函数名 + 参数）→ 你的代码执行真实函数 → 把结果以 role: "tool" 回传 → 模型基于结果生成最终回答。

### 2. 定义第一个工具 query_data
先定义工具列表，描述这个工具能做什么、需要什么参数
```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "query_data",
            "description": "查询业务数据，支持按时间范围查询订单数量或订单列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "enum": ["order_count", "order_list"],
                        "description": "查询类型：order_count 返回订单数量，order_list 返回订单列表"
                    },
                    "date_range": {
                        "type": "string",
                        "description": "时间范围，格式如 '2025-01' 表示 2025 年 1 月"
                    }
                },
                "required": ["query_type", "date_range"]
            }
        }
    }
]
```
**两个设计要点：**  query_type 用 enum 限定模型只能选预设值，避免它“发明”一个不存在的查询类型；date_range 用 string 并给出格式示例，引导模型输出规范参数。description 写得越清楚，模型选择工具和填充参数就越准。

### 3. 跑通完整的工具调用循环
定义好工具后，调用 API 时要传入 tools 参数，并处理模型可能返回的 tool_calls。下面是完整的可运行代码：

```python
import os
import json
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

# tools 定义放在这里（上面那段）

def send_messages(messages):
    response = client.chat.completions.create(
        model="deepseek-flash",
        messages=messages,
        tools=tools,
        extra_body={"thinking": {"type": "disabled"}},
    )
    return response.choices[0].message

def mock_query_data(query_type, date_range):
    """用假数据模拟内部系统的查询返回，暂不接真实 API"""
    if query_type == "order_count":
        return {"count": 128, "range": date_range}
    return {
        "orders": [
            {"id": "ORD-001", "status": "待处理"},
            {"id": "ORD-002", "status": "已完成"},
        ],
        "range": date_range
    }

# ---- 主流程 ----
messages = [
    {"role": "user", "content": "帮我查一下 2025 年 1 月有多少订单？"}
]

# 第一轮：模型判断是否需要调用工具
message = send_messages(messages)

if message.tool_calls:
    tool_call = message.tool_calls[0]
    print(f"模型请求调用工具：{tool_call.function.name}")
    print(f"参数：{tool_call.function.arguments}")

    # 解析参数，执行你的真实函数
    args = json.loads(tool_call.function.arguments)
    result = mock_query_data(args["query_type"], args["date_range"])

    # 把模型的消息和工具结果依次加入对话历史
    messages.append(message)
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": json.dumps(result, ensure_ascii=False)
    })

    # 第二轮：模型看到工具结果，生成自然语言回答
    final_message = send_messages(messages)
    print(f"最终回答：{final_message.content}")
else:
    print(f"模型直接回答：{message.content}")
```
运行这个脚本，如果一切正常，你会在终端看到类似这样的输出：

```text
模型请求调用工具：query_data
参数：{"query_type": "order_count", "date_range": "2025-01"}
最终回答：2025年1月共有128笔订单。
```
**如果模型没有触发工具调用**，而是直接回答了“我无法查询”，通常是因为工具的 **description** 不够清晰，或者用户问法太模糊。可以试着把提问改得更明确：“请使用 query_data 工具查询 2025-01 的 order_count”，观察模型是否被“引导”去调用工具。理解 **description** 对模型决策的影响。

> 这个循环【模型请求 → 代码执行 → 结果回传 → 模型总结】是整个 Agent 系统的核心骨架，后续的页面跳转工具只是在这个骨架上再加一个 navigate_to_page 而已

### 4. 页面注册表

#### 关键设计：为什么不让模型直接生成 URL？
如果让模型自由生成 URL，它可能会编造出 /order/detail?id=abc 这种系统里根本不存在的地址，用户点进去就是 404。所以正确做法是：
- 维护一张页面注册表，把 page_id 映射到真实的相对路径
- 工具参数只允许模型选 page_id，用 enum 限定可选值
- URL 由代码根据注册表拼接生成

模型只负责“选哪个页面”，链接的安全性和正确性完全由后端控制

#### 定义页面注册表
在脚本里加一个 dict，模拟内部的页面映射关系：
```python
PAGE_REGISTRY = {
    "order_list": {
        "title": "订单列表",
        "path": "/orders?range={date_range}"
    },
    "user_profile": {
        "title": "个人中心",
        "path": "/profile"
    },
    "dashboard": {
        "title": "数据看板",
        "path": "/dashboard"
    }
}

BASE_URL = "http://localhost:3000"  # Demo 阶段用假域名即可
```
注意 `order_list` 的路径里带了 `{date_range}` 占位符，后面会根据模型传入的参数填充

### 5. 定义第二个工具 navigate_to_page
#### 追加 tools 列表
```python
{
    "type": "function",
    "function": {
        "name": "navigate_to_page",
        "description": "跳转到内部系统的指定业务页面，例如订单列表、个人中心、数据看板。只接受 page_id，不生成 URL。",
        "parameters": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "enum": ["order_list", "user_profile", "dashboard"],
                    "description": "页面标识：order_list=订单列表，user_profile=个人中心，dashboard=数据看板"
                },
                "date_range": {
                    "type": "string",
                    "description": "可选。跳转订单列表时可带时间范围，格式如 '2025-01'"
                }
            },
            "required": ["page_id"]
        }
    }
}
```
和 query_data 一样，page_id 用 enum 限定，模型不可能选出一个不存在的页面。

#### 添加页面跳转的执行函数
```python
def navigate_to_page(page_id, date_range=None):
    """根据 page_id 从注册表生成真实跳转链接"""
    page = PAGE_REGISTRY.get(page_id)
    if not page:
        return {"error": f"页面不存在：{page_id}"}

    path = page["path"]
    if "{date_range}" in path:
        path = path.format(date_range=date_range or "")

    return {
        "type": "navigation",
        "label": page["title"],
        "url": f"{BASE_URL}{path}"
    }
```

#### 改造 Agent 循环，支持多工具分发
把之前的 if message.tool_calls: 分支改成用字典分发，两个工具都能被执行：

```python
# 工具名 → 执行函数 的映射，方便扩展
TOOL_HANDLERS = {
    "query_data": lambda args: mock_query_data(args["query_type"], args["date_range"]),
    "navigate_to_page": lambda args: navigate_to_page(args["page_id"], args.get("date_range")),
}

# ... 前面的 messages 初始化保持不变 ...

message = send_messages(messages)

if message.tool_calls:
    messages.append(message)

    navigation = None  # 用于收集跳转卡片，最后单独返回给前端

    for tool_call in message.tool_calls:
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        print(f"模型请求调用工具：{name}，参数：{args}")

        handler = TOOL_HANDLERS.get(name)
        result = handler(args) if handler else {"error": f"未知工具：{name}"}

        # 如果工具返回的是跳转卡片，记录下来
        if isinstance(result, dict) and result.get("type") == "navigation":
            navigation = result

        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(result, ensure_ascii=False)
        })

    final_message = send_messages(messages)
    print(f"最终回答：{final_message.content}")
    if navigation:
        print(f"跳转卡片：{navigation['label']} → {navigation['url']}")
else:
    print(f"模型直接回答：{message.content}")
```
这段代码的关键是 TOOL_HANDLERS 字典：用工具名做 key 分发执行，比 if/elif 更好扩展，后面再加工具只需往字典里加一行。

#### 用三种问法测试模型的选择能力
模型能不能正确区分“查数据”和“跳页面”。依次试这三个问题：

##### 测试 1：只查数据
```text
帮我查一下 2025 年 1 月有多少订单？
预期：调用 query_data，回答包含 128。
```

##### 测试 2：只跳页面
```text
帮我打开个人中心页面
预期：调用 navigate_to_page，page_id 为 user_profile，返回跳转卡片 个人中心 → http://localhost:3000/profile。
```

##### 测试 3：先查再跳
```text
看一下 2025 年 1 月的订单数量，然后帮我跳转到订单列表页
预期：模型可能连续调用两个工具（query_data 查数量，navigate_to_page 跳转并带上 date_range=2025-01），最终回答同时包含数量和跳转卡片，URL 应该是 /orders?range=2025-01。
```

**如果测试 3 模型只调了一个工具或选错了，不用急着改代码**。先调整工具的 **description**：把 **navigate_to_page** 的描述改成“当用户明确要求打开、跳转、查看某个页面时使用”；把 **query_data** 的描述限定为“仅用于查询数据”，两个工具的边界越清晰，模型选得越准。

## 三、AI对话的聊天页面

### 1. 安装依赖
FastAPI 用来做后端服务，uvicorn 是它的运行服务器。比 Flask 更适合做这种带 JSON 接口的服务：
```bash
python3 -m pip install fastapi uvicorn
```
验证一下：
```bash
python3 -c "import fastapi, uvicorn; print('ok')"
```

### 2. 建一个项目目录
```bash
mkdir -p ./ai-demo && cd ./ai-demo
```
后续所有文件都放这里。

### 3. 后端：main.py
在 ./ai-demo 目录下新建 main.py，它就是前三步脚本的 Web 版，主要多了三个东西：会话历史管理、HTTP 接口、HTML 页面返回
#### 几个关键点：
- SESSIONS 字典：按 session_id 保存对话历史，这样多轮对话能保持上下文。Demo 阶段放内存，重启会清空，这是可接受的。
- for _ in range(5)：模型可能连续触发多个工具调用（比如先查数据再跳转），循环处理直到模型不再请求工具。设上限防止模型陷入死循环。
- navigation 单独收集：工具返回的跳转卡片，不通过模型转述（模型可能会改写 URL），而是直接作为结构化字段返回给前端。

### 4. 前端：index.html
前端只做三件事：发送用户消息 → 接收 JSON → 渲染消息气泡和跳转卡片。没有框架，纯原生 JS。

### 5. 启动并测试
在 `./ai-demo` 目录下运行：

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
看到 Uvicorn running on http://0.0.0.0:8000 就成功了。浏览器打开 http://localhost:8000。

### 6. 验证效果

#### 1. 数据查询
> 帮我查一下 2025 年 1 月有多少订单

预期：AI 回复“128 笔订单”。
#### 2. 页面跳转
> 打开个人中心

预期：AI 回复“已为你打开个人中心”，下方出现可点击卡片 → 个人中心。
#### 3. 先查再跳（关键测试）

> 看一下 2025 年 1 月的订单数，然后跳转到订单列表

预期：AI 回复里包含数量，同时出现卡片 → 订单列表，卡片链接带 ?range=2025-01。

点开卡片会是 404，这是正常的——BASE_URL 目前指向 http://localhost:3000，只是假地址接入真实内部系统时改成真实域名即可

---

## 四、前端渲染跳转卡片
> 把后端返回的 navigation 结构给前端，用两行 JS 渲染成可点击链接。

## 五、本地代理（模拟本地模型） 模拟“本地大模型”：启动一个 OpenAI 兼容代理
> 用 OpenAI 兼容代理把 base_url 换成 http://127.0.0.1:8787/v1，代码其余不变。

## 六、接入真实内部 API
> 把 mock_query_data 替换成真实 HTTP 调用，同时把用户身份从会话注入（而不是让模型传），这是从 Demo 走向 MVP 的关键一步。
> 把 mock_query_data 替换成对内部 API 的 HTTP 调用，并把从会话中提取的用户身份注入请求头，接上单元系统的鉴权。这一步是从 Demo 走向 MVP 的关键，建议在 Demo 演示通过后再做