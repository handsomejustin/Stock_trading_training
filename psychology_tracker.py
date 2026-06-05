"""
盘感训练器 - 心理状态追踪组件

综合训练模式下的心理状态记录面板，
用户点击情感标签按钮记录当前心理状态。
"""

from datetime import datetime

try:
    from PySide6.QtWidgets import (
        QWidget, QHBoxLayout, QVBoxLayout, QLabel,
        QPushButton, QLineEdit, QTextEdit,
    )
    from PySide6.QtCore import Signal
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QHBoxLayout, QVBoxLayout, QLabel,
        QPushButton, QLineEdit, QTextEdit,
    )
    from PyQt5.QtCore import pyqtSignal as Signal

STATES = [
    ("贪婪", "#ff4444"),
    ("恐惧", "#4444ff"),
    ("犹豫", "#FFD700"),
    ("坚定", "#00cc00"),
    ("焦虑", "#ff8800"),
    ("平静", "#888888"),
]


class PsychologyTracker(QWidget):
    """心理状态追踪面板。"""

    state_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timeline: list[dict] = []
        self._cursor_ref = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        # 标题 + 按钮行
        top_row = QHBoxLayout()
        top_row.setSpacing(4)

        label = QLabel("🧠 心理状态:")
        label.setStyleSheet("color: #cccccc; font-size: 13px; font-weight: bold;")
        top_row.addWidget(label)

        for state_name, color in STATES:
            btn = QPushButton(state_name)
            btn.setFixedHeight(26)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color}33; color: {color};
                    border: 1px solid {color}; border-radius: 3px;
                    padding: 2px 8px; font-size: 12px; font-weight: bold;
                }}
                QPushButton:hover {{ background-color: {color}55; }}
                QPushButton:pressed {{ background-color: {color}88; }}
            """)
            btn.clicked.connect(lambda checked, s=state_name: self._on_click(s))
            top_row.addWidget(btn)

        # 备注输入
        self._note_edit = QLineEdit()
        self._note_edit.setPlaceholderText("备注(可选)...")
        self._note_edit.setFixedHeight(26)
        self._note_edit.setStyleSheet("""
            QLineEdit {
                background: #1e1e1e; color: #cccccc; border: 1px solid #555;
                border-radius: 3px; padding: 2px 6px; font-size: 12px;
            }
        """)
        self._note_edit.setMaximumWidth(150)
        top_row.addWidget(self._note_edit)

        top_row.addStretch()
        layout.addLayout(top_row)

        # 时间线日志
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(50)
        self._log.setStyleSheet("""
            QTextEdit {
                background: #1a1a1a; color: #aaaaaa;
                font-size: 11px; border: 1px solid #3c3c3c;
            }
        """)
        layout.addWidget(self._log)

    def set_cursor(self, cursor: int):
        self._cursor_ref = cursor

    def reset(self):
        self._timeline.clear()
        self._log.clear()
        self._note_edit.clear()

    def get_timeline(self) -> list[dict]:
        return list(self._timeline)

    def _on_click(self, state: str):
        note = self._note_edit.text().strip()
        entry = {
            "cursor": self._cursor_ref,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "state": state,
            "notes": note,
        }
        self._timeline.append(entry)
        self._note_edit.clear()
        self.state_changed.emit(state)

        self._log.append(
            f"<span style='color:#888888'>[{entry['timestamp']}]</span> "
            f"<b>{state}</b>"
            + (f" — {note}" if note else "")
        )

    def export_for_report(self) -> str:
        if not self._timeline:
            return ""
        lines = ["## 心理状态追踪", "", "训练过程中的心理状态记录。", ""]
        lines.append("| 时间 | K线位置 | 心理状态 | 备注 |")
        lines.append("|:----:|--------:|:--------:|:----:|")
        for e in self._timeline:
            lines.append(
                f"| {e['timestamp']} | 第{e['cursor']}根 "
                f"| {e['state']} | {e['notes']} |"
            )
        return "\n".join(lines)
