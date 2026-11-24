import os
import json
from openai import OpenAI

# 初始化模型客户端
client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

# tools 定义在这里
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
    },
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
]

# 页面注册表
BASE_URL = "http://localhost:3000" 
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


# 调用大模型
def send_messages(messages):
    response = client.chat.completions.create(
        model="deepseek-flash",
        messages=messages,
        tools=tools,
        extra_body={"thinking": {"type": "disabled"}},
    )
    return response.choices[0].message

# 数据查询的执行函数
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

# 页面跳转的执行函数
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

# 工具名 → 执行函数 的映射，方便扩展
TOOL_HANDLERS = {
    "query_data": lambda args: mock_query_data(args["query_type"], args["date_range"]),
    "navigate_to_page": lambda args: navigate_to_page(args["page_id"], args.get("date_range")),
}

# ---- 主流程 ----
messages = [
    {"role": "user", "content": "看一下 2025 年 1 月的订单数量，然后帮我跳转到订单列表页"}
]

# 第一轮：模型判断是否需要调用工具
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
    
    # 第二轮：模型看到工具结果，生成自然语言回答
    final_message = send_messages(messages)
    print(f"最终回答：{final_message.content}")
    if navigation:
        print(f"跳转卡片：{navigation['label']} → {navigation['url']}")
else:
    print(f"模型直接回答：{message.content}")
