"""
盘感训练器 - 训练统计面板

嵌入主窗口 Tab 页签的统计 Widget。
展示历史训练的总体概览、趋势图表和薄弱环节分析。
"""

# PySide6/PyQt5 兼容
try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
        QFrame, QGridLayout, QSizePolicy,
    )
    from PySide6.QtCore import Qt
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
        QFrame, QGridLayout, QSizePolicy,
    )
    from PyQt5.QtCore import Qt

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg

import matplotlib
import matplotlib.font_manager as _fm
for _font in ["Microsoft YaHei", "SimHei", "SimSun", "KaiTi", "Noto Sans CJK SC", "WenQuanYi Zen Hei", "WenQuanYi Micro Hei"]:
    _found = any(_font in f.name for f in _fm.fontManager.ttflist)
    if _found:
        matplotlib.rcParams["font.sans-serif"] = [_font, "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False
        break


# 暗色主题色板（与 chart_canvas.py 一致）
BG_FIGURE = "#1e1e1e"
BG_AXES = "#2b2b2b"
COLOR_TEXT = "#cccccc"
COLOR_GRID = "#3c3c3c"
COLOR_UP = "#ff4444"
COLOR_DOWN = "#00cc00"
COLOR_ACCENT = "#4a9eff"


class StatsPanel(QWidget):
    """
    训练统计面板。

    包含：概览卡片、趋势图表、薄弱环节列表。
    调用 refresh() 从数据库重新加载并重绘。
    """

    def __init__(self, db, parent=None):
        """
        Args:
            db: Database 实例
            parent: 父控件
        """
        super().__init__(parent)
        self.db = db
        self._build_ui()

    # ============================================================
    # UI 构建
    # ============================================================
    def _build_ui(self) -> None:
        """构建统计面板布局。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(12)

        # ---- 概览卡片 ----
        self._cards_frame = QFrame()
        self._cards_layout = QGridLayout(self._cards_frame)
        self._cards_layout.setSpacing(8)
        self._build_overview_cards()
        layout.addWidget(self._cards_frame)

        # ---- 趋势图表 ----
        charts_label = QLabel("📈 训练趋势")
        charts_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #cccccc;")
        layout.addWidget(charts_label)

        self._charts_canvas = StatsChartCanvas()
        self._charts_canvas.setMinimumHeight(400)
        layout.addWidget(self._charts_canvas)

        # ---- 薄弱环节 ----
        self._weak_label = QLabel("⚠ 薄弱环节")
        self._weak_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #cccccc;")
        layout.addWidget(self._weak_label)

        self._weak_text = QLabel("暂无数据")
        self._weak_text.setStyleSheet(
            "color: #aaaaaa; font-size: 14px; padding: 8px; "
            "background-color: #2b2b2b; border-radius: 4px;"
        )
        self._weak_text.setWordWrap(True)
        layout.addWidget(self._weak_text)

        layout.addStretch()
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.addWidget(scroll)

    def _build_overview_cards(self) -> None:
        """创建 6 个概览卡片。"""
        card_style = """
            QFrame {
                background-color: #2b2b2b;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                padding: 8px;
            }
            QLabel { background: transparent; border: none; }
        """

        self._card_labels = {}
        cards = [
            ("sessions", "累计训练", "0 次"),
            ("trades", "总交易次数", "0 次"),
            ("total_return", "总收益率", "0.00%"),
            ("avg_return", "平均收益", "0.00%"),
            ("win_rate", "胜率", "0.0%"),
            ("avg_hold", "平均持仓", "0 天"),
        ]

        for i, (key, title, default) in enumerate(cards):
            frame = QFrame()
            frame.setStyleSheet(card_style)
            card_layout = QVBoxLayout(frame)
            card_layout.setSpacing(2)
            card_layout.setContentsMargins(8, 6, 8, 6)

            title_label = QLabel(title)
            title_label.setStyleSheet("color: #888888; font-size: 13px; border: none;")
            card_layout.addWidget(title_label)

            value_label = QLabel(default)
            value_label.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold; border: none;")
            card_layout.addWidget(value_label)

            self._card_labels[key] = value_label
            self._cards_layout.addWidget(frame, i // 3, i % 3)

    # ============================================================
    # 数据刷新
    # ============================================================
    def refresh(self) -> None:
        """从数据库重新加载统计数据并刷新 UI。"""
        if self.db is None:
            return

        # 更新概览卡片
        stats = self.db.get_session_stats()
        self._card_labels["sessions"].setText(f"{stats['total_sessions']} 次")
        self._card_labels["trades"].setText(f"{stats['total_trades']} 次")

        sign = "+" if stats["total_return"] >= 0 else ""
        self._card_labels["total_return"].setText(f"{sign}{stats['total_return']:.2f}%")
        self._card_labels["total_return"].setStyleSheet(
            self._value_style(stats["total_return"]))

        sign = "+" if stats["avg_return"] >= 0 else ""
        self._card_labels["avg_return"].setText(f"{sign}{stats['avg_return']:.2f}%")
        self._card_labels["avg_return"].setStyleSheet(
            self._value_style(stats["avg_return"]))

        self._card_labels["win_rate"].setText(f"{stats['win_rate']:.1f}%")
        self._card_labels["avg_hold"].setText(f"{stats['avg_hold_days']:.1f} 天")

        # 更新图表
        self._charts_canvas.draw_charts(self.db)

        # 更新薄弱环节
        self._update_weak_spots()

    # ============================================================
    # 薄弱环节
    # ============================================================
    def _update_weak_spots(self) -> None:
        """更新薄弱环节信息。"""
        worst = self.db.get_worst_trades(5)
        max_dd = self.db.get_max_drawdown()

        if not worst:
            self._weak_text.setText("暂无数据。完成训练后这里会显示分析结果。")
            return

        lines = []
        lines.append(f"**历史最大回撤**: {max_dd:.2f}%")
        lines.append("")
        lines.append("**亏损最多的交易**:")
        for t in worst:
            lines.append(
                f"- {t['buy_date']} → {t['sell_date']}: "
                f"{t['return_pct']:.2f}% (持仓 {t['hold_days']} 天, "
                f"最大浮亏 {t['max_floating_loss']:.2f}%)"
            )

        self._weak_text.setText("\n".join(lines))

    # ============================================================
    # 样式辅助
    # ============================================================
    @staticmethod
    def _value_style(value: float) -> str:
        """根据正负返回文字颜色样式。"""
        color = COLOR_UP if value >= 0 else COLOR_DOWN
        return (
            f"color: {color}; font-size: 18px; font-weight: bold; "
            "background: transparent; border: none;"
        )


class StatsChartCanvas(FigureCanvasQTAgg):
    """统计图表画布（收益率趋势 + 持仓天数分布）。"""

    def __init__(self, parent=None):
        self.fig = Figure(facecolor=BG_FIGURE, dpi=100)
        super().__init__(self.fig)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def draw_charts(self, db) -> None:
        """从数据库读取数据并绘制图表。"""
        self.fig.clear()

        trend = db.get_return_trend(50)
        hold_days = db.get_hold_days_distribution()

        if not trend and not hold_days:
            ax = self.fig.add_subplot(111)
            ax.set_facecolor(BG_AXES)
            ax.text(0.5, 0.5, "暂无训练数据", transform=ax.transAxes,
                    color=COLOR_TEXT, ha="center", va="center", fontsize=14)
            ax.set_xticks([])
            ax.set_yticks([])
            self.draw_idle()
            return

        # 布局：2 行 1 列
        gs = self.fig.add_gridspec(2, 1, hspace=0.3,
                                    left=0.12, right=0.95, top=0.95, bottom=0.08)

        # ---- 收益率趋势 ----
        ax1 = self.fig.add_subplot(gs[0])
        ax1.set_facecolor(BG_AXES)
        ax1.tick_params(colors=COLOR_TEXT, labelsize=8)
        ax1.grid(True, color=COLOR_GRID, linewidth=0.5, alpha=0.5)
        for spine in ax1.spines.values():
            spine.set_color(COLOR_GRID)

        if trend:
            returns = [t["return_pct"] for t in trend]
            x = list(range(1, len(returns) + 1))
            colors = [COLOR_UP if r >= 0 else COLOR_DOWN for r in returns]
            ax1.bar(x, returns, color=colors, width=0.8, alpha=0.8)
            ax1.axhline(y=0, color=COLOR_TEXT, linewidth=0.5, alpha=0.3)
            ax1.set_ylabel("收益率 %", color=COLOR_TEXT, fontsize=9)
            ax1.set_title("训练收益率趋势", color=COLOR_TEXT, fontsize=10)
        else:
            ax1.text(0.5, 0.5, "暂无数据", transform=ax1.transAxes,
                     color=COLOR_TEXT, ha="center", va="center")

        # ---- 持仓天数分布 ----
        ax2 = self.fig.add_subplot(gs[1])
        ax2.set_facecolor(BG_AXES)
        ax2.tick_params(colors=COLOR_TEXT, labelsize=8)
        ax2.grid(True, color=COLOR_GRID, linewidth=0.5, alpha=0.5)
        for spine in ax2.spines.values():
            spine.set_color(COLOR_GRID)

        if hold_days:
            max_days = max(hold_days) if hold_days else 1
            bins = min(20, max(5, max_days // 2))
            ax2.hist(hold_days, bins=bins, color=COLOR_ACCENT,
                     alpha=0.7, edgecolor=COLOR_GRID)
            ax2.set_ylabel("次数", color=COLOR_TEXT, fontsize=9)
            ax2.set_xlabel("持仓天数（K线根数）", color=COLOR_TEXT, fontsize=9)
            ax2.set_title("持仓天数分布", color=COLOR_TEXT, fontsize=10)
        else:
            ax2.text(0.5, 0.5, "暂无数据", transform=ax2.transAxes,
                     color=COLOR_TEXT, ha="center", va="center")

        self.draw_idle()
