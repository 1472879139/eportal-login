"""
配置文件管理

配置文件位置: %APPDATA%/dormnet_login/config.json

密码存储: 使用机器特征 (MAC 地址) 派生的密钥进行加密，非明文存储。
         更换硬件或复制配置文件到其他电脑会导致密码无法解密，需重新输入。
"""

import base64
import hashlib
import json
import os
import secrets
import uuid
from typing import Any, Optional

from .config import DEFAULT_CONFIG

# 用于密钥派生的固定盐值 (防止彩虹表攻击)
_KEY_SALT = b"dormnet_login_v1\x00\xff\xaa"


class ConfigManager:
    """用户配置文件读写"""

    def __init__(self):
        self._config_dir = os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")),
            "dormnet_login",
        )
        self._config_path = os.path.join(self._config_dir, "config.json")

    # ------------------------------------------------------------------
    # 密码加密 / 解密 (内部)
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_key(salt: bytes) -> bytes:
        """基于本机特征 + 随机盐派生 32 字节加密密钥"""
        machine_id = str(uuid.getnode()).encode()
        return hashlib.sha256(salt + machine_id + _KEY_SALT).digest()

    @classmethod
    def _encrypt_password(cls, plaintext: str) -> str:
        """加密密码，返回 base64 字符串"""
        salt = secrets.token_bytes(16)
        key = cls._derive_key(salt)
        plain_bytes = plaintext.encode("utf-8")

        # XOR 加密 (密钥循环使用)
        cipher_bytes = bytes(
            plain_bytes[i] ^ key[i % len(key)] for i in range(len(plain_bytes))
        )

        # 格式: salt(16) + ciphertext
        return base64.b64encode(salt + cipher_bytes).decode("ascii")

    @classmethod
    def _decrypt_password(cls, encrypted: str) -> Optional[str]:
        """解密密码，失败返回 None"""
        try:
            raw = base64.b64decode(encrypted)
            if len(raw) < 17:
                return None

            salt = raw[:16]
            cipher_bytes = raw[16:]
            key = cls._derive_key(salt)

            plain_bytes = bytes(
                cipher_bytes[i] ^ key[i % len(key)] for i in range(len(cipher_bytes))
            )
            return plain_bytes.decode("utf-8")
        except Exception:
            return None

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
        """加载登录凭据 (自动解密密码)"""
        config = self.load()
        password = ""

        # 优先读取加密密码
        encrypted = config.get("encrypted_password", "")
        if encrypted:
            decrypted = self._decrypt_password(encrypted)
            if decrypted is not None:
                password = decrypted
            # 解密失败时返回空密码，用户需重新输入
        else:
            # 向后兼容: 读取旧版明文密码并自动迁移
            password = config.get("password", "")

        return {
            "username": config.get("username", ""),
            "password": password,
            "device": config.get("device", "mobile"),
            "operator": config.get("operator", "telecom"),
            "remember_password": config.get("remember_password", True),
        }

    def save_credentials(
        self,
        username: str,
        password: str,
        device: str = "mobile",
        operator: str = "telecom",
        remember_password: bool = True,
    ) -> None:
        """保存登录凭据 (加密存储密码，可选是否记住密码)"""
        config = self.load()
        config["username"] = username
        if remember_password:
            config["encrypted_password"] = self._encrypt_password(password)
        else:
            config.pop("encrypted_password", None)  # 不记住密码时清除已保存密码
        config.pop("password", None)  # 移除旧版明文密码
        config["device"] = device
        config["operator"] = operator
        config["remember_password"] = remember_password
        self.save(config)

    def clear_credentials(self) -> None:
        """清除登录凭据 (保留其他设置)"""
        config = self.load()
        config.pop("username", None)
        config.pop("password", None)
        config.pop("encrypted_password", None)
        self.save(config)

    def load_network_params(self) -> Optional[dict]:
        """加载缓存的网络参数 (供跨会话注销使用)"""
        return self.get("cached_network_params")

    def save_network_params(self, params: dict) -> None:
        """保存网络参数到配置文件"""
        self.set("cached_network_params", params)

    def clear_network_params(self) -> None:
        """清除缓存的网络参数"""
        config = self.load()
        config.pop("cached_network_params", None)
        self.save(config)
