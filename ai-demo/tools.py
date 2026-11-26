# ---------- 工具定义 ----------
from page import PAGE_REGISTRY

# 后端基础URL
BASE_URL_BACKEND = "http://192.168.11.200:8889"

# 工具生成函数
def _tool(name, description, properties=None, required=None):
    parameters = {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
    }
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


_page = {"type": "integer", "description": "页码，默认 1", "default": 1}
_limit = {"type": "integer", "description": "每页数量，默认 10", "default": 10}
_page_size = {"type": "integer", "description": "每页数量，默认 20", "default": 20}
_keyword = {"type": "string", "description": "搜索关键词"}
_username = {"type": "string", "description": "用户名"}
_status = {"type": "string", "description": "状态筛选"}
_start_time = {"type": "string", "description": "开始时间，例如 2025-01-01"}
_end_time = {"type": "string", "description": "结束时间，例如 2025-01-31"}
_department_id = {"type": "integer", "description": "部门 ID"}
_role_id = {"type": "integer", "description": "角色 ID"}

# 工具列表，包含所有工具的定义
TOOLS = [
    _tool(
        "login",
        "使用账号密码登录。POST /api/v1/login。",
        {
            "username": _username,
            "password": {"type": "string", "description": "登录密码"},
        },
        ["username", "password"],
    ),
    _tool("logout", "退出当前登录。需要登录。POST /api/v1/logout。"),
    _tool("health", "检查服务健康状态。GET /api/v1/health。"),
    _tool("get_config", "获取系统配置信息。GET /api/v1/config。"),
    _tool(
        "list_api_resources",
        "查询接口资源列表。需要超级管理员权限。GET /api/v1/api-resources。",
    ),
    _tool(
        "get_api_resource",
        "查询接口资源详情。需要超级管理员权限。GET /api/v1/api-resources/:apiResourceID。",
        {"apiResourceID": {"type": "integer", "description": "接口资源 ID"}},
        ["apiResourceID"],
    ),
    _tool(
        "list_login_logs",
        "分页查询登录日志。GET /api/v1/login/logs。",
        {
            "page": _page,
            "limit": _limit,
            "username": _username,
            "status": _status,
            "startTime": _start_time,
            "endTime": _end_time,
        },
    ),
    _tool(
        "list_operation_logs",
        "分页查询操作日志。GET /api/v1/operation/logs。",
        {
            "page": _page,
            "limit": _limit,
            "username": _username,
            "module": {"type": "string", "description": "操作模块"},
            "action": {"type": "string", "description": "操作动作"},
            "status": _status,
            "startTime": _start_time,
            "endTime": _end_time,
        },
    ),
    _tool(
        "list_departments",
        "分页查询部门。GET /api/v1/depts。",
        {"page": _page, "limit": _limit, "keyword": _keyword},
    ),
    _tool("get_department_tree", "查询部门树。GET /api/v1/depts/tree。"),
    _tool(
        "list_department_users",
        "分页查询部门下的用户。GET /api/v1/depts/:departmentID/users。",
        {"departmentID": _department_id, "page": _page, "limit": _limit},
        ["departmentID"],
    ),
    _tool(
        "get_department",
        "查询部门详情。GET /api/v1/depts/:departmentID。",
        {"departmentID": _department_id},
        ["departmentID"],
    ),
    _tool("list_devices", "查询设备列表。GET /api/v1/devices。"),
    _tool(
        "get_device",
        "根据设备 ID 查询设备详情。GET /api/v1/devices/:deviceID。",
        {"deviceID": {"type": "string", "description": "设备 ID"}},
        ["deviceID"],
    ),
    _tool("get_accessible_menu_tree", "查询当前用户可访问的菜单树。GET /api/v1/menus/tree。"),
    _tool("get_current_access", "查询当前用户权限与菜单。GET /api/v1/me/access。"),
    _tool(
        "list_menus",
        "分页查询菜单配置。需要超级管理员权限。GET /api/v1/menus。",
        {
            "page": _page,
            "limit": _limit,
            "keyword": _keyword,
            "isMenu": {"type": "boolean", "description": "是否为菜单"},
        },
    ),
    _tool(
        "get_menu",
        "查询菜单配置详情。需要超级管理员权限。GET /api/v1/menus/:menuID。",
        {"menuID": {"type": "integer", "description": "菜单 ID"}},
        ["menuID"],
    ),
    _tool("list_models", "查询模型列表。GET /api/v1/models。"),
    _tool(
        "get_model",
        "根据模型 ID 查询模型详情。GET /api/v1/models/:modelID。",
        {"modelID": {"type": "string", "description": "模型 ID"}},
        ["modelID"],
    ),
    _tool(
        "list_roles",
        "分页查询角色。GET /api/v1/roles。",
        {
            "page": _page,
            "limit": _limit,
            "name": {"type": "string", "description": "角色名称"},
        },
    ),
    _tool("get_role_list", "查询角色列表。GET /api/v1/roles/list。"),
    _tool(
        "get_role",
        "查询角色详情。GET /api/v1/roles/:roleID。",
        {"roleID": _role_id},
        ["roleID"],
    ),
    _tool(
        "list_role_users",
        "分页查询角色下的用户。GET /api/v1/roles/:roleID/users。",
        {"roleID": _role_id, "page": _page, "limit": _limit},
        ["roleID"],
    ),
    _tool(
        "get_role_permission_ids",
        "查询角色拥有的权限 ID。GET /api/v1/roles/:roleID/permissions/ids。",
        {"roleID": _role_id},
        ["roleID"],
    ),
    _tool(
        "list_scheduler_tasks",
        "分页查询调度任务档案。需要超级管理员权限。GET /api/v1/scheduler/tasks。",
        {"page": _page, "pageSize": _page_size, "status": _status},
    ),
    _tool(
        "get_scheduler_task",
        "查询调度任务详情。需要超级管理员权限。GET /api/v1/scheduler/tasks/:taskID。",
        {"taskID": {"type": "integer", "description": "任务 ID"}},
        ["taskID"],
    ),
    _tool(
        "get_scheduler_state",
        "查询调度器运行状态。需要超级管理员权限。GET /api/v1/scheduler。",
    ),
    _tool(
        "list_signals",
        "分页查询和筛选信号。需要超级管理员权限。GET /api/v1/signals。",
        {
            "page": _page,
            "pageSize": _page_size,
            "name": {"type": "string", "description": "信号名称"},
            "address": {"type": "string", "description": "信号地址"},
            "isStatus": {"type": "integer", "description": "状态信号筛选，默认 -1", "default": -1},
            "sender": {"type": "integer", "description": "发送方筛选，默认 0", "default": 0},
        },
    ),
    _tool(
        "get_signal",
        "查询信号详情。需要超级管理员权限。GET /api/v1/signals/:signalID。",
        {"signalID": {"type": "integer", "description": "信号 ID"}},
        ["signalID"],
    ),
    _tool("get_system_runtime", "获取服务运行时间。GET /api/v1/system/runtime。"),
    _tool("get_system_status", "查询系统运行状态。GET /api/v1/system/status。"),
    _tool(
        "list_users",
        "分页查询用户。GET /api/v1/users。",
        {
            "page": _page,
            "limit": _limit,
            "keyword": _keyword,
            "state": {"type": "integer", "description": "用户状态"},
            "departmentId": _department_id,
            "includeSubdepartments": {"type": "boolean", "description": "是否包含子部门"},
        },
    ),
    _tool(
        "get_user",
        "查询用户详情。GET /api/v1/users/:userID。",
        {"userID": {"type": "integer", "description": "用户 ID"}},
        ["userID"],
    ),
    _tool(
        "navigate_to_page",
        "跳转到内部系统指定页面。只在用户明确要求打开、跳转、进入某个页面时使用。",
        {
            "page_id": {
                "type": "string",
                "enum": list(PAGE_REGISTRY),
                "description": "页面标识：" + "，".join(
                    f"{page_id}={page['title']}"
                    for page_id, page in PAGE_REGISTRY.items()
                ),
            },
        },
        ["page_id"],
    ),
]

# 工具 API 路由映射，方便根据工具名称获取对应的 HTTP 方法和路径
TOOL_API_ROUTES = {
    "login": ("POST", "/api/v1/login"),
    "logout": ("POST", "/api/v1/logout"),
    "health": ("GET", "/api/v1/health"),
    "get_config": ("GET", "/api/v1/config"),
    "list_api_resources": ("GET", "/api/v1/api-resources"),
    "get_api_resource": ("GET", "/api/v1/api-resources/:apiResourceID"),
    "list_login_logs": ("GET", "/api/v1/login/logs"),
    "list_operation_logs": ("GET", "/api/v1/operation/logs"),
    "list_departments": ("GET", "/api/v1/depts"),
    "get_department_tree": ("GET", "/api/v1/depts/tree"),
    "list_department_users": ("GET", "/api/v1/depts/:departmentID/users"),
    "get_department": ("GET", "/api/v1/depts/:departmentID"),
    "list_devices": ("GET", "/api/v1/devices"),
    "get_device": ("GET", "/api/v1/devices/:deviceID"),
    "get_accessible_menu_tree": ("GET", "/api/v1/menus/tree"),
    "get_current_access": ("GET", "/api/v1/me/access"),
    "list_menus": ("GET", "/api/v1/menus"),
    "get_menu": ("GET", "/api/v1/menus/:menuID"),
    "list_models": ("GET", "/api/v1/models"),
    "get_model": ("GET", "/api/v1/models/:modelID"),
    "list_roles": ("GET", "/api/v1/roles"),
    "get_role_list": ("GET", "/api/v1/roles/list"),
    "get_role": ("GET", "/api/v1/roles/:roleID"),
    "list_role_users": ("GET", "/api/v1/roles/:roleID/users"),
    "get_role_permission_ids": ("GET", "/api/v1/roles/:roleID/permissions/ids"),
    "list_scheduler_tasks": ("GET", "/api/v1/scheduler/tasks"),
    "get_scheduler_task": ("GET", "/api/v1/scheduler/tasks/:taskID"),
    "get_scheduler_state": ("GET", "/api/v1/scheduler"),
    "list_signals": ("GET", "/api/v1/signals"),
    "get_signal": ("GET", "/api/v1/signals/:signalID"),
    "get_system_runtime": ("GET", "/api/v1/system/runtime"),
    "get_system_status": ("GET", "/api/v1/system/status"),
    "list_users": ("GET", "/api/v1/users"),
    "get_user": ("GET", "/api/v1/users/:userID"),
}