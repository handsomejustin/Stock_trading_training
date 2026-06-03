"""
盘感训练器 - 交易管理模块

TradeManager 作为 Portfolio 的薄封装层，
保持向后兼容 API，同时暴露新的分仓、止损止盈功能。
"""

from portfolio import Portfolio, CompletedTrade
import pandas as pd


class TradeManager:
    """
    模拟交易管理器。

    委托 Portfolio 执行实际仓位管理，
    对外提供兼容旧版的简化接口 + 新增的分仓/止损止盈接口。
    """

    def __init__(self):
        """初始化。"""
        self.portfolio = Portfolio()
        # 向后兼容属性：外部代码可能直接读取
        self.position: float = 0.0
        self.trades: list[dict] = []
        # 保留旧属性以兼容（部分代码可能读取）
        self.buy_price = 0.0
        self.buy_date = ""
        self.buy_idx = -1

    # ============================================================
    # 买入 / 卖出
    # ============================================================
    def buy(self, idx: int, price: float, date: str,
            ratio: float = 1.0) -> bool:
        """
        买入。

        Args:
            idx: K 线索引
            price: 成交价
            date: 成交日期
            ratio: 买入仓位比例（默认 1.0 = 全仓）

        Returns:
            bool: 是否成功
        """
        result = self.portfolio.buy(idx, price, date, ratio)
        if result:
            self._sync_state()
        return result

    def sell(self, idx: int, price: float, date: str,
             ratio: float = 1.0, is_auto: bool = False,
             auto_reason: str = "") -> bool:
        """
        卖出。

        Args:
            idx: K 线索引
            price: 成交价
            date: 成交日期
            ratio: 卖出仓位比例（默认 1.0 = 全部卖出）
            is_auto: 是否为自动止损/止盈触发
            auto_reason: "stop_loss" 或 "take_profit"

        Returns:
            bool: 是否成功
        """
        result = self.portfolio.sell(idx, price, date, ratio,
                                     is_auto, auto_reason)
        if result:
            self._sync_state()
        return result

    # ============================================================
    # 止损止盈
    # ============================================================
    def check_stop_loss_take_profit(self, idx: int, high: float,
                                     low: float, date: str) -> str:
        """
        检查是否触发止损或止盈。

        Returns:
            "stop_loss" / "take_profit" / None
        """
        return self.portfolio.check_stop_loss_take_profit(idx, high, low, date)

    def update_floating(self, high: float, low: float) -> None:
        """更新浮动盈亏追踪。"""
        self.portfolio.update_floating(high, low)

    def set_stop_loss(self, pct) -> None:
        """
        设置止损百分比。

        Args:
            pct: 负数表示止损（如 -0.05 = -5%），None 不启用
        """
        self.portfolio.stop_loss_pct = pct

    def set_take_profit(self, pct) -> None:
        """
        设置止盈百分比。

        Args:
            pct: 正数表示止盈（如 0.10 = +10%），None 不启用
        """
        self.portfolio.take_profit_pct = pct

    # ============================================================
    # 查询接口
    # ============================================================
    def get_trade_markers(self) -> list[dict]:
        """
        获取所有买卖标记点，供图表绘制。

        每条记录包含旧字段 (idx, action, price, date) 和新字段
        (ratio, position_after, is_auto, auto_reason)。
        """
        return self.portfolio.get_trade_markers()

    def get_completed_trades(self) -> list[CompletedTrade]:
        """获取所有已闭环的完整交易记录。"""
        return self.portfolio.completed_trades

    def summary(self, last_price: float) -> str:
        """
        生成训练结束时的收益总结。

        Args:
            last_price: 最后一根 K 线收盘价
        """
        return self.portfolio.summary(last_price)

    # ============================================================
    # 时机评分
    # ============================================================
    def score_all_timing(self, df: pd.DataFrame) -> None:
        """
        对所有已闭环但未评分的交易计算时机评分。

        Args:
            df: 完整 K 线数据
        """
        for ct in self.portfolio.completed_trades:
            if ct.timing_score_5d == 0.0 and ct.buy_records:
                buy_idx = ct.buy_records[0].idx
                s5, s10, s20 = self.portfolio.score_timing(df, buy_idx)
                ct.timing_score_5d = s5
                ct.timing_score_10d = s10
                ct.timing_score_20d = s20

    # ============================================================
    # 重置
    # ============================================================
    def reset(self) -> None:
        """重置所有交易状态。"""
        self.portfolio.reset()
        self._sync_state()

    # ============================================================
    # 内部同步
    # ============================================================
    def _sync_state(self) -> None:
        """从 Portfolio 同步本地状态。"""
        self.position = self.portfolio.position
        self.trades = self.portfolio.get_trade_markers()
        # 同步旧兼容属性
        if self.portfolio._pending_buys:
            last_buy = self.portfolio._pending_buys[-1]
            self.buy_price = last_buy.price
            self.buy_date = last_buy.date
            self.buy_idx = last_buy.idx
        else:
            self.buy_price = 0.0
            self.buy_date = ""
            self.buy_idx = -1
