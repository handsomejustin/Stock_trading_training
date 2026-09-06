"""Phase 1 冒烟测试:QuizPanel / 主窗口 quiz 流程(离屏)。"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 任何 QWidget 实例化之前必须先建 QApplication
try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    from PyQt5.QtWidgets import QApplication

app = QApplication([])

import quiz_panel

from db import Database
from stats_panel import StatsPanel

db2 = Database(db_path=tempfile.mktemp(suffix=".db"))
sp = StatsPanel(db2)
sp.refresh()
print("StatsPanel OK")

from signal_bank import SignalBank, grade_choice

# ---- grade_choice 判分单元测试 ----
assert grade_choice("cash", "buy", 5.0) == (True, "buy")      # 持币买入后涨→对
assert grade_choice("cash", "hold", 5.0) == (False, "buy")    # 持币观望错过涨→错
assert grade_choice("cash", "hold", -5.0) == (True, "hold")   # 持币观望躲过跌→对
assert grade_choice("held", "sell", -5.0) == (True, "sell")   # 持股卖出躲过跌→对
assert grade_choice("held", "sell", 5.0) == (False, "hold")   # 持股卖飞→错
assert grade_choice("cash", "buy", 0.05) == (True, "hold")    # 横盘:都对
assert grade_choice("held", "hold", -0.05) == (True, "hold")  # 横盘:都对
assert grade_choice("cash", "buy", None) == (True, "buy")     # 缺数据不判负
print("grade_choice OK")

bank = SignalBank(db_path="signal_bank_test.db")
q = bank.draw_question()
assert q and q["position"] in ("cash", "held")

panel = quiz_panel.QuizPanel(advance_cb=lambda: None, reveal_bars=20)
records = []
panel.answered.connect(records.append)
panel.begin_question(1, 10, q)
assert len(panel._choice_keys) == 2, "持仓二选一"
panel.answer_from_key(0)
assert not panel._question_active and len(records) == 1
first_choice = "buy" if q["position"] == "cash" else "sell"
exp_correct, exp_choice = grade_choice(q["position"], first_choice, q["fwd20"])
assert records[0]["is_correct"] == exp_correct
assert records[0]["correct_choice"] == exp_choice
assert records[0]["position"] == q["position"]
assert panel._reveal_shown and panel._play_timer.isActive()
panel.try_next()
print("QuizPanel OK:", records[0]["user_choice"], records[0]["correct_choice"],
      "correct" if records[0]["is_correct"] else "wrong")

from report_generator import _build_quiz_section
md = _build_quiz_section(records)
assert "| 1 |" in md
print("report section OK")

# ---- 主窗口冒烟:构造 + quiz 流程 ----
import numpy as np
import pandas as pd

import main as app_main
from data_loader import DataLoader

w = app_main.MainWindow()
assert w.quiz_panel is None and w.quiz_state is None
print("MainWindow construct OK")

w.current_mode = "quiz"
w.quiz_state = {"total": 3, "no": 1, "answers": []}

n = 400
rng = np.random.default_rng(1)
close = 100 + np.cumsum(rng.normal(0, 1, n))
df = pd.DataFrame({
    "date": [f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)],
    "open": close, "high": close + 1, "low": close - 1,
    "close": close, "volume": [1e6] * n,
})
w.data_loader = DataLoader()

# 真实 IndicatorHub(渲染需要指标数据)
from indicators import IndicatorHub
hub = IndicatorHub(df, {"indicators": {}, "ma_periods": [5, 10, 20]})
hub.calculate_all()

event_cursor = (n - 21) + 1
w._on_load_done(df, q["code"], hub, 30, event_cursor, q)
assert w.quiz_panel is not None and w.training_active
assert w.cursor == event_cursor, w.cursor
w.quiz_panel.answer_from_key(1)   # 第二个选项恒为「观望」
assert len(w.quiz_state["answers"]) == 1
exp2 = grade_choice(q["position"], "hold", q["fwd20"])[0]
assert w.quiz_state["answers"][0]["is_correct"] == exp2
print("quiz flow (load→begin→answer) OK, cursor at event day:", w.cursor)

# 按键分发:quiz 状态下 1/2/3 走作答,方向键被屏蔽,揭晓态不能重复作答
Qt = quiz_panel.Qt   # 与 quiz_panel 相同的 Qt 绑定(PySide6/PyQt5)

w2_cursor = w.cursor
assert w._handle_key(Qt.Key_Left) is True
assert w.cursor == w2_cursor, "← 在答题模式应被屏蔽"

# 第 1 题已作答(揭晓态):再次按键应被拦截但不产生新答案
assert w._handle_key(Qt.Key_3) is True
assert len(w.quiz_state["answers"]) == 1, "揭晓态不能重复作答"
print("key dispatch OK (1/2/3 作答, 方向键屏蔽, 揭晓态不可重复作答)")

print("\n=== ALL SMOKE TESTS PASSED ===")
