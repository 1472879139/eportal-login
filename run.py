"""
CQUPT 校园网登录工具 — 打包入口

PyInstaller 打包用入口脚本，放在 dormnet_login 包同级目录。
"""

import sys
import os

# 确保包所在的目录在 sys.path 中
_package_dir = os.path.dirname(os.path.abspath(__file__))
if _package_dir not in sys.path:
    sys.path.insert(0, _package_dir)

from dormnet_login.main import main

if __name__ == "__main__":
    main()
