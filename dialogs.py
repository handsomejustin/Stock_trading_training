"""
盘感训练器 - 对话框集合

SessionSummaryDialog: 训练结束小结弹窗（收益/持有不动/择时超额/答题正确率）。
OnboardingDialog: 首次启动新手引导（数据源/快捷键/模式介绍 三页向导）。
"""

try:
    from PySide6.QtWidgets import (
        QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QLineEdit, QFileDialog, QStackedWidget,
    )
    from PySide6.QtCore import Qt
except ImportError:
    from PyQt5.QtWidgets import (
        QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QLineEdit, QFileDialog, QStackedWidget,
    )
    from PyQt5.QtCore import Qt, pyqtSignal as Signal

from modes import MODES, mode_name


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

        title = QLabel(f"📌 {stock_code} · {mode_name(mode)}")
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
        for key, icon, name, desc in MODES:
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
