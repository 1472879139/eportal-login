"""
CQUPT 校园网登录/注销 HTTP 客户端

基于 DormNet-GUI 项目 CQUPT 适配实现的 Python 移植:
  dormnet-targets/src/commonMain/kotlin/.../targets/CQUPT.kt

登录流程:
  1. GET 网关地址 (http://192.168.198.1)，禁止重定向
  2. 从 302 Location 头解析 wlanuserip, wlanacname, wlanacip, mac
  3. 携带网络参数 + 用户凭据 向认证服务器发起 GET 请求
  4. 解析 JSONP 响应，检查 result == "1"
"""

import json
import urllib.request
import urllib.error
import urllib.parse
from http.client import HTTPResponse
from typing import Optional

from .config import (
    PROBE_URLS,
    LOGIN_URL,
    DEVICE_CONFIG,
    OPERATOR_MAP,
    REQUEST_TIMEOUT,
)


class LoginError(Exception):
    """登录/注销过程中的错误"""
    pass


class NetworkParamsError(LoginError):
    """获取网络参数失败 (可能未连接校园网)"""
    pass


class CquptClient:
    """CQUPT 校园网认证客户端"""

    def __init__(self, timeout: int = REQUEST_TIMEOUT):
        self._timeout = timeout
        self._cached_params: Optional[dict] = None  # 缓存网络参数供注销复用

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def get_network_params(self) -> dict:
        """
        第一步: 通过访问外部 HTTP 地址触发校园网强制门户重定向

        校园网会在未认证时拦截外部 HTTP 请求，302 重定向到认证页面。
        从重定向 URL 中提取 wlanuserip, wlanacname, wlanacip, mac 等参数。

        返回: {"wlanuserip": ..., "wlanacname": ..., "wlanacip": ..., "mac": ...}

        抛出 NetworkParamsError: 如果无法获取参数
        """
        last_error = None

        for probe_url in PROBE_URLS:
            try:
                return self._try_get_params(probe_url)
            except NetworkParamsError as e:
                last_error = e
                continue

        if last_error:
            raise last_error
        raise NetworkParamsError(
            "无法获取网络参数: 所有探测地址均未触发重定向，"
            "请确认已连接 CQUPT 校园网 (WiFi 或有线)"
        )

    def _try_get_params(self, probe_url: str) -> dict:
        """尝试访问探测 URL，拦截强制门户重定向"""
        req = urllib.request.Request(probe_url, method="GET")

        opener = urllib.request.build_opener(_NoRedirectHandler)

        try:
            opener.open(req, timeout=self._timeout)
            raise NetworkParamsError(
                f"探测 {probe_url} 未触发重定向，"
                "可能已处于认证状态或不在校园网环境"
            )

        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                location = e.headers.get("Location", "")
                if location:
                    return self._parse_location(location)

            raise NetworkParamsError(
                f"探测 {probe_url} 返回 HTTP {e.code}"
            )

        except urllib.error.URLError as e:
            raise NetworkParamsError(
                f"无法连接探测地址 ({probe_url}): {e.reason}"
            )

    def login(
        self,
        username: str,
        password: str,
        device: str = "mobile",
        operator: str = "telecom",
    ) -> str:
        """
        第二步: 执行校园网认证登录

        参数:
            username: 校园网账号
            password: 校园网密码
            device:   设备类型 ("pc" 或 "mobile")
            operator: 运营商 ("telecom" / "cmcc" / "unicom")

        返回: 登录成功时的服务器消息

        抛出 LoginError: 登录失败时
        """
        if device not in DEVICE_CONFIG:
            raise LoginError(f"不支持的设备类型: {device}")

        if operator not in OPERATOR_MAP:
            raise LoginError(f"不支持的运营商: {operator}")

        # 第一步: 获取网络参数并缓存 (供注销时复用)
        net_params = self.get_network_params()
        self._cached_params = net_params

        # 第二步: 构造登录请求
        dev = DEVICE_CONFIG[device]

        # 构造 user_account: ,{prefix},{username}@{operator}
        user_account = f",{dev['account_prefix']},{username}@{operator}"

        params = {
            "c": "Portal",
            "a": "login",
            "callback": dev["callback"],
            "login_method": "1",
            "user_account": user_account,
            "user_password": password,
            "wlan_user_ip": net_params["wlanuserip"],
            "wlan_user_ipv6": "",
            "wlan_user_mac": net_params["mac"],
            "wlan_ac_ip": "",
            "wlan_ac_name": "",
            "jsVersion": "3.3.3",
        }

        headers = {
            "User-Agent": dev["user_agent"],
            "Referer": "http://192.168.200.2/",
            "DNT": "1",
        }

        return self._do_request(
            url=LOGIN_URL,
            params=params,
            headers=headers,
            operation="登录",
        )

    def logout(
        self,
        username: str,
        password: str,
        device: str = "mobile",
        operator: str = "telecom",
    ) -> str:
        """
        注销校园网认证

        参数同 login()
        返回: 注销成功时的服务器消息
        """
        if device not in DEVICE_CONFIG:
            raise LoginError(f"不支持的设备类型: {device}")

        if operator not in OPERATOR_MAP:
            raise LoginError(f"不支持的运营商: {operator}")

        # 优先使用登录时缓存的参数 (在线状态下无法触发重定向)
        net_params = self._cached_params or self.get_network_params()
        dev = DEVICE_CONFIG[device]

        user_account = f",{dev['account_prefix']},{username}@{operator}"

        params = {
            "c": "Portal",
            "a": "logout",
            "callback": dev["callback"],
            "login_method": "1",
            "user_account": user_account,
            "user_password": password,
            "wlan_user_ip": net_params["wlanuserip"],
            "wlan_user_ipv6": "",
            "wlan_user_mac": net_params["mac"],
            "wlan_ac_ip": "",
            "wlan_ac_name": "",
            "jsVersion": "3.3.3",
        }

        headers = {
            "User-Agent": dev["user_agent"],
            "Referer": "http://192.168.200.2/",
            "DNT": "1",
        }

        return self._do_request(
            url=LOGIN_URL,
            params=params,
            headers=headers,
            operation="注销",
        )

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _parse_location(self, location: str) -> dict:
        """从网关重定向 URL 中解析网络参数"""
        # location 格式: http://...?wlanuserip=xxx&wlanacname=yyy&...
        if "?" in location:
            query = location.split("?", 1)[1]
        else:
            query = location

        parsed = urllib.parse.parse_qs(query)

        params = {
            "wlanuserip": parsed.get("wlanuserip", [""])[0],
            "wlanacname": parsed.get("wlanacname", [""])[0],
            "wlanacip": parsed.get("wlanacip", [""])[0],
            "mac": parsed.get("mac", [""])[0],
        }

        missing = [k for k, v in params.items() if not v]
        if missing:
            raise NetworkParamsError(
                f"网关重定向参数不完整，缺少: {', '.join(missing)}"
            )

        return params

    def _do_request(
        self,
        url: str,
        params: dict,
        headers: dict,
        operation: str,
    ) -> str:
        """
        发送认证请求并解析 JSONP 响应
        响应格式: callback({"result":"1","msg":"..."})
        """
        query_string = urllib.parse.urlencode(params)
        full_url = f"{url}?{query_string}"

        req = urllib.request.Request(full_url, method="GET")
        for key, value in headers.items():
            req.add_header(key, value)

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as e:
            raise LoginError(f"{operation}失败: 无法连接认证服务器 - {e.reason}")
        except Exception as e:
            raise LoginError(f"{operation}失败: {e}")

        return self._parse_response(body, operation)

    def _parse_response(self, body: str, operation: str) -> str:
        """解析 JSONP 响应，返回服务器消息"""
        if not body or len(body) <= 2:
            raise LoginError(f"{operation}失败: 服务器返回空响应")

        # JSONP 格式: dr1003({...}) 或 dr1005({...})
        try:
            json_str = body
            if "(" in body and ")" in body:
                json_str = body[body.index("(") + 1: body.rindex(")")]

            data = json.loads(json_str)
        except (json.JSONDecodeError, ValueError) as e:
            raise LoginError(
                f"{operation}失败: 无法解析服务器响应\n响应内容: {body[:200]}"
            )

        result = data.get("result", "")
        message = data.get("msg", "")

        if result != "1":
            raise LoginError(
                f"{operation}失败: {message or '未知错误'}"
            )

        return message or f"{operation}成功"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """禁止自动重定向的 HTTP handler

    redirect_request 返回 None 时，urllib 会抛出 HTTPError。
    我们在 get_network_params() 中捕获 HTTPError，
    从 e.headers 提取 Location 头来获取网络参数。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
