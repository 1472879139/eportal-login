"""
CQUPT 校园网登录工具 — 程序入口

用法:
  python -m dormnet_login.main          # 普通启动 (显示窗口)
  python -m dormnet_login.main --silent # 静默启动 (最小化到任务栏, 用于开机自启)
"""

import sys

from .gui import CquptLoginGUI


def main():
    """程序主入口"""
    silent = "--silent" in sys.argv
    app = CquptLoginGUI(silent=silent)
    app.run()


if __name__ == "__main__":
    main()
