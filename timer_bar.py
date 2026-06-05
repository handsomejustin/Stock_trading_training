"""
盘感训练器 - 限时模式倒计时组件

每根 K 线的倒计时进度条，时间到自动触发前进。
"""

try:
    from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QProgressBar
    from PySide6.QtCore import Qt, Signal, QTimer
    from PySide6.QtGui import QPainter, QColor
except ImportError:
    from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QProgressBar
    from PyQt5.QtCore import Qt, pyqtSignal as Signal, QTimer
    from PyQt5.QtGui import QPainter, QColor


class TimerBar(QWidget):
    """限时模式倒计时条。"""

    timeout = Signal()

    COLOR_GREEN = "#00cc00"
    COLOR_YELLOW = "#FFD700"
    COLOR_RED = "#ff4444"

    def __init__(self, parent=None, seconds: int = 10):
        super().__init__(parent)
        self.setFixedHeight(32)
        self._duration = seconds * 1000
        self._elapsed = 0
        self._running = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self._label = QLabel("⏱ --")
        self._label.setStyleSheet("color: #cccccc; font-size: 14px; font-weight: bold;")
        self._label.setFixedWidth(70)
        layout.addWidget(self._label)

        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)
        self._bar.setValue(1000)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(18)
        self._apply_bar_style(1.0)
        layout.addWidget(self._bar, stretch=1)

        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)

    def _apply_bar_style(self, ratio: float):
        if ratio > 0.5:
            color = self.COLOR_GREEN
        elif ratio > 0.2:
            color = self.COLOR_YELLOW
        else:
            color = self.COLOR_RED
        self._bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid #555; border-radius: 3px;
                background: #1e1e1e;
            }}
            QProgressBar::chunk {{
                background: {color}; border-radius: 2px;
            }}
        """)

    def set_duration(self, seconds: int):
        self._duration = seconds * 1000

    def start(self, seconds: int = None):
        if seconds is not None:
            self._duration = seconds * 1000
        self._elapsed = 0
        self._running = True
        self._update_display()
        self._timer.start()

    def stop(self):
        self._running = False
        self._timer.stop()

    def reset(self):
        self._elapsed = 0
        self._running = False
        self._timer.stop()
        self._update_display()

    def _tick(self):
        self._elapsed += 50
        if self._elapsed >= self._duration:
            self._elapsed = self._duration
            self._running = False
            self._timer.stop()
            self._update_display()
            self.timeout.emit()
            return
        self._update_display()

    def _update_display(self):
        ratio = max(0.0, 1.0 - self._elapsed / self._duration) if self._duration > 0 else 1.0
        self._bar.setValue(int(ratio * 1000))
        self._apply_bar_style(ratio)
        remaining = max(0, (self._duration - self._elapsed) / 1000.0)
        self._label.setText(f"⏱ {remaining:.1f}s")
