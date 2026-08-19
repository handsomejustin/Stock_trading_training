"""
盘感训练器 - 数据加载模块

负责从本地通达信 .day 文件加载日线数据，
支持随机选股和随机截取指定长度的历史片段。
加载后自动进行前复权处理（基于 gbbq 除权除息数据）。
"""

import random
from pathlib import Path

import numpy as np
import pandas as pd
from easy_tdx.offline import (
    detect_tdx_home,
    read_daily_bars,
    read_gbbq,
    resolve_vipdoc,
)
from easy_tdx.offline.daily_bar import find_daily_bar_file


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
        self._gbbq_cache: dict | None = None  # 惰性加载

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

    def random_pick(self, days: int = 120,
                    ma_periods: list[int] | None = None) -> tuple[pd.DataFrame, str]:
        """
        随机选择一只股票，随机截取指定长度的历史数据。

        包含额外的缓冲K线用于指标预热（均线等需要历史前缀）。
        缓冲量根据最长均线周期动态计算，至少保证总数据量 ≥ 250 根。

        Args:
            days: 训练天数（用户可见的部分）
            ma_periods: 均线周期列表，用于确定预热缓冲量。
                        为 None 时默认按 MA120 计算。

        Returns:
            tuple: (DataFrame, 股票代码字符串)
            DataFrame 列: date, open, high, low, close, volume

        Raises:
            ValueError: 数据不可用或没有足够长的股票
        """
        if not self.stock_list:
            raise ValueError("未扫描到任何股票数据，请检查通达信数据目录")

        # 根据最长均线周期计算缓冲量
        if ma_periods:
            max_ma = max(ma_periods)
        else:
            max_ma = 120
        buffer = max(max_ma + 10, 130)  # 至少 130 根缓冲
        total_needed = max(days + buffer, 250)  # 至少 250 根总量

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
                "date_int": b.year * 10000 + b.month * 100 + b.day,
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": float(b.vol),
            } for b in sliced])

            # 重置索引
            df = df.reset_index(drop=True)

            # ---- 前复权处理 ----
            df = self._apply_forward_adjust(df, stock["market"], stock["code"])

            # 移除临时列
            if "date_int" in df.columns:
                df = df.drop(columns=["date_int"])

            code = f"{stock['market']}{stock['code']}"
            return df, code

        raise ValueError(
            f"没有找到足够长的股票数据（需要 {total_needed} 根K线）。"
            "请在通达信中下载更多日线数据。"
        )

    def get_stock_count(self) -> int:
        """获取已扫描到的股票数量。"""
        return len(self.stock_list)

    # ============================================================
    # 指定股票加载
    # ============================================================
    def load_specific_stock(self, stock_code: str) -> pd.DataFrame:
        """
        根据股票代码加载完整日线数据。

        Args:
            stock_code: 如 "SH600519" 或 "SZ000001"

        Returns:
            pd.DataFrame: 前复权日线数据
        """
        prefix = stock_code[:2].upper()
        code = stock_code[2:]
        market = 1 if prefix == "SH" else 0

        filepath = find_daily_bar_file(market, code, self.vipdoc)
        if not filepath.is_file():
            raise ValueError(f"股票数据文件不存在: {filepath}")

        bars = read_daily_bars(filepath)
        if not bars:
            raise ValueError(f"股票 {stock_code} 无日线数据")

        df = pd.DataFrame([{
            "date": f"{b.year}-{b.month:02d}-{b.day:02d}",
            "date_int": b.year * 10000 + b.month * 100 + b.day,
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "close": float(b.close),
            "volume": float(b.vol),
        } for b in bars])

        df = df.reset_index(drop=True)
        df = self._apply_forward_adjust(df, prefix, code)

        if "date_int" in df.columns:
            df = df.drop(columns=["date_int"])

        return df

    # ============================================================
    # 周线重采样
    # ============================================================
    @staticmethod
    def resample_weekly(daily_df: pd.DataFrame) -> pd.DataFrame:
        """
        将日线数据重采样为周线。

        按自然周聚合（周五结束），生成 _daily_indices 列
        记录每根周线对应的日线索引范围（用于 cursor 映射）。

        Args:
            daily_df: 日线 DataFrame（需含 date, open, high, low, close, volume）

        Returns:
            pd.DataFrame: 周线数据 + _daily_indices 列
        """
        df = daily_df.copy()
        df["_orig_idx"] = range(len(df))
        df["date_dt"] = pd.to_datetime(df["date"])

        weekly_groups = df.groupby(pd.Grouper(key="date_dt", freq="W-FRI"))

        rows = []
        for _date, group in weekly_groups:
            if group.empty:
                continue
            rows.append({
                "date": _date.strftime("%Y-%m-%d"),
                "open": group["open"].iloc[0],
                "high": group["high"].max(),
                "low": group["low"].min(),
                "close": group["close"].iloc[-1],
                "volume": group["volume"].sum(),
                "_daily_indices": group["_orig_idx"].tolist(),
            })

        if not rows:
            return pd.DataFrame(columns=["date", "open", "high", "low",
                                          "close", "volume", "_daily_indices"])

        result = pd.DataFrame(rows)
        result = result.reset_index(drop=True)
        return result

    # ============================================================
    # 板块联动
    # ============================================================
    def load_sector_peers(self, stock_code: str,
                          peer_count: int = 3) -> list[tuple[str, pd.DataFrame]]:
        """
        加载同板块的其他股票数据。

        Args:
            stock_code: 当前股票代码 (如 "SH600519")
            peer_count: 需要加载的同板块股票数量

        Returns:
            list of (stock_code_str, DataFrame) 元组
        """
        code_digits = stock_code[2:]

        # 同板块候选代码：优先 block_zs.dat，回退 tdxhy.cfg 行业分类
        candidates = self._find_sector_candidates(code_digits)
        if not candidates:
            return []

        candidates = [c for c in candidates if c != code_digits]
        random.shuffle(candidates)

        peers = []
        for candidate_code in candidates:
            if len(peers) >= peer_count:
                break

            prefix = "SH" if candidate_code.startswith("6") else "SZ"
            full_code = f"{prefix}{candidate_code}"

            try:
                df = self.load_specific_stock(full_code)
                if len(df) >= 50:
                    peers.append((full_code, df))
            except Exception:
                continue

        return peers

    def _find_sector_candidates(self, code_digits: str) -> list[str]:
        """查找与指定股票同板块的代码列表。

        新版通达信可能没有 block_zs.dat，此时回退到 tdxhy.cfg
        行业分类文件（按通达信行业代码匹配同行业个股）。
        """
        # 来源 1: block_zs.dat 板块文件
        block_path = self.tdx_home / "T0002" / "hq_cache" / "block_zs.dat"
        if block_path.is_file():
            try:
                from easy_tdx.offline.block import read_block_dat
                blocks = read_block_dat(block_path)
                for block in blocks:
                    if code_digits in block.codes:
                        return list(block.codes)
            except Exception:
                pass

        # 来源 2: tdxhy.cfg 行业分类（{code: (tdx_industry, sw_industry)}）
        hy_path = self.tdx_home / "T0002" / "hq_cache" / "tdxhy.cfg"
        if hy_path.is_file():
            try:
                from easy_tdx.codec.industry import parse_tdxhy_cfg
                mapping = parse_tdxhy_cfg(hy_path.read_bytes())
                entry = mapping.get(code_digits)
                if entry and entry[0]:
                    tdx_ind = entry[0]
                    return [c for c, (t, _s) in mapping.items() if t == tdx_ind]
            except Exception:
                pass

        return []

    # ============================================================
    # 前复权
    # ============================================================
    def _load_gbbq(self) -> dict:
        """
        惰性加载 gbbq 除权除息数据，按 market+code 索引。

        Returns:
            dict: key = "SH600519" / "SZ000001"，value = list[GbbqRecord]
        """
        if self._gbbq_cache is not None:
            return self._gbbq_cache

        self._gbbq_cache = {}
        try:
            gbbq_path = self.tdx_home / "T0002" / "hq_cache" / "gbbq"
            if not gbbq_path.is_file():
                return self._gbbq_cache

            records = read_gbbq(gbbq_path)
            for r in records:
                if r.category != 1:
                    continue  # 仅保留除权除息记录
                prefix = "SH" if r.market == 1 else "SZ"
                key = f"{prefix}{r.code}"
                if key not in self._gbbq_cache:
                    self._gbbq_cache[key] = []
                self._gbbq_cache[key].append(r)
        except Exception:
            pass  # gbbq 不可用时跳过复权

        return self._gbbq_cache

    def _apply_forward_adjust(self, df: pd.DataFrame,
                              market: str, code: str) -> pd.DataFrame:
        """
        对 DataFrame 进行前复权处理。

        前复权原理：保持最新价格不变，用累计除权因子调整历史价格。
        每次除权除息的调整因子 = (收盘价 - 每股分红 + 配股价×每股配股)
                                 / (收盘价 × (1 + 每股送股 + 每股配股))

        Args:
            df: 包含 date_int, open, high, low, close, volume 列的 DataFrame
            market: "SH" 或 "SZ"
            code: 6位股票代码

        Returns:
            pd.DataFrame: 前复权后的 DataFrame
        """
        gbbq = self._load_gbbq()
        key = f"{market}{code}"
        events = gbbq.get(key, [])

        if not events:
            return df  # 无除权记录，直接返回

        # 按日期排序
        events.sort(key=lambda r: r.datetime)

        # 构建 DataFrame 的日期索引映射
        date_ints = df["date_int"].values

        # 从最新日期向回计算累计除权因子
        # factor[i] 表示第 i 根 bar 的前复权因子
        factors = np.ones(len(df), dtype=np.float64)

        for event in events:
            ex_date = event.datetime

            # 找到除权日在 df 中的位置（除权日当天开始用新价格）
            # np.searchsorted 找到第一个 >= ex_date 的位置
            idx = np.searchsorted(date_ints, ex_date)
            if idx >= len(date_ints) or date_ints[idx] != ex_date:
                # 除权日不在当前数据范围内，跳过
                continue

            # 需要调整的是除权日之前（idx 左侧）的所有 bar
            if idx == 0:
                continue  # 没有更早的 bar 需要调整

            # 取除权日前一天的收盘价作为基准
            prev_close = df.iloc[idx - 1]["close"]

            if prev_close <= 0:
                continue

            # gbbq 字段含义（每10股）：
            #   hongli = 每10股派息（元）
            #   songgu = 每10股送股（股）
            #   peigu  = 每10股配股（股）
            #   peigujia = 配股价（元/股）
            dividend = event.hongli_panqianliutong / 10.0   # 每股派息
            bonus = event.songgu_qianzongguben / 10.0       # 每股送股
            rights = event.peigu_houzongguben / 10.0        # 每股配股
            rights_price = event.peigujia_qianzongguben      # 配股价

            # 除权因子
            total_dilution = 1.0 + bonus + rights
            if total_dilution == 0:
                continue

            # 调整因子 = (前收盘 - 分红 + 配股价×配股比) / (前收盘 × (1+送股比+配股比))
            # 简化：对 OHLC 的价格乘以 1/(1+送+配)，再减去每股分红的影响
            event_factor = (prev_close - dividend + rights_price * rights) / (prev_close * total_dilution)

            if event_factor <= 0:
                continue

            # 对除权日之前的所有 bar 累乘因子
            factors[:idx] *= event_factor

        # 应用因子到 OHLC（保留2位小数精度）
        for col in ("open", "high", "low", "close"):
            df[col] = np.round(df[col].values * factors, 2)

        return df
