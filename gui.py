"""
CQUPT 校园网登录工具 — tkinter 可视化界面

功能:
  - 账号/密码输入 (支持显示/隐藏密码)
  - 设备类型选择 (PC / Mobile)
  - 运营商选择 (电信 / 移动 / 联通)
  - 一键登录 / 注销
  - 登录状态实时显示
  - 开机自启开关
  - 断线自动重连
  - 配置自动保存
"""

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from .client import CquptClient, LoginError, NetworkParamsError
from .config_manager import ConfigManager
from .autostart import AutoStartManager
from .config import DEVICE_CONFIG, OPERATOR_MAP

# 设备类型显示标签列表 (顺序与 combo 一致)
DEVICE_LABELS = [cfg["label"] for cfg in DEVICE_CONFIG.values()]
DEVICE_KEYS = list(DEVICE_CONFIG.keys())

# 运营商显示标签列表
OPERATOR_LABELS = list(OPERATOR_MAP.values())
OPERATOR_KEYS = list(OPERATOR_MAP.keys())


class CquptLoginGUI:
    """CQUPT 校园网登录主窗口"""

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def __init__(self, silent: bool = False):
        self._silent = silent

        # 管理器
        self._config_mgr = ConfigManager()
        self._client = CquptClient()
        self._autostart = AutoStartManager()

        # 状态
        self._is_logged_in = False
        self._is_logging = False       # 正在登录/注销中，防止重复点击
        self._keep_alive_job: Optional[str] = None  # after() job ID

        # 加载配置
        self._config = self._config_mgr.load()

        # 创建窗口
        self._root = tk.Tk()
        self._root.title("CQUPT 校园网登录工具")
        self._root.resizable(True, True)
        self._root.minsize(420, 480)

        # 居中窗口
        self._center_window(420, 540)

        # 窗口关闭事件
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 消息 Label 引用 (用于动态设置颜色)
        self._message_label: Optional[ttk.Label] = None

        # 构建界面
        self._build_ui()

        # 填充已保存的配置
        self._load_saved_config()

        # 启动自动重连
        if self._config.get("keep_alive", True):
            self._start_keep_alive()

        # 如果 silent 模式，最小化到任务栏
        if silent:
            self._root.iconify()

    def run(self):
        """启动 GUI 主循环"""
        self._root.mainloop()

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------

    def _build_ui(self):
        """构建完整界面"""
        # 主框架
        main_frame = ttk.Frame(self._root, padding="16 12 16 12")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 标题
        title_label = ttk.Label(
            main_frame,
            text="🏫 CQUPT 校园网登录工具",
            font=("Microsoft YaHei UI", 14, "bold"),
        )
        title_label.pack(pady=(0, 12))

        # ---- 账号区域 ----
        account_frame = ttk.LabelFrame(main_frame, text="账号信息", padding="10 8 10 8")
        account_frame.pack(fill=tk.X, pady=(0, 8))

        # 账号
        lbl = ttk.Label(account_frame, text="账号:")
        lbl.grid(row=0, column=0, sticky=tk.W, pady=4)
        self._username_var = tk.StringVar()
        self._username_entry = ttk.Entry(
            account_frame, textvariable=self._username_var, width=30
        )
        self._username_entry.grid(row=0, column=1, sticky=tk.EW, pady=4, padx=(8, 0))

        # 密码
        lbl = ttk.Label(account_frame, text="密码:")
        lbl.grid(row=1, column=0, sticky=tk.W, pady=4)
        self._password_var = tk.StringVar()
        self._password_entry = ttk.Entry(
            account_frame, textvariable=self._password_var, show="●", width=30
        )
        self._password_entry.grid(row=1, column=1, sticky=tk.EW, pady=4, padx=(8, 0))

        # 显示/隐藏密码按钮
        self._show_password = tk.BooleanVar(value=False)
        self._eye_button = ttk.Button(
            account_frame,
            text="👁",
            width=3,
            command=self._toggle_password_visibility,
        )
        self._eye_button.grid(row=1, column=2, padx=(4, 0))

        # 设备类型
        lbl = ttk.Label(account_frame, text="设备:")
        lbl.grid(row=2, column=0, sticky=tk.W, pady=4)
        self._device_var = tk.StringVar()
        self._device_combo = ttk.Combobox(
            account_frame,
            textvariable=self._device_var,
            values=DEVICE_LABELS,
            state="readonly",
            width=27,
        )
        self._device_combo.grid(
            row=2, column=1, columnspan=2, sticky=tk.EW, pady=4, padx=(8, 0)
        )

        # 运营商
        lbl = ttk.Label(account_frame, text="运营商:")
        lbl.grid(row=3, column=0, sticky=tk.W, pady=4)
        self._operator_var = tk.StringVar()
        self._operator_combo = ttk.Combobox(
            account_frame,
            textvariable=self._operator_var,
            values=OPERATOR_LABELS,
            state="readonly",
            width=27,
        )
        self._operator_combo.grid(
            row=3, column=1, columnspan=2, sticky=tk.EW, pady=4, padx=(8, 0)
        )

        # 设置列权重
        account_frame.columnconfigure(1, weight=1)

        # ---- 状态区域 ----
        status_frame = ttk.LabelFrame(main_frame, text="状态", padding="10 8 10 8")
        status_frame.pack(fill=tk.X, pady=(0, 8))

        self._status_indicator = tk.Canvas(
            status_frame, width=14, height=14, highlightthickness=0
        )
        self._status_indicator.pack(side=tk.LEFT, padx=(0, 6))
        self._draw_status_dot("gray")

        self._status_text = tk.StringVar(value="未连接")
        ttk.Label(
            status_frame,
            textvariable=self._status_text,
            font=("Microsoft YaHei UI", 10),
        ).pack(side=tk.LEFT)

        # 消息区域
        self._message_var = tk.StringVar(value="就绪，请点击登录")
        self._message_label = ttk.Label(
            status_frame,
            textvariable=self._message_var,
            foreground="gray",
            wraplength=360,
        )
        self._message_label.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))

        # ---- 操作按钮 ----
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(0, 8))

        self._login_button = ttk.Button(
            button_frame,
            text="🔗 登录",
            command=self._on_login,
        )
        self._login_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        self._logout_button = ttk.Button(
            button_frame,
            text="❌ 注销",
            command=self._on_logout,
            state=tk.DISABLED,
        )
        self._logout_button.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(4, 0))

        # ---- 设置区域 ----
        settings_frame = ttk.LabelFrame(main_frame, text="设置", padding="10 8 10 8")
        settings_frame.pack(fill=tk.X, pady=(0, 8))

        # 开机自启
        self._auto_start_var = tk.BooleanVar()
        auto_start_cb = ttk.Checkbutton(
            settings_frame,
            text="开机自动启动",
            variable=self._auto_start_var,
            command=self._on_auto_start_toggle,
        )
        auto_start_cb.pack(anchor=tk.W, pady=(0, 4))

        # 断线重连
        self._keep_alive_var = tk.BooleanVar()
        keep_alive_frame = ttk.Frame(settings_frame)
        keep_alive_frame.pack(anchor=tk.W, fill=tk.X)

        keep_alive_cb = ttk.Checkbutton(
            keep_alive_frame,
            text="断线自动重连",
            variable=self._keep_alive_var,
            command=self._on_keep_alive_toggle,
        )
        keep_alive_cb.pack(side=tk.LEFT)

        ttk.Label(keep_alive_frame, text="间隔(秒):").pack(side=tk.LEFT, padx=(12, 4))
        self._interval_var = tk.StringVar(value="300")
        interval_entry = ttk.Entry(
            keep_alive_frame,
            textvariable=self._interval_var,
            width=6,
        )
        interval_entry.pack(side=tk.LEFT)

        # 保存设置按钮
        ttk.Button(
            settings_frame,
            text="💾 保存设置",
            command=self._on_save_settings,
        ).pack(anchor=tk.W, pady=(8, 0))

        # ---- 底部 ----
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X, pady=(8, 0))

        self._exit_button = ttk.Button(
            bottom_frame,
            text="🛑 退出程序",
            command=self._on_close,
        )
        self._exit_button.pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    # 配置加载/保存
    # ------------------------------------------------------------------

    def _load_saved_config(self):
        """将已保存的配置填充到界面"""
        creds = self._config_mgr.load_credentials()

        if creds.get("username"):
            self._username_var.set(creds["username"])
        if creds.get("password"):
            self._password_var.set(creds["password"])

        # 设备类型: key → label
        device_key = creds.get("device", "mobile")
        if device_key in DEVICE_CONFIG:
            self._device_var.set(DEVICE_CONFIG[device_key]["label"])

        # 运营商: key → label
        operator_key = creds.get("operator", "telecom")
        operator_label = OPERATOR_MAP.get(operator_key, "中国电信")
        self._operator_var.set(operator_label)

        self._auto_start_var.set(
            self._config.get("auto_start", False)
        )
        self._keep_alive_var.set(
            self._config.get("keep_alive", True)
        )
        self._interval_var.set(
            str(self._config.get("keep_alive_interval", 300))
        )

    def _collect_config(self) -> dict:
        """从界面收集当前配置"""
        # 设备类型: label → key
        device_label = self._device_var.get()
        device_key = "mobile"
        for key, cfg in DEVICE_CONFIG.items():
            if cfg["label"] == device_label:
                device_key = key
                break

        # 运营商: label → key
        operator_label = self._operator_var.get()
        operator_key = "telecom"
        for key, label in OPERATOR_MAP.items():
            if label == operator_label:
                operator_key = key
                break

        try:
            interval = int(self._interval_var.get())
        except ValueError:
            interval = 300

        return {
            "username": self._username_var.get().strip(),
            "password": self._password_var.get(),
            "device": device_key,
            "operator": operator_key,
            "auto_start": self._auto_start_var.get(),
            "keep_alive": self._keep_alive_var.get(),
            "keep_alive_interval": interval,
        }

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def _on_login(self):
        """点击登录按钮"""
        if self._is_logging:
            return

        username = self._username_var.get().strip()
        password = self._password_var.get()

        if not username:
            messagebox.showwarning("提示", "请输入校园网账号")
            return
        if not password:
            messagebox.showwarning("提示", "请输入密码")
            return

        config = self._collect_config()

        # 自动保存凭据
        self._config_mgr.save_credentials(
            username=username,
            password=password,
            device=config["device"],
            operator=config["operator"],
        )

        self._set_logging_state(True)
        self._set_message("正在登录...", "blue")
        self._draw_status_dot("orange")

        thread = threading.Thread(
            target=self._do_login,
            args=(username, password, config),
            daemon=True,
        )
        thread.start()

    def _do_login(self, username: str, password: str, config: dict):
        """在后台线程执行登录"""
        try:
            message = self._client.login(
                username=username,
                password=password,
                device=config["device"],
                operator=config["operator"],
            )
            self._root.after(0, self._on_login_success, message)
        except LoginError as e:
            self._root.after(0, self._on_login_failed, str(e))
        except Exception as e:
            self._root.after(0, self._on_login_failed, f"未知错误: {e}")

    def _on_login_success(self, message: str):
        """登录成功回调 (主线程)"""
        self._is_logged_in = True
        self._set_logging_state(False)
        self._draw_status_dot("green")
        self._status_text.set("● 已连接")
        self._set_message(f"✅ {message}", "green")

        self._login_button.configure(state=tk.DISABLED)
        self._logout_button.configure(state=tk.NORMAL)

    def _on_login_failed(self, error: str):
        """登录失败回调 (主线程)"""
        self._is_logged_in = False
        self._set_logging_state(False)
        self._draw_status_dot("red")
        self._status_text.set("○ 连接失败")
        self._set_message(f"❌ {error}", "red")

    def _on_logout(self):
        """点击注销按钮"""
        if self._is_logging:
            return

        username = self._username_var.get().strip()
        password = self._password_var.get()
        config = self._collect_config()

        self._set_logging_state(True)
        self._set_message("正在注销...", "blue")
        self._draw_status_dot("orange")

        thread = threading.Thread(
            target=self._do_logout,
            args=(username, password, config),
            daemon=True,
        )
        thread.start()

    def _do_logout(self, username: str, password: str, config: dict):
        """在后台线程执行注销"""
        try:
            message = self._client.logout(
                username=username,
                password=password,
                device=config["device"],
                operator=config["operator"],
            )
            self._root.after(0, self._on_logout_success, message)
        except LoginError as e:
            self._root.after(0, self._on_logout_failed, str(e))
        except Exception as e:
            self._root.after(0, self._on_logout_failed, f"未知错误: {e}")

    def _on_logout_success(self, message: str):
        """注销成功回调 (主线程)"""
        self._is_logged_in = False
        self._set_logging_state(False)
        self._draw_status_dot("gray")
        self._status_text.set("未连接")
        self._set_message(f"✅ {message}", "gray")

        self._login_button.configure(state=tk.NORMAL)
        self._logout_button.configure(state=tk.DISABLED)

    def _on_logout_failed(self, error: str):
        """注销失败回调 (主线程)"""
        self._set_logging_state(False)
        self._set_message(f"⚠ 注销失败: {error}", "orange")

    def _on_auto_start_toggle(self):
        """开机自启开关切换"""
        enabled = self._auto_start_var.get()
        success = self._autostart.set_enabled(enabled)
        if success:
            self._set_message(
                f"已{'启用' if enabled else '禁用'}开机自启",
                "gray",
            )
        else:
            self._auto_start_var.set(not enabled)  # 恢复原值
            messagebox.showerror("错误", "设置开机自启失败，请检查系统权限")

    def _on_keep_alive_toggle(self):
        """断线重连开关切换"""
        if self._keep_alive_var.get():
            self._start_keep_alive()
        else:
            self._stop_keep_alive()

    def _on_save_settings(self):
        """保存设置按钮"""
        config = self._collect_config()
        self._config_mgr.save(config)
        self._config = config
        self._set_message("💾 设置已保存", "gray")

        # 同步 keep-alive 状态
        if config["keep_alive"]:
            self._start_keep_alive()
        else:
            self._stop_keep_alive()

    def _on_close(self):
        """窗口关闭 / 退出程序"""
        if self._is_logged_in:
            result = messagebox.askyesnocancel(
                "退出确认",
                "当前处于登录状态。\n\n"
                "选择 [是] - 先注销再退出\n"
                "选择 [否] - 直接退出 (保持在线)\n"
                "选择 [取消] - 返回",
            )
            if result is None:
                return  # 取消
            if result is True:
                # 先注销再退出
                self._do_logout_sync()
        else:
            if not messagebox.askokcancel("退出确认", "确定要退出程序吗？"):
                return

        self._on_exit()

    def _on_exit(self):
        """清理并退出"""
        self._stop_keep_alive()
        self._root.destroy()

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _set_logging_state(self, logging: bool):
        """设置登录中状态，禁用/启用相关控件"""
        self._is_logging = logging
        state = tk.DISABLED if logging else tk.NORMAL
        combo_state = "disabled" if logging else "readonly"

        self._username_entry.configure(state=state)
        self._password_entry.configure(state=state)
        self._device_combo.configure(state=combo_state)
        self._operator_combo.configure(state=combo_state)

        if not self._is_logged_in:
            self._login_button.configure(state=state)
            self._logout_button.configure(state=tk.DISABLED)
        else:
            self._login_button.configure(state=tk.DISABLED)
            self._logout_button.configure(state=state)

    def _set_message(self, text: str, color: str = "gray"):
        """更新消息文本和颜色"""
        self._message_var.set(text)
        if self._message_label is not None:
            self._message_label.configure(foreground=color)

    def _draw_status_dot(self, color: str):
        """在 status canvas 上绘制状态圆点"""
        self._status_indicator.delete("all")
        self._status_indicator.create_oval(
            2, 2, 12, 12, fill=color, outline=""
        )

    def _toggle_password_visibility(self):
        """切换密码显示/隐藏"""
        if self._show_password.get():
            self._password_entry.configure(show="●")
            self._eye_button.configure(text="👁")
            self._show_password.set(False)
        else:
            self._password_entry.configure(show="")
            self._eye_button.configure(text="🔒")
            self._show_password.set(True)

    def _center_window(self, width: int, height: int):
        """将窗口居中显示"""
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        self._root.geometry(f"{width}x{height}+{x}+{y}")

    # ------------------------------------------------------------------
    # 断线重连
    # ------------------------------------------------------------------

    def _start_keep_alive(self):
        """启动断线重连定时器"""
        interval_ms = self._config.get("keep_alive_interval", 300) * 1000
        if self._keep_alive_job is not None:
            self._root.after_cancel(self._keep_alive_job)
        self._schedule_keep_alive(int(interval_ms))

    def _schedule_keep_alive(self, interval_ms: int):
        """调度下一次重连检查"""
        self._keep_alive_job = self._root.after(
            interval_ms, self._keep_alive_check
        )

    def _keep_alive_check(self):
        """断线重连检查 (在主线程调度)"""
        if not self._keep_alive_var.get():
            return

        if self._is_logged_in and not self._is_logging:
            thread = threading.Thread(
                target=self._do_keep_alive_check, daemon=True
            )
            thread.start()

        # 调度下一次检查
        interval_ms = self._config.get("keep_alive_interval", 300) * 1000
        self._schedule_keep_alive(int(interval_ms))

    def _do_keep_alive_check(self):
        """后台执行重连检查"""
        config = self._config_mgr.load_credentials()
        username = config.get("username")
        password = config.get("password")

        if not username or not password:
            return

        try:
            self._client.login(
                username=username,
                password=password,
                device=config["device"],
                operator=config["operator"],
            )
        except LoginError:
            pass  # 静默重试，下次定时器会自动再试

    def _stop_keep_alive(self):
        """停止断线重连定时器"""
        if self._keep_alive_job is not None:
            self._root.after_cancel(self._keep_alive_job)
            self._keep_alive_job = None

    def _do_logout_sync(self):
        """同步注销 (在关闭窗口时使用)"""
        config = self._config_mgr.load_credentials()
        username = config.get("username", "")
        password = config.get("password", "")

        if not username or not password:
            return

        try:
            self._client.logout(
                username=username,
                password=password,
                device=config.get("device", "mobile"),
                operator=config.get("operator", "telecom"),
            )
        except Exception:
            pass  # 退出时忽略注销错误
