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


class PopupNotification:
    """居中弹窗通知 — 带"确定"按钮，用户手动关闭

    用法:
        PopupNotification.show(parent, "标题", "消息内容", "success")
        类型: "success" | "error" | "warning" | "info"
    """

    # (标题栏背景, 消息区背景, 前景色, 图标)
    _STYLES = {
        "success": ("#e8f5e9", "#c8e6c9", "#2e7d32", "✅"),
        "error":   ("#fce4ec", "#ffcdd2", "#c62828", "❌"),
        "warning": ("#fff3e0", "#ffe0b2", "#e65100", "⚠"),
        "info":    ("#e3f2fd", "#bbdefb", "#1565c0", "ℹ"),
    }

    @classmethod
    def show(cls, parent: tk.Tk, title: str, message: str, popup_type: str = "info") -> None:
        """显示居中弹窗，阻塞父窗口直到用户点击确定"""
        bg_title, bg_msg, fg, icon = cls._STYLES.get(
            popup_type, cls._STYLES["info"]
        )

        dlg = tk.Toplevel(parent)
        dlg.title(title)
        dlg.resizable(False, False)
        dlg.transient(parent)         # 从属于父窗口
        dlg.grab_set()                # 模态: 阻止操作父窗口

        # 内容区域
        frame = tk.Frame(dlg, bg=bg_msg, padx=20, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)

        # 图标 + 消息
        inner = tk.Frame(frame, bg=bg_msg)
        inner.pack()

        tk.Label(
            inner, text=icon, bg=bg_msg,
            font=("Microsoft YaHei UI", 18),
        ).pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(
            inner, text=message, bg=bg_msg, fg=fg,
            font=("Microsoft YaHei UI", 10),
            wraplength=360, justify=tk.LEFT,
        ).pack(side=tk.LEFT)

        # 确定按钮
        btn_frame = tk.Frame(frame, bg=bg_msg)
        btn_frame.pack(pady=(12, 0))

        btn = tk.Button(
            btn_frame, text="确定", width=12,
            command=dlg.destroy,
            bg=bg_title, fg=fg, activebackground=bg_title,
            font=("Microsoft YaHei UI", 9),
            relief="raised", bd=1,
        )
        btn.pack()
        btn.focus_set()

        # 绑定 Enter 键关闭
        dlg.bind("<Return>", lambda e: dlg.destroy())

        # 居中于父窗口
        dlg.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        dw = dlg.winfo_reqwidth()
        dh = dlg.winfo_reqheight()
        x = px + (pw - dw) // 2
        y = py + (ph - dh) // 2
        dlg.geometry(f"+{x}+{y}")

        # 等待弹窗关闭
        dlg.wait_window()


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
        self._startup_auth_checked = False  # 启动认证检测是否完成
        self._auto_login_tried = False     # 自动登录是否已尝试（避免反复重试）
        self._actually_disconnected = False  # GUI 认为已登录但实际已断开（浏览器注销等）

        # 加载配置
        self._config = self._config_mgr.load()

        # 创建窗口
        self._root = tk.Tk()
        self._root.title("CQUPT 校园网登录工具")
        self._root.resizable(True, True)
        self._root.minsize(460, 500)

        # 居中窗口（默认打开尺寸）
        self._center_window(460, 570)

        # 窗口关闭事件
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 消息 Label 引用 (用于动态设置颜色)
        self._message_label: Optional[ttk.Label] = None

        # 构建界面
        self._build_ui()

        # 填充已保存的配置
        self._load_saved_config()

        # 每次启动时刷新自启 VBS 脚本，确保路径指向当前 exe
        if self._config.get("auto_start", False):
            self._autostart.enable()

        # 启动自动重连
        if self._config.get("keep_alive", True):
            self._start_keep_alive()

        # 如果 silent 模式，最小化到任务栏
        if silent:
            self._root.iconify()

        # 启动时检测认证状态 (后台线程，避免阻塞 UI)
        thread = threading.Thread(target=self._detect_auth_status, daemon=True)
        thread.start()

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

        # 记住密码
        self._remember_password_var = tk.BooleanVar(value=True)
        self._remember_password_cb = ttk.Checkbutton(
            account_frame,
            text="记住密码",
            variable=self._remember_password_var,
        )
        self._remember_password_cb.grid(row=2, column=1, columnspan=2, sticky=tk.W, pady=2, padx=(8, 0))

        # 设备类型
        lbl = ttk.Label(account_frame, text="设备:")
        lbl.grid(row=3, column=0, sticky=tk.W, pady=4)
        self._device_var = tk.StringVar()
        self._device_combo = ttk.Combobox(
            account_frame,
            textvariable=self._device_var,
            values=DEVICE_LABELS,
            state="readonly",
            width=27,
        )
        self._device_combo.grid(
            row=3, column=1, columnspan=2, sticky=tk.EW, pady=4, padx=(8, 0)
        )

        # 运营商
        lbl = ttk.Label(account_frame, text="运营商:")
        lbl.grid(row=4, column=0, sticky=tk.W, pady=4)
        self._operator_var = tk.StringVar()
        self._operator_combo = ttk.Combobox(
            account_frame,
            textvariable=self._operator_var,
            values=OPERATOR_LABELS,
            state="readonly",
            width=27,
        )
        self._operator_combo.grid(
            row=4, column=1, columnspan=2, sticky=tk.EW, pady=4, padx=(8, 0)
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

        # 刷新按钮
        self._refresh_button = ttk.Button(
            status_frame,
            text="刷新",
            width=5,
            command=self._on_refresh,
        )
        self._refresh_button.pack(side=tk.RIGHT, padx=(4, 0))

        # 消息区域
        self._message_var = tk.StringVar(value="就绪，请点击登录")
        self._message_label = ttk.Label(
            status_frame,
            textvariable=self._message_var,
            foreground="gray",
        )
        self._message_label.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))
        # 消息文字自适应窗口宽度
        self._message_label.bind("<Configure>", lambda e: self._message_label.configure(
            wraplength=self._message_label.winfo_width() - 4))

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
        auto_start_cb.pack(anchor=tk.W, pady=(0, 2))

        # 自动登录
        self._auto_login_var = tk.BooleanVar()
        auto_login_cb = ttk.Checkbutton(
            settings_frame,
            text="自动登录",
            variable=self._auto_login_var,
        )
        auto_login_cb.pack(anchor=tk.W, pady=(0, 4))

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

        # 记住密码复选框状态 (默认 True，兼容旧配置)
        remember = creds.get("remember_password", True)
        self._remember_password_var.set(remember)

        # 仅当用户勾选记住密码时才填充密码
        if remember and creds.get("password"):
            self._password_var.set(creds["password"])
        # 否则密码框保持为空

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
        self._auto_login_var.set(
            self._config.get("auto_login", False)
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
            "remember_password": self._remember_password_var.get(),
            "auto_login": self._auto_login_var.get(),
        }

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def _detect_auth_status(self):
        """后台线程: 检测启动时的认证状态"""
        try:
            status = self._client.check_auth_status()
        except Exception:
            status = "offline"
        self._root.after(0, self._on_startup_auth_detected, status)

    def _on_startup_auth_detected(self, status: str):
        """主线程回调: 处理启动时认证状态检测结果"""
        self._startup_auth_checked = True

        if status == "authenticated":
            self._is_logged_in = True
            self._draw_status_dot("green")
            self._status_text.set("● 已连接")
            self._login_button.configure(state=tk.DISABLED)

            # 已登录时禁用账号字段，注销后才能编辑
            self._username_entry.configure(state=tk.DISABLED)
            self._password_entry.configure(state=tk.DISABLED)
            self._device_combo.configure(state="disabled")
            self._operator_combo.configure(state="disabled")
            self._remember_password_cb.configure(state=tk.DISABLED)

            # 尝试恢复缓存的网络参数，使注销按钮可用
            params = self._config_mgr.load_network_params()
            if not params:
                # 无缓存时用本机 IP/MAC 构造兜底参数（注销只需要这两个值）
                params = self._client.build_local_network_params()
            self._client.set_cached_params(params)
            self._logout_button.configure(state=tk.NORMAL)
            self._set_message("检测到已认证状态，可直接注销", "green")

        elif status == "not_authenticated":
            self._is_logged_in = False
            self._draw_status_dot("gray")
            self._status_text.set("未认证")
            self._login_button.configure(state=tk.NORMAL)
            self._logout_button.configure(state=tk.DISABLED)

            # 自动登录
            if self._try_auto_login():
                return
            self._set_message("未登录认证，请点击登录", "gray")

        else:  # offline
            self._is_logged_in = False
            self._draw_status_dot("red")
            self._status_text.set("○ 未连接")
            self._login_button.configure(state=tk.NORMAL)
            self._logout_button.configure(state=tk.DISABLED)
            self._set_message("未检测到校园网连接", "red")

    def _on_refresh(self):
        """手动刷新状态按钮回调"""
        if self._is_logging:
            return
        if not self._startup_auth_checked:
            return

        self._refresh_button.configure(state=tk.DISABLED, text="...")
        self._set_message("正在刷新状态...", "blue")
        thread = threading.Thread(target=self._do_refresh_check, daemon=True)
        thread.start()

    def _do_refresh_check(self):
        """后台执行手动刷新检测"""
        try:
            status = self._client.check_auth_status()
        except Exception:
            status = "offline"
        self._root.after(0, self._on_refresh_done, status)

    def _on_refresh_done(self, status: str):
        """刷新完成回调 — 更新 UI 状态但不触发自动重连"""
        self._refresh_button.configure(state=tk.NORMAL, text="刷新")
        self._on_status_update(status, allow_reconnect=False)

    def _on_login(self):
        """点击登录按钮"""
        if self._is_logging:
            return

        # 启动检测未完成时阻止操作
        if not self._startup_auth_checked:
            self._set_message("正在检测网络状态，请稍候...", "blue")
            return

        # 拦截重复登录
        if self._is_logged_in:
            self._show_popup(
                "提示",
                "已处于认证状态，无需重复登录。\n如需重新登录，请先点击注销。",
                "warning",
            )
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
            remember_password=self._remember_password_var.get(),
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

        # 持久化网络参数，使跨会话注销可用
        params = self._client.get_cached_params()
        if params:
            self._config_mgr.save_network_params(params)

        self._show_popup("登录成功", message, "success")

    def _on_login_failed(self, error: str):
        """登录失败回调 (主线程)"""
        self._is_logged_in = False
        self._set_logging_state(False)
        self._draw_status_dot("red")
        self._status_text.set("○ 连接失败")
        self._set_message(f"❌ {error}", "red")

        self._show_popup("登录失败", error, "error")

    def _on_logout(self):
        """点击注销按钮"""
        if self._is_logging:
            return

        # 状态不一致时（浏览器注销等），实际已是注销状态，只重置 UI
        if self._actually_disconnected:
            self._apply_logged_out_state()
            self._set_message("UI 状态已重置，可重新登录", "gray")
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
        self._status_text.set("未认证")
        self._set_message(f"✅ {message}", "gray")

        self._login_button.configure(state=tk.NORMAL)
        self._logout_button.configure(state=tk.DISABLED)

        # 清除缓存的网络参数
        self._config_mgr.clear_network_params()
        self._client.set_cached_params(None)

        self._show_popup("注销成功", message, "success")

    def _on_logout_failed(self, error: str):
        """注销失败回调 (主线程)"""
        self._set_logging_state(False)
        self._set_message(f"⚠ 注销失败: {error}", "orange")

        self._show_popup("注销失败", error, "warning")

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
        # 合并已有配置以保留内部字段（如 cached_network_params）
        existing = self._config_mgr.load()
        existing.update(config)
        self._config_mgr.save(existing)
        self._config = existing
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
        """设置登录中状态，禁用/启用相关控件

        已登录时账号字段保持禁用 (注销后才能编辑)
        """
        self._is_logging = logging
        state = tk.DISABLED if logging else tk.NORMAL
        combo_state = "disabled" if logging else "readonly"

        # 已登录时账号字段始终禁用，注销后才能编辑
        if not logging and self._is_logged_in:
            state = tk.DISABLED
            combo_state = "disabled"

        self._username_entry.configure(state=state)
        self._password_entry.configure(state=state)
        self._device_combo.configure(state=combo_state)
        self._operator_combo.configure(state=combo_state)
        self._remember_password_cb.configure(state=state)

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

    def _show_popup(self, title: str, message: str, popup_type: str = "info") -> None:
        """显示居中弹窗通知"""
        PopupNotification.show(self._root, title, message, popup_type)

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
        """启动断线重连定时器，根据当前登录状态自适应间隔"""
        if self._is_logged_in:
            interval_ms = self._config.get("keep_alive_interval", 300) * 1000
        else:
            interval_ms = 30000  # 未登录时 30 秒快检，尽快发现网络变化
        if self._keep_alive_job is not None:
            self._root.after_cancel(self._keep_alive_job)
        self._schedule_keep_alive(int(interval_ms))

    def _schedule_keep_alive(self, interval_ms: int):
        """调度下一次重连检查"""
        self._keep_alive_job = self._root.after(
            interval_ms, self._keep_alive_check
        )

    def _keep_alive_check(self):
        """定时状态检测 + 断线重连 (在主线程调度)

        状态检测始终运行，不受登录状态限制；自动重登仅在之前已登录时才触发。
        未登录时用短间隔 (30s) 快速发现网络变化，已登录时用配置间隔降低请求量。
        """
        if not self._keep_alive_var.get():
            return

        # 始终检测认证状态 (不登入，只探测)
        if not self._is_logging:
            thread = threading.Thread(
                target=self._do_status_check, daemon=True
            )
            thread.start()

        # 自适应间隔：未登录时 30 秒快检，已登录时用配置间隔
        if self._is_logged_in:
            interval_ms = self._config.get("keep_alive_interval", 300) * 1000
        else:
            interval_ms = 30000  # 30 秒快速轮询，等待网络就绪
        self._schedule_keep_alive(int(interval_ms))

    def _do_status_check(self):
        """后台探测认证状态，根据结果分发到主线程更新 UI 或触发重连"""
        try:
            status = self._client.check_auth_status()
        except Exception:
            return  # 探测失败，等下次

        self._root.after(0, self._on_status_update, status)

    def _on_status_update(self, status: str, allow_reconnect: bool = True):
        """根据检测到的认证状态更新 UI；allow_reconnect 为 True 时断线自动重连"""
        was_logged_in = self._is_logged_in

        if status == "authenticated":
            if was_logged_in:
                # 一切正常，清除不一致标志
                self._actually_disconnected = False
                if not allow_reconnect:
                    self._set_message("认证状态正常", "green")
                return
            # 检测到已认证但 GUI 认为未登录：可能被浏览器/其他设备登录了
            self._apply_logged_in_state("检测到已认证状态，无需重复登录", "green")

        elif status == "not_authenticated":
            if was_logged_in:
                self._actually_disconnected = True
                self._set_message(
                    "认证已断开，正在等待断线重连中，"
                    "若想立即重连，请退出程序重启或点击注销",
                    "orange",
                )
                if allow_reconnect:
                    self._try_auto_reconnect()
            else:
                # 从 offline 恢复，或持续未认证
                self._apply_logged_out_state()
                if self._try_auto_login():
                    return
                self._set_message("未登录认证，请点击登录", "gray")

        else:  # offline
            if was_logged_in:
                # 网络断开了
                self._apply_logged_out_state()
                self._set_message("网络连接已断开", "red")
            # 未登录 + offline：保持"未连接"状态 (可能由 _on_startup_auth_detected 设置)

    def _apply_logged_in_state(self, message: str, color: str):
        """将 GUI 切换到已登录状态"""
        self._is_logged_in = True
        self._draw_status_dot("green")
        self._status_text.set("● 已连接")
        self._login_button.configure(state=tk.DISABLED)
        self._logout_button.configure(state=tk.NORMAL)
        self._username_entry.configure(state=tk.DISABLED)
        self._password_entry.configure(state=tk.DISABLED)
        self._device_combo.configure(state="disabled")
        self._operator_combo.configure(state="disabled")
        self._remember_password_cb.configure(state=tk.DISABLED)
        self._set_message(message, color)

        # 更新缓存的网络参数
        params = self._client.get_cached_params()
        if not params:
            # 无缓存时用本机 IP/MAC 构造兜底参数
            params = self._client.build_local_network_params()
            self._client.set_cached_params(params)
        if params:
            self._config_mgr.save_network_params(params)

        self._actually_disconnected = False

    def _apply_logged_out_state(self):
        """将 GUI 切换到未登录状态，恢复输入控件可编辑"""
        self._is_logged_in = False
        self._draw_status_dot("gray")
        self._status_text.set("未认证")
        self._login_button.configure(state=tk.NORMAL)
        self._logout_button.configure(state=tk.DISABLED)
        self._username_entry.configure(state=tk.NORMAL)
        self._password_entry.configure(state=tk.NORMAL)
        self._device_combo.configure(state="readonly")
        self._operator_combo.configure(state="readonly")
        self._remember_password_cb.configure(state=tk.NORMAL)
        self._actually_disconnected = False

    def _try_auto_reconnect(self):
        """后台尝试自动重连 (仅在之前已登录、检测到断线时调用)"""
        config = self._config_mgr.load_credentials()
        username = config.get("username")
        password = config.get("password")

        if not username or not password:
            return

        thread = threading.Thread(
            target=self._do_auto_reconnect,
            args=(username, password, config["device"], config["operator"]),
            daemon=True,
        )
        thread.start()

    def _do_auto_reconnect(self, username, password, device, operator):
        """后台执行自动重连"""
        try:
            # 重连前再确认一次状态，避免重复登录
            if self._client.check_auth_status() == "authenticated":
                self._root.after(0, self._apply_logged_in_state,
                                "网络已恢复，无需重新登录", "green")
                return
        except Exception:
            pass

        try:
            message = self._client.login(
                username=username,
                password=password,
                device=device,
                operator=operator,
            )
            self._root.after(0, self._on_keep_alive_reconnect, message)
        except LoginError:
            pass  # 静默重试，下次定时器会自动再试

    def _on_keep_alive_reconnect(self, message: str):
        """断线自动重连成功回调"""
        self._apply_logged_in_state("断线已自动重连", "green")

    def _try_auto_login(self) -> bool:
        """尝试自动登录，返回 True 表示已触发。

        由启动检测和 keep-alive 检测到 not_authenticated 且有 auto_login 配置时调用。
        _auto_login_tried 防止反复重试。
        """
        if not self._config.get("auto_login", False):
            return False
        if self._auto_login_tried:
            return False

        creds = self._config_mgr.load_credentials()
        if not creds.get("username") or not creds.get("password"):
            self._set_message("自动登录已开启但未保存凭据，请手动登录", "orange")
            self._auto_login_tried = True
            return False

        self._auto_login_tried = True
        self._set_message("正在自动登录...", "blue")
        self._is_logging = True
        thread = threading.Thread(
            target=self._do_auto_login_startup,
            args=(
                creds["username"], creds["password"],
                creds.get("device", "mobile"),
                creds.get("operator", "telecom"),
            ),
            daemon=True,
        )
        thread.start()
        return True

    def _do_auto_login_startup(self, username, password, device, operator):
        """后台执行启动时自动登录"""
        try:
            # 确认仍需登录（可能在此期间网络状态变化）
            if self._client.check_auth_status() == "authenticated":
                self._root.after(0, self._apply_logged_in_state,
                                "网络已认证，无需重复登录", "green")
                self._root.after(0, self._set_is_logging_false)
                return
        except Exception:
            pass

        try:
            message = self._client.login(
                username=username,
                password=password,
                device=device,
                operator=operator,
            )
            self._root.after(0, self._on_auto_login_success, message)
        except LoginError as e:
            self._root.after(0, self._on_auto_login_failed, str(e))

    def _on_auto_login_success(self, message: str):
        """自动登录成功回调"""
        self._is_logging = False
        self._apply_logged_in_state("启动时自动登录成功", "green")
        self._show_popup("自动登录成功", message, "success")

    def _on_auto_login_failed(self, error: str):
        """自动登录失败回调"""
        self._is_logging = False
        self._draw_status_dot("red")
        self._status_text.set("○ 连接失败")
        self._login_button.configure(state=tk.NORMAL)
        self._set_message(f"自动登录失败: {error}，请手动登录", "red")

    def _set_is_logging_false(self):
        """重置 _is_logging 标志（供 auto_login 等路径复用）"""
        self._is_logging = False

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
