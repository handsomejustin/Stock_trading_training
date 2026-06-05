"""
盘感训练器 - 数据库管理模块

使用 SQLite 存储训练历史数据（sessions + trades），
供统计面板查询聚合。
"""

import sys
import sqlite3
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd


class Database:
    """
    SQLite 数据库管理器。

    管理训练历史数据的持久化、查询和聚合统计。
    使用 WAL 模式确保读写安全。
    """

    DB_NAME = "training_history.db"

    def __init__(self, db_path: str = None):
        """
        初始化数据库连接并建表。

        Args:
            db_path: 数据库文件路径。默认为项目根目录。
        """
        if db_path is None:
            if getattr(sys, 'frozen', False):
                base = Path(sys.executable).parent
            else:
                base = Path(__file__).parent
            db_path = str(base / self.DB_NAME)

        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    # ============================================================
    # 建表
    # ============================================================
    def _create_tables(self) -> None:
        """创建数据表（如果不存在）。"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL,
                training_date TEXT NOT NULL,
                total_bars INTEGER,
                trade_count INTEGER,
                total_return_pct REAL,
                buy_hold_return_pct REAL,
                win_rate REAL,
                max_drawdown_pct REAL,
                avg_hold_days REAL,
                timing_score REAL,
                report_path TEXT,
                training_mode TEXT DEFAULT 'classic'
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER REFERENCES sessions(id),
                buy_date TEXT,
                buy_price REAL,
                buy_ratio REAL,
                sell_date TEXT,
                sell_price REAL,
                sell_ratio REAL,
                return_pct REAL,
                hold_days INTEGER,
                max_floating_profit REAL,
                max_floating_loss REAL,
                is_auto_exit INTEGER DEFAULT 0,
                timing_score_5d REAL,
                timing_score_10d REAL,
                timing_score_20d REAL
            );
        """)

        # 兼容旧数据库：添加 training_mode 列（如果不存在）
        try:
            self.conn.execute(
                "ALTER TABLE sessions ADD COLUMN training_mode TEXT DEFAULT 'classic'"
            )
        except Exception:
            pass

        self.conn.commit()

    # ============================================================
    # 写入
    # ============================================================
    def save_session(self, stock_code: str, df: pd.DataFrame,
                     trade_manager, report_path: str,
                     config: dict) -> int:
        """
        保存一次训练会话及其所有交易记录。

        Args:
            stock_code: 股票代码
            df: K 线数据
            trade_manager: TradeManager 实例
            report_path: 报告文件路径
            config: 配置字典

        Returns:
            int: 新创建的 session_id
        """
        completed = trade_manager.get_completed_trades()

        # 计算会话级统计
        total_return = sum(ct.return_pct for ct in completed)
        # 未平仓部分
        if trade_manager.portfolio.position > 0 and trade_manager.portfolio.avg_cost > 0:
            last_price = df.iloc[-1]["close"]
            open_ret = (last_price / trade_manager.portfolio.avg_cost - 1.0) * 100.0
            total_return += open_ret

        # 持有不动收益率（从训练开始到结束）
        min_warmup = 30  # 与 main.py 中一致
        if len(df) > min_warmup:
            buy_hold = (df.iloc[-1]["close"] / df.iloc[min_warmup]["close"] - 1.0) * 100.0
        else:
            buy_hold = 0.0

        # 胜率
        wins = sum(1 for ct in completed if ct.return_pct > 0)
        total = len(completed)
        win_rate = wins / total if total > 0 else 0.0

        # 平均持仓天数
        hold_days_list = [ct.hold_days for ct in completed]
        avg_hold = np.mean(hold_days_list) if hold_days_list else 0.0

        # 时机评分均值
        timing_scores = [ct.timing_score_5d for ct in completed if ct.timing_score_5d != 0]
        avg_timing = np.mean(timing_scores) if timing_scores else 0.0

        # 最大回撤
        max_dd = self._calc_max_drawdown(completed)

        training_mode = config.get("mode", {}).get("current", "classic") if config else "classic"

        # 插入 session
        cursor = self.conn.execute("""
            INSERT INTO sessions
                (stock_code, training_date, total_bars, trade_count,
                 total_return_pct, buy_hold_return_pct, win_rate,
                 max_drawdown_pct, avg_hold_days, timing_score, report_path,
                 training_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            stock_code,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            len(df),
            total,
            total_return,
            buy_hold,
            win_rate,
            max_dd,
            avg_hold,
            avg_timing,
            report_path,
            training_mode,
        ))
        session_id = cursor.lastrowid

        # 插入 trades
        for ct in completed:
            self.conn.execute("""
                INSERT INTO trades
                    (session_id, buy_date, buy_price, buy_ratio,
                     sell_date, sell_price, sell_ratio,
                     return_pct, hold_days,
                     max_floating_profit, max_floating_loss,
                     is_auto_exit, timing_score_5d, timing_score_10d,
                     timing_score_20d)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                ct.buy_records[0].date if ct.buy_records else "",
                ct.buy_avg_price,
                sum(r.ratio for r in ct.buy_records),
                ct.sell_records[-1].date if ct.sell_records else "",
                ct.sell_avg_price,
                sum(r.ratio for r in ct.sell_records),
                ct.return_pct,
                ct.hold_days,
                ct.max_floating_profit,
                ct.max_floating_loss,
                1 if ct.is_auto_exit else 0,
                ct.timing_score_5d,
                ct.timing_score_10d,
                ct.timing_score_20d,
            ))

        self.conn.commit()
        return session_id

    # ============================================================
    # 查询
    # ============================================================
    def get_session_stats(self) -> dict:
        """
        获取全局统计概览。

        Returns:
            dict: {total_sessions, total_trades, total_return, avg_return,
                   win_rate, avg_hold_days}
        """
        row = self.conn.execute("""
            SELECT
                COUNT(*) as total_sessions,
                COALESCE(SUM(trade_count), 0) as total_trades,
                COALESCE(SUM(total_return_pct), 0) as total_return,
                COALESCE(AVG(total_return_pct), 0) as avg_return,
                COALESCE(SUM(CASE WHEN total_return_pct > 0 THEN 1 ELSE 0 END) * 1.0
                         / NULLIF(COUNT(*), 0), 0) as win_rate,
                COALESCE(AVG(avg_hold_days), 0) as avg_hold_days
            FROM sessions
        """).fetchone()

        if row is None:
            return {
                "total_sessions": 0, "total_trades": 0,
                "total_return": 0.0, "avg_return": 0.0,
                "win_rate": 0.0, "avg_hold_days": 0.0,
            }

        return {
            "total_sessions": row[0] or 0,
            "total_trades": row[1] or 0,
            "total_return": row[2] or 0.0,
            "avg_return": row[3] or 0.0,
            "win_rate": row[4] or 0.0,
            "avg_hold_days": row[5] or 0.0,
        }

    def get_return_trend(self, limit: int = 50) -> list[dict]:
        """
        获取最近 N 次训练的收益率趋势。

        Returns:
            list[dict]: [{session_id, stock_code, date, return_pct}]
        """
        rows = self.conn.execute("""
            SELECT id, stock_code, training_date, total_return_pct
            FROM sessions ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()

        return [
            {"session_id": r[0], "stock_code": r[1],
             "date": r[2], "return_pct": r[3] or 0.0}
            for r in reversed(rows)
        ]

    def get_win_rate_trend(self, window: int = 10) -> list[float]:
        """
        计算滚动胜率趋势。

        Args:
            window: 滑动窗口大小

        Returns:
            list[float]: 滚动胜率列表
        """
        rows = self.conn.execute("""
            SELECT total_return_pct FROM sessions ORDER BY id ASC
        """).fetchall()

        returns = [r[0] or 0.0 for r in rows]
        if not returns:
            return []

        trend = []
        for i in range(len(returns)):
            start = max(0, i - window + 1)
            window_vals = returns[start:i + 1]
            wins = sum(1 for v in window_vals if v > 0)
            trend.append(wins / len(window_vals) * 100.0)

        return trend

    def get_worst_trades(self, n: int = 5) -> list[dict]:
        """
        获取亏损最严重的 N 笔交易。

        Returns:
            list[dict]: [{session_id, buy_date, sell_date, return_pct, ...}]
        """
        rows = self.conn.execute("""
            SELECT session_id, buy_date, sell_date, return_pct,
                   hold_days, max_floating_loss
            FROM trades WHERE return_pct IS NOT NULL
            ORDER BY return_pct ASC LIMIT ?
        """, (n,)).fetchall()

        return [
            {"session_id": r[0], "buy_date": r[1], "sell_date": r[2],
             "return_pct": r[3] or 0.0, "hold_days": r[4] or 0,
             "max_floating_loss": r[5] or 0.0}
            for r in rows
        ]

    def get_hold_days_distribution(self) -> list[int]:
        """
        获取所有交易的持仓天数分布。

        Returns:
            list[int]: 持仓天数列表
        """
        rows = self.conn.execute("""
            SELECT hold_days FROM trades WHERE hold_days IS NOT NULL
        """).fetchall()
        return [r[0] for r in rows if r[0] is not None]

    def get_max_drawdown(self) -> float:
        """获取历史最大回撤（基于累计收益序列）。"""
        rows = self.conn.execute("""
            SELECT total_return_pct FROM sessions ORDER BY id ASC
        """).fetchall()

        if not rows:
            return 0.0

        cumsum = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in rows:
            cumsum += r[0] or 0.0
            if cumsum > peak:
                peak = cumsum
            dd = (cumsum - peak)
            if dd < max_dd:
                max_dd = dd

        return max_dd

    # ============================================================
    # 内部计算
    # ============================================================
    @staticmethod
    def _calc_max_drawdown(completed_trades) -> float:
        """从已完成交易列表计算最大回撤。"""
        if not completed_trades:
            return 0.0

        cumsum = 0.0
        peak = 0.0
        max_dd = 0.0

        for ct in completed_trades:
            cumsum += ct.return_pct
            if cumsum > peak:
                peak = cumsum
            dd = cumsum - peak
            if dd < max_dd:
                max_dd = dd

        return max_dd

    # ============================================================
    # 关闭
    # ============================================================
    def close(self) -> None:
        """关闭数据库连接。"""
        if self.conn:
            self.conn.close()
