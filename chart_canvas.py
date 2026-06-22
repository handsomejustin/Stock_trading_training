"""
盘感训练器 - 图表画布模块

基于 matplotlib FigureCanvasQTAgg 的动态多子图画布：
  - 子图0 (ax_kline):       K线图 + 主图叠加指标 + 买卖标记
  - 子图1 (ax_volume):      成交量柱状图（红绿配色）
  - 子图2..N (ax_indicators): 3~5个副图技术指标曲线

支持十字光标联动、逐根K线推演渲染、动态面板数量切换。
"""

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.patches import Rectangle

# ---- 中文字体配置 ----
import matplotlib
import matplotlib.font_manager as _fm
for _font in ["Microsoft YaHei", "SimHei", "SimSun", "KaiTi"]:
    _found = any(_font in f.name for f in _fm.fontManager.ttflist)
    if _found:
        matplotlib.rcParams["font.sans-serif"] = [_font, "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False
        break
import matplotlib.ticker as mticker

import pandas as pd


class ChartCanvas(FigureCanvasQTAgg):
    """
    动态多子图 K 线画布。

    支持 3~5 个额外副图指标框，用户可切换面板数量。
    渲染策略：ax.clear() + 全量重绘可见切片。
    """

    # 暗色主题色板
    BG_FIGURE = "#1e1e1e"
    BG_AXES = "#2b2b2b"
    COLOR_TEXT = "#cccccc"
    COLOR_GRID = "#3c3c3c"
    COLOR_UP = "#ff4444"
    COLOR_DOWN = "#00cc00"
    COLOR_CROSS = "#888888"

    def __init__(self, parent=None, panel_count: int = 3):
        """
        初始化画布。

        Args:
            parent: 父控件
            panel_count: 副图指标框数量（3~5）
        """
        self.fig = Figure(facecolor=self.BG_FIGURE, dpi=100)
        super().__init__(self.fig)

        # 数据引用
        self.df: pd.DataFrame = None
        self.indicator_hub = None
        self.trade_manager = None

        # 面板管理
        self.panel_count = panel_count  # 副图数量
        self.ax_kline = None
        self.ax_volume = None
        self.ax_indicators: list = []  # 副图 axes 列表

        # 十字光标
        self.cross_vlines = []
        self.cross_hlines = []

        # ---- 拖拽 / 缩放状态 ----
        self._view_start: int = 0       # 可见窗口起始 bar 索引
        self._view_count: int = 80      # 可见窗口宽度（K 线根数）
        self._dragging: bool = False    # 是否正在拖拽
        self._drag_start_x: float = 0   # 拖拽起始 x 像素
        self._drag_start_xlim: tuple = (0, 80)  # 拖拽起始 xlim
        self._cursor: int = 0           # 当前推演位置（最新 bar 数）

        # 创建子图
        self._build_panels(panel_count)

        # 绑定鼠标事件
        self.mpl_connect("button_press_event", self._on_mouse_press)
        self.mpl_connect("button_release_event", self._on_mouse_release)
        self.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.mpl_connect("scroll_event", self._on_scroll)

        self.draw()

    # ============================================================
    # 面板管理
    # ============================================================
    def _build_panels(self, panel_count: int):
        """
        创建子图布局：1主图 + 1成交量 + N副图。

        Args:
            panel_count: 副图指标框数量（3~5）
        """
        panel_count = max(3, min(5, panel_count))
        self.panel_count = panel_count

        # 清除旧子图
        self.fig.clear()

        # 总子图数 = 2（主图+成交量）+ panel_count
        total = 2 + panel_count
        # 高度比：主图占大头，成交量小，副图各 1
        height_ratios = [4, 1] + [1] * panel_count

        gs = self.fig.add_gridspec(
            total, 1,
            height_ratios=height_ratios,
            hspace=0.08,
            left=0.03, right=0.97, top=0.96, bottom=0.03,
        )

        # 主图
        self.ax_kline = self.fig.add_subplot(gs[0])
        # 成交量
        self.ax_volume = self.fig.add_subplot(gs[1], sharex=self.ax_kline)
        # 副图
        self.ax_indicators = []
        for i in range(panel_count):
            ax = self.fig.add_subplot(gs[2 + i], sharex=self.ax_kline)
            self.ax_indicators.append(ax)

        # 隐藏除最底部以外的 x 轴标签
        for label in self.ax_kline.get_xticklabels():
            label.set_visible(False)
        for label in self.ax_volume.get_xticklabels():
            label.set_visible(False)
        for ax in self.ax_indicators[:-1]:
            for label in ax.get_xticklabels():
                label.set_visible(False)

        # 应用暗色主题
        self._style_axes(self.ax_kline)
        self._style_axes(self.ax_volume)
        for ax in self.ax_indicators:
            self._style_axes(ax)

        # 重建十字光标
        self._init_crosshair()

    def setup_panels(self, panel_count: int):
        """
        切换副图面板数量。

        Args:
            panel_count: 副图指标框数量（3~5）
        """
        self._build_panels(panel_count)
        if self.df is not None:
            # 保持当前数据，等待外部调用 render 刷新
            pass
        self.draw_idle()

    # ============================================================
    # 样式
    # ============================================================
    def _style_axes(self, ax):
        """为子图应用暗色主题。"""
        ax.set_facecolor(self.BG_AXES)
        ax.tick_params(colors=self.COLOR_TEXT, labelsize=8)
        ax.spines["top"].set_color(self.COLOR_GRID)
        ax.spines["bottom"].set_color(self.COLOR_GRID)
        ax.spines["left"].set_color(self.COLOR_GRID)
        ax.spines["right"].set_color(self.COLOR_GRID)
        ax.grid(True, color=self.COLOR_GRID, linewidth=0.5, alpha=0.5)

    # ============================================================
    # 十字光标
    # ============================================================
    def _init_crosshair(self):
        """初始化十字光标（所有子图各一条竖线 + 一条横线）。"""
        self.cross_vlines = []
        self.cross_hlines = []

        all_axes = [self.ax_kline, self.ax_volume] + self.ax_indicators
        for ax in all_axes:
            vl = ax.axvline(x=0, color=self.COLOR_CROSS, linewidth=0.8,
                            linestyle="--", visible=False, zorder=100)
            hl = ax.axhline(y=0, color=self.COLOR_CROSS, linewidth=0.8,
                            linestyle="--", visible=False, zorder=100)
            self.cross_vlines.append(vl)
            self.cross_hlines.append(hl)

    # ============================================================
    # 鼠标事件：拖拽 + 十字光标 + 滚轮缩放
    # ============================================================
    def _on_mouse_press(self, event):
        """鼠标按下：记录拖拽起点。"""
        if event.button == 1 and event.inaxes is not None:
            self._dragging = True
            self._drag_start_x = event.x
            self._drag_start_xlim = self.ax_kline.get_xlim()

    def _on_mouse_release(self, event):
        """鼠标松开：结束拖拽。"""
        if event.button == 1:
            self._dragging = False

    def _on_mouse_move(self, event):
        """鼠标移动：拖拽时平移视图，否则更新十字光标。"""
        if self._dragging and event.x is not None:
            # ---- 拖拽平移 ----
            dx_pixels = event.x - self._drag_start_x
            # 将像素偏移转为数据坐标偏移
            xlim = self._drag_start_xlim
            x_range = xlim[1] - xlim[0]
            if x_range <= 0:
                return
            fig_w = self.fig.get_figwidth() * self.fig.dpi
            # 估算 axes 占 figure 的宽度比例
            bbox = self.ax_kline.get_position()
            ax_w_frac = bbox.width
            ax_w_pixels = fig_w * ax_w_frac
            if ax_w_pixels <= 0:
                return
            dx_data = -dx_pixels / ax_w_pixels * x_range

            new_left = xlim[0] + dx_data
            new_right = xlim[1] + dx_data
            # 限制边界
            new_left = max(-1, new_left)
            new_right = max(new_right, new_left + 10)
            self.ax_kline.set_xlim(new_left, new_right)
            # 同步 _view_start
            self._view_start = max(0, int(new_left + 0.5))
            self._view_count = int(new_right - new_left)

            # 隐藏十字光标
            for vl in self.cross_vlines:
                vl.set_visible(False)
            for hl in self.cross_hlines:
                hl.set_visible(False)
            self.draw_idle()
            return

        # ---- 十字光标 ----
        if event.inaxes is None:
            return

        xdata = event.xdata
        ydata = event.ydata
        if xdata is None or ydata is None:
            return

        # 竖线同步
        for vl in self.cross_vlines:
            vl.set_xdata([xdata, xdata])
            vl.set_visible(True)

        # 横线：只更新鼠标所在子图
        all_axes = [self.ax_kline, self.ax_volume] + self.ax_indicators
        for ax, hl in zip(all_axes, self.cross_hlines):
            if event.inaxes == ax:
                hl.set_ydata([ydata, ydata])
                hl.set_visible(True)
            else:
                hl.set_visible(False)

        self.draw_idle()

    def _on_scroll(self, event):
        """滚轮缩放：以鼠标位置为中心调整可见 K 线数量。"""
        if event.inaxes is None:
            return

        xlim = self.ax_kline.get_xlim()
        cur_left, cur_right = xlim
        cur_count = cur_right - cur_left
        if cur_count <= 0:
            return

        # 鼠标在当前视图中的相对位置（0~1）
        mouse_ratio = (event.xdata - cur_left) / cur_count

        # 缩放因子
        if event.button == "up":
            factor = 0.85   # 放大（减少可见 K 线）
        elif event.button == "down":
            factor = 1.18   # 缩小（增加可见 K 线）
        else:
            return

        new_count = cur_count * factor
        new_count = max(20, min(new_count, self._cursor + 2))  # 20~全部
        if new_count >= self._cursor + 2:
            # 显示全部
            new_left = -1
            new_right = self._cursor
        else:
            # 以鼠标位置为中心缩放
            new_left = event.xdata - mouse_ratio * new_count
            new_right = new_left + new_count
            # 边界限制
            if new_left < -1:
                new_left = -1
                new_right = new_left + new_count
            if new_right > self._cursor:
                new_right = self._cursor
                new_left = new_right - new_count
                new_left = max(-1, new_left)

        self._view_start = max(0, int(new_left + 0.5))
        self._view_count = int(new_count)
        self.ax_kline.set_xlim(new_left, new_right)
        self.draw_idle()

    # ============================================================
    # 数据与渲染
    # ============================================================
    def set_data(self, df: pd.DataFrame, indicator_hub, trade_manager):
        """设置画布使用的数据和引用。"""
        self.df = df
        self.indicator_hub = indicator_hub
        self.trade_manager = trade_manager
        # 重置视口
        self._view_start = 0
        self._view_count = min(80, len(df))
        self._cursor = 0

    def scroll_to_latest(self, cursor: int):
        """
        将视图窗口滚动到最新 bar 位置。

        在推演前进时调用，确保用户始终看到最新 K 线。

        Args:
            cursor: 当前推演位置
        """
        if cursor <= self._view_count:
            self._view_start = 0
        else:
            self._view_start = cursor - self._view_count

    def show_all(self, cursor: int):
        """
        显示全部 K 线（训练结束时调用）。

        Args:
            cursor: 总 bar 数量
        """
        self._view_start = 0
        self._view_count = cursor

    def render(self, cursor: int, sub_indicators: list = None,
               main_overlays: list = None):
        """
        核心渲染方法：绘制可见切片的所有内容。

        渲染全部 0..cursor 的 K 线数据，通过 xlim 控制可见窗口。
        拖拽/缩放只改变 xlim，不重新绘制。

        Args:
            cursor: 当前推演位置（可见的K线数量）
            sub_indicators: 副图指标名称列表（长度应等于 panel_count）
            main_overlays: 启用的主图叠加指标列表
        """
        if self.df is None or cursor <= 0:
            return

        cursor = min(cursor, len(self.df))
        self._cursor = cursor

        # 默认指标列表
        if sub_indicators is None:
            sub_indicators = ["MACD"] * self.panel_count

        # 可见切片：绘制全部 0..cursor
        vis = self.df.iloc[:cursor].reset_index(drop=True)
        n = len(vis)

        # ---- 清除所有子图 ----
        self.ax_kline.clear()
        self.ax_volume.clear()
        for ax in self.ax_indicators:
            ax.clear()

        # ---- 重新应用暗色主题 ----
        self._style_axes(self.ax_kline)
        self._style_axes(self.ax_volume)
        for ax in self.ax_indicators:
            self._style_axes(ax)

        # ---- 绘制 K 线 ----
        self._draw_candlestick(self.ax_kline, vis)

        # ---- 绘制主图叠加指标 ----
        if main_overlays and self.indicator_hub:
            overlay_lines = self.indicator_hub.get_main_overlay_lines(main_overlays)
            for line_info in overlay_lines:
                arr = line_info["array"][:cursor]
                if len(arr) == n:
                    idx = cursor - 1
                    val = arr[idx]
                    label_text = f"{line_info['name']}: {val:.2f}" if not np.isnan(val) else f"{line_info['name']}: --"
                    self.ax_kline.plot(
                        range(n), arr,
                        color=line_info["color"],
                        linewidth=line_info["linewidth"],
                        label=label_text,
                    )

        # ---- 绘制止损/止盈参考线 ----
        if (self.trade_manager and hasattr(self.trade_manager, 'portfolio')
                and self.trade_manager.portfolio.position > 0):
            pf = self.trade_manager.portfolio
            cost = pf.avg_cost
            if cost > 0:
                if pf.stop_loss_pct is not None and pf.stop_loss_pct < 0:
                    sl_price = cost * (1.0 + pf.stop_loss_pct)
                    self.ax_kline.axhline(
                        y=sl_price, color="#ff6666", linewidth=0.6,
                        linestyle="--", alpha=0.5, label="止损线")
                if pf.take_profit_pct is not None and pf.take_profit_pct > 0:
                    tp_price = cost * (1.0 + pf.take_profit_pct)
                    self.ax_kline.axhline(
                        y=tp_price, color="#66ff66", linewidth=0.6,
                        linestyle="--", alpha=0.5, label="止盈线")

        # ---- 绘制买卖标记 ----
        if self.trade_manager:
            markers = self.trade_manager.get_trade_markers()
            for m in markers:
                if m["idx"] < cursor:
                    x_pos = m["idx"]
                    if x_pos >= n:
                        continue
                    ratio = m.get("ratio", 1.0)
                    is_auto = m.get("is_auto", False)
                    auto_reason = m.get("auto_reason", "")
                    pos_after = m.get("position_after", None)

                    # 字体大小随仓位比例缩放: 8pt(小仓) ~ 14pt(全仓)
                    font_size = 8 + int(ratio * 6)

                    if m["action"] == "buy":
                        label = "B"
                        color = "#ff4444"
                        y_anchor = vis.iloc[x_pos]["low"]
                        y_offset = y_anchor * 0.97
                        va = "top"
                    else:
                        # 自动止损/止盈用特殊标记
                        if is_auto and auto_reason == "stop_loss":
                            label = "SL"
                        elif is_auto and auto_reason == "take_profit":
                            label = "TP"
                        else:
                            label = "S"
                        color = "#00cc00"
                        y_anchor = vis.iloc[x_pos]["high"]
                        y_offset = y_anchor * 1.03
                        va = "bottom"

                    self.ax_kline.annotate(
                        label, xy=(x_pos, y_anchor),
                        xytext=(x_pos, y_offset),
                        fontsize=font_size, fontweight="bold",
                        color=color, ha="center", va=va,
                        arrowprops=dict(arrowstyle="->", color=color,
                                        lw=0.8 + ratio * 0.7),
                    )
                    # 显示操作后仓位百分比
                    if pos_after is not None:
                        pos_label = f"{pos_after * 100:.0f}%"
                        label_y = y_offset * (0.98 if m["action"] == "buy" else 1.02)
                        self.ax_kline.text(
                            x_pos + 0.5, label_y, pos_label,
                            fontsize=6, color="#aaaaaa", ha="left",
                            va=va)

        # ---- 绘制成交量 ----
        self._draw_volume(self.ax_volume, vis)

        # ---- 绘制各副图指标 ----
        if self.indicator_hub:
            for i, ax_ind in enumerate(self.ax_indicators):
                if i < len(sub_indicators):
                    self._draw_sub_indicator(ax_ind, cursor, n, sub_indicators[i])

        # ---- 设置 x 轴日期标签（最底部副图） ----
        if self.ax_indicators:
            self._set_date_labels(self.ax_indicators[-1], vis)

        # ---- 标题和图例 ----
        self.ax_kline.set_title(
            f"推演进度: {cursor}/{len(self.df)}",
            color=self.COLOR_TEXT, fontsize=10, pad=5,
        )
        if main_overlays:
            self.ax_kline.legend(
                loc="upper left", fontsize=7,
                facecolor=self.BG_AXES, edgecolor=self.COLOR_GRID,
                labelcolor=self.COLOR_TEXT,
            )

        # ---- 应用可见窗口（xlim） ----
        view_end = min(self._view_start + self._view_count, cursor)
        if view_end <= self._view_start:
            view_end = cursor
            self._view_start = 0
        self.ax_kline.set_xlim(self._view_start - 1, view_end)

        # ---- 重建十字光标 ----
        # 上面的 ax.clear() 会把十字光标 Line2D 从 axes 中移除，旧引用变成
        # 脱离 axes 的孤立对象，鼠标移动时 set_visible(True) 也永远画不出来。
        # 必须在每次 render 后重新创建（创建时为隐藏状态，鼠标移动时再显示）。
        self._init_crosshair()

        self.draw_idle()

    # ============================================================
    # 绘制辅助方法
    # ============================================================
    def _draw_candlestick(self, ax, vis: pd.DataFrame):
        """绘制K线蜡烛图。涨红跌绿。"""
        for i in range(len(vis)):
            row = vis.iloc[i]
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
            color = self.COLOR_UP if c >= o else self.COLOR_DOWN

            bottom = min(o, c)
            height = abs(c - o)
            if height < 0.001:
                height = 0.001
            rect = Rectangle(
                (i - 0.4, bottom), 0.8, height,
                facecolor=color, edgecolor=color, linewidth=0.5,
            )
            ax.add_patch(rect)
            ax.plot([i, i], [max(o, c), h], color=color, linewidth=0.6)
            ax.plot([i, i], [l, min(o, c)], color=color, linewidth=0.6)

        if len(vis) > 0:
            y_min = vis["low"].min()
            y_max = vis["high"].max()
            margin = (y_max - y_min) * 0.05
            ax.set_ylim(y_min - margin, y_max + margin)

    def _draw_volume(self, ax, vis: pd.DataFrame):
        """绘制成交量柱状图。涨红跌绿。"""
        colors = [
            self.COLOR_UP if vis.iloc[i]["close"] >= vis.iloc[i]["open"]
            else self.COLOR_DOWN
            for i in range(len(vis))
        ]
        ax.bar(range(len(vis)), vis["volume"].values, color=colors, width=0.8)
        ax.set_ylabel("成交量", color=self.COLOR_TEXT, fontsize=8)

    def _draw_sub_indicator(self, ax, cursor: int, n: int, indicator_name: str):
        """
        绘制副图技术指标。

        支持主 outputs 线、bar_output 柱状图、extra_lines 均线叠加。
        """
        info = self.indicator_hub.get_sub_indicator(indicator_name)
        if not info or not info.get("data"):
            ax.text(0.5, 0.5, f"{indicator_name} N/A",
                    transform=ax.transAxes, color=self.COLOR_TEXT,
                    ha="center", va="center", fontsize=9)
            return

        reg = info["registry"]
        data = info["data"]

        # 画柱状输出（如 MACD 柱）
        bar_output = reg.get("bar_output")
        idx = cursor - 1  # 当天数据索引
        if bar_output and bar_output in data:
            bar_data = data[bar_output][:cursor]
            bar_colors = [
                self.COLOR_UP if v >= 0 else self.COLOR_DOWN
                for v in bar_data
            ]
            ax.bar(range(len(bar_data)), bar_data, color=bar_colors, width=0.8, alpha=0.8)
            # 柱状数值显示
            if cursor > 0:
                bar_val = data[bar_output][idx]
                bar_label = f"{bar_output}: {bar_val:.4f}" if not np.isnan(bar_val) else f"{bar_output}: --"
                # 用一个不可见的 bar 占位来加入 legend
                ax.bar([], [], color=self.COLOR_TEXT, label=bar_label)

        # 画主 outputs 线图
        for out_name, color in zip(reg["outputs"], reg["colors"]):
            if out_name in data and out_name != bar_output:
                arr = data[out_name][:cursor]
                if len(arr) == cursor:
                    val = arr[idx]
                    label_text = f"{out_name}: {val:.2f}" if not np.isnan(val) else f"{out_name}: --"
                    ax.plot(range(cursor), arr, color=color, linewidth=1.0, label=label_text)

        # 画 extra_lines 均线叠加（OBV_MA30, CR_MA10 等）
        extra_lines = reg.get("extra_lines", [])
        for el in extra_lines:
            el_name = el["name"]
            el_color = el["color"]
            if el_name in data:
                arr = data[el_name][:cursor]
                if len(arr) == cursor:
                    val = arr[idx]
                    label_text = f"{el_name}: {val:.2f}" if not np.isnan(val) else f"{el_name}: --"
                    ax.plot(range(cursor), arr, color=el_color, linewidth=0.8,
                            linestyle="--", label=label_text)

        # 画零线
        if reg.get("zero_line"):
            ax.axhline(y=0, color=self.COLOR_TEXT, linewidth=0.5, linestyle="-", alpha=0.3)

        # 画参考线
        ref_lines = reg.get("ref_lines", [])
        for ref in ref_lines:
            ax.axhline(y=ref, color=self.COLOR_TEXT, linewidth=0.5, linestyle="--", alpha=0.3)

        # 图例
        ax.legend(
            loc="upper left", fontsize=6,
            facecolor=self.BG_AXES, edgecolor=self.COLOR_GRID,
            labelcolor=self.COLOR_TEXT,
        )
        ax.set_ylabel(indicator_name, color=self.COLOR_TEXT, fontsize=8)

    def _set_date_labels(self, ax, vis: pd.DataFrame):
        """设置 x 轴日期标签（基于可见窗口范围）。"""
        n = len(vis)
        if n <= 0:
            return

        # 根据当前视口计算日期标签步长
        view_left = max(0, int(self._view_start))
        view_right = min(n, view_left + self._view_count)
        view_n = view_right - view_left
        if view_n <= 0:
            return

        step = max(1, view_n // 8)
        positions = list(range(view_left, view_right, step))
        labels = [vis.iloc[i]["date"] for i in positions if i < n]

        ax.set_xticks(positions)
        ax.set_xticklabels(labels, rotation=30, fontsize=7, color=self.COLOR_TEXT)
