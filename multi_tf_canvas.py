"""
盘感训练器 - 多周期副图组件

在主图下方显示周线 K 线图，同样隐藏未来数据。
"""

import numpy as np
try:
    from PySide6.QtCore import Qt
except ImportError:
    from PyQt5.QtCore import Qt
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

import pandas as pd


class MultiTFCanvas(FigureCanvasQTAgg):
    """周线 K 线小图画布。"""

    BG_FIGURE = "#1e1e1e"
    BG_AXES = "#2b2b2b"
    COLOR_TEXT = "#cccccc"
    COLOR_GRID = "#3c3c3c"
    COLOR_UP = "#ff4444"
    COLOR_DOWN = "#00cc00"

    def __init__(self, parent=None, height_px: int = 180):
        self._height_px = height_px
        self.fig = Figure(figsize=(10, height_px / 100), dpi=100,
                          facecolor=self.BG_FIGURE)
        super().__init__(self.fig)
        self.setFixedHeight(height_px)
        self.setFocusPolicy(Qt.NoFocus)

        self.ax = self.fig.add_subplot(111)
        self._style_axes(self.ax)
        self.fig.subplots_adjust(left=0.03, right=0.97, top=0.88, bottom=0.12)

        self.df: pd.DataFrame = None

    def set_data(self, weekly_df: pd.DataFrame):
        self.df = weekly_df

    def render(self, weekly_cursor: int):
        if self.df is None or len(self.df) == 0 or weekly_cursor <= 0:
            return

        weekly_cursor = min(weekly_cursor, len(self.df))
        vis = self.df.iloc[:weekly_cursor].reset_index(drop=True)

        self.ax.clear()
        self._style_axes(self.ax)
        self._draw_candlestick(self.ax, vis)

        self.ax.set_title(f"周线 ({weekly_cursor}/{len(self.df)})",
                          color=self.COLOR_TEXT, fontsize=10, pad=4)

        if len(vis) > 60:
            self.ax.set_xlim(len(vis) - 60, len(vis))
        else:
            self.ax.set_xlim(-1, max(len(vis), 10))

        self.draw_idle()

    def _style_axes(self, ax):
        ax.set_facecolor(self.BG_AXES)
        ax.tick_params(colors=self.COLOR_TEXT, labelsize=8)
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

            ax.plot([i, i], [l, min(o, c)], color=color, linewidth=0.6)
            ax.plot([i, i], [max(o, c), h], color=color, linewidth=0.6)

            highs.append(h)
            lows.append(l)

        if highs and lows:
            y_min, y_max = min(lows), max(highs)
            margin = max((y_max - y_min) * 0.05, 0.01)
            ax.set_ylim(y_min - margin, y_max + margin)
