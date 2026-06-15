"""
CQUPT 校园网登录常量定义

设备参数来自 DormNet-GUI 项目 CQUPT 适配实现:
  dormnet-targets/src/commonMain/kotlin/.../targets/CQUPT.kt
"""

# 探测地址 - 访问这些外部 HTTP URL 触发校园网强制门户重定向
# 校园网会拦截外部 HTTP 请求，302 重定向到认证页面
# 我们从重定向 URL 中提取 wlanuserip, mac 等网络参数
PROBE_URLS = [
    "http://www.baidu.com/",
    "http://httpbin.org/",
    "http://detectportal.firefox.com/success.txt",
    "http://www.msftconnecttest.com/redirect",
]

# 登录认证服务器地址
LOGIN_URL = "http://192.168.200.2:801/eportal/"

# 设备类型配置
# 通过伪装为手机端，可绕过校园网 "一账号一设备" 限制
# 实现两台电脑共享一个账号上网
DEVICE_CONFIG = {
    "pc": {
        "callback": "dr1003",
        "account_prefix": "0",
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0"
        ),
        "label": "PC (电脑端)",
    },
    "mobile": {
        "callback": "dr1005",
        "account_prefix": "1",
        "user_agent": (
            "Mozilla/5.0 (Linux; Android 10; K) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/141.0.0.0 Mobile Safari/537.36 EdgA/141.0.0.0"
        ),
        "label": "Mobile (手机端)",
    },
}

# 运营商选项
# CQUPT 认证时需要选择运营商
OPERATOR_MAP = {
    "telecom": "中国电信",
    "cmcc": "中国移动",
    "unicom": "中国联通",
}

# HTTP 请求超时 (秒)
REQUEST_TIMEOUT = 10

# 默认配置
DEFAULT_CONFIG = {
    "device": "mobile",
    "operator": "telecom",
    "auto_start": False,
    "keep_alive": True,
    "keep_alive_interval": 300,  # 断线重连间隔 (秒), 默认 5 分钟
}
