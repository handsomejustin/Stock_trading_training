"""
盘感训练器 - 答题模式组件

QuizPanel: 图表下方的出题/作答/揭晓面板。
QuizLoadWorker: 后台加载题目对应的股票数据（定位到信号日）。
BankBuildWorker: 后台构建信号题库（signal_bank.SignalBank.build）。
"""

try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    )
    from PySide6.QtCore import Qt, Signal, QTimer, QThread
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    )
    from PyQt5.QtCore import Qt, pyqtSignal as Signal, QTimer, QThread

from indicators import IndicatorHub


# ============================================================
# 后台线程：加载题目股票
# ============================================================
class QuizLoadWorker(QThread):
    """后台线程：加载题目股票数据，定位到信号日。"""
    finished_ok = Signal(object, object, object, int, int, object)
    # df, stock_code, hub, warmup, start_cursor, event
    finished_err = Signal(str)

    def __init__(self, data_loader, ma_periods, config, event: dict):
        super().__init__()
        self.data_loader = data_loader
        self.ma_periods = ma_periods
        self.config = config
        self.event = event

    def run(self):
        try:
            event = self.event
            full = self.data_loader.load_specific_stock(event["code"])

            dates = full["date"].tolist()
            if event["date"] not in dates:
                raise ValueError(
                    f"{event['code']} 中未找到日期 {event['date']}（数据可能已更新，"
                    "请重建题库）")
            idx = dates.index(event["date"])

            # 事件日前留足指标预热缓冲，事件日后保留 20 根揭晓K线
            if self.ma_periods:
                buffer = max(max(self.ma_periods) + 10, 130)
            else:
                buffer = 130
            start = max(0, idx - buffer)
            end = min(len(full), idx + 1 + 21)
            df = full.iloc[start:end].reset_index(drop=True)

            config = dict(self.config)
            config["ma_periods"] = self.ma_periods
            hub = IndicatorHub(df, config)
            hub.calculate_all()
            warmup = hub.get_min_warmup()
            start_cursor = (idx - start) + 1     # 事件日为最新可见K线

            self.finished_ok.emit(df, event["code"], hub, warmup,
                                  start_cursor, event)
        except Exception as e:
            self.finished_err.emit(str(e))


class BankBuildWorker(QThread):
    """后台线程：构建信号题库。"""
    progress = Signal(str)
    built = Signal(int)      # 事件总数
    failed = Signal(str)

    def __init__(self, data_loader, bank):
        super().__init__()
        self.data_loader = data_loader
        self.bank = bank

    def run(self):
        try:
            self.bank.build(self.data_loader,
                            progress_cb=self.progress.emit)
            self.built.emit(self.bank.event_count())
        except Exception as e:
            self.failed.emit(str(e))


# ============================================================
# 答题面板
# ============================================================
class QuizPanel(QWidget):
    """
    答题模式面板：出题 → 作答（按钮或 1/2/3 键）→ 自动播放 20 根 → 揭晓。

    批分依据是该信号的历史统计基率（standard action），
    单次事件的实际走势仅作揭晓展示。
    """

    answered = Signal(dict)        # 一题的作答记录（主窗口收集入库）
    next_requested = Signal()      # 请求下一题（按钮或回车）

    CHOICES = [
        ("buy", "1 买入"),
        ("hold", "2 观望"),
        ("sell", "3 清仓"),
    ]
    CHOICE_TEXT = {"buy": "买入", "hold": "观望", "sell": "清仓"}

    def __init__(self, parent=None, advance_cb=None, reveal_bars: int = 20):
        super().__init__(parent)
        self.setFixedHeight(112)
        self.setFocusPolicy(Qt.NoFocus)
        self._advance_cb = advance_cb
        self._reveal_bars = reveal_bars
        self._question_active = False
        self._reveal_shown = False
        self._current = None          # 当前题 event dict
        self._played = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        # ---- 标题行 ----
        self._title = QLabel("🎯 答题模式")
        self._title.setStyleSheet(
            "color: #4a9eff; font-size: 15px; font-weight: bold;")
        layout.addWidget(self._title)

        # ---- 作答行 ----
        self._question_row = QWidget()
        q_layout = QHBoxLayout(self._question_row)
        q_layout.setContentsMargins(0, 0, 0, 0)
        self._qinfo = QLabel("")
        self._qinfo.setStyleSheet("color: #cccccc; font-size: 14px;")
        q_layout.addWidget(self._qinfo, stretch=1)

        self._choice_buttons = []
        btn_styles = [
            ("background-color: #5a2020; color: #ff6666; "
             "border: 1px solid #ff4444;"),
            ("background-color: #4a4220; color: #ffd700; "
             "border: 1px solid #ffd700;"),
            ("background-color: #1a4a1a; color: #66ff66; "
             "border: 1px solid #00cc00;"),
        ]
        for (choice, text), style in zip(self.CHOICES, btn_styles):
            btn = QPushButton(text)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setStyleSheet(f"""
                QPushButton {{
                    {style} padding: 5px 18px; border-radius: 4px;
                    font-size: 14px; font-weight: bold;
                }}
                QPushButton:hover {{ background-color: #3a3a3a; }}
                QPushButton:disabled {{ color: #666666; border-color: #444444; }}
            """)
            btn.clicked.connect(lambda _=False, c=choice: self._do_answer(c))
            q_layout.addWidget(btn)
            self._choice_buttons.append(btn)
        layout.addWidget(self._question_row)

        # ---- 揭晓行 ----
        self._reveal_row = QWidget()
        r_layout = QHBoxLayout(self._reveal_row)
        r_layout.setContentsMargins(0, 0, 0, 0)
        r_layout.setSpacing(10)

        self._verdict = QLabel("")
        self._verdict.setStyleSheet("font-size: 15px; font-weight: bold;")
        r_layout.addWidget(self._verdict)

        self._detail = QLabel("")
        self._detail.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        r_layout.addWidget(self._detail, stretch=1)

        self._next_btn = QPushButton("下一题 ⏎")
        self._next_btn.setFocusPolicy(Qt.NoFocus)
        self._next_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a4a6a; color: #ffffff;
                padding: 5px 18px; border: 1px solid #4a9eff;
                border-radius: 4px; font-size: 14px; font-weight: bold;
            }
            QPushButton:hover { background-color: #3a5a8a; }
        """)
        self._next_btn.clicked.connect(self.try_next)
        r_layout.addWidget(self._next_btn)
        layout.addWidget(self._reveal_row)
        self._reveal_row.hide()

        # ---- 自动播放定时器 ----
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(130)
        self._play_timer.timeout.connect(self._play_tick)

    # ============================================================
    # 出题
    # ============================================================
    def begin_question(self, no: int, total: int, event: dict) -> None:
        """展示新题目。event 来自 SignalBank.draw_question()。"""
        self._current = event
        event["question_no"] = no
        self._question_active = True
        self._reveal_shown = False
        self._played = 0

        self._title.setText(
            f"🎯 第 {no}/{total} 题 · {event['signal_name']}"
            f"（{event['code']} · {event['date']}）")
        self._qinfo.setText(
            f"该日出现「{event['signal_name']}」，假设你正关注此股，下一步？")
        self._reveal_row.hide()
        self._question_row.show()
        for btn in self._choice_buttons:
            btn.setEnabled(True)

    # ============================================================
    # 作答
    # ============================================================
    def answer_from_key(self, index: int) -> None:
        """键盘 1/2/3 作答（index 0..2）。"""
        if 0 <= index < len(self.CHOICES) and self._question_active:
            self._do_answer(self.CHOICES[index][0])

    def _do_answer(self, choice: str) -> None:
        if not self._question_active or self._current is None:
            return
        self._question_active = False
        for btn in self._choice_buttons:
            btn.setEnabled(False)

        event = self._current
        correct = event.get("correct", "hold")
        is_correct = choice == correct
        stats = event.get("stats") or {}

        record = {
            "question_no": event.get("question_no", 0),
            "signal_id": event["signal_id"],
            "signal_name": event["signal_name"],
            "code": event["code"],
            "date": event["date"],
            "user_choice": choice,
            "correct_choice": correct,
            "is_correct": is_correct,
            "stats": stats,
            "fwd5": event.get("fwd5"),
            "fwd10": event.get("fwd10"),
            "fwd20": event.get("fwd20"),
            "max_gain20": event.get("max_gain20"),
            "max_dd20": event.get("max_dd20"),
        }
        self.answered.emit(record)
        self._show_reveal(record)

    # ============================================================
    # 揭晓 & 自动播放
    # ============================================================
    def _show_reveal(self, record: dict) -> None:
        correct = record["correct_choice"]
        user = record["user_choice"]
        stats = record.get("stats") or {}

        if record["is_correct"]:
            self._verdict.setText(
                f"✅ 回答正确 · 标准动作:{self.CHOICE_TEXT[correct]}")
            self._verdict.setStyleSheet(
                "color: #66ff66; font-size: 15px; font-weight: bold;")
        else:
            self._verdict.setText(
                f"❌ 回答错误 · 你选{self.CHOICE_TEXT[user]}，"
                f"标准动作:{self.CHOICE_TEXT[correct]}")
            self._verdict.setStyleSheet(
                "color: #ff6666; font-size: 15px; font-weight: bold;")

        if stats and stats.get("sample_n"):
            detail = (
                f"历史统计(样本{stats['sample_n']}): "
                f"5日涨{stats['up5_rate']:.0%}/均{stats['avg5']:+.1f}% · "
                f"20日涨{stats['up20_rate']:.0%}/均{stats['avg20']:+.1f}% · "
                f"盈亏比{stats['profit_factor']}  |  "
                f"本题实际: 20日{record['fwd20']:+.1f}%"
                f"(期间最大+{record['max_gain20']:.1f}%/"
                f"最大{record['max_dd20']:.1f}%)")
        else:
            detail = f"本题实际: 20日{record['fwd20']:+.1f}%"
        self._detail.setText(detail)

        self._question_row.hide()
        self._reveal_row.show()
        self._reveal_shown = True

        # 自动播放后续 K 线
        self._played = 0
        self._play_timer.start()

    def _play_tick(self) -> None:
        if self._played >= self._reveal_bars:
            self._play_timer.stop()
            return
        self._played += 1
        if self._advance_cb:
            self._advance_cb()

    def try_next(self) -> None:
        """回车或按钮请求下一题（仅揭晓状态有效）。"""
        if self._reveal_shown:
            self.next_requested.emit()

    def stop(self) -> None:
        """停止自动播放（面板销毁前调用）。"""
        self._play_timer.stop()
