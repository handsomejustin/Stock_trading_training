"""
盘感训练器 - 训练报告生成模块

训练结束时生成结构化 Markdown 报告，保存到文件。
报告包含：基本信息、完整K线数据、技术指标、操作记录、
交易评分、收益总结。支持追加 AI 分析结果。
格式设计为 AI 可直接解析分析。
"""

import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np

from indicators import SUB_INDICATOR_REGISTRY
from trade_manager import TradeManager


def generate_report(
    stock_code: str,
    df: pd.DataFrame,
    indicator_hub,
    trade_manager: TradeManager,
    cursor: int,
    config: dict,
    output_dir: str = None,
    ai_analysis: str = None,
    quiz_answers: list = None,
) -> tuple:
    """
    生成训练报告并保存为 Markdown 文件。

    Args:
        stock_code: 股票代码
        df: K线数据 DataFrame
        indicator_hub: IndicatorHub 实例
        trade_manager: TradeManager 实例
        cursor: 训练结束时推演到的位置
        config: 配置字典
        output_dir: 输出目录，默认为项目目录
        ai_analysis: AI 分析结果文本（可选）

    Returns:
        tuple: (report_path, report_text) 报告文件路径和完整文本
    """
    sections = []

    # ---- 标题和基本信息 ----
    sections.append(_build_header(stock_code, df, cursor, config))

    # ---- 交易操作记录 ----
    sections.append(_build_trade_log(df, trade_manager))

    # ---- 完整K线数据 ----
    sections.append(_build_kline_table(df, trade_manager))

    # ---- 技术指标数据 ----
    sections.append(_build_indicator_table(df, indicator_hub, cursor))

    # ---- 决策点指标快照 ----
    sections.append(_build_decision_snapshots(df, indicator_hub, trade_manager))

    # ---- 交易评分 ----
    sections.append(_build_trade_scoring(df, trade_manager))

    # ---- 收益总结 ----
    sections.append(_build_summary(df, trade_manager))

    # ---- 答题记录（quiz 模式） ----
    if quiz_answers:
        sections.append(_build_quiz_section(quiz_answers))

    # ---- AI 复盘分析 ----
    if ai_analysis:
        sections.append(f"## AI 复盘分析\n\n{ai_analysis}")

    # 拼接完整报告
    report = "\n\n".join(sections)

    # 保存到文件
    if output_dir is None:
        if getattr(sys, 'frozen', False):
            base = Path(sys.executable).parent
        else:
            base = Path(__file__).parent
        output_dir = str(base / "docs")
    report_path = _save_report(report, stock_code, output_dir)

    return report_path, report


def _build_header(stock_code: str, df: pd.DataFrame, cursor: int, config: dict) -> str:
    """生成报告标题和基本信息。"""
    lines = [
        "# 盘感训练报告",
        "",
        f"**股票代码**: {stock_code}",
        f"**训练时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**数据区间**: {df.iloc[0]['date']} ~ {df.iloc[-1]['date']}",
        f"**K线总数**: {len(df)} 根（含 {config.get('training_days', 120)} 天训练期 + 指标预热缓冲）",
        f"**实际推演**: 推进至第 {cursor} 根",
        f"**副图指标**: {config.get('default_sub_indicator', 'MACD')}",
        f"**主图叠加**: {', '.join(config.get('default_main_overlays', []))}",
        "",
    ]

    # 简单统计价格区间
    lines.append("## 价格统计")
    lines.append("")
    lines.append(f"- **区间最高价**: {df['high'].max():.2f} ({df.loc[df['high'].idxmax(), 'date']})")
    lines.append(f"- **区间最低价**: {df['low'].min():.2f} ({df.loc[df['low'].idxmin(), 'date']})")
    lines.append(f"- **区间振幅**: {(df['high'].max() / df['low'].min() - 1) * 100:.2f}%")
    lines.append(f"- **首日收盘**: {df.iloc[0]['close']:.2f}")
    lines.append(f"- **末日收盘**: {df.iloc[-1]['close']:.2f}")
    lines.append(f"- **区间涨跌**: {(df.iloc[-1]['close'] / df.iloc[0]['close'] - 1) * 100:.2f}%")
    lines.append(f"- **平均日成交量**: {df['volume'].mean():.0f}")

    return "\n".join(lines)


def _build_trade_log(df: pd.DataFrame, trade_manager: TradeManager) -> str:
    """生成交易操作记录表。"""
    lines = [
        "## 交易操作记录",
        "",
        "按时间顺序列出所有买卖操作及其当时的K线上下文。",
        "",
    ]

    trades = trade_manager.get_trade_markers()
    if not trades:
        lines.append("> 本次训练未进行任何交易。")
        return "\n".join(lines)

    # 表头（含仓位信息）
    lines.append("| # | 操作 | 日期 | 价格 | 仓位比 | 操作后仓位 | K线位置 | 当日开盘 | 当日最高 | 当日最低 | 涨跌幅 |")
    lines.append("|---:|:----:|:----:|-----:|-------:|----------:|--------:|--------:|--------:|--------:|-------:|")

    prev_close = None
    for i, t in enumerate(trades):
        idx = t["idx"]
        if idx >= len(df):
            continue
        row = df.iloc[idx]
        # 计算当日涨跌幅
        if prev_close is not None:
            chg = (row["close"] / prev_close - 1) * 100
            chg_str = f"{chg:+.2f}%"
        else:
            chg_str = "-"
        prev_close = row["close"]

        action = "买入" if t["action"] == "buy" else "卖出"
        ratio = t.get("ratio", 1.0)
        pos_after = t.get("position_after", 1.0 if t["action"] == "buy" else 0.0)
        is_auto = t.get("is_auto", False)
        if is_auto:
            reason = t.get("auto_reason", "")
            if reason == "stop_loss":
                action = "自动止损"
            elif reason == "take_profit":
                action = "自动止盈"

        lines.append(
            f"| {i+1} | {action} | {t['date']} | {t['price']:.2f} "
            f"| {ratio*100:.0f}% | {pos_after*100:.0f}% "
            f"| 第{idx}根 | {row['open']:.2f} | {row['high']:.2f} "
            f"| {row['low']:.2f} | {chg_str} |"
        )

    return "\n".join(lines)


def _build_kline_table(df: pd.DataFrame, trade_manager: TradeManager) -> str:
    """生成完整K线数据表。"""
    lines = [
        "## K线数据（完整）",
        "",
        "标记说明: **[B]** = 买入点, **[S]** = 卖出点, **[SL]** = 自动止损, **[TP]** = 自动止盈",
        "",
        "| 序号 | 日期 | 开盘 | 最高 | 最低 | 收盘 | 成交量 | 涨跌幅 | 标记 |",
        "|-----:|:----:|-----:|-----:|-----:|-----:|-------:|-------:|:----:|",
    ]

    # 构建标记集合
    markers = {}
    for t in trade_manager.get_trade_markers():
        if t["action"] == "buy":
            markers[t["idx"]] = "B"
        else:
            is_auto = t.get("is_auto", False)
            reason = t.get("auto_reason", "")
            if is_auto and reason == "stop_loss":
                markers[t["idx"]] = "SL"
            elif is_auto and reason == "take_profit":
                markers[t["idx"]] = "TP"
            else:
                markers[t["idx"]] = "S"

    prev_close = None
    for i in range(len(df)):
        row = df.iloc[i]
        if prev_close is not None:
            chg = (row["close"] / prev_close - 1) * 100
            chg_str = f"{chg:+.2f}%"
        else:
            chg_str = "-"
        prev_close = row["close"]

        mark = f"**[{markers[i]}]**" if i in markers else ""
        lines.append(
            f"| {i} | {row['date']} | {row['open']:.2f} | {row['high']:.2f} "
            f"| {row['low']:.2f} | {row['close']:.2f} | {row['volume']:.0f} "
            f"| {chg_str} | {mark} |"
        )

    return "\n".join(lines)


def _build_indicator_table(df: pd.DataFrame, indicator_hub, cursor: int) -> str:
    """生成主要技术指标数据表。"""
    lines = [
        "## 技术指标数据",
        "",
        "选取关键指标，展示每日数值。",
        "",
    ]

    # 选取要展示的指标和输出列
    display_indicators = {
        "MA5": "MA5",
        "MA20": "MA20",
        "MACD_DIF": ("MACD", "DIF"),
        "MACD_DEA": ("MACD", "DEA"),
        "KDJ_K": ("KDJ", "K"),
        "RSI": ("RSI", "RSI"),
    }

    # 表头
    header = "| 序号 | 日期 | 收盘"
    separator = "|-----:|:----:|-----:"
    for col_name in display_indicators:
        header += f" | {col_name}"
        separator += ":------:"
    header += " |"
    separator += "|"

    lines.append(header)
    lines.append(separator)

    n = len(df)
    for i in range(n):
        row = df.iloc[i]
        line = f"| {i} | {row['date']} | {row['close']:.2f}"

        for col_name, source in display_indicators.items():
            if isinstance(source, str):
                # 主图叠加指标
                arr = indicator_hub.main_overlays.get(source)
            else:
                # 副图指标
                ind_name, out_name = source
                data = indicator_hub.results.get(ind_name, {})
                arr = data.get(out_name)

            if arr is not None and i < len(arr):
                val = arr[i]
                if np.isnan(val):
                    line += " | -"
                else:
                    line += f" | {val:.2f}"
            else:
                line += " | -"

        line += " |"
        lines.append(line)

    return "\n".join(lines)


def _build_decision_snapshots(
    df: pd.DataFrame, indicator_hub, trade_manager: TradeManager
) -> str:
    """生成每个决策点的指标快照。"""
    lines = [
        "## 决策点指标快照",
        "",
        "展示每次买入/卖出操作时，主要技术指标的具体数值。",
        "用于分析交易决策时的技术面环境。",
        "",
    ]

    trades = trade_manager.get_trade_markers()
    if not trades:
        lines.append("> 无交易操作，无决策点数据。")
        return "\n".join(lines)

    for i, t in enumerate(trades):
        idx = t["idx"]
        if idx >= len(df):
            continue
        row = df.iloc[idx]
        action = "买入" if t["action"] == "buy" else "卖出"
        is_auto = t.get("is_auto", False)
        if is_auto:
            reason = t.get("auto_reason", "")
            if reason == "stop_loss":
                action = "自动止损"
            elif reason == "take_profit":
                action = "自动止盈"
        ratio = t.get("ratio", 1.0)
        pos_after = t.get("position_after", None)

        lines.append(f"### 决策 {i+1}: {action} @ {t['date']} (价格 {t['price']:.2f})")
        lines.append("")
        lines.append(f"**K线数据**: O={row['open']:.2f} H={row['high']:.2f} L={row['low']:.2f} C={row['close']:.2f} V={row['volume']:.0f}")
        lines.append(f"**仓位**: 本次{ratio*100:.0f}%, 操作后{pos_after*100:.0f}%" if pos_after is not None else "")
        lines.append("")

        # 展示所有指标在该点的值
        lines.append("**技术指标**:")
        lines.append("")

        # 主图叠加
        for overlay_name in ["MA5", "MA20", "BBI", "EXPMA12", "EXPMA50", "BOLL_UPPER", "BOLL_MID", "BOLL_LOWER"]:
            arr = indicator_hub.main_overlays.get(overlay_name)
            if arr is not None and idx < len(arr):
                val = arr[idx]
                if not np.isnan(val):
                    lines.append(f"- **{overlay_name}**: {val:.2f}")

        # 副图指标
        for ind_name in indicator_hub.results:
            data = indicator_hub.results[ind_name]
            reg = SUB_INDICATOR_REGISTRY.get(ind_name, {})
            outputs = reg.get("outputs", [])
            for out_name in outputs:
                arr = data.get(out_name)
                if arr is not None and idx < len(arr):
                    val = arr[idx]
                    if not np.isnan(val):
                        lines.append(f"- **{ind_name}.{out_name}**: {val:.2f}")

        lines.append("")

    return "\n".join(lines)


def _build_trade_scoring(df: pd.DataFrame, trade_manager: TradeManager) -> str:
    """生成交易评分段落。"""
    lines = [
        "## 交易评分",
        "",
        "每笔完整交易（从首次买入到清仓）的详细评分数据。",
        "",
    ]

    completed = trade_manager.get_completed_trades()
    if not completed:
        lines.append("> 无完整交易记录。")
        return "\n".join(lines)

    # Buy-and-hold 基准
    min_warmup = 30
    if len(df) > min_warmup:
        bh_return = (df.iloc[-1]["close"] / df.iloc[min_warmup]["close"] - 1) * 100
    else:
        bh_return = 0.0

    lines.append(f"**持有不动基准收益**: {bh_return:+.2f}%")
    lines.append("")

    for i, ct in enumerate(completed):
        sign = "+" if ct.return_pct >= 0 else ""
        lines.append(f"### 交易 {i+1}")
        lines.append("")
        lines.append(f"- **买入均价**: {ct.buy_avg_price:.2f}")
        lines.append(f"- **卖出均价**: {ct.sell_avg_price:.2f}")
        lines.append(f"- **收益率**: {sign}{ct.return_pct:.2f}%")
        lines.append(f"- **持仓天数**: {ct.hold_days} 根K线")
        lines.append(f"- **最大浮盈**: +{ct.max_floating_profit:.2f}%")
        lines.append(f"- **最大浮亏**: {ct.max_floating_loss:.2f}%")
        if ct.is_auto_exit:
            lines.append(f"- **退出方式**: 自动止损/止盈")
        if ct.timing_score_5d != 0:
            lines.append(
                f"- **时机评分**: 5日{ct.timing_score_5d:+.2f}% "
                f"10日{ct.timing_score_10d:+.2f}% "
                f"20日{ct.timing_score_20d:+.2f}%"
            )
        # 与基准对比
        diff = ct.return_pct - bh_return
        lines.append(f"- **超越基准**: {diff:+.2f}%")
        lines.append("")

    return "\n".join(lines)


def _build_summary(df: pd.DataFrame, trade_manager: TradeManager) -> str:
    """生成训练总结。"""
    lines = [
        "## 训练总结",
        "",
    ]

    last_price = df.iloc[-1]["close"]
    summary = trade_manager.summary(last_price)
    lines.append("```")
    lines.append(summary)
    lines.append("```")
    lines.append("")

    # 额外统计
    completed = trade_manager.get_completed_trades()
    if completed:
        # 持仓天数统计
        hold_days = [ct.hold_days for ct in completed]
        if hold_days:
            lines.append(f"- **平均持仓天数**: {np.mean(hold_days):.1f} 根K线")
            lines.append(f"- **最短持仓**: {min(hold_days)} 根K线")
            lines.append(f"- **最长持仓**: {max(hold_days)} 根K线")

        # 交易次数
        trades = trade_manager.get_trade_markers()
        buy_count = sum(1 for t in trades if t["action"] == "buy")
        sell_count = sum(1 for t in trades if t["action"] == "sell")
        lines.append(f"- **买入次数**: {buy_count}")
        lines.append(f"- **卖出次数**: {sell_count}")

    lines.append("")
    lines.append("---")
    lines.append(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

    return "\n".join(lines)


def _build_quiz_section(quiz_answers: list) -> str:
    """生成答题模式作答记录段落。"""
    lines = [
        "## 答题记录",
        "",
        f"共 **{len(quiz_answers)}** 题，答对 "
        f"**{sum(1 for a in quiz_answers if a['is_correct'])}** 题。",
        "",
        "| # | 信号 | 股票 | 信号日 | 我的作答 | 标准动作 | 结果 | 实际20日 |",
        "|---|------|------|--------|----------|----------|------|----------|",
    ]
    choice_text = {"buy": "买入", "hold": "观望", "sell": "清仓"}
    for a in quiz_answers:
        result = "✅" if a["is_correct"] else "❌"
        fwd20 = a.get("fwd20")
        fwd_str = f"{fwd20:+.1f}%" if fwd20 is not None else "-"
        lines.append(
            f"| {a.get('question_no', '-')} | {a.get('signal_name', '-')} "
            f"| {a.get('code', '-')} | {a.get('date', '-')} "
            f"| {choice_text.get(a.get('user_choice'), '-')} "
            f"| {choice_text.get(a.get('correct_choice'), '-')} "
            f"| {result} | {fwd_str} |")

    # 分信号正确率
    by_signal = {}
    for a in quiz_answers:
        by_signal.setdefault(a.get("signal_name", "-"), []).append(a)
    if len(by_signal) > 1:
        lines.append("")
        lines.append("**分信号正确率**:")
        for name, answers in by_signal.items():
            correct = sum(1 for a in answers if a["is_correct"])
            lines.append(f"- {name}: {correct}/{len(answers)}")

    return "\n".join(lines)


def _save_report(report: str, stock_code: str, output_dir: str) -> str:
    """
    将报告保存为 Markdown 文件。

    文件名格式: report_股票代码_YYYYMMDD_HHMMSS.md

    Args:
        report: 报告内容
        stock_code: 股票代码
        output_dir: 输出目录

    Returns:
        str: 保存的文件路径
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 清理股票代码中的特殊字符
    safe_code = stock_code.replace("/", "_").replace("\\", "_")
    filename = f"report_{safe_code}_{timestamp}.md"
    filepath = output_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)

    return str(filepath)
