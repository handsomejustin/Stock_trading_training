"""
盘感训练器 - 主窗口模块

整合所有模块，构建 PyQt5/PySide6 主窗口。
包含：暗色主题、Tab布局、分仓快捷键、止损止盈、AI分析、统计面板。
"""

import sys
from pathlib import Path
from datetime import datetime

# 兼容 PyQt5（本地开发）与 PySide6（CI 多平台构建）
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
        QLabel, QLineEdit, QPushButton, QSpinBox, QComboBox, QTextEdit,
        QFileDialog, QGroupBox, QStatusBar, QCheckBox,
        QMessageBox, QSplitter, QTabWidget, QDoubleSpinBox,
        QProgressDialog, QDialog, QStackedWidget, QGridLayout,
    )
    from PySide6.QtCore import Qt, QDateTime, QEvent, QThread, Signal, QTimer
    from PySide6.QtGui import QPalette, QColor, QFont, QIcon, QPainter, QPen, QAction
    from PySide6.QtWidgets import QApplication as QApp
except ImportError:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
        QLabel, QLineEdit, QPushButton, QSpinBox, QComboBox, QTextEdit,
        QFileDialog, QGroupBox, QStatusBar, QCheckBox,
        QMessageBox, QSplitter, QTabWidget, QDoubleSpinBox,
        QProgressDialog, QDialog, QStackedWidget, QGridLayout,
    )
    from PyQt5.QtCore import Qt, QDateTime, QEvent, QThread, pyqtSignal as Signal, QTimer
    from PyQt5.QtGui import QPalette, QColor, QFont, QIcon, QPainter, QPen
    from PyQt5.QtWidgets import QAction

from config import load_config, save_config
from data_loader import DataLoader
from indicators import IndicatorHub, SUB_INDICATOR_NAMES
from chart_canvas import ChartCanvas
from trade_manager import TradeManager
from report_generator import generate_report
from db import Database
from ai_analyzer import AIAnalyzer
from stats_panel import StatsPanel
from updater import __version__, check_update, download_update, apply_update, UpdateInfo
from timer_bar import TimerBar
from multi_tf_canvas import MultiTFCanvas
from sector_panel import SectorPanel
from psychology_tracker import PsychologyTracker
from signal_bank import SignalBank
from quiz_panel import QuizPanel, QuizLoadWorker, BankBuildWorker


# ============================================================
# 加载遮罩 & 后台加载线程
# ============================================================

class LoadingOverlay(QWidget):
    """居中半透明加载遮罩，带旋转点动画。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setFixedSize(parent.size())
        self._dots = 0
        self._base_text = "正在载入数据"

        # 半透明黑色背景
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(0, 0, 0, 160))
        self.setPalette(pal)

        # 动画定时器
        self._timer = self.startTimer(400)

    def timerEvent(self, event):
        self._dots = (self._dots + 1) % 4
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 半透明背景（paintEvent 里再画一层确保覆盖）
        painter.fillRect(self.rect(), QColor(0, 0, 0, 160))

        # 文字
        dots = "." * self._dots
        text = f"{self._base_text}{dots}"
        font = QFont("Microsoft YaHei", 18, QFont.Bold)
        painter.setFont(font)
        painter.setPen(QPen(QColor(255, 255, 255, 230)))
        painter.drawText(self.rect(), Qt.AlignCenter, text)
        painter.end()

    def set_text(self, text: str):
        self._base_text = text
        self.update()

    def cleanup(self):
        self.killTimer(self._timer)


class SessionSummaryDialog(QDialog):
    """
    训练结束小结弹窗。

    展示本次收益、对比持有不动、（答题模式）正确率，
    并提供 AI 复盘入口。done(2) 表示用户点击了「AI 复盘」。
    """

    RET_AI = 2

    def __init__(self, parent, stock_code: str, mode: str,
                 stats: dict, quiz_answers: list = None):
        super().__init__(parent)
        self.setWindowTitle("训练小结")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel(f"📌 {stock_code} · {dict_mode_name(mode)}")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)

        def _stat_row(label: str, value_text: str, color: str) -> QWidget:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            lab = QLabel(label)
            lab.setStyleSheet("color: #aaaaaa; font-size: 15px;")
            val = QLabel(value_text)
            val.setStyleSheet(f"color: {color}; font-size: 17px; font-weight: bold;")
            h.addWidget(lab)
            h.addStretch()
            h.addWidget(val)
            return row

        sign = "+" if stats["total_return"] >= 0 else ""
        layout.addWidget(_stat_row(
            "本次收益（含浮动）", f"{sign}{stats['total_return']:.2f}%",
            "#ff6666" if stats["total_return"] >= 0 else "#66ff66"))

        sign = "+" if stats["buy_hold"] >= 0 else ""
        layout.addWidget(_stat_row(
            "持有不动", f"{sign}{stats['buy_hold']:.2f}%",
            "#ff6666" if stats["buy_hold"] >= 0 else "#66ff66"))

        excess = stats["total_return"] - stats["buy_hold"]
        sign = "+" if excess >= 0 else ""
        layout.addWidget(_stat_row(
            "择时超额", f"{sign}{excess:.2f}%",
            "#ff6666" if excess >= 0 else "#66ff66"))

        layout.addWidget(_stat_row(
            "交易次数", f"{stats['trade_count']} 次", "#cccccc"))

        if quiz_answers:
            n = len(quiz_answers)
            correct = sum(1 for a in quiz_answers if a["is_correct"])
            layout.addWidget(_stat_row(
                "答题正确率", f"{correct}/{n} ({correct / n * 100:.0f}%)"
                if n else "—", "#4a9eff"))

        hint = QLabel("正的择时超额说明你的买卖点跑赢了「拿住不动」。")
        hint.setStyleSheet("color: #888888; font-size: 13px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_ai = QPushButton("🤖 AI 复盘")
        btn_ai.setStyleSheet("""
            QPushButton {
                background-color: #2a4a6a; color: #ffffff;
                padding: 8px 20px; border: 1px solid #4a9eff;
                border-radius: 4px; font-size: 15px; font-weight: bold;
            }
            QPushButton:hover { background-color: #3a5a8a; }
        """)
        btn_ai.clicked.connect(lambda: self.done(self.RET_AI))
        btn_close = QPushButton("关闭")
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c; color: #cccccc;
                padding: 8px 20px; border: 1px solid #555555;
                border-radius: 4px; font-size: 15px;
            }
            QPushButton:hover { background-color: #505050; }
        """)
        btn_close.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(btn_ai)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)


def dict_mode_name(mode: str) -> str:
    """模式 key 转中文名。"""
    return {
        "classic": "经典模式", "timed": "限时模式", "multi_tf": "多周期模式",
        "sector": "板块联动", "comprehensive": "综合训练", "quiz": "答题模式",
    }.get(mode, mode)


class OnboardingDialog(QDialog):
    """
    首次启动新手引导（3 页向导）。

    关闭后主窗口读取 apply_path（若有变更）并写入 first_run_done。
    """

    def __init__(self, parent, tdx_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("欢迎使用盘感训练器")
        self.setMinimumSize(600, 420)
        self._initial_path = tdx_path
        self.apply_path = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_welcome_page(tdx_path))
        self.stack.addWidget(self._build_keys_page())
        self.stack.addWidget(self._build_modes_page())
        layout.addWidget(self.stack)

        btn_row = QHBoxLayout()
        self._btn_back = QPushButton("← 上一步")
        self._btn_back.clicked.connect(self._go_prev)
        self._btn_next = QPushButton("下一步 →")
        self._btn_next.clicked.connect(self._go_next)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_back)
        btn_row.addWidget(self._btn_next)
        layout.addLayout(btn_row)
        self._sync_buttons()

    def _make_page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        return page, layout

    def _build_welcome_page(self, tdx_path: str) -> QWidget:
        page, layout = self._make_page()
        title = QLabel("👋 欢迎使用盘感训练器")
        title.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: bold;")
        layout.addWidget(title)

        intro = QLabel(
            "这是一款 K 线推演训练工具：程序隐藏未来行情，你逐根揭K线、\n"
            "模拟买卖，练的是「技术选时」的盘感。\n\n"
            "第一步：确认本地通达信数据目录（行情数据从这里读取）。")
        intro.setStyleSheet("color: #bbbbbb; font-size: 15px;")
        layout.addWidget(intro)

        path_row = QHBoxLayout()
        self._edit_tdx = QLineEdit(tdx_path)
        self._edit_tdx.setPlaceholderText("例如 C:\\new_tdx（自动检测失败时手动选择）")
        path_row.addWidget(self._edit_tdx, stretch=1)
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._browse)
        path_row.addWidget(btn_browse)
        layout.addLayout(path_row)

        tip = QLabel("提示：之后也可以在「⚙ 高级设置」中随时修改。")
        tip.setStyleSheet("color: #888888; font-size: 13px;")
        layout.addWidget(tip)
        layout.addStretch()
        return page

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "选择通达信安装目录")
        if path:
            self._edit_tdx.setText(path)

    def _build_keys_page(self) -> QWidget:
        page, layout = self._make_page()
        title = QLabel("⌨ 记住这几组快捷键")
        title.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: bold;")
        layout.addWidget(title)
        keys = QLabel(
            "→            前进一根K线（核心操作）\n"
            "←            后退\n"
            "PgDn         快进 10 根\n"
            "1 / 2 / 3 / 4      买入 25% / 33% / 50% / 100% 仓位\n"
            "Shift+1/2/3/4     卖出对应仓位\n"
            "↑ / ↓        按默认仓位买入 / 卖出\n"
            "Space        观望一天\n"
            "Esc          结束训练（出报告和小结）\n"
            "F1           随时查看快捷键速查")
        keys.setStyleSheet(
            "color: #cccccc; font-size: 16px; background-color: #252525; "
            "border-radius: 6px; padding: 16px;")
        layout.addWidget(keys)
        layout.addStretch()
        return page

    def _build_modes_page(self) -> QWidget:
        page, layout = self._make_page()
        title = QLabel("🎯 六种训练模式")
        title.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: bold;")
        layout.addWidget(title)
        lines = []
        for key, icon, name, desc in MainWindow.MODE_CARDS:
            lines.append(f"{icon}  {name} —— {desc}")
        modes = QLabel("\n".join(lines))
        modes.setStyleSheet(
            "color: #cccccc; font-size: 15px; background-color: #252525; "
            "border-radius: 6px; padding: 16px;")
        layout.addWidget(modes)
        ready = QLabel("就绪了？回首页选一个模式，开始训练！")
        ready.setStyleSheet("color: #4a9eff; font-size: 15px; font-weight: bold;")
        layout.addWidget(ready)
        layout.addStretch()
        return page

    def _go_prev(self):
        if self.stack.currentIndex() > 0:
            self.stack.setCurrentIndex(self.stack.currentIndex() - 1)
        self._sync_buttons()

    def _go_next(self):
        if self.stack.currentIndex() < self.stack.count() - 1:
            self.stack.setCurrentIndex(self.stack.currentIndex() + 1)
        else:
            self._finish()
        self._sync_buttons()

    def _finish(self):
        path = self._edit_tdx.text().strip()
        if path and path != self._initial_path:
            self.apply_path = path
        self.accept()

    def _sync_buttons(self):
        first = self.stack.currentIndex() == 0
        last = self.stack.currentIndex() == self.stack.count() - 1
        self._btn_back.setEnabled(not first)
        self._btn_next.setText("完成 ✓" if last else "下一步 →")


class LoadWorker(QThread):
    """后台线程：执行扫描选股 + 指标计算。"""
    status = Signal(str)       # 进度文字
    finished_ok = Signal(object, object, object, int, int)
    # df, stock_code, hub, warmup, start_cursor
    finished_err = Signal(str)  # 错误信息

    def __init__(self, data_loader, days, ma_periods, config):
        super().__init__()
        self.data_loader = data_loader
        self.days = days
        self.ma_periods = ma_periods
        self.config = config

    def run(self):
        try:
            self.status.emit("正在扫描股票数据…")
            stocks = self.data_loader.scan_stocks()
            self.status.emit(f"扫描到 {len(stocks)} 只股票，正在选股…")

            df, stock_code = self.data_loader.random_pick(self.days, self.ma_periods)
            self.status.emit(f"已选中 {stock_code}，正在计算指标…")

            config = dict(self.config)
            config["ma_periods"] = self.ma_periods
            hub = IndicatorHub(df, config)
            hub.calculate_all()
            warmup = hub.get_min_warmup()

            self.finished_ok.emit(df, stock_code, hub, warmup, warmup)
        except Exception as e:
            self.finished_err.emit(str(e))


class _UpdateCheckThread(QThread):
    """后台线程：检查更新。"""
    found = Signal(object)      # UpdateInfo
    not_found = Signal()

    def __init__(self, config: dict):
        super().__init__()
        self.config = config

    def run(self):
        info = check_update(self.config)
        if info:
            self.found.emit(info)
        else:
            self.not_found.emit()


class _UpdateDownloadThread(QThread):
    """后台线程：下载更新文件。"""
    progress = Signal(int, int)     # downloaded, total
    done = Signal(str)              # zip_path
    error = Signal(str)             # error message

    def __init__(self, info: UpdateInfo):
        super().__init__()
        self.info = info

    def run(self):
        try:
            zip_path = download_update(self.info, progress_cb=self._on_progress)
            self.done.emit(zip_path)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, downloaded: int, total: int):
        self.progress.emit(downloaded, total)


class MainWindow(QMainWindow):
    """盘感训练器主窗口。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"盘感训练器 v{__version__} - K线推演模拟交易")
        self.resize(1500, 900)

        # ---- 窗口图标 ----
        icon_path = Path(__file__).parent / "logo.ico"
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

        # ---- 暗色主题 ----
        self._apply_dark_theme()

        # ---- 状态变量 ----
        self.config = load_config()
        self.data_loader: DataLoader = None
        self.indicator_hub: IndicatorHub = None
        self.trade_manager = TradeManager()
        self.df = None              # 当前训练数据
        self.cursor = 0             # 当前推演位置
        self.stock_code = ""        # 当前股票代码
        self.training_active = False
        self.min_warmup = 30        # 指标预热最小根数
        self._loading_overlay = None  # 加载遮罩

        # ---- 训练模式 ----
        self.current_mode = self.config.get("mode", {}).get("current", "classic")
        self.weekly_df = None
        self.weekly_cursor = 0
        self.sector_peers = []
        self.sector_cursors = {}
        self._mode_widgets = []
        self.timer_bar: TimerBar = None
        self.multi_tf_canvas: MultiTFCanvas = None
        self.sector_panel: SectorPanel = None
        self.psychology_tracker: PsychologyTracker = None

        # ---- 答题模式 ----
        self.signal_bank = SignalBank()
        self.quiz_state = None            # {total, no, answers, current}
        self.quiz_panel: QuizPanel = None

        # ---- 数据库 & AI ----
        self.db = Database()
        self.ai_analyzer = AIAnalyzer(self.config)

        # ---- 默认仓位 ----
        trading_cfg = self.config.get("trading", {})
        self.default_buy_ratio = trading_cfg.get("default_buy_ratio", 1.0)
        self.default_sell_ratio = trading_cfg.get("default_sell_ratio", 1.0)

        # ---- 构建 UI ----
        self._build_ui()

        # ---- 安装全局事件过滤器 ----
        self._install_key_filter()

        # ---- 菜单栏 ----
        self._build_menu()

        # ---- 初始化数据加载器 ----
        self._init_data_loader()

        # ---- 首次启动新手引导 ----
        if not self.config.get("first_run_done"):
            QTimer.singleShot(300, self._show_onboarding)

        # ---- 启动时自动检查更新 ----
        self._pending_update: UpdateInfo | None = None
        update_cfg = self.config.get("update", {})
        if update_cfg.get("auto_check", True):
            QTimer.singleShot(3000, self._silent_check_update)

    def _show_onboarding(self):
        """首次启动新手引导（3 页向导）。"""
        try:
            dlg = OnboardingDialog(self, self.tdx_path_edit.text())
            dlg.exec()
            if dlg.apply_path:
                self.tdx_path_edit.setText(dlg.apply_path)
                self.data_loader = DataLoader(dlg.apply_path or None)
                if self.data_loader.is_available():
                    self.config["tdx_home"] = dlg.apply_path
                    self.log(f"✅ 通达信目录: {dlg.apply_path}")
                else:
                    self.log("⚠ 所选目录无效，可在「高级设置」中重试")
        except Exception as e:
            self.log(f"⚠ 新手引导显示失败: {e}")
        finally:
            self.config["first_run_done"] = True
            save_config(self.config)
        if hasattr(self, "_home_hint"):
            ok = self.data_loader and self.data_loader.is_available()
            self._home_hint.setText(
                "" if ok else "⚠ 未找到通达信数据目录，请到「高级设置」选择")

    # ============================================================
    # 菜单栏 & 自动更新
    # ============================================================
    def _build_menu(self):
        """构建菜单栏。"""
        menubar = self.menuBar()
        menubar.setStyleSheet("""
            QMenuBar { background: #2d2d2d; color: #cccccc; font-size: 14px; }
            QMenuBar::item:selected { background: #3d3d3d; }
            QMenu { background: #2d2d2d; color: #cccccc; font-size: 14px; }
            QMenu::item:selected { background: #0078d7; }
        """)

        help_menu = menubar.addMenu("帮助")

        check_action = QAction("检查更新…", self)
        check_action.triggered.connect(self._manual_check_update)
        help_menu.addAction(check_action)

        about_action = QAction(f"关于 (v{__version__})", self)
        about_action.triggered.connect(
            lambda: QMessageBox.about(self, "关于", f"盘感训练器 v{__version__}\n\nK线推演模拟交易工具")
        )
        help_menu.addAction(about_action)

    def _silent_check_update(self):
        """启动时静默检查更新（后台线程）。"""
        if self._pending_update is not None:
            return  # 已经在检查
        self._update_check_thread = _UpdateCheckThread(self.config)
        self._update_check_thread.found.connect(self._on_update_found)
        self._update_check_thread.start()

    def _manual_check_update(self):
        """手动检查更新（菜单触发）。"""
        self.statusBar().showMessage("正在检查更新…")
        self._manual_check_thread = _UpdateCheckThread(self.config)
        self._manual_check_thread.found.connect(self._on_update_found)
        self._manual_check_thread.not_found.connect(self._on_update_not_found)
        self._manual_check_thread.start()

    def _on_update_found(self, info: UpdateInfo):
        """发现新版本回调。"""
        self._pending_update = info
        # 状态栏显示可点击的更新提示
        self.statusBar().showMessage(
            f"🔄 发现新版本 v{info.version} — 点击此处或菜单「帮助 → 检查更新」进行升级"
        )
        self.statusBar().linkActivated.connect(lambda: self._prompt_update())
        # 弹窗提示
        self._prompt_update()

    def _on_update_not_found(self):
        """手动检查：已是最新版本。"""
        self.statusBar().showMessage(f"当前已是最新版本 (v{__version__})")

    def _prompt_update(self):
        """弹窗询问用户是否升级。"""
        info = self._pending_update
        if not info:
            return

        changelog_text = info.changelog or "详见发布说明"
        msg = (
            f"<h3>发现新版本 v{info.version}</h3>"
            f"<p>当前版本: v{__version__}</p>"
            f"<hr>"
            f"<p><b>更新内容：</b></p>"
            f"<p>{changelog_text}</p>"
            f"<hr>"
            f"<p>文件大小: {info.size / 1024 / 1024:.1f} MB</p>"
        )

        reply = QMessageBox.question(
            self, "软件更新", msg,
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Ignore,
            QMessageBox.Yes,
        )

        if reply == QMessageBox.Yes:
            self._do_download_update(info)
        elif reply == QMessageBox.Ignore:
            # 跳过此版本
            self.config.setdefault("update", {})["skip_version"] = info.version
            save_config(self.config)
            self._pending_update = None
            self.statusBar().showMessage(f"已跳过 v{info.version}")

    def _do_download_update(self, info: UpdateInfo):
        """下载更新并显示进度条，下载完成后自动执行升级。"""
        progress = QProgressDialog(
            f"正在下载 v{info.version} ({info.size / 1024 / 1024:.1f} MB)…",
            "取消", 0, 100, self
        )
        progress.setWindowTitle("下载更新")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setStyleSheet("""
            QProgressDialog { background: #2d2d2d; color: #cccccc; }
            QProgressBar { border: 1px solid #555; text-align: center; background: #1e1e1e; }
            QProgressBar::chunk { background: #0078d7; }
        """)

        self._update_download_thread = _UpdateDownloadThread(info)
        self._update_download_thread.progress.connect(
            lambda d, t: progress.setValue(int(d / t * 100)) if t > 0 else None
        )
        self._update_download_thread.done.connect(self._on_download_done)
        self._update_download_thread.error.connect(self._on_download_error)
        self._update_download_thread.start()

        progress.canceled.connect(self._update_download_thread.quit)
        self._update_progress = progress

    def _on_download_done(self, zip_path: str):
        """下载完成，自动执行升级（无需二次确认）。"""
        if hasattr(self, "_update_progress"):
            self._update_progress.close()

        try:
            apply_update(zip_path)
        except Exception as e:
            log_path = Path(sys.executable).parent / "_update.log"
            QMessageBox.critical(
                self, "升级失败",
                f"启动升级失败: {e}\n\n"
                f"日志文件: {log_path}"
            )

    def _on_download_error(self, err_msg: str):
        """下载失败。"""
        if hasattr(self, "_update_progress"):
            self._update_progress.close()
        log_path = Path(sys.executable).parent / "_update.log"
        QMessageBox.critical(
            self, "下载失败",
            f"更新下载失败:\n{err_msg}\n\n"
            f"详细日志: {log_path}"
        )

    # ============================================================
    # 暗色主题
    # ============================================================
    def _apply_dark_theme(self):
        """应用深色调色板。"""
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#2b2b2b"))
        palette.setColor(QPalette.WindowText, QColor("#cccccc"))
        palette.setColor(QPalette.Base, QColor("#1e1e1e"))
        palette.setColor(QPalette.AlternateBase, QColor("#2b2b2b"))
        palette.setColor(QPalette.ToolTipBase, QColor("#2b2b2b"))
        palette.setColor(QPalette.ToolTipText, QColor("#cccccc"))
        palette.setColor(QPalette.Text, QColor("#cccccc"))
        palette.setColor(QPalette.Button, QColor("#3c3c3c"))
        palette.setColor(QPalette.ButtonText, QColor("#cccccc"))
        palette.setColor(QPalette.BrightText, QColor("#ff4444"))
        palette.setColor(QPalette.Highlight, QColor("#4a9eff"))
        palette.setColor(QPalette.HighlightedText, QColor("#000000"))
        QApplication.instance().setPalette(palette)

    # ============================================================
    def resizeEvent(self, event):
        """窗口大小变化时同步遮罩尺寸。"""
        super().resizeEvent(event)
        if self._loading_overlay:
            self._loading_overlay.setFixedSize(self.centralWidget().size())

    # ============================================================
    # 快捷键事件过滤器
    # ============================================================
    def _install_key_filter(self):
        """对所有可聚焦子控件安装事件过滤器。"""
        for widget in self.findChildren(QWidget):
            widget.installEventFilter(self)

    # ============================================================
    # UI 构建
    # ============================================================
    def _build_ui(self):
        """构建主窗口 UI 布局（首页 + 训练页双页栈）。"""
        self.main_stack = QStackedWidget()
        self.setCentralWidget(self.main_stack)

        # ---- 训练页：图表 + 控制面板 ----
        training_page = QWidget()
        main_layout = QVBoxLayout(training_page)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # ---- 上部：图表 + 控制面板（水平分割） ----
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：图表区域（可扩展模式组件）
        left_container = QWidget()
        self.left_chart_layout = QVBoxLayout(left_container)
        self.left_chart_layout.setContentsMargins(0, 0, 0, 0)
        self.left_chart_layout.setSpacing(2)

        self.chart = ChartCanvas(parent=self)
        self.left_chart_layout.addWidget(self.chart, stretch=1)

        splitter.addWidget(left_container)

        # 右侧：Tab 面板
        right_panel = self._build_right_panel()
        splitter.addWidget(right_panel)

        # 设置分割比例（图表:面板 = 5:2）
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([1050, 420])

        main_layout.addWidget(splitter, stretch=1)

        # ---- 底部：操作按钮栏 ----
        bottom_bar = self._build_bottom_bar()
        main_layout.addWidget(bottom_bar)

        self.main_stack.addWidget(training_page)

        # ---- 首页：模式选择卡片 ----
        home_page = self._build_home_page()
        self.main_stack.addWidget(home_page)
        self.main_stack.setCurrentIndex(0)

        # ---- 状态栏 ----
        self.statusBar().showMessage("就绪 - 选择一种模式开始训练（F1 查看快捷键）")
        self.statusBar().setStyleSheet("color: #cccccc; font-size: 14px;")

    # 模式卡片定义: (key, 图标, 名称, 一句话说明)
    MODE_CARDS = [
        ("classic", "📈", "经典模式", "随机个股逐根揭开K线，手动买卖练盘感"),
        ("timed", "⏱", "限时模式", "每根K线倒计时，逼你快速决策"),
        ("multi_tf", "📅", "多周期模式", "日线+周线联动推演，看大做小"),
        ("sector", "🏭", "板块联动", "同板块多股同步对照，识别共振"),
        ("comprehensive", "🧠", "综合训练", "全要素训练 + 心理状态记录"),
        ("quiz", "🎯", "答题模式", "信号出现你怎么做？历史数据来判分"),
    ]

    def _build_home_page(self) -> QWidget:
        """构建首页：标题 + 模式卡片 + 工具入口。"""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(48, 36, 48, 24)
        outer.setSpacing(18)

        title = QLabel("盘感训练器")
        title.setStyleSheet("font-size: 34px; font-weight: bold; color: #ffffff;")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        subtitle = QLabel("K线推演 · 模拟交易 · 信号判分 —— 练出你的技术选时盘感")
        subtitle.setStyleSheet("color: #888888; font-size: 15px;")
        subtitle.setAlignment(Qt.AlignCenter)
        outer.addWidget(subtitle)

        grid = QGridLayout()
        grid.setSpacing(14)
        card_style = """
            QPushButton {
                background-color: #2b2b2b; color: #e0e0e0;
                border: 1px solid #3c3c3c; border-radius: 8px;
                padding: 14px 16px; text-align: left;
            }
            QPushButton:hover {
                background-color: #333333; border: 1px solid #4a9eff;
            }
        """
        for i, (key, icon, name, desc) in enumerate(self.MODE_CARDS):
            btn = QPushButton(f"{icon}  {name}\n     {desc}")
            btn.setStyleSheet(card_style)
            btn.setMinimumHeight(92)
            btn.setFont(QFont("Microsoft YaHei", 12))
            btn.clicked.connect(
                lambda _=False, k=key: self._start_mode_from_home(k))
            grid.addWidget(btn, i // 3, i % 3)
        outer.addLayout(grid, stretch=1)

        tool_row = QHBoxLayout()
        btn_advanced = QPushButton("⚙ 高级设置")
        btn_advanced.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c; color: #cccccc;
                padding: 8px 20px; border: 1px solid #555555;
                border-radius: 4px; font-size: 14px;
            }
            QPushButton:hover { background-color: #505050; }
        """)
        btn_advanced.clicked.connect(
            lambda: self.main_stack.setCurrentIndex(1))
        tool_row.addWidget(btn_advanced)

        btn_rebuild = QPushButton("🔄 重建题库")
        btn_rebuild.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c; color: #cccccc;
                padding: 8px 20px; border: 1px solid #555555;
                border-radius: 4px; font-size: 14px;
            }
            QPushButton:hover { background-color: #505050; }
        """)
        btn_rebuild.setToolTip("重新扫描全市场历史数据，刷新答题模式题库")
        btn_rebuild.clicked.connect(self._rebuild_bank_from_home)
        tool_row.addWidget(btn_rebuild)
        tool_row.addStretch()

        self._home_hint = QLabel("")
        self._home_hint.setStyleSheet("color: #888888; font-size: 13px;")
        tool_row.addWidget(self._home_hint)
        outer.addLayout(tool_row)

        # 数据源不可用时在首页提示
        if not (self.data_loader and self.data_loader.is_available()):
            self._home_hint.setText("⚠ 未找到通达信数据目录，请到「高级设置」选择")

        return page

    def _start_mode_from_home(self, mode_key: str):
        """首页点击模式卡片：切到训练页并启动训练。"""
        keys = [c[0] for c in self.MODE_CARDS]
        if mode_key in keys:
            self.combo_mode.setCurrentIndex(keys.index(mode_key))
        self.main_stack.setCurrentIndex(1)
        self.start_training()

    def _rebuild_bank_from_home(self):
        """首页手动重建题库（构建完成后停留在首页）。"""
        if not self.data_loader or not self.data_loader.is_available():
            QMessageBox.warning(
                self, "数据源不可用",
                "未找到通达信数据目录，请先到「高级设置」选择。")
            return
        self._bank_build_reason = "manual"
        self._quiz_build_bank()

    def _go_home(self):
        """返回首页。"""
        if hasattr(self, "main_stack"):
            self.main_stack.setCurrentIndex(0)
            self.statusBar().showMessage("就绪 - 选择一种模式开始训练（F1 查看快捷键）")

    def _build_right_panel(self) -> QWidget:
        """构建右侧 Tab 面板。"""
        panel = QWidget()
        panel.setMaximumWidth(520)
        panel.setMinimumWidth(320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self.right_tabs = QTabWidget()
        self.right_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #3c3c3c; }
            QTabBar::tab {
                background-color: #3c3c3c; color: #cccccc;
                padding: 8px 16px; border: 1px solid #555555;
                border-bottom: none; border-top-left-radius: 4px;
                border-top-right-radius: 4px; font-size: 14px;
            }
            QTabBar::tab:selected {
                background-color: #2b2b2b; color: #ffffff;
                border-bottom: 2px solid #4a9eff;
            }
        """)

        # Tab 1: 训练配置
        config_tab = self._build_config_tab()
        self.right_tabs.addTab(config_tab, "⚙ 配置")

        # Tab 2: 操作日志
        log_tab = self._build_log_tab()
        self.right_tabs.addTab(log_tab, "📋 日志")

        # Tab 3: 训练统计
        self.stats_panel = StatsPanel(self.db)
        self.right_tabs.addTab(self.stats_panel, "📊 统计")

        # Tab 切换时刷新统计面板
        self.right_tabs.currentChanged.connect(self._on_tab_changed)

        layout.addWidget(self.right_tabs)
        return panel

    def _build_config_tab(self) -> QWidget:
        """构建训练配置 Tab。"""
        tab = QWidget()
        tab.setStyleSheet("""
            QLabel { font-size: 15px; }
            QComboBox { font-size: 15px; padding: 2px 4px; }
            QSpinBox { font-size: 15px; padding: 2px 4px; }
            QDoubleSpinBox { font-size: 15px; padding: 2px 4px; }
            QLineEdit { font-size: 15px; padding: 2px 4px; }
            QPushButton { font-size: 15px; }
            QGroupBox { font-size: 16px; font-weight: bold; }
            QCheckBox { font-size: 15px; }
        """)
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)

        # ---- 快捷键说明 ----
        keys_group = QGroupBox("⌨ 快捷键说明")
        keys_layout = QVBoxLayout(keys_group)
        keys_text = (
            "→ 前进  |  ← 后退  |  PgDn 快进10\n"
            "1/2/3/4 买入 25%/33%/50%/100%\n"
            "Shift+1/2/3/4 卖出对应仓位\n"
            "↑ 买入(默认仓位)  ↓ 卖出(默认仓位)\n"
            "Space 观望  |  Esc 结束训练"
        )
        keys_label = QLabel(keys_text)
        keys_label.setStyleSheet("color: #aaaaaa; font-size: 14px;")
        keys_label.setWordWrap(True)
        keys_layout.addWidget(keys_label)
        layout.addWidget(keys_group)

        # ---- 训练模式 ----
        mode_group = QGroupBox("🎯 训练模式")
        mode_layout = QVBoxLayout(mode_group)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("模式:"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(
            ["经典模式", "限时模式", "多周期模式", "板块联动", "综合训练", "答题模式"])
        _mode_keys = ["classic", "timed", "multi_tf", "sector", "comprehensive", "quiz"]
        _mode_val = self.config.get("mode", {}).get("current", "classic")
        if _mode_val in _mode_keys:
            self.combo_mode.setCurrentIndex(_mode_keys.index(_mode_val))
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self.combo_mode, stretch=1)
        mode_layout.addLayout(mode_row)

        # 限时配置
        self.timed_config_widget = QWidget()
        timed_layout = QHBoxLayout(self.timed_config_widget)
        timed_layout.setContentsMargins(0, 0, 0, 0)
        timed_layout.addWidget(QLabel("限时(秒):"))
        self.combo_timed_seconds = QComboBox()
        self.combo_timed_seconds.addItems(["3", "5", "10", "15", "30"])
        default_sec = str(self.config.get("mode", {}).get("timed_seconds", 10))
        idx = self.combo_timed_seconds.findText(default_sec)
        if idx >= 0:
            self.combo_timed_seconds.setCurrentIndex(idx)
        timed_layout.addWidget(self.combo_timed_seconds)
        self.timed_config_widget.setVisible(False)
        mode_layout.addWidget(self.timed_config_widget)

        # 板块配置
        self.sector_config_widget = QWidget()
        sec_layout = QHBoxLayout(self.sector_config_widget)
        sec_layout.setContentsMargins(0, 0, 0, 0)
        sec_layout.addWidget(QLabel("同板块股票数:"))
        self.spin_peer_count = QSpinBox()
        self.spin_peer_count.setRange(1, 5)
        self.spin_peer_count.setValue(self.config.get("mode", {}).get("sector_peer_count", 3))
        sec_layout.addWidget(self.spin_peer_count)
        self.sector_config_widget.setVisible(False)
        mode_layout.addWidget(self.sector_config_widget)

        layout.addWidget(mode_group)

        # 初始化模式配置可见性
        self._on_mode_changed(self.combo_mode.currentIndex())

        # ---- 训练配置 ----
        config_group = QGroupBox("⚙ 训练配置")
        config_layout = QVBoxLayout(config_group)

        # 通达信目录
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("TDX目录:"))
        self.tdx_path_edit = QLineEdit()
        self.tdx_path_edit.setPlaceholderText("自动检测或手动选择...")
        self.tdx_path_edit.setText(self.config.get("tdx_home", ""))
        dir_layout.addWidget(self.tdx_path_edit, stretch=1)
        self.btn_browse = QPushButton("浏览")
        self.btn_browse.clicked.connect(self._on_browse_tdx)
        dir_layout.addWidget(self.btn_browse)
        config_layout.addLayout(dir_layout)

        # 训练天数
        days_layout = QHBoxLayout()
        days_layout.addWidget(QLabel("训练天数:"))
        self.spin_days = QSpinBox()
        self.spin_days.setRange(30, 500)
        self.spin_days.setValue(self.config.get("training_days", 120))
        days_layout.addWidget(self.spin_days)
        config_layout.addLayout(days_layout)

        # 副图面板数量
        panel_layout = QHBoxLayout()
        panel_layout.addWidget(QLabel("副图数量:"))
        self.spin_panel_count = QSpinBox()
        self.spin_panel_count.setRange(3, 5)
        self.spin_panel_count.setValue(self.config.get("panel_count", 3))
        self.spin_panel_count.valueChanged.connect(self._on_panel_count_changed)
        panel_layout.addWidget(self.spin_panel_count)
        config_layout.addLayout(panel_layout)

        # 副图指标选择（最多5个下拉框）
        self.combo_subs = []
        self.sub_indicator_widgets = []
        default_subs = self.config.get("default_sub_indicators",
                                       ["MACD", "KDJ", "RSI", "CCI", "BIAS"])
        for i in range(5):
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(QLabel(f"副图{i+1}:"))
            combo = QComboBox()
            combo.addItems(SUB_INDICATOR_NAMES)
            if i < len(default_subs):
                idx = combo.findText(default_subs[i])
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.currentTextChanged.connect(self._on_indicator_changed)
            row.addWidget(combo)
            config_layout.addWidget(container)
            self.combo_subs.append(combo)
            self.sub_indicator_widgets.append(container)

        self._update_combo_visibility()

        # 主图叠加指标
        overlay_layout = QVBoxLayout()

        # 均线周期配置行
        ma_row = QHBoxLayout()
        self.chk_ma = QCheckBox("均线")
        self.chk_ma.setChecked(self.config.get("ma_enabled", True))
        self.chk_ma.stateChanged.connect(self._on_overlay_changed)
        ma_row.addWidget(self.chk_ma)

        ma_row.addWidget(QLabel("周期:"))
        self.edit_ma_periods = QLineEdit()
        default_periods = self.config.get("ma_periods", [5, 10, 20, 30, 60, 120])
        self.edit_ma_periods.setText(",".join(str(p) for p in default_periods))
        self.edit_ma_periods.setPlaceholderText("如: 5,10,20,30,60,120")
        self.edit_ma_periods.setToolTip(
            "均线周期，逗号分隔，最多6条\n"
            "默认: 5,10,20,30,60,120"
        )
        self.edit_ma_periods.editingFinished.connect(self._on_ma_periods_changed)
        ma_row.addWidget(self.edit_ma_periods, stretch=1)
        overlay_layout.addLayout(ma_row)

        # 其他叠加指标行
        other_overlay_row = QHBoxLayout()
        other_overlay_row.addWidget(QLabel("叠加:"))
        self.chk_bbi = QCheckBox("BBI")
        self.chk_bbi.setChecked(False)
        other_overlay_row.addWidget(self.chk_bbi)
        self.chk_expma = QCheckBox("EXPMA")
        self.chk_expma.setChecked(False)
        other_overlay_row.addWidget(self.chk_expma)
        self.chk_boll = QCheckBox("BOLL")
        self.chk_boll.setChecked(False)
        other_overlay_row.addWidget(self.chk_boll)

        for chk in [self.chk_bbi, self.chk_expma, self.chk_boll]:
            chk.stateChanged.connect(self._on_overlay_changed)

        other_overlay_row.addStretch()
        overlay_layout.addLayout(other_overlay_row)

        config_layout.addLayout(overlay_layout)

        # ---- 止损止盈 ----
        sl_tp_layout = QHBoxLayout()
        sl_tp_layout.addWidget(QLabel("止损%:"))
        self.spin_stop_loss = QDoubleSpinBox()
        self.spin_stop_loss.setRange(0, 50)
        self.spin_stop_loss.setDecimals(1)
        self.spin_stop_loss.setSuffix("%")
        sl_val = abs(self.config.get("trading", {}).get("stop_loss_pct", 0)) * 100
        self.spin_stop_loss.setValue(sl_val)
        sl_tp_layout.addWidget(self.spin_stop_loss)
        sl_tp_layout.addWidget(QLabel("止盈%:"))
        self.spin_take_profit = QDoubleSpinBox()
        self.spin_take_profit.setRange(0, 200)
        self.spin_take_profit.setDecimals(1)
        self.spin_take_profit.setSuffix("%")
        tp_val = abs(self.config.get("trading", {}).get("take_profit_pct", 0)) * 100
        self.spin_take_profit.setValue(tp_val)
        sl_tp_layout.addWidget(self.spin_take_profit)
        # 训练中修改阈值即时生效
        self.spin_stop_loss.valueChanged.connect(self._on_sl_tp_changed)
        self.spin_take_profit.valueChanged.connect(self._on_sl_tp_changed)
        config_layout.addLayout(sl_tp_layout)

        # 开始训练按钮
        self.btn_start = QPushButton("🚀 开始新训练")
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: #2d7d46; color: white;
                font-size: 18px; font-weight: bold;
                padding: 10px; border-radius: 6px;
            }
            QPushButton:hover { background-color: #3a9e5a; }
            QPushButton:pressed { background-color: #256e3c; }
        """)
        self.btn_start.clicked.connect(self.start_training)
        config_layout.addWidget(self.btn_start)

        layout.addWidget(config_group)

        # ---- AI 设置 ----
        ai_group = QGroupBox("🤖 AI 分析设置")
        ai_layout = QVBoxLayout(ai_group)

        ai_layout.addWidget(QLabel("Provider:"))
        self.combo_ai_provider = QComboBox()
        self.combo_ai_provider.addItems(["", "openai", "anthropic", "deepseek", "custom"])
        ai_provider = self.config.get("ai", {}).get("provider", "")
        idx = self.combo_ai_provider.findText(ai_provider)
        if idx >= 0:
            self.combo_ai_provider.setCurrentIndex(idx)
        ai_layout.addWidget(self.combo_ai_provider)

        ai_layout.addWidget(QLabel("API Key:"))
        self.edit_api_key = QLineEdit()
        self.edit_api_key.setEchoMode(QLineEdit.Password)
        self.edit_api_key.setText(self.config.get("ai", {}).get("api_key", ""))
        self.edit_api_key.setPlaceholderText("输入 API Key...")
        ai_layout.addWidget(self.edit_api_key)

        ai_layout.addWidget(QLabel("Base URL:"))
        self.edit_base_url = QLineEdit()
        self.edit_base_url.setPlaceholderText("自定义端点 (可选)")
        self.edit_base_url.setText(self.config.get("ai", {}).get("base_url", ""))
        ai_layout.addWidget(self.edit_base_url)

        ai_layout.addWidget(QLabel("模型:"))
        self.edit_model = QLineEdit()
        self.edit_model.setPlaceholderText("如 gpt-4o-mini, deepseek-chat")
        self.edit_model.setText(self.config.get("ai", {}).get("model", ""))
        ai_layout.addWidget(self.edit_model)

        ai_layout.addWidget(QLabel("鉴权方式 (仅 anthropic):"))
        self.combo_ai_auth_style = QComboBox()
        self.combo_ai_auth_style.addItems(["x-api-key", "bearer"])
        self.combo_ai_auth_style.setToolTip(
            "x-api-key: 官方 Anthropic API\n"
            "bearer: 部分中转网关 (Authorization: Bearer)"
        )
        auth_style = self.config.get("ai", {}).get("auth_style", "x-api-key")
        idx = self.combo_ai_auth_style.findText(auth_style)
        if idx >= 0:
            self.combo_ai_auth_style.setCurrentIndex(idx)
        ai_layout.addWidget(self.combo_ai_auth_style)

        # 保存按钮
        self.btn_save_ai = QPushButton("💾 保存 AI 配置")
        self.btn_save_ai.setStyleSheet("""
            QPushButton {
                background-color: #2d5a8e; color: #ffffff;
                padding: 8px 16px; border: 1px solid #4a9eff;
                border-radius: 4px; font-size: 15px; font-weight: bold;
            }
            QPushButton:hover { background-color: #3a7ac0; }
            QPushButton:pressed { background-color: #1e4a70; }
        """)
        self.btn_save_ai.clicked.connect(self._on_save_ai_clicked)
        ai_layout.addWidget(self.btn_save_ai)

        layout.addWidget(ai_group)
        layout.addStretch()

        return tab

    def _build_log_tab(self) -> QWidget:
        """构建操作日志 Tab。"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # ---- 顶部按钮栏 ----
        btn_bar = QHBoxLayout()

        self.btn_ai_analysis = QPushButton("🤖 AI 分析")
        self.btn_ai_analysis.setStyleSheet("""
            QPushButton {
                background-color: #2d5a8e; color: #ffffff;
                padding: 8px 20px; border: 1px solid #4a9eff;
                border-radius: 4px; font-size: 15px; font-weight: bold;
            }
            QPushButton:hover { background-color: #3a7ac0; }
            QPushButton:pressed { background-color: #1e4a70; }
            QPushButton:disabled { background-color: #3c3c3c; color: #666666; border-color: #555555; }
        """)
        self.btn_ai_analysis.setToolTip("手动触发 AI 复盘分析（需先结束训练并配置 AI）")
        self.btn_ai_analysis.clicked.connect(self._on_ai_analysis_clicked)

        self.btn_export_prompt = QPushButton("📋 导出 Prompt")
        self.btn_export_prompt.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c; color: #cccccc;
                padding: 8px 20px; border: 1px solid #555555;
                border-radius: 4px; font-size: 15px;
            }
            QPushButton:hover { background-color: #505050; }
        """)
        self.btn_export_prompt.setToolTip("导出分析 Prompt 到剪贴板（无需 API Key）")
        self.btn_export_prompt.clicked.connect(self._on_export_prompt_clicked)

        btn_bar.addWidget(self.btn_ai_analysis)
        btn_bar.addWidget(self.btn_export_prompt)
        btn_bar.addStretch()
        layout.addLayout(btn_bar)

        # ---- 日志文本框 ----
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a; color: #cccccc;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 16px; border: 1px solid #3c3c3c;
            }
        """)
        layout.addWidget(self.log_text)
        return tab

    def _build_bottom_bar(self) -> QWidget:
        """构建底部操作按钮栏。"""
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(4, 2, 4, 2)

        btn_style = """
            QPushButton {
                background-color: #3c3c3c; color: #cccccc;
                padding: 6px 16px; border: 1px solid #555555;
                border-radius: 4px; font-size: 15px;
            }
            QPushButton:hover { background-color: #505050; }
            QPushButton:pressed { background-color: #2a2a2a; }
        """
        btn_buy_style = """
            QPushButton {
                background-color: #5a2020; color: #ff6666;
                padding: 6px 16px; border: 1px solid #ff4444;
                border-radius: 4px; font-size: 15px; font-weight: bold;
            }
            QPushButton:hover { background-color: #7a3030; }
        """
        btn_sell_style = """
            QPushButton {
                background-color: #1a4a1a; color: #66ff66;
                padding: 6px 16px; border: 1px solid #00cc00;
                border-radius: 4px; font-size: 15px; font-weight: bold;
            }
            QPushButton:hover { background-color: #2a6a2a; }
        """

        buttons = [
            ("⏪ 前一天", self.prev_day, btn_style),
            ("⏩ 后一天", self.next_day, btn_style),
            ("⏭ 快进10", self.fast_forward, btn_style),
            ("⏹ 结束训练", self.end_training, btn_style),
            ("📈 买入", lambda: self.do_buy(), btn_buy_style),
            ("📉 卖出", lambda: self.do_sell(), btn_sell_style),
        ]

        for text, slot, style in buttons:
            btn = QPushButton(text)
            btn.setStyleSheet(style)
            btn.clicked.connect(slot)
            layout.addWidget(btn)

        return bar

    # ============================================================
    # 数据加载器初始化
    # ============================================================
    def _init_data_loader(self):
        """尝试初始化数据加载器。"""
        tdx_home = self.tdx_path_edit.text().strip()
        try:
            self.data_loader = DataLoader(tdx_home or None)
            if self.data_loader.is_available():
                self.log(f"✅ 通达信目录: {self.data_loader.tdx_home}")
                self.tdx_path_edit.setText(str(self.data_loader.tdx_home))
                if hasattr(self, "_home_hint"):
                    self._home_hint.setText("")
            else:
                self.log("⚠ 未找到通达信数据目录，请手动选择")
        except Exception as e:
            self.log(f"⚠ 初始化失败: {e}")

    def _on_browse_tdx(self):
        """浏览选择通达信安装目录。"""
        path = QFileDialog.getExistingDirectory(self, "选择通达信安装目录")
        if path:
            self.tdx_path_edit.setText(path)
            self.data_loader = DataLoader(path)
            if self.data_loader.is_available():
                self.log(f"✅ 已选择: {path}")
                self.config["tdx_home"] = path
                save_config(self.config)
            else:
                self.log(f"⚠ 目录无效: {path}")

    # ============================================================
    # 训练控制
    # ============================================================
    def start_training(self):
        """开始新的训练会话（后台加载 + 遮罩动画）。"""
        # 防止重复点击
        if hasattr(self, '_loading_overlay') and self._loading_overlay is not None:
            return

        # 检查数据加载器
        if not self.data_loader or not self.data_loader.is_available():
            path = self.tdx_path_edit.text().strip()
            if path:
                self.data_loader = DataLoader(path)
            else:
                self.data_loader = DataLoader()

            if not self.data_loader.is_available():
                QMessageBox.warning(
                    self, "数据源不可用",
                    "未找到通达信数据目录。\n"
                    "请在右侧面板选择通达信安装目录。"
                )
                return

        # 保存 AI 配置
        self._save_ai_config()

        # 保存模式配置
        self._save_mode_config()

        # 重置状态
        self.trade_manager.reset()
        self.weekly_df = None
        self.weekly_cursor = 0
        self.sector_peers = []
        self.sector_cursors = {}
        self.quiz_state = None
        self._clear_mode_widgets()
        days = self.spin_days.value()

        # 设置止损止盈
        self._apply_sl_tp()

        ma_periods = self._parse_ma_periods()
        self.config["ma_periods"] = ma_periods

        # 答题模式走独立流程（题库检查 → 逐题加载）
        if self.current_mode == "quiz":
            self._quiz_start_session()
            return

        # 显示遮罩
        self._loading_overlay = LoadingOverlay(self.centralWidget())
        self._loading_overlay.show()
        self._loading_overlay.raise_()

        # 启动后台线程
        self._load_worker = LoadWorker(
            self.data_loader, days, ma_periods, self.config
        )
        self._load_worker.status.connect(self._on_load_status)
        self._load_worker.finished_ok.connect(self._on_load_done)
        self._load_worker.finished_err.connect(self._on_load_error)
        self._load_worker.start()

    def _on_load_status(self, text: str):
        """后台加载进度回调。"""
        self.log(f"🔍 {text}")
        if self._loading_overlay:
            self._loading_overlay.set_text(text)

    def _on_load_done(self, df, stock_code, hub, warmup,
                      start_cursor: int = None, quiz_event: dict = None):
        """后台加载完成回调。

        start_cursor: 初始可见K线位置（答题模式定位到信号日；普通模式=warmup）
        quiz_event: 答题模式当前题目（来自 SignalBank.draw_question）
        """
        self._hide_loading()

        self.df = df
        self.stock_code = stock_code
        self.indicator_hub = hub
        self.min_warmup = warmup
        self.cursor = start_cursor if start_cursor is not None else warmup

        self.log(f"✅ 选中: {stock_code}, 数据量: {len(df)} 根K线")
        self.log("📈 指标计算完成")

        # 设置画布数据
        self.chart.set_data(self.df, self.indicator_hub, self.trade_manager)
        self.chart.setup_panels(self.spin_panel_count.value())
        self.chart.scroll_to_latest(self.cursor)
        overlays = self._get_enabled_overlays()
        sub_inds = self._get_sub_indicators()
        self.chart.render(self.cursor, sub_inds, overlays)

        self.training_active = True
        if hasattr(self, "main_stack"):
            self.main_stack.setCurrentIndex(1)   # 确保训练页可见
        if self.current_mode == "quiz":
            self.log(f"🎯 答题开始! 当前可见 {self.cursor}/{len(self.df)} 根K线")
        else:
            self.log(f"🎮 训练开始! 当前可见 {self.cursor}/{len(self.df)} 根K线")

        # ---- 模式初始化 ----
        try:
            mode = self.current_mode
            if mode in ("multi_tf", "comprehensive"):
                self.weekly_df = DataLoader.resample_weekly(self.df)

            if mode in ("sector", "comprehensive"):
                self._load_sector_peers_sync()
        except Exception as e:
            self.log(f"⚠ 模式数据准备失败: {e}")

        self._setup_mode_widgets()

        if self.current_mode == "quiz":
            state_label = "答题中" if quiz_event is None else "出题"
            self.statusBar().showMessage(
                f"{state_label} | {self.stock_code} | "
                f"进度: {self.cursor}/{len(self.df)}")
        else:
            self.statusBar().showMessage(
                f"训练中 | {self.stock_code} | 进度: {self.cursor}/{len(self.df)} | 仓位: 0%"
            )

        # ---- 答题模式：展示题目 ----
        if quiz_event is not None and self.quiz_panel is not None:
            self.quiz_panel.begin_question(
                self.quiz_state["no"], self.quiz_state["total"], quiz_event)

    def _on_load_error(self, err_msg: str):
        """后台加载失败回调。"""
        self._hide_loading()
        self.log(f"❌ 启动训练失败: {err_msg}")
        QMessageBox.critical(self, "启动失败", err_msg)

    def _hide_loading(self):
        """隐藏并销毁加载遮罩。"""
        if self._loading_overlay:
            self._loading_overlay.cleanup()
            self._loading_overlay.hide()
            self._loading_overlay.deleteLater()
            self._loading_overlay = None

    # ============================================================
    # 答题模式
    # ============================================================
    def _quiz_start_session(self):
        """开始答题会话：检查题库 → 初始化状态 → 出第一题。"""
        if not self.signal_bank.is_built():
            ret = QMessageBox.question(
                self, "构建题库",
                "首次使用答题模式需要构建题库（扫描全市场历史数据，"
                "约 3-5 分钟，之后可重复使用）。\n\n现在构建吗？")
            if ret != QMessageBox.Yes:
                return
            self._bank_build_reason = "quiz"
            self._quiz_build_bank()
            return

        total = int(self.config.get("mode", {}).get("quiz_questions", 10))
        self.quiz_state = {"total": total, "no": 0, "answers": []}
        self.log(f"🎯 答题模式开始，共 {total} 题。按 1/2/3 作答，回车下一题。")
        self._quiz_load_question()

    def _quiz_build_bank(self):
        """后台构建题库，带进度遮罩。"""
        self._loading_overlay = LoadingOverlay(self.centralWidget())
        self._loading_overlay.set_text("准备构建题库")
        self._loading_overlay.show()
        self._loading_overlay.raise_()

        self._bank_worker = BankBuildWorker(self.data_loader, self.signal_bank)
        self._bank_worker.progress.connect(self._on_bank_progress)
        self._bank_worker.built.connect(self._on_bank_built)
        self._bank_worker.failed.connect(self._on_bank_failed)
        self._bank_worker.start()

    def _on_bank_progress(self, text: str):
        if self._loading_overlay:
            self._loading_overlay.set_text(text)
        self.log(f"⏳ {text}")

    def _on_bank_built(self, count: int):
        self._hide_loading()
        self.log(f"✅ 题库构建完成，共 {count} 道题")
        if getattr(self, "_bank_build_reason", "quiz") == "quiz":
            self._quiz_start_session()
        else:
            QMessageBox.information(
                self, "题库已重建", f"题库构建完成，共 {count} 道题。")

    def _on_bank_failed(self, err_msg: str):
        self._hide_loading()
        self.log(f"❌ 题库构建失败: {err_msg}")
        QMessageBox.critical(self, "题库构建失败", err_msg)

    def _quiz_load_question(self):
        """从题库抽题并后台加载对应股票数据。"""
        event = self.signal_bank.draw_question()
        if event is None:
            QMessageBox.warning(
                self, "题库为空",
                "题库中没有题目。请通过菜单或重新进入答题模式构建题库。")
            return

        self.quiz_state["no"] += 1
        ma_periods = self.config.get("ma_periods", [5, 10, 20, 30, 60, 120])

        self._loading_overlay = LoadingOverlay(self.centralWidget())
        self._loading_overlay.set_text(
            f"加载第 {self.quiz_state['no']}/{self.quiz_state['total']} 题")
        self._loading_overlay.show()
        self._loading_overlay.raise_()

        self._quiz_worker = QuizLoadWorker(
            self.data_loader, ma_periods, self.config, event)
        self._quiz_worker.finished_ok.connect(self._on_quiz_load_done)
        self._quiz_worker.finished_err.connect(self._on_load_error)
        self._quiz_worker.start()

    def _on_quiz_load_done(self, df, stock_code, hub, warmup,
                           start_cursor, event):
        """题目数据加载完成 → 复用统一加载回调展示题目。"""
        self._on_load_done(df, stock_code, hub, warmup, start_cursor, event)

    def _on_quiz_answered(self, record: dict):
        """收集作答记录，结束时统一入库。"""
        self.quiz_state["answers"].append(record)

    def _quiz_next(self):
        """揭晓后进入下一题或结束会话。"""
        if not self.quiz_state:
            return
        if self.quiz_state["no"] >= self.quiz_state["total"]:
            self.end_training()
        else:
            self._quiz_load_question()

    def next_day(self):
        """推演下一天（→键）。"""
        if not self.training_active or self.df is None:
            return
        if self.cursor < len(self.df):
            self.cursor += 1
            # 更新浮动盈亏
            row = self.df.iloc[self.cursor - 1]
            self.trade_manager.update_floating(row["high"], row["low"])
            # 检查止损止盈
            self._check_sl_tp()
            # 跟随最新 bar
            self.chart.scroll_to_latest(self.cursor)
            self._refresh_chart()
            self.statusBar().showMessage(
                f"训练中 | {self.stock_code} | 进度: {self.cursor}/{len(self.df)} | "
                f"仓位: {self.trade_manager.position*100:.0f}%"
            )
            self._update_mode_on_advance()
            if self.cursor >= len(self.df):
                if self.current_mode == "quiz":
                    return   # 答题模式：20根播放完毕由揭晓面板控制节奏
                self.log("🏁 已到达最后一根K线")
                self.end_training()

    def prev_day(self):
        """回退前一天（←键）。"""
        if not self.training_active or self.df is None:
            return
        if self.cursor > self.min_warmup:
            self.cursor -= 1
            self._refresh_chart()
            if self.timer_bar:
                self.timer_bar.stop()
            if self.multi_tf_canvas and self.current_mode in ("multi_tf", "comprehensive"):
                self._update_weekly_cursor()
                self.multi_tf_canvas.render(self.weekly_cursor)
            if self.sector_panel and self.current_mode in ("sector", "comprehensive"):
                self._update_sector_cursors()
                self.sector_panel.render(self.sector_cursors)
            if self.psychology_tracker and self.current_mode == "comprehensive":
                self.psychology_tracker.set_cursor(self.cursor)
            self.statusBar().showMessage(
                f"训练中 | {self.stock_code} | 进度: {self.cursor}/{len(self.df)} | "
                f"仓位: {self.trade_manager.position*100:.0f}%"
            )

    def fast_forward(self):
        """快进10天（PgDn键），逐根检查止损止盈。"""
        if not self.training_active or self.df is None:
            return
        if self.timer_bar:
            self.timer_bar.stop()
        target = min(self.cursor + 10, len(self.df))
        while self.cursor < target:
            self.cursor += 1
            row = self.df.iloc[self.cursor - 1]
            self.trade_manager.update_floating(row["high"], row["low"])
            # 持仓时检查止损止盈
            if self.trade_manager.position > 0:
                trigger = self.trade_manager.check_stop_loss_take_profit(
                    self.cursor - 1, row["high"], row["low"], row["date"]
                )
                if trigger:
                    self._execute_auto_exit(trigger, self.cursor - 1, row)
                    break  # 自动退出后停止推进
        self.chart.scroll_to_latest(self.cursor)
        self._refresh_chart()
        self._update_mode_on_advance()
        self.statusBar().showMessage(
            f"训练中 | {self.stock_code} | 进度: {self.cursor}/{len(self.df)} | "
            f"仓位: {self.trade_manager.position*100:.0f}%"
        )
        if self.cursor >= len(self.df):
            self.log("🏁 已到达最后一根K线")
            self.end_training()

    def do_buy(self, ratio: float = None):
        """模拟买入。"""
        if not self.training_active or self.df is None:
            return
        if ratio is None:
            ratio = self.default_buy_ratio
        price = self.df.iloc[self.cursor - 1]["close"]
        date = self.df.iloc[self.cursor - 1]["date"]
        if self.trade_manager.buy(self.cursor - 1, price, date, ratio):
            pct = ratio * 100
            self.log(
                f"📈 买入 {pct:.0f}% @ {price:.2f} ({date}) "
                f"仓位:{self.trade_manager.position*100:.0f}%"
            )
            self._refresh_chart()
        else:
            self.log("⚠ 已满仓，无法继续买入")

    def do_sell(self, ratio: float = None):
        """模拟卖出。"""
        if not self.training_active or self.df is None:
            return
        if ratio is None:
            ratio = self.default_sell_ratio
        price = self.df.iloc[self.cursor - 1]["close"]
        date = self.df.iloc[self.cursor - 1]["date"]
        if self.trade_manager.sell(self.cursor - 1, price, date, ratio):
            pct = ratio * 100
            self.log(
                f"📉 卖出 {pct:.0f}% @ {price:.2f} ({date}) "
                f"仓位:{self.trade_manager.position*100:.0f}%"
            )
            self._refresh_chart()
        else:
            self.log("⚠ 当前空仓，无法卖出")

    def end_training(self):
        """结束训练（Esc键）。"""
        if not self.training_active:
            return
        self.training_active = False

        # 停止计时器
        if self.timer_bar:
            self.timer_bar.stop()

        # 显示全部 K 线
        self.cursor = len(self.df)
        self.chart.show_all(self.cursor)
        self._refresh_chart()

        # 导出完整K线图 PNG（供 AI 视觉复盘）
        self._last_chart_png = b""
        try:
            import io
            buf = io.BytesIO()
            self.chart.fig.savefig(
                buf, format="png",
                facecolor=self.chart.fig.get_facecolor())
            self._last_chart_png = buf.getvalue()
        except Exception as e:
            self.log(f"⚠ 复盘图导出失败: {e}")

        # 计算时机评分
        self.trade_manager.score_all_timing(self.df)

        last_price = self.df.iloc[-1]["close"]
        summary = self.trade_manager.summary(last_price)
        self.log(summary)

        # 小结数据（与 db.save_session 同口径）
        completed = self.trade_manager.get_completed_trades()
        total_return = sum(ct.return_pct for ct in completed)
        if (self.trade_manager.portfolio.position > 0
                and self.trade_manager.portfolio.avg_cost > 0):
            total_return += (last_price / self.trade_manager.portfolio.avg_cost
                             - 1.0) * 100.0
        if len(self.df) > 30:
            buy_hold = (last_price / self.df.iloc[30]["close"] - 1.0) * 100.0
        else:
            buy_hold = 0.0
        win_count = sum(1 for ct in completed if ct.return_pct > 0)
        summary_stats = {
            "total_return": total_return,
            "buy_hold": buy_hold,
            "trade_count": len(completed),
            "win_count": win_count,
        }

        # 答题模式：收集作答记录
        quiz_answers = None
        if self.current_mode == "quiz" and self.quiz_state:
            quiz_answers = self.quiz_state["answers"]

        # 生成报告
        report_path = ""
        report_text = ""
        try:
            report_path, report_text = generate_report(
                stock_code=self.stock_code,
                df=self.df,
                indicator_hub=self.indicator_hub,
                trade_manager=self.trade_manager,
                cursor=self.cursor,
                config=self.config,
                quiz_answers=quiz_answers,
            )
            self.log(f"📄 训练报告已保存: {report_path}")
        except Exception as e:
            self.log(f"❌ 报告生成失败: {e}")

        # 保存到数据库
        try:
            session_id = self.db.save_session(
                self.stock_code, self.df, self.trade_manager,
                report_path, self.config,
            )
            self.log(f"💾 训练记录已保存 (ID: {session_id})")
        except Exception as e:
            self.log(f"❌ 数据库保存失败: {e}")
            session_id = None

        # 答题记录入库
        if quiz_answers and session_id is not None:
            try:
                self.db.save_quiz_answers(session_id, quiz_answers)
                n = len(quiz_answers)
                correct = sum(1 for a in quiz_answers if a["is_correct"])
                pct = (correct / n * 100) if n else 0.0
                self.log(f"📝 答题结果: {correct}/{n} 正确 ({pct:.0f}%)，已入库")
            except Exception as e:
                self.log(f"❌ 答题记录保存失败: {e}")

        # AI 分析 — 保存最新配置后提示用户手动触发
        self._save_ai_config()
        self._last_report_path = report_path
        self._last_report_text = report_text
        self._last_summary = summary
        if report_text:
            if self.ai_analyzer.is_configured():
                self.log("💡 训练结束。点击日志 Tab 中的「🤖 AI 分析」按钮获取 AI 复盘。")
            else:
                self.log("💡 AI 未配置。可在配置面板设置 API Key，或点击「📋 导出 Prompt」手动分析。")

        self.statusBar().showMessage(
            f"训练结束 | {self.stock_code} | 报告: {report_path}"
        )

        # 导出心理状态数据到报告
        if self.psychology_tracker and self.current_mode == "comprehensive":
            psych_md = self.psychology_tracker.export_for_report()
            if psych_md and report_path:
                try:
                    from pathlib import Path as PPath
                    p = PPath(report_path)
                    if p.is_file():
                        with open(p, "a", encoding="utf-8") as f:
                            f.write("\n\n")
                            f.write(psych_md)
                        self.log("🧠 心理状态数据已追加到报告")
                except Exception as e:
                    self.log(f"⚠ 心理状态数据保存失败: {e}")

        # 清理模式组件
        self._clear_mode_widgets()

        # 训练小结弹窗（可选触发 AI 复盘），关闭后返回首页
        self._show_session_summary(summary_stats, quiz_answers)
        self._go_home()

    def _show_session_summary(self, stats: dict, quiz_answers: list = None):
        """弹出训练小结，用户选择 AI 复盘时接续触发。"""
        try:
            dlg = SessionSummaryDialog(
                self, self.stock_code or "未知", self.current_mode,
                stats, quiz_answers)
            if dlg.exec() == SessionSummaryDialog.RET_AI:
                self._on_ai_analysis_clicked()
        except Exception as e:
            self.log(f"⚠ 小结弹窗显示失败: {e}")

    def _show_shortcut_help(self):
        """快捷键速查。"""
        QMessageBox.information(
            self, "⌨ 快捷键速查",
            "→ 前进  |  ← 后退  |  PgDn 快进10\n"
            "1/2/3/4 买入 25%/33%/50%/100%\n"
            "Shift+1/2/3/4 卖出对应仓位\n"
            "↑ 买入(默认仓位)  ↓ 卖出(默认仓位)\n"
            "Space 观望  |  Esc 结束训练\n\n"
            "答题模式：1 买入 / 2 观望 / 3 清仓，回车下一题\n"
            "（答题模式下交易与推进键自动屏蔽）")
    # ============================================================
    def _apply_sl_tp(self):
        """把面板里的止损/止盈百分比写入 trade_manager（0 表示不启用）。"""
        sl_pct = self.spin_stop_loss.value()
        tp_pct = self.spin_take_profit.value()
        self.trade_manager.set_stop_loss(-sl_pct / 100.0 if sl_pct > 0 else None)
        self.trade_manager.set_take_profit(tp_pct / 100.0 if tp_pct > 0 else None)

    def _on_sl_tp_changed(self, _value=None):
        """训练中修改止损/止盈阈值：即时生效并立刻对当前 bar 复检一次。"""
        self._apply_sl_tp()
        if self.training_active:
            sl_pct = self.spin_stop_loss.value()
            tp_pct = self.spin_take_profit.value()
            self.log(
                f"⚙ 止损止盈已更新: "
                f"止损 {sl_pct:.1f}% / 止盈 {tp_pct:.1f}%"
            )
            # 新阈值可能已被当前 K 线触及，立即检查一次
            self._check_sl_tp()
            self._refresh_chart()

    def _check_sl_tp(self):
        """检查当前 bar 是否触发止损止盈。"""
        if self.trade_manager.position <= 0:
            return
        idx = self.cursor - 1
        row = self.df.iloc[idx]
        trigger = self.trade_manager.check_stop_loss_take_profit(
            idx, row["high"], row["low"], row["date"]
        )
        if trigger:
            self._execute_auto_exit(trigger, idx, row)

    def _execute_auto_exit(self, trigger: str, idx: int, row):
        """执行自动止损/止盈卖出。"""
        if trigger == "stop_loss":
            price = row["low"]  # 止损以最低价成交（保守）
            self.trade_manager.sell(idx, price, row["date"], 1.0,
                                    is_auto=True, auto_reason="stop_loss")
            self.log(f"🔴 [自动止损] @ {price:.2f} ({row['date']})")
        elif trigger == "take_profit":
            price = row["high"]  # 止盈以最高价成交（乐观）
            self.trade_manager.sell(idx, price, row["date"], 1.0,
                                    is_auto=True, auto_reason="take_profit")
            self.log(f"🟢 [自动止盈] @ {price:.2f} ({row['date']})")

    # ============================================================
    # AI 回调
    # ============================================================
    def _on_ai_success(self, analysis_text: str, report_path: str):
        """AI 分析成功回调。"""
        self.log("✅ AI 分析完成!")
        self.btn_ai_analysis.setEnabled(True)
        self.btn_ai_analysis.setText("🤖 AI 分析")

        worker = getattr(self.ai_analyzer, "worker", None)
        if getattr(worker, "degraded", False):
            self.log("ℹ 当前模型不支持图片输入，已自动降级为纯文本分析。")

        # 1) 显示在日志中
        self.log("──── AI 复盘分析 ────")
        for line in analysis_text.split("\n"):
            if line.strip():
                self.log(line)
        self.log("──── 分析结束 ────")

        # 2) 追加到报告文件
        if report_path:
            try:
                from pathlib import Path as PPath
                p = PPath(report_path)
                if p.is_file():
                    with open(p, "a", encoding="utf-8") as f:
                        f.write("\n\n## AI 复盘分析\n\n")
                        f.write(analysis_text)
                    self.log(f"📄 AI 分析已追加到报告: {report_path}")
            except Exception as e:
                self.log(f"⚠ 追加 AI 分析到报告失败: {e}")

        # 3) 保存到 docs/ 目录为独立 MD 文件
        try:
            docs_dir = Path(__file__).parent / "docs"
            docs_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stock = self.stock_code or "unknown"
            ai_path = docs_dir / f"ai_analysis_{stock}_{timestamp}.md"
            with open(ai_path, "w", encoding="utf-8") as f:
                f.write(f"# AI 复盘分析 — {stock}\n\n")
                f.write(f"**分析时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(analysis_text)
            self.log(f"💾 AI 分析已保存: {ai_path}")
        except Exception as e:
            self.log(f"⚠ 保存 AI 分析文件失败: {e}")

    def _on_ai_error(self, error_msg: str):
        """AI 分析失败回调。"""
        self.log(f"⚠ AI 分析失败: {error_msg}")
        self.log("💡 可使用「📋 导出 Prompt」功能手动分析。")
        self.btn_ai_analysis.setEnabled(True)
        self.btn_ai_analysis.setText("🤖 AI 分析")

    def _on_ai_analysis_clicked(self):
        """手动触发 AI 分析按钮回调。"""
        # 先保存最新 AI 配置
        self._save_ai_config()

        if not self.ai_analyzer.is_configured():
            QMessageBox.warning(
                self, "AI 未配置",
                "请先在「⚙ 配置」Tab 中设置 AI Provider 和 API Key。\n\n"
                "支持 OpenAI / Anthropic / DeepSeek / 自定义端点。"
            )
            return

        report_text = getattr(self, "_last_report_text", "")
        summary = getattr(self, "_last_summary", "")
        report_path = getattr(self, "_last_report_path", "")

        if not report_text:
            QMessageBox.information(
                self, "无报告数据",
                "请先完成一次训练（按 Esc 结束），再进行 AI 分析。"
            )
            return

        # 禁用按钮防止重复点击
        self.btn_ai_analysis.setEnabled(False)
        self.btn_ai_analysis.setText("🤖 分析中...")
        self.log("🤖 正在调用 AI 分析，请稍候（最长约 2 分钟）...")

        # 视觉复盘：把完整K线图一并发给模型（模型不支持时自动降级纯文本）
        chart_png = None
        if self.config.get("ai", {}).get("send_chart", True):
            chart_png = getattr(self, "_last_chart_png", b"") or None

        self.ai_analyzer.analyze_async(
            report_text, summary,
            on_success=lambda text: self._on_ai_success(text, report_path),
            on_error=self._on_ai_error,
            chart_png=chart_png,
        )

    def _on_export_prompt_clicked(self):
        """导出 Prompt 到剪贴板。"""
        self._save_ai_config()

        report_text = getattr(self, "_last_report_text", "")
        summary = getattr(self, "_last_summary", "")

        if not report_text:
            QMessageBox.information(
                self, "无报告数据",
                "请先完成一次训练（按 Esc 结束），再导出 Prompt。"
            )
            return

        prompt = self.ai_analyzer.export_prompt(report_text, summary)
        clipboard = QApplication.clipboard()
        clipboard.setText(prompt)
        self.log("📋 分析 Prompt 已复制到剪贴板，可粘贴到任意 AI 工具使用。")

    # ============================================================
    # 图表刷新辅助
    # ============================================================
    def _refresh_chart(self):
        """刷新图表。"""
        overlays = self._get_enabled_overlays()
        sub_inds = self._get_sub_indicators()
        self.chart.render(self.cursor, sub_inds, overlays)

    def _get_sub_indicators(self) -> list:
        """获取当前各副图选中的指标名称列表。"""
        count = self.spin_panel_count.value()
        result = []
        for i in range(min(count, len(self.combo_subs))):
            result.append(self.combo_subs[i].currentText())
        return result

    def _get_enabled_overlays(self) -> list:
        """获取当前启用的主图叠加指标列表。"""
        overlays = []
        if self.chk_ma.isChecked():
            overlays.append("MA")
        if self.chk_bbi.isChecked():
            overlays.append("BBI")
        if self.chk_expma.isChecked():
            overlays.append("EXPMA")
        if self.chk_boll.isChecked():
            overlays.append("BOLL")
        return overlays

    def _parse_ma_periods(self) -> list[int]:
        """解析均线周期输入框，返回有效的周期列表。"""
        text = self.edit_ma_periods.text().strip()
        periods = []
        for part in text.replace("，", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                p = int(part)
                if 1 <= p <= 250:
                    periods.append(p)
            except ValueError:
                continue
        # 最多 6 条
        return periods[:6] if periods else [5, 10, 20, 30, 60, 120]

    def _on_ma_periods_changed(self):
        """均线周期输入框编辑完成回调。"""
        periods = self._parse_ma_periods()
        self.edit_ma_periods.setText(",".join(str(p) for p in periods))
        self.config["ma_periods"] = periods
        if self.indicator_hub is not None:
            self.indicator_hub.ma_periods = periods
            self.indicator_hub.calculate_all()
        if self.training_active or self.df is not None:
            self._refresh_chart()

    # ============================================================
    # 配置保存
    # ============================================================
    def _save_ai_config(self):
        """保存 AI 配置到 config。"""
        self.config["ai"] = {
            "provider": self.combo_ai_provider.currentText(),
            "api_key": self.edit_api_key.text(),
            "base_url": self.edit_base_url.text(),
            "model": self.edit_model.text(),
            "auth_style": self.combo_ai_auth_style.currentText(),
            # 非面板项：保留原值（无则取默认）
            "send_chart": self.config.get("ai", {}).get("send_chart", True),
        }
        # 更新 AI analyzer 的配置引用
        self.ai_analyzer.config = self.config
        save_config(self.config)

    def _save_mode_config(self):
        """保存训练模式配置到 config。"""
        self.config["mode"] = {
            "current": self.current_mode,
            "timed_seconds": int(self.combo_timed_seconds.currentText()),
            "sector_peer_count": self.spin_peer_count.value(),
        }
        save_config(self.config)

    def _on_save_ai_clicked(self):
        """AI 配置保存按钮回调。"""
        self._save_ai_config()
        self.log("✅ AI 配置已保存到 config.yaml")
        self.btn_save_ai.setText("✅ 已保存")
        # 2秒后恢复按钮文字
        try:
            from PySide6.QtCore import QTimer
        except ImportError:
            from PyQt5.QtCore import QTimer
        QTimer.singleShot(2000, lambda: self.btn_save_ai.setText("💾 保存 AI 配置"))

    # ============================================================
    # 事件回调
    # ============================================================
    def _update_combo_visibility(self):
        """根据面板数量显示/隐藏副图指标下拉框。"""
        count = self.spin_panel_count.value()
        for i, widget in enumerate(self.sub_indicator_widgets):
            widget.setVisible(i < count)

    def _on_panel_count_changed(self, value: int):
        """副图面板数量变化回调。"""
        self._update_combo_visibility()
        if self.training_active or self.df is not None:
            self.chart.setup_panels(value)
            self._refresh_chart()

    def _on_indicator_changed(self, name: str):
        """副图指标切换回调。"""
        if self.training_active or self.df is not None:
            self._refresh_chart()

    def _on_overlay_changed(self):
        """主图叠加指标切换回调。"""
        if self.training_active or self.df is not None:
            self._refresh_chart()

    # ============================================================
    # 训练模式管理
    # ============================================================
    def _on_mode_changed(self, index: int):
        """训练模式切换回调。"""
        modes = ["classic", "timed", "multi_tf", "sector", "comprehensive", "quiz"]
        if index < 0 or index >= len(modes):
            return
        self.current_mode = modes[index]

        self.timed_config_widget.setVisible(
            self.current_mode in ("timed", "comprehensive"))
        self.sector_config_widget.setVisible(
            self.current_mode in ("sector", "comprehensive"))

        self.config.setdefault("mode", {})["current"] = self.current_mode
        save_config(self.config)

        if self.training_active and self.df is not None:
            self._setup_mode_widgets()

    def _setup_mode_widgets(self):
        """创建当前模式的辅助组件并添加到图表下方。"""
        self._clear_mode_widgets()
        mode = self.current_mode

        try:
            if mode in ("timed", "comprehensive"):
                seconds = int(self.combo_timed_seconds.currentText())
                self.timer_bar = TimerBar(parent=self, seconds=seconds)
                self.timer_bar.setFocusPolicy(Qt.NoFocus)
                self.left_chart_layout.addWidget(self.timer_bar)
                self._mode_widgets.append(self.timer_bar)
                self.timer_bar.timeout.connect(self._on_timer_timeout)
                self.timer_bar.start()
        except Exception as e:
            self.log(f"⚠ 限时模式组件初始化失败: {e}")

        try:
            if mode in ("multi_tf", "comprehensive"):
                if self.weekly_df is None and self.df is not None:
                    self.weekly_df = DataLoader.resample_weekly(self.df)
                self.multi_tf_canvas = MultiTFCanvas(parent=self, height_px=180)
                self.left_chart_layout.addWidget(self.multi_tf_canvas)
                self._mode_widgets.append(self.multi_tf_canvas)
                if self.weekly_df is not None:
                    self.multi_tf_canvas.set_data(self.weekly_df)
                    self._update_weekly_cursor()
                    self.multi_tf_canvas.render(self.weekly_cursor)
        except Exception as e:
            self.log(f"⚠ 多周期组件初始化失败: {e}")

        try:
            if mode in ("sector", "comprehensive"):
                if not self.sector_peers and self.stock_code:
                    self._load_sector_peers_sync()
                peer_count = self.spin_peer_count.value()
                self.sector_panel = SectorPanel(parent=self, peer_count=peer_count)
                self.left_chart_layout.addWidget(self.sector_panel)
                self._mode_widgets.append(self.sector_panel)
                if self.sector_peers:
                    self.sector_panel.set_peers(self.sector_peers)
                    self._update_sector_cursors()
                    self.sector_panel.render(self.sector_cursors)
                else:
                    self.log("ℹ 未找到同板块股票，板块联动面板为空")
        except Exception as e:
            self.log(f"⚠ 板块联动组件初始化失败: {e}")

        try:
            if mode == "comprehensive":
                self.psychology_tracker = PsychologyTracker(parent=self)
                self.psychology_tracker.setFocusPolicy(Qt.NoFocus)
                self.left_chart_layout.addWidget(self.psychology_tracker)
                self._mode_widgets.append(self.psychology_tracker)
                self.psychology_tracker.set_cursor(self.cursor)
        except Exception as e:
            self.log(f"⚠ 心理追踪组件初始化失败: {e}")

        try:
            if mode == "quiz":
                total = self.quiz_state["total"] if self.quiz_state else 10
                self.quiz_panel = QuizPanel(
                    parent=self, advance_cb=self.next_day, reveal_bars=20)
                self.quiz_panel.setFocusPolicy(Qt.NoFocus)
                self.left_chart_layout.addWidget(self.quiz_panel)
                self._mode_widgets.append(self.quiz_panel)
                self.quiz_panel.answered.connect(self._on_quiz_answered)
                self.quiz_panel.next_requested.connect(self._quiz_next)
        except Exception as e:
            self.log(f"⚠ 答题组件初始化失败: {e}")

    def _clear_mode_widgets(self):
        """移除所有模式辅助组件。"""
        if self.timer_bar:
            self.timer_bar.stop()
        for widget in self._mode_widgets:
            if hasattr(widget, "stop"):
                widget.stop()
            self.left_chart_layout.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
        self._mode_widgets.clear()
        self.timer_bar = None
        self.multi_tf_canvas = None
        self.sector_panel = None
        self.psychology_tracker = None
        self.quiz_panel = None

    def _update_mode_on_advance(self):
        """K 线前进后更新所有模式组件。"""
        if self.timer_bar and self.current_mode in ("timed", "comprehensive"):
            self.timer_bar.start()

        if self.multi_tf_canvas and self.current_mode in ("multi_tf", "comprehensive"):
            self._update_weekly_cursor()
            self.multi_tf_canvas.render(self.weekly_cursor)

        if self.sector_panel and self.current_mode in ("sector", "comprehensive"):
            self._update_sector_cursors()
            self.sector_panel.render(self.sector_cursors)

        if self.psychology_tracker and self.current_mode == "comprehensive":
            self.psychology_tracker.set_cursor(self.cursor)

    def _update_weekly_cursor(self):
        """将日线 cursor 映射到周线 cursor。"""
        if self.weekly_df is None or self.cursor <= 0:
            self.weekly_cursor = 0
            return
        daily_idx = self.cursor - 1
        indices_col = self.weekly_df.get("_daily_indices")
        if indices_col is not None:
            for w_idx, indices in enumerate(indices_col):
                if daily_idx in indices:
                    self.weekly_cursor = w_idx + 1
                    return
        self.weekly_cursor = len(self.weekly_df)

    def _update_sector_cursors(self):
        """将当前日线日期映射到每只同板块股票的 cursor。"""
        if self.df is None or self.cursor <= 0:
            return
        current_date = self.df.iloc[self.cursor - 1]["date"]
        for code, peer_df in self.sector_peers:
            mask = peer_df["date"] <= current_date
            self.sector_cursors[code] = mask.sum()

    def _load_sector_peers_sync(self):
        """同步加载同板块股票数据。"""
        try:
            peer_count = self.spin_peer_count.value()
            self.sector_peers = self.data_loader.load_sector_peers(
                self.stock_code, peer_count
            )
            if self.sector_peers:
                self.log(f"✅ 板块联动: 已加载 {len(self.sector_peers)} 只同板块股票")
            else:
                self.log("⚠ 未找到同板块股票数据")
        except Exception as e:
            self.log(f"⚠ 板块数据加载失败: {e}")
            self.sector_peers = []

    def _on_timer_timeout(self):
        """限时模式倒计时归零回调。"""
        self.log("⏰ 时间到! 自动前进")
        self.next_day()

    def _on_tab_changed(self, index: int):
        """Tab 切换回调。"""
        if index == 2:  # 统计面板
            self.stats_panel.refresh()

    def keyPressEvent(self, event):
        """键盘事件分发。"""
        if self._handle_key(event.key(), event.modifiers()):
            event.accept()
        else:
            super().keyPressEvent(event)

    def _handle_key(self, key, modifiers=None) -> bool:
        """
        统一处理按键逻辑。

        Args:
            key: 按键码
            modifiers: 修饰键（Shift 等）
        Returns:
            bool: 是否已处理
        """
        if modifiers is None:
            modifiers = Qt.NoModifier

        # F1 / ? 快捷键速查（任何界面可用）
        if key in (Qt.Key_F1, Qt.Key_Question):
            self._show_shortcut_help()
            return True

        # Qt 在 Shift+数字键时返回上档字符 key code，需归一化
        _SHIFT_NUM_MAP = {
            Qt.Key_Exclam: (Qt.Key_1, True),       # Shift+1 = !
            Qt.Key_At: (Qt.Key_2, True),            # Shift+2 = @
            Qt.Key_NumberSign: (Qt.Key_3, True),    # Shift+3 = #
            Qt.Key_Dollar: (Qt.Key_4, True),        # Shift+4 = $
        }
        if key in _SHIFT_NUM_MAP:
            key, _ = _SHIFT_NUM_MAP[key]
            modifiers |= Qt.ShiftModifier

        # 答题模式：1/2/3 作答，回车下一题，Esc 结束；屏蔽交易与推进键
        if (self.current_mode == "quiz" and self.training_active
                and self.quiz_panel is not None):
            if key == Qt.Key_Escape:
                self.end_training()
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self.quiz_panel.try_next()
                return True
            if key in (Qt.Key_1, Qt.Key_2, Qt.Key_3) and not (
                    modifiers & Qt.ShiftModifier):
                self.quiz_panel.answer_from_key(
                    (Qt.Key_1, Qt.Key_2, Qt.Key_3).index(key))
                return True
            if key in (Qt.Key_Right, Qt.Key_Left, Qt.Key_PageDown,
                       Qt.Key_Space, Qt.Key_Up, Qt.Key_Down, Qt.Key_4):
                return True    # 答题阶段屏蔽，防止误触交易/推进
            return False

        # 方向/翻页
        if key == Qt.Key_Right:
            self.next_day()
            return True
        elif key == Qt.Key_Left:
            self.prev_day()
            return True
        elif key == Qt.Key_PageDown:
            self.fast_forward()
            return True

        # 观望 / 结束
        elif key == Qt.Key_Space:
            if self.training_active:
                self.log("⏸ 观望")
            return True
        elif key == Qt.Key_Escape:
            self.end_training()
            return True

        # ↑↓ 使用默认仓位
        elif key == Qt.Key_Up:
            self.do_buy()
            return True
        elif key == Qt.Key_Down:
            self.do_sell()
            return True

        # 数字键 1-4：买入 / Shift+1-4：卖出
        elif key == Qt.Key_1:
            if modifiers & Qt.ShiftModifier:
                self.do_sell(0.25)
            else:
                self.do_buy(0.25)
            return True
        elif key == Qt.Key_2:
            if modifiers & Qt.ShiftModifier:
                self.do_sell(0.333)
            else:
                self.do_buy(0.333)
            return True
        elif key == Qt.Key_3:
            if modifiers & Qt.ShiftModifier:
                self.do_sell(0.50)
            else:
                self.do_buy(0.50)
            return True
        elif key == Qt.Key_4:
            if modifiers & Qt.ShiftModifier:
                self.do_sell(1.0)
            else:
                self.do_buy(1.0)
            return True

        return False

    def eventFilter(self, obj, event):
        """
        全局事件过滤器。

        拦截训练快捷键，但不在文本输入控件中拦截数字键。
        """
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            modifiers = event.modifiers()

            # 方向/功能键：始终拦截
            if key in (Qt.Key_Right, Qt.Key_Left, Qt.Key_PageDown,
                       Qt.Key_Space, Qt.Key_Escape):
                if self._handle_key(key, modifiers):
                    return True

            # ↑↓ 键：始终拦截
            if key in (Qt.Key_Up, Qt.Key_Down):
                if self._handle_key(key, modifiers):
                    return True

            # 数字键（含 Shift 上档）：仅在训练中且焦点不在文本控件时拦截
            _NUM_KEYS = (Qt.Key_1, Qt.Key_2, Qt.Key_3, Qt.Key_4,
                         Qt.Key_Exclam, Qt.Key_At, Qt.Key_NumberSign, Qt.Key_Dollar)
            if key in _NUM_KEYS:
                if self.training_active:
                    # 检查焦点是否在文本输入控件中
                    focus_widget = QApplication.focusWidget()
                    is_text_input = isinstance(focus_widget, (QLineEdit, QTextEdit, QSpinBox))
                    if not is_text_input:
                        if self._handle_key(key, modifiers):
                            return True

        return super().eventFilter(obj, event)

    # ============================================================
    # 日志
    # ============================================================
    def log(self, msg: str):
        """在操作日志中追加带时间戳的消息。"""
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self.log_text.append(f"[{timestamp}] {msg}")
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


# ============================================================
# 入口
# ============================================================
def main():
    """应用入口函数。"""

    # ===================== 使用期限 =====================
    EXPIRE_DATE = datetime(2026, 12, 31)
    # ===================================================

    if datetime.now() > EXPIRE_DATE:
        app = QApplication(sys.argv)
        QMessageBox.critical(
            None, "使用期限已到",
            f"本程序使用期限已于 {EXPIRE_DATE.strftime('%Y-%m-%d')} 到期。\n"
            "请联系开发者获取更新版本。"
        )
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec() if hasattr(app, 'exec') else app.exec_())


def _global_exception_hook(exc_type, exc_value, exc_tb):
    """全局异常钩子，将未捕获异常写入日志文件。"""
    import traceback as _tb
    from pathlib import Path as _P
    # 打包环境下 __file__ 在临时目录，用 exe 路径代替
    try:
        base = _P(sys.executable).parent
    except Exception:
        base = _P(__file__).parent
    log_path = base / "crash.log"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"崩溃时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            _tb.print_exception(exc_type, exc_value, exc_tb, file=f)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


if __name__ == "__main__":
    sys.excepthook = _global_exception_hook
    main()
