"""
盘感训练器 - 交易管理模块

管理模拟交易的仓位状态、买卖记录和收益率计算。
首版支持简单三态模型：空仓 → 满仓买入 → 清仓卖出。
"""


class TradeManager:
    """模拟交易仓位管理器。"""

    def __init__(self):
        """初始化空仓状态。"""
        self.position = 0        # 0=空仓, 1=满仓
        self.trades: list[dict] = []  # 所有交易记录
        self.buy_price = 0.0     # 买入价格
        self.buy_date = ""       # 买入日期
        self.buy_idx = -1        # 买入时的K线索引

    def buy(self, idx: int, price: float, date: str) -> bool:
        """
        满仓买入。

        Args:
            idx: K 线索引
            price: 成交价（当日收盘价）
            date: 成交日期

        Returns:
            bool: 买入是否成功（已持仓时返回 False）
        """
        if self.position != 0:
            return False

        self.position = 1
        self.buy_price = price
        self.buy_date = date
        self.buy_idx = idx

        self.trades.append({
            "idx": idx,
            "action": "buy",
            "price": price,
            "date": date,
        })
        return True

    def sell(self, idx: int, price: float, date: str) -> bool:
        """
        清仓卖出。

        Args:
            idx: K 线索引
            price: 成交价（当日收盘价）
            date: 成交日期

        Returns:
            bool: 卖出是否成功（空仓时返回 False）
        """
        if self.position != 1:
            return False

        self.position = 0
        self.trades.append({
            "idx": idx,
            "action": "sell",
            "price": price,
            "date": date,
        })
        return True

    def get_trade_markers(self) -> list[dict]:
        """
        获取所有买卖标记点，供图表绘制箭头。

        Returns:
            list[dict]: 每项含 idx, action, price, date
        """
        return list(self.trades)

    def summary(self, last_price: float) -> str:
        """
        生成训练结束时的收益总结。

        如果仍持仓未卖出，用 last_price 做虚拟平仓计算。

        Args:
            last_price: 最后一根K线的收盘价

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

        # 遍历交易记录，计算每笔完整交易（买入→卖出）的收益
        total_return = 0.0
        trade_count = 0
        current_buy = None

        for t in self.trades:
            if t["action"] == "buy":
                current_buy = t
                lines.append(f"  [B] 买入: {t['date']} @ {t['price']:.2f}")
            elif t["action"] == "sell" and current_buy is not None:
                ret = (t["price"] / current_buy["price"] - 1) * 100
                total_return += ret
                trade_count += 1
                sign = "+" if ret >= 0 else ""
                lines.append(f"  [S] 卖出: {t['date']} @ {t['price']:.2f}")
                lines.append(f"  [$] 收益率: {sign}{ret:.2f}%")
                lines.append("-" * 30)
                current_buy = None

        # 如果仍持仓，用最新价虚拟平仓
        if self.position == 1 and current_buy is not None:
            ret = (last_price / current_buy["price"] - 1) * 100
            total_return += ret
            trade_count += 1
            sign = "+" if ret >= 0 else ""
            lines.append(f"  [S] 虚拟平仓: {last_price:.2f}")
            lines.append(f"  [$] 收益率: {sign}{ret:.2f}%")
            lines.append("-" * 30)

        lines.append(f"  [#] 交易次数: {trade_count}")
        if trade_count > 0:
            sign = "+" if total_return >= 0 else ""
            lines.append(f"  [!] 总收益率: {sign}{total_return:.2f}%")
        lines.append("=" * 50)

        return "\n".join(lines)

    def reset(self) -> None:
        """重置所有交易状态。"""
        self.position = 0
        self.trades.clear()
        self.buy_price = 0.0
        self.buy_date = ""
        self.buy_idx = -1
