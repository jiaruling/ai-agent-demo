# ---------- 页面注册表 ----------
# 前端基础URL
BASE_URL_FRONT = "http://192.168.11.200:5187"

# 页面注册表，包含所有页面的定义
PAGE_REGISTRY = {
    "home": {"title": "首页", "path": "/home"},
    "operation_panel": {"title": "控制面板", "path": "/operationPanel"},
    "equipment_panel": {"title": "设备面板", "path": "/equipmentPanel"},
    "scheduler": {"title": "任务调度", "path": "/scheduler"},
    "iot_order_list": {"title": "IoT订单", "path": "/iot-order"},
    "order_list": {"title": "订单列表", "path": "/order"},
    "measure_data": {"title": "检测数据", "path": "/measure/data"},
    "quality_charts": {"title": "数据统计", "path": "/quality/charts"},
    "characteristic_display": {
        "title": "特征统计",
        "path": "/quality/characteristic-display",
    },
    "production_statistics": {
        "title": "生产统计",
        "path": "/quality/production-statistics",
    },
    "login_log": {"title": "登录日志", "path": "/audit/login-log"},
    "operation_log": {"title": "操作日志", "path": "/audit/operation-log"},
    "organization": {"title": "用户组织", "path": "/organization"},
    "role": {"title": "角色权限", "path": "/role"},
    "access_settings": {"title": "菜单接口", "path": "/settings/access"},
    "profile": {"title": "个人中心", "path": "/profile"},
    "login": {"title": "登录", "path": "/login"},
}

