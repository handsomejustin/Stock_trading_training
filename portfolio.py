"""
盘感训练器 - 仓位管理模块

核心仓位管理逻辑：百分比仓位模型、分批建仓减仓、
加权均价计算、浮动盈亏追踪、交易评分。
"""

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class TradeRecord:
    """单笔交易记录。"""
    idx: int               # K 线索引
    action: str            # "buy" 或 "sell"
    price: float           # 成交价格
    date: str              # 成交日期
    ratio: float           # 本次交易仓位比例
    position_after: float  # 交易后总仓位
    is_auto: bool = False          # 是否为自动止损/止盈
    auto_reason: str = ""          # "stop_loss" 或 "take_profit"


@dataclass
class CompletedTrade:
    """一笔完整的往返交易（从首次买入到清仓）。"""
    buy_records: list[TradeRecord] = field(default_factory=list)
    sell_records: list[TradeRecord] = field(default_factory=list)
    buy_avg_price: float = 0.0     # 加权平均买入价
    sell_avg_price: float = 0.0    # 加权平均卖出价
    return_pct: float = 0.0        # 收益率 %
    hold_days: int = 0             # 持仓 K 线根数
    max_floating_profit: float = 0.0   # 持仓期间最大浮盈 %
    max_floating_loss: float = 0.0     # 持仓期间最大浮亏 %
    is_auto_exit: bool = False         # 是否由止损/止盈自动退出
    timing_score_5d: float = 0.0       # 买入后 5 日涨幅 %
    timing_score_10d: float = 0.0      # 买入后 10 日涨幅 %
    timing_score_20d: float = 0.0      # 买入后 20 日涨幅 %


class Portfolio:
    """
    百分比仓位管理器。

    position 用 0.0~1.0 表示持仓占总资金的比例。
    支持分批买卖、止损止盈、浮动盈亏追踪、交易评分。
    """

    def __init__(self):
        """初始化空仓状态。"""
        self.position: float = 0.0
        self.avg_cost: float = 0.0
        self.trades: list[TradeRecord] = []
        self.completed_trades: list[CompletedTrade] = []

        # 当前轮次（从买入到清仓）的中间记录
        self._pending_buys: list[TradeRecord] = []
        self._pending_sells: list[TradeRecord] = []

        # 止损止盈阈值（百分比，如 -0.05 表示 -5%）
        self.stop_loss_pct: Optional[float] = None
        self.take_profit_pct: Optional[float] = None

        # 持仓期间追踪的浮动盈亏
        self._max_floating_profit: float = 0.0
        self._max_floating_loss: float = 0.0

        # 持仓起始索引（用于计算 hold_days）
        self._hold_start_idx: int = -1

    # ============================================================
    # 买入
    # ============================================================
    def buy(self, idx: int, price: float, date: str,
            ratio: float = 1.0) -> bool:
        """
        分批买入。

        Args:
            idx: K 线索引
            price: 成交价
            date: 成交日期
            ratio: 期望买入仓位比例（0.0~1.0）

        Returns:
            bool: 是否成功（满仓或 ratio<=0 时返回 False）
        """
        if ratio <= 0 or self.position >= 1.0:
            return False

        # 实际可买入量
        actual = min(ratio, 1.0 - self.position)

        # 记录旧仓位
        old_position = self.position
        old_avg = self.avg_cost

        # 更新仓位
        self.position = old_position + actual

        # 更新加权均价
        if old_position > 0:
            self.avg_cost = (old_avg * old_position + price * actual) / self.position
        else:
            self.avg_cost = price

        # 创建交易记录
        record = TradeRecord(
            idx=idx, action="buy", price=price, date=date,
            ratio=actual, position_after=self.position,
        )
        self.trades.append(record)
        self._pending_buys.append(record)

        # 记录持仓起始（首次买入）
        if len(self._pending_buys) == 1:
            self._hold_start_idx = idx

        return True

    # ============================================================
    # 卖出
    # ============================================================
    def sell(self, idx: int, price: float, date: str,
             ratio: float = 1.0, is_auto: bool = False,
             auto_reason: str = "") -> bool:
        """
        分批卖出。

        Args:
            idx: K 线索引
            price: 成交价
            date: 成交日期
            ratio: 期望卖出仓位比例（0.0~1.0）
            is_auto: 是否为自动止损/止盈
            auto_reason: "stop_loss" 或 "take_profit"

        Returns:
            bool: 是否成功（空仓或 ratio<=0 时返回 False）
        """
        if ratio <= 0 or self.position <= 0:
            return False

        # 实际可卖出量
        actual = min(ratio, self.position)

        # 更新仓位
        self.position -= actual
        if self.position < 1e-10:
            self.position = 0.0

        # 创建交易记录
        record = TradeRecord(
            idx=idx, action="sell", price=price, date=date,
            ratio=actual, position_after=self.position,
            is_auto=is_auto, auto_reason=auto_reason,
        )
        self.trades.append(record)
        self._pending_sells.append(record)

        # 如果清仓了，闭环这笔完整交易
        if self.position == 0.0:
            self._close_round()

        return True

    # ============================================================
    # 闭环完整交易
    # ============================================================
    def _close_round(self) -> None:
        """将当前轮次的 pending 交易闭环为 CompletedTrade。"""
        if not self._pending_buys or not self._pending_sells:
            # 异常情况：没有买卖记录
            self._pending_buys.clear()
            self._pending_sells.clear()
            return

        # 计算加权平均买入价
        total_buy_value = sum(r.price * r.ratio for r in self._pending_buys)
        total_buy_ratio = sum(r.ratio for r in self._pending_buys)
        buy_avg = total_buy_value / total_buy_ratio if total_buy_ratio > 0 else 0.0

        # 计算加权平均卖出价
        total_sell_value = sum(r.price * r.ratio for r in self._pending_sells)
        total_sell_ratio = sum(r.ratio for r in self._pending_sells)
        sell_avg = total_sell_value / total_sell_ratio if total_sell_ratio > 0 else 0.0

        # 收益率
        return_pct = (sell_avg / buy_avg - 1.0) * 100.0 if buy_avg > 0 else 0.0

        # 持仓天数
        first_buy_idx = self._pending_buys[0].idx
        last_sell_idx = self._pending_sells[-1].idx
        hold_days = last_sell_idx - first_buy_idx

        # 是否自动退出
        is_auto_exit = any(r.is_auto for r in self._pending_sells)

        completed = CompletedTrade(
            buy_records=list(self._pending_buys),
            sell_records=list(self._pending_sells),
            buy_avg_price=buy_avg,
            sell_avg_price=sell_avg,
            return_pct=return_pct,
            hold_days=hold_days,
            max_floating_profit=self._max_floating_profit,
            max_floating_loss=self._max_floating_loss,
            is_auto_exit=is_auto_exit,
        )
        self.completed_trades.append(completed)

        # 重置轮次状态
        self._pending_buys.clear()
        self._pending_sells.clear()
        self._max_floating_profit = 0.0
        self._max_floating_loss = 0.0
        self._hold_start_idx = -1
        self.avg_cost = 0.0

    # ============================================================
    # 止损止盈检查
    # ============================================================
    def check_stop_loss_take_profit(self, idx: int, high: float,
                                     low: float, date: str) -> Optional[str]:
        """
        检查当前 K 线是否触发止损或止盈。

        止损用 low 检查（保守），止盈用 high 检查。
        两者同时触发时止损优先（保护本金）。

        Args:
            idx: K 线索引
            high: 当日最高价
            low: 当日最低价
            date: 日期

        Returns:
            "stop_loss" / "take_profit" / None
        """
        if self.position <= 0 or self.avg_cost <= 0:
            return None

        # 止损检查（优先）
        if self.stop_loss_pct is not None and self.stop_loss_pct < 0:
            change = (low - self.avg_cost) / self.avg_cost
            if change <= self.stop_loss_pct:
                return "stop_loss"

        # 止盈检查
        if self.take_profit_pct is not None and self.take_profit_pct > 0:
            change = (high - self.avg_cost) / self.avg_cost
            if change >= self.take_profit_pct:
                return "take_profit"

        return None

    # ============================================================
    # 浮动盈亏追踪
    # ============================================================
    def update_floating(self, high: float, low: float) -> None:
        """
        更新持仓期间的最大浮动盈亏。

        每次推演前进时调用，使用当日的最高/最低价。

        Args:
            high: 当日最高价
            low: 当日最低价
        """
        if self.position <= 0 or self.avg_cost <= 0:
            return

        profit_pct = (high - self.avg_cost) / self.avg_cost * 100.0
        loss_pct = (low - self.avg_cost) / self.avg_cost * 100.0

        if profit_pct > self._max_floating_profit:
            self._max_floating_profit = profit_pct
        if loss_pct < self._max_floating_loss:
            self._max_floating_loss = loss_pct

    # ============================================================
    # 时机评分
    # ============================================================
    def score_timing(self, df: pd.DataFrame,
                     buy_idx: int) -> tuple[float, float, float]:
        """
        计算买入时机评分（买入后 5/10/20 日的股价涨幅）。

        Args:
            df: 完整 K 线数据
            buy_idx: 买入 K 线索引

        Returns:
            (score_5d, score_10d, score_20d) 百分比
        """
        buy_price = df.iloc[buy_idx]["close"]
        n = len(df)
        scores = []

        for period in [5, 10, 20]:
            target_idx = min(buy_idx + period, n - 1)
            future_price = df.iloc[target_idx]["close"]
            score = (future_price / buy_price - 1.0) * 100.0
            scores.append(score)

        return tuple(scores)

    # ============================================================
    # 查询接口
    # ============================================================
    def get_trade_markers(self) -> list[dict]:
        """
        获取所有买卖标记，供图表绘制。

        返回兼容旧格式的 dict 列表，额外包含 ratio, position_after, is_auto。
        """
        return [
            {
                "idx": r.idx,
                "action": r.action,
                "price": r.price,
                "date": r.date,
                "ratio": r.ratio,
                "position_after": r.position_after,
                "is_auto": r.is_auto,
                "auto_reason": r.auto_reason,
            }
            for r in self.trades
        ]

    def summary(self, last_price: float) -> str:
        """
        生成训练结束时的收益总结。

        Args:
            last_price: 最后一根 K 线收盘价（用于虚拟平仓未闭环持仓）

        Returns:
            str: 格式化的收益总结文本
        """
        lines = []
        lines.append("=" * 50)
        lines.append("[训练结果总结]")
        lines.append("=" * 50)

        if not self.trades:
            lines.append("本次训练未进行任何交易。")
            return "\n".join(lines)

        total_return = 0.0
        trade_count = 0

        for i, ct in enumerate(self.completed_trades):
            sign = "+" if ct.return_pct >= 0 else ""
            lines.append(f"  交易 {i + 1}:")
            lines.append(f"    买入均价: {ct.buy_avg_price:.2f}")
            lines.append(f"    卖出均价: {ct.sell_avg_price:.2f}")
            lines.append(f"    收益率: {sign}{ct.return_pct:.2f}%")
            lines.append(f"    持仓天数: {ct.hold_days} 根K线")
            if ct.max_floating_profit != 0 or ct.max_floating_loss != 0:
                lines.append(f"    最大浮盈: +{ct.max_floating_profit:.2f}%")
                lines.append(f"    最大浮亏: {ct.max_floating_loss:.2f}%")
            if ct.is_auto_exit:
                lines.append(f"    [自动退出]")
            if ct.timing_score_5d != 0:
                lines.append(f"    时机评分: 5日{ct.timing_score_5d:+.2f}% "
                             f"10日{ct.timing_score_10d:+.2f}% "
                             f"20日{ct.timing_score_20d:+.2f}%")
            lines.append("-" * 30)
            total_return += ct.return_pct
            trade_count += 1

        # 如果仍持仓，虚拟平仓
        if self.position > 0 and self.avg_cost > 0:
            ret = (last_price / self.avg_cost - 1.0) * 100.0
            total_return += ret
            trade_count += 1
            sign = "+" if ret >= 0 else ""
            lines.append(f"  [未平仓] 虚拟平仓: {last_price:.2f}")
            lines.append(f"    买入均价: {self.avg_cost:.2f}")
            lines.append(f"    收益率: {sign}{ret:.2f}%")
            lines.append("-" * 30)

        lines.append(f"  [#] 完整交易次数: {trade_count}")
        if trade_count > 0:
            sign = "+" if total_return >= 0 else ""
            lines.append(f"  [!] 总收益率: {sign}{total_return:.2f}%")
        lines.append("=" * 50)

        return "\n".join(lines)

    # ============================================================
    # 重置
    # ============================================================
    def reset(self) -> None:
        """重置所有状态。"""
        self.position = 0.0
        self.avg_cost = 0.0
        self.trades.clear()
        self.completed_trades.clear()
        self._pending_buys.clear()
        self._pending_sells.clear()
        self.stop_loss_pct = None
        self.take_profit_pct = None
        self._max_floating_profit = 0.0
        self._max_floating_loss = 0.0
        self._hold_start_idx = -1

    # ============================================================
    # 属性
    # ============================================================
    @property
    def cash_ratio(self) -> float:
        """剩余现金比例。"""
        return 1.0 - self.position
