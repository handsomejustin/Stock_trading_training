"""
盘感训练器 - 首页

模式选择卡片页。只负责展示与发信号，训练编排由主窗口完成。
"""

try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout,
    )
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QFont
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout,
    )
    from PyQt5.QtCore import Qt, pyqtSignal as Signal
    from PyQt5.QtGui import QFont

from modes import MODES


class HomePage(QWidget):
    """
    首页：标题 + 模式卡片 + 工具入口。

    Signals:
        mode_selected(str): 点击模式卡片，参数为模式 key
        advanced_clicked(): 点击「高级设置」
        rebuild_clicked(): 点击「重建题库」
    """

    mode_selected = Signal(str)
    advanced_clicked = Signal()
    rebuild_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
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
        for i, (key, icon, name, desc) in enumerate(MODES):
            btn = QPushButton(f"{icon}  {name}\n     {desc}")
            btn.setStyleSheet(card_style)
            btn.setMinimumHeight(92)
            btn.setFont(QFont("Microsoft YaHei", 12))
            btn.clicked.connect(
                lambda _=False, k=key: self.mode_selected.emit(k))
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
        btn_advanced.clicked.connect(self.advanced_clicked.emit)
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
        btn_rebuild.setToolTip("重新扫描股票历史数据，刷新答题模式题库")
        btn_rebuild.clicked.connect(self.rebuild_clicked.emit)
        tool_row.addWidget(btn_rebuild)
        tool_row.addStretch()

        self._hint = QLabel("")
        self._hint.setStyleSheet("color: #888888; font-size: 13px;")
        tool_row.addWidget(self._hint)
        outer.addLayout(tool_row)

    def set_hint(self, text: str) -> None:
        """设置首页底部提示文字（空串隐藏）。"""
        self._hint.setText(text)
