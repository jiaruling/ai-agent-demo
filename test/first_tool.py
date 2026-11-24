import os
import json
from openai import OpenAI

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
    }
]

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
    {"role": "user", "content": "帮我查一下登录日志信息？"}
]

# 第一轮：模型判断是否需要调用工具
message = send_messages(messages)

if message.tool_calls:
    tool_call = message.tool_calls[0]
    print(f"模型请求调用工具：{tool_call.function.name}")
    print(f"参数：{tool_call.function.arguments}")

    # 解析参数，执行真实函数
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
