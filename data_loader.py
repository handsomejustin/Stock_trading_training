"""
盘感训练器 - 数据加载模块

负责从本地通达信 .day 文件加载日线数据，
支持随机选股和随机截取指定长度的历史片段。
"""

import random
from pathlib import Path

import pandas as pd
from easy_tdx.offline import (
    detect_tdx_home,
    read_daily_bars,
    resolve_vipdoc,
)


class DataLoader:
    """通达信日线数据加载器，支持随机选股。"""

    def __init__(self, tdx_home: str = None):
        """
        初始化数据加载器。

        Args:
            tdx_home: 通达信安装目录路径。为 None 时自动检测。
        """
        if tdx_home:
            self.tdx_home = Path(tdx_home)
        else:
            detected = detect_tdx_home()
            self.tdx_home = Path(detected) if detected else None

        self.vipdoc = None
        self.stock_list: list[dict] = []

        if self.tdx_home and self.tdx_home.is_dir():
            # 尝试解析 vipdoc 目录
            vipdoc_path = self.tdx_home / "vipdoc"
            if vipdoc_path.is_dir():
                self.vipdoc = vipdoc_path

    def is_available(self) -> bool:
        """检查数据源是否可用（通达信目录存在且包含 vipdoc）。"""
        return self.vipdoc is not None and self.vipdoc.is_dir()

    def scan_stocks(self) -> list[dict]:
        """
        扫描通达信 vipdoc 目录下所有 A 股日线文件。

        过滤规则：
        - 仅保留上海 sh6*.day（沪市主板A股）
        - 仅保留深圳 sz0*.day（深市主板）和 sz3*.day（创业板）
        - 排除指数（sh0*, sz399*）和基金/债券

        Returns:
            list[dict]: 股票列表，每项含 path, market, code, name
        """
        if not self.is_available():
            return []

        stocks = []
        # 扫描上海市场
        sh_lday = self.vipdoc / "sh" / "lday"
        if sh_lday.is_dir():
            for f in sh_lday.glob("sh6*.day"):
                code = f.stem[2:]  # 去掉 "sh" 前缀
                stocks.append({
                    "path": f,
                    "market": "SH",
                    "code": code,
                    "name": f.stem,
                })

        # 扫描深圳市场（主板 000xxx + 创业板 300xxx）
        sz_lday = self.vipdoc / "sz" / "lday"
        if sz_lday.is_dir():
            for f in sz_lday.glob("sz0*.day"):
                code = f.stem[2:]
                # 排除指数（sz399xxx 为深证指数）
                if code.startswith("399"):
                    continue
                stocks.append({
                    "path": f,
                    "market": "SZ",
                    "code": code,
                    "name": f.stem,
                })
            for f in sz_lday.glob("sz3*.day"):
                code = f.stem[2:]
                if code.startswith("399"):
                    continue
                stocks.append({
                    "path": f,
                    "market": "SZ",
                    "code": code,
                    "name": f.stem,
                })

        self.stock_list = stocks
        return stocks

    def random_pick(self, days: int = 120) -> tuple[pd.DataFrame, str]:
        """
        随机选择一只股票，随机截取指定长度的历史数据。

        包含额外的 50 根缓冲K线用于指标预热（EMA/SMA 等需要历史前缀）。

        Args:
            days: 训练天数（用户可见的部分）

        Returns:
            tuple: (DataFrame, 股票代码字符串)
            DataFrame 列: date, open, high, low, close, volume

        Raises:
            ValueError: 数据不可用或没有足够长的股票
        """
        if not self.stock_list:
            raise ValueError("未扫描到任何股票数据，请检查通达信数据目录")

        # 需要的总长度：训练天数 + 指标预热缓冲
        total_needed = days + 50
        min_warmup = 26  # MACD LONG 参数，确保主要指标有有效值

        # 打乱顺序后逐一尝试，找到第一个足够长的股票
        candidates = list(self.stock_list)
        random.shuffle(candidates)

        for stock in candidates:
            try:
                bars = read_daily_bars(stock["path"])
            except Exception:
                continue

            if not bars or len(bars) < total_needed:
                continue

            # 随机选择起始位置，确保截取后有足够的总长度
            max_start = len(bars) - total_needed
            start_idx = random.randint(0, max_start)
            sliced = bars[start_idx:start_idx + total_needed]

            # 转为 DataFrame
            df = pd.DataFrame([{
                "date": f"{b.year}-{b.month:02d}-{b.day:02d}",
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": float(b.vol),
            } for b in sliced])

            # 重置索引
            df = df.reset_index(drop=True)

            code = f"{stock['market']}{stock['code']}"
            return df, code

        raise ValueError(
            f"没有找到足够长的股票数据（需要 {total_needed} 根K线）。"
            "请在通达信中下载更多日线数据。"
        )

    def get_stock_count(self) -> int:
        """获取已扫描到的股票数量。"""
        return len(self.stock_list)
