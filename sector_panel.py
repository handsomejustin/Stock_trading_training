"""
盘感训练器 - 板块联动面板

显示 2-3 只同板块股票的缩略 K 线图，同样隐藏未来数据。
"""

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.patches import Rectangle

import matplotlib
import matplotlib.font_manager as _fm
for _font in ["Microsoft YaHei", "SimHei", "SimSun", "KaiTi"]:
    _found = any(_font in f.name for f in _fm.fontManager.ttflist)
    if _found:
        matplotlib.rcParams["font.sans-serif"] = [_font, "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False
        break

try:
    from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QVBoxLayout
    from PySide6.QtCore import Qt
except ImportError:
    from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QVBoxLayout
    from PyQt5.QtCore import Qt

import pandas as pd


class _MiniChart(FigureCanvasQTAgg):
    """单只股票的缩略 K 线画布。"""

    BG_FIGURE = "#1e1e1e"
    BG_AXES = "#2b2b2b"
    COLOR_TEXT = "#cccccc"
    COLOR_GRID = "#3c3c3c"
    COLOR_UP = "#ff4444"
    COLOR_DOWN = "#00cc00"

    def __init__(self, parent=None, height_px: int = 160):
        self.fig = Figure(figsize=(3, height_px / 100), dpi=100,
                          facecolor=self.BG_FIGURE)
        super().__init__(self.fig)
        self.setFixedHeight(height_px)
        self.setFocusPolicy(Qt.NoFocus)

        self.ax = self.fig.add_subplot(111)
        self._style_axes(self.ax)
        self.fig.subplots_adjust(left=0.06, right=0.96, top=0.85, bottom=0.12)

        self.df: pd.DataFrame = None
        self._stock_code = ""

    def set_data(self, df: pd.DataFrame, stock_code: str):
        self.df = df
        self._stock_code = stock_code

    def render(self, cursor: int):
        if self.df is None or len(self.df) == 0 or cursor <= 0:
            return

        cursor = min(cursor, len(self.df))
        vis = self.df.iloc[:cursor].reset_index(drop=True)

        self.ax.clear()
        self._style_axes(self.ax)
        self._draw_candlestick(self.ax, vis)

        self.ax.set_title(self._stock_code, color=self.COLOR_TEXT,
                          fontsize=9, pad=3)

        if len(vis) > 40:
            self.ax.set_xlim(len(vis) - 40, len(vis))
        else:
            self.ax.set_xlim(-1, max(len(vis), 10))

        self.draw_idle()

    def _style_axes(self, ax):
        ax.set_facecolor(self.BG_AXES)
        ax.tick_params(colors=self.COLOR_TEXT, labelsize=7)
        ax.grid(True, color=self.COLOR_GRID, linewidth=0.3, alpha=0.5)
        for spine in ax.spines.values():
            spine.set_color(self.COLOR_GRID)

    def _draw_candlestick(self, ax, vis: pd.DataFrame):
        if len(vis) == 0:
            return

        highs = []
        lows = []
        for i, row in vis.iterrows():
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
            color = self.COLOR_UP if c >= o else self.COLOR_DOWN
            body_bottom = min(o, c)
            body_height = abs(c - o)

            rect = Rectangle((i - 0.4, body_bottom), 0.8,
                              max(body_height, 0.01),
                              facecolor=color, edgecolor=color, linewidth=0.5)
            ax.add_patch(rect)

            ax.plot([i, i], [l, min(o, c)], color=color, linewidth=0.5)
            ax.plot([i, i], [max(o, c), h], color=color, linewidth=0.5)

            highs.append(h)
            lows.append(l)

        if highs and lows:
            y_min, y_max = min(lows), max(highs)
            margin = max((y_max - y_min) * 0.05, 0.01)
            ax.set_ylim(y_min - margin, y_max + margin)


class SectorPanel(QWidget):
    """板块联动面板：水平排列多个缩略 K 线图。"""

    def __init__(self, parent=None, peer_count: int = 3):
        super().__init__(parent)
        self._peer_count = peer_count
        self._charts: list[_MiniChart] = []
        self._peer_codes: list[str] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._layout = layout
        self._build_charts(peer_count)

    def _build_charts(self, count: int):
        for chart in self._charts:
            self._layout.removeWidget(chart)
            chart.deleteLater()
        self._charts.clear()

        for _ in range(count):
            chart = _MiniChart(self, height_px=160)
            self._layout.addWidget(chart, stretch=1)
            self._charts.append(chart)

    def set_peer_count(self, count: int):
        self._peer_count = count
        self._build_charts(count)

    def set_peers(self, peer_data_list: list):
        self._peer_codes = []
        for i, (code, df) in enumerate(peer_data_list):
            if i >= len(self._charts):
                break
            self._charts[i].set_data(df, code)
            self._peer_codes.append(code)

        for i in range(len(peer_data_list), len(self._charts)):
            self._charts[i].ax.clear()
            self._charts[i].ax.set_facecolor(self.BG_AXES)
            self._charts[i].draw_idle()

    def render(self, cursor_map: dict):
        for code in self._peer_codes:
            idx = self._peer_codes.index(code)
            cursor = cursor_map.get(code, 0)
            if idx < len(self._charts):
                self._charts[idx].render(cursor)
