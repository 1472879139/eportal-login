"""
配置文件管理

配置文件位置: %APPDATA%/dormnet_login/config.json

注意: 密码以明文存储 (与 DormNet-GUI 的 DataStore 行为一致)。
      如需更安全的方式，可后续改为 keyring 加密存储。
"""

import json
import os
from typing import Any, Optional

from .config import DEFAULT_CONFIG


class ConfigManager:
    """用户配置文件读写"""

    def __init__(self):
        self._config_dir = os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")),
            "dormnet_login",
        )
        self._config_path = os.path.join(self._config_dir, "config.json")

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def load(self) -> dict:
        """
        加载配置文件，返回 dict。
        如果文件不存在则返回默认配置。
        """
        defaults = dict(DEFAULT_CONFIG)

        if not os.path.exists(self._config_path):
            return defaults

        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return defaults

        # 合并默认值 (确保新增字段有默认值)
        defaults.update(data)
        return defaults

    def save(self, config: dict) -> None:
        """保存配置文件"""
        os.makedirs(self._config_dir, exist_ok=True)

        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        """读取单个配置项"""
        config = self.load()
        return config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """设置单个配置项"""
        config = self.load()
        config[key] = value
        self.save(config)

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------

    def load_credentials(self) -> dict:
        """加载登录凭据"""
        config = self.load()
        return {
            "username": config.get("username", ""),
            "password": config.get("password", ""),
            "device": config.get("device", "mobile"),
            "operator": config.get("operator", "telecom"),
        }

    def save_credentials(
        self,
        username: str,
        password: str,
        device: str = "mobile",
        operator: str = "telecom",
    ) -> None:
        """保存登录凭据"""
        config = self.load()
        config["username"] = username
        config["password"] = password
        config["device"] = device
        config["operator"] = operator
        self.save(config)

    def clear_credentials(self) -> None:
        """清除登录凭据 (保留其他设置)"""
        config = self.load()
        config.pop("username", None)
        config.pop("password", None)
        self.save(config)
