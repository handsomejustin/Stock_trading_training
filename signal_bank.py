"""
盘感训练器 - 信号题库引擎

扫描全市场日线数据，检测 6 类经典选时信号事件，预计算事件后
5/10/20 日的前瞻收益，缓存到独立的 signal_bank.db（与训练记录库分离）。

答题模式的批分依据是信号的【历史统计基率】（该信号历史上出现后的
上涨概率 / 平均收益），而非单次事件的实际结果——奖励"做期望为正的事"，
不奖励运气。单次事件的实际走势仅在揭晓时展示。

纯 pandas/numpy 实现，不依赖 Qt，可供脚本独立运行自测。
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from easy_tdx.MyTT import MACD, KDJ, RSI, MA


# ============================================================
# 信号定义
# 每个函数输入 dict(open/high/low/close/volume numpy数组)，
# 返回 bool 数组（True = 当日触发该信号）。
# 算法与 indicators.py 注册表保持一致（复用 IndicatorHub 计算）。
# ============================================================

def _shift(arr: np.ndarray) -> np.ndarray:
    """右移一位，首位补 NaN。"""
    out = np.empty_like(arr, dtype=float)
    out[0] = np.nan
    out[1:] = arr[:-1]
    return out


def _prev_max(arr: np.ndarray, window: int) -> np.ndarray:
    """前 window 根（不含当日）的滚动最大值，前 window 位为 NaN。"""
    return pd.Series(arr).rolling(window).max().shift(1).values


def _sig_macd_golden(hub_results, a) -> np.ndarray:
    dif = hub_results["MACD"]["DIF"]
    dea = hub_results["MACD"]["DEA"]
    return (dif > dea) & (_shift(dif) <= _shift(dea))


def _sig_kdj_golden_low(hub_results, a) -> np.ndarray:
    k = hub_results["KDJ"]["K"]
    d = hub_results["KDJ"]["D"]
    j = hub_results["KDJ"]["J"]
    cross = (k > d) & (_shift(k) <= _shift(d))
    return cross & (j < 30)


def _sig_break_high_20(hub_results, a) -> np.ndarray:
    prev_max = _prev_max(a["close"], 20)
    return a["close"] > prev_max


def _sig_pullback_ma20(hub_results, a) -> np.ndarray:
    ma20 = MA(a["close"], 20)
    touch = a["low"] <= ma20 * 1.02          # 盘中回踩至 MA20 附近（2%以内）
    above = a["close"] > ma20                # 收盘站上 MA20
    yang = a["close"] > a["open"]            # 收阳
    rising = ma20 > _shift(ma20)             # MA20 向上
    return touch & above & yang & rising


def _sig_volume_breakout(hub_results, a) -> np.ndarray:
    avg_vol = pd.Series(a["volume"]).rolling(20).mean().shift(1).values
    heavy = a["volume"] > 2 * avg_vol                     # 放量 2 倍
    surge = a["close"] / _shift(a["close"]) - 1 > 0.05    # 涨幅 > 5%
    breakout = a["close"] > _prev_max(a["close"], 20)     # 突破 20 日新高
    return heavy & surge & breakout


def _sig_rsi_overbought(hub_results, a) -> np.ndarray:
    rsi6 = hub_results["RSI"]["RSI6"]
    return (rsi6 > 85) & (_shift(rsi6) <= 85)             # 首日进入超买区


def _compute_signal_inputs(a: dict) -> dict:
    """
    只计算 6 个信号所需的指标数组。

    调用与 indicators.py 注册表完全相同的 MyTT 函数与默认参数，
    保证信号检测结果与训练图表所见指标一致。
    全量 15 指标计算约 800ms/股，仅算 3 个约 2ms/股。
    """
    toarr = lambda x: np.asarray(x, dtype=float)
    dif, dea, _ = MACD(a["close"], SHORT=12, LONG=26, M=9)
    k, d, j = KDJ(a["close"], a["high"], a["low"], N=9, M1=3, M2=3)
    rsi6 = RSI(a["close"], N=6)
    return {
        "MACD": {"DIF": toarr(dif), "DEA": toarr(dea)},
        "KDJ": {"K": toarr(k), "D": toarr(d), "J": toarr(j)},
        "RSI": {"RSI6": toarr(rsi6)},
    }


SIGNAL_DEFS = {
    "macd_golden": {
        "name": "MACD金叉",
        "desc": "DIF 上穿 DEA",
        "func": _sig_macd_golden,
    },
    "kdj_golden_low": {
        "name": "KDJ低位金叉",
        "desc": "K 上穿 D 且 J < 30",
        "func": _sig_kdj_golden_low,
    },
    "break_high_20": {
        "name": "突破20日新高",
        "desc": "收盘价创之前 20 日新高",
        "func": _sig_break_high_20,
    },
    "pullback_ma20": {
        "name": "回踩MA20获支撑",
        "desc": "回踩 MA20 不破且收阳，MA20 向上",
        "func": _sig_pullback_ma20,
    },
    "volume_breakout": {
        "name": "放量突破",
        "desc": "量能 2 倍于 20 日均量，涨幅超 5%，创 20 日新高",
        "func": _sig_volume_breakout,
    },
    "rsi_overbought": {
        "name": "RSI超买",
        "desc": "RSI6 首日突破 85 超买区",
        "func": _sig_rsi_overbought,
    },
}

# 事件检测前置预热（指标需要历史数据）与前瞻窗口
WARMUP_BARS = 60
FORWARD_BARS = 20


class SignalBank:
    """
    信号题库：全市场信号事件缓存 + 历史统计 + 随机出题。

    事件缓存存独立 SQLite（signal_bank.db），与 training_history.db
    互不影响，可随时删除重建。
    """

    DB_NAME = "signal_bank.db"

    # 每只股票每个信号最多保留的事件数（控制构建期内存）
    PER_STOCK_CAP = 20
    # 每个信号全局最多保留的题数（按日期取最近的）
    GLOBAL_CAP = 2000
    # 每只股票只检测最近 N 根 K 线内的事件（约10年）
    RECENT_BARS = 2500

    def __init__(self, db_path: str = None):
        if db_path is None:
            if getattr(sys, "frozen", False):
                base = Path(sys.executable).parent
            else:
                base = Path(__file__).parent
            db_path = str(base / self.DB_NAME)
        self.db_path = db_path

    # ============================================================
    # 连接 & 表
    # ============================================================
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                code TEXT NOT NULL,
                date TEXT NOT NULL,
                date_int INTEGER NOT NULL,
                signal_id TEXT NOT NULL,
                close REAL,
                fwd5 REAL, fwd10 REAL, fwd20 REAL,
                max_gain20 REAL, max_dd20 REAL
            );
            CREATE INDEX IF NOT EXISTS idx_events_signal
                ON events(signal_id);
            CREATE TABLE IF NOT EXISTS signal_stats (
                signal_id TEXT PRIMARY KEY,
                sample_n INTEGER,
                up5_rate REAL, avg5 REAL,
                up10_rate REAL, avg10 REAL,
                up20_rate REAL, avg20 REAL,
                avg_gain20 REAL, avg_dd20 REAL,
                profit_factor REAL
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)

    # ============================================================
    # 状态查询
    # ============================================================
    def is_built(self) -> bool:
        """题库是否已构建。"""
        if not Path(self.db_path).is_file():
            return False
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT value FROM meta WHERE key='built_at'").fetchone()
            return row is not None
        except sqlite3.DatabaseError:
            return False
        finally:
            conn.close()

    def event_count(self) -> int:
        conn = self._connect()
        try:
            return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        except sqlite3.DatabaseError:
            return 0
        finally:
            conn.close()

    # ============================================================
    # 构建
    # ============================================================
    def build(self, data_loader, progress_cb=None, stock_limit: int = 0) -> int:
        """
        全市场扫描并重建题库。

        Args:
            data_loader: DataLoader 实例（须已可用）
            progress_cb: 可选回调 progress_cb(text)，每 100 只股票汇报一次
            stock_limit: 仅扫描前 N 只股票（自测用，0 = 不限制）

        Returns:
            int: 入库事件总数
        """
        stocks = data_loader.scan_stocks()
        if not stocks:
            raise ValueError("未扫描到任何股票数据，请检查通达信数据目录")
        if stock_limit > 0:
            stocks = stocks[:stock_limit]

        conn = self._connect()
        try:
            self._create_tables(conn)
            conn.execute("DELETE FROM events")
            conn.execute("DELETE FROM signal_stats")
            conn.execute("DELETE FROM meta")

            collected = {sid: [] for sid in SIGNAL_DEFS}
            hub_config = {"indicators": {}, "ma_periods": []}

            for i, stock in enumerate(stocks):
                try:
                    df = data_loader.load_stock_dict(stock)
                except Exception:
                    continue
                if len(df) < WARMUP_BARS + FORWARD_BARS + 10:
                    continue

                try:
                    rows = self._detect_stock(df, stock)
                except Exception:
                    continue
                for sid, event_rows in rows.items():
                    collected[sid].extend(event_rows)

                if progress_cb and (i + 1) % 50 == 0:
                    progress_cb(f"构建题库 {i + 1}/{len(stocks)} 只…")

            # ---- 历史统计（基于全部采集事件，早于降采样） ----
            stats_rows = []
            for sid, rows in collected.items():
                stats_rows.append(self._stats_row(sid, rows))
            if stats_rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO signal_stats VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?)", stats_rows)

            # ---- 全局降采样：每信号保留最近 GLOBAL_CAP 条 ----
            all_rows = []
            for sid, rows in collected.items():
                rows.sort(key=lambda r: r[2])          # 按 date_int 升序
                all_rows.extend(rows[-self.GLOBAL_CAP:])
            conn.executemany(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)", all_rows)

            conn.execute("INSERT OR REPLACE INTO meta VALUES ('built_at', ?)",
                         (datetime.now().isoformat(timespec="seconds"),))
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('stock_count', ?)",
                         (str(len(stocks)),))
            conn.commit()
            return len(all_rows)
        finally:
            conn.close()

    def _detect_stock(self, df: pd.DataFrame, stock: dict) -> dict:
        """
        检测单只股票的信号事件，返回 {signal_id: [event_rows]}。

        event_row 为 events 表的元组：
        (code, date, date_int, signal_id, close, fwd5, fwd10, fwd20,
         max_gain20, max_dd20)
        """
        a = {
            "open": df["open"].values.astype(float),
            "high": df["high"].values.astype(float),
            "low": df["low"].values.astype(float),
            "close": df["close"].values.astype(float),
            "volume": df["volume"].values.astype(float),
        }
        n = len(a["close"])
        lo_i = WARMUP_BARS
        hi_i = n - 1 - FORWARD_BARS          # 需要完整 20 日前瞻窗口
        if hi_i <= lo_i:
            return {}

        # 仅计算信号所需的 MACD/KDJ/RSI（与训练图表指标算法一致）
        hub_results = _compute_signal_inputs(a)

        # 前瞻收益 / 期间最大涨跌（向量化滑窗）
        high_win = sliding_window_view(a["high"], FORWARD_BARS)
        low_win = sliding_window_view(a["low"], FORWARD_BARS)
        c = a["close"]

        dates = df["date"].tolist()
        date_ints = [int(s.replace("-", "")) for s in dates]
        code = f"{stock['market']}{stock['code']}"
        recent_from = n - self.RECENT_BARS

        out = {}
        for sid, defn in SIGNAL_DEFS.items():
            try:
                mask = defn["func"](hub_results, a)
            except Exception:
                continue
            idxs = np.where(mask[lo_i:hi_i + 1])[0] + lo_i
            idxs = idxs[idxs >= recent_from]
            if len(idxs) == 0:
                continue
            idxs = idxs[-self.PER_STOCK_CAP:]   # 每股每信号只留最近 N 条

            c0 = c[idxs]
            rows = []
            for k, i in enumerate(idxs):
                win_h = high_win[i + 1]
                win_l = low_win[i + 1]
                rows.append((
                    code, dates[i], date_ints[i], sid, float(c0[k]),
                    round(float((c[idxs[k] + 5] / c0[k] - 1) * 100), 4),
                    round(float((c[idxs[k] + 10] / c0[k] - 1) * 100), 4),
                    round(float((c[idxs[k] + 20] / c0[k] - 1) * 100), 4),
                    round(float((win_h.max() / c0[k] - 1) * 100), 4),
                    round(float((win_l.min() / c0[k] - 1) * 100), 4),
                ))
            out[sid] = rows
        return out

    @staticmethod
    def _stats_row(signal_id: str, rows: list) -> tuple:
        """基于全部采集事件计算该信号的历史统计。"""
        if not rows:
            return (signal_id, 0, None, None, None, None, None,
                    None, None, None, None)
        fwd5 = np.array([r[5] for r in rows])
        fwd10 = np.array([r[6] for r in rows])
        fwd20 = np.array([r[7] for r in rows])
        gain = np.array([r[8] for r in rows])
        dd = np.array([r[9] for r in rows])

        pos_sum = fwd20[fwd20 > 0].sum()
        neg_sum = abs(fwd20[fwd20 < 0].sum())
        profit_factor = round(float(pos_sum / neg_sum), 3) if neg_sum > 0 \
            else (99.0 if pos_sum > 0 else 0.0)

        return (
            signal_id, len(rows),
            round(float((fwd5 > 0).mean()), 4), round(float(fwd5.mean()), 4),
            round(float((fwd10 > 0).mean()), 4), round(float(fwd10.mean()), 4),
            round(float((fwd20 > 0).mean()), 4), round(float(fwd20.mean()), 4),
            round(float(gain.mean()), 4), round(float(dd.mean()), 4),
            profit_factor,
        )

    # ============================================================
    # 查询 & 出题
    # ============================================================
    def get_stats(self, signal_id: str) -> dict:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM signal_stats WHERE signal_id=?",
                (signal_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def correct_action(stats: dict) -> str:
        """
        由历史统计基率推导标准动作。

        - 20日上涨概率 ≥ 55% 且平均收益 ≥ +0.5% → 买入（期望为正）
        - 20日上涨概率 ≤ 45% 且平均收益 ≤ -0.5% → 清仓（期望为负）
        - 其余 → 观望（无显著优势）
        """
        if not stats or stats.get("sample_n", 0) < 30:
            return "hold"       # 样本不足，保守观望
        up20, avg20 = stats["up20_rate"], stats["avg20"]
        if up20 >= 0.55 and avg20 >= 0.5:
            return "buy"
        if up20 <= 0.45 and avg20 <= -0.5:
            return "sell"
        return "hold"

    def draw_question(self, signal_id: str = None) -> dict:
        """
        随机抽取一道题。

        Args:
            signal_id: 指定信号；None 则全信号随机

        Returns:
            dict: code/date/signal_id/signal_name/close/fwd*/max_* +
                  stats(历史统计 dict) + correct(标准动作)；
                  题库为空时返回 None
        """
        conn = self._connect()
        try:
            if signal_id:
                row = conn.execute(
                    "SELECT * FROM events WHERE signal_id=? "
                    "ORDER BY RANDOM() LIMIT 1", (signal_id,)).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM events ORDER BY RANDOM() LIMIT 1").fetchone()
            if row is None:
                return None
            event = dict(row)
            event["signal_name"] = SIGNAL_DEFS[event["signal_id"]]["name"]
            event["stats"] = self.get_stats(event["signal_id"])
            event["correct"] = self.correct_action(event["stats"])
            return event
        finally:
            conn.close()


# ============================================================
# 自测入口：python signal_bank.py [股票数量上限]
# ============================================================
if __name__ == "__main__":
    from data_loader import DataLoader

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    dl = DataLoader()
    if not dl.is_available():
        print("❌ 未找到通达信数据目录")
        sys.exit(1)

    if limit > 0:
        print(f"⚠ 自测模式：仅扫描前 {limit} 只股票")

    bank = SignalBank(db_path=str(Path(__file__).parent / "signal_bank_test.db"))
    import time
    t0 = time.time()

    def _p(text):
        print(f"  {text}  [{time.time() - t0:.0f}s]")

    total = bank.build(dl, progress_cb=_p, stock_limit=limit)
    print(f"✅ 题库构建完成: {total} 个事件, 耗时 {time.time() - t0:.0f}s")

    conn = bank._connect()
    print("\n各信号统计:")
    for row in conn.execute("SELECT * FROM signal_stats"):
        d = dict(row)
        if d["sample_n"]:
            print(f"  {SIGNAL_DEFS[d['signal_id']]['name']:<12} "
                  f"样本{d['sample_n']:>6} | 5日涨{d['up5_rate']:.1%} 均{d['avg5']:+.2f}% | "
                  f"20日涨{d['up20_rate']:.1%} 均{d['avg20']:+.2f}% | "
                  f"盈亏比{d['profit_factor']} | 标准动作={bank.correct_action(d)}")
    conn.close()

    q = bank.draw_question()
    if q:
        print(f"\n抽题验证: {q['code']} {q['date']} {q['signal_name']} "
              f"fwd20={q['fwd20']}% 正确={q['correct']}")
