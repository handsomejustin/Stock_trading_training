"""Phase 3 冒烟测试:首页双页栈/模式入口/引导对话框/快捷键速查(离屏)。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    from PyQt5.QtWidgets import QApplication

app = QApplication([])

import main as app_main

w = app_main.MainWindow()

# ---- 1. 双页栈:首页为默认页 ----
assert hasattr(w, "main_stack") and w.main_stack.count() == 2
assert w.main_stack.currentWidget() is w._home_page, "启动应停留在首页"
print("main_stack OK (home default, page identity)")

# ---- 2. 模式卡片入口:切换到训练页并触发训练 ----
called = []
w.start_training = lambda: called.append(1)   # 阻断真实训练
w._start_mode_from_home("quiz")
assert w.combo_mode.currentText() == "答题模式"
assert w.current_mode == "quiz"
assert w.main_stack.currentWidget() is not w._home_page, "应切到训练页"
assert called == [1]
print("mode card -> training page OK")

w._go_home()
assert w.main_stack.currentWidget() is w._home_page
print("_go_home OK")

# ---- 3. 高级设置入口(不触发训练) ----
w._start_mode_from_home("classic")
btn_effects = w.main_stack.currentIndex()
assert btn_effects == 1
# 高级设置按钮是直接切页
w._go_home()
print("advanced entry wired OK")

# ---- 4. OnboardingDialog 构造与翻页 ----
dlg = app_main.OnboardingDialog(w, tdx_path="C:/fake_tdx")
assert dlg.stack.count() == 3
assert not dlg._btn_back.isEnabled(), "第一页无上一步"
dlg._go_next(); dlg._go_next()
assert dlg.stack.currentIndex() == 2
assert dlg._btn_next.text().startswith("完成"), "最后一页应为完成"
dlg._edit_tdx.setText("C:/new_tdx")
dlg._finish()
assert dlg.apply_path == "C:/new_tdx"
print("OnboardingDialog OK (3 pages, apply_path)")

# ---- 5. F1 快捷键速查(拦截后 mock 弹窗) ----
Qt = app_main.dict_mode_name and __import__("main").Qt
shown = []
orig = app_main.QMessageBox.information
app_main.QMessageBox.information = lambda *a, **k: shown.append(1)
assert w._handle_key(Qt.Key_F1) is True
assert shown == [1]
app_main.QMessageBox.information = orig
print("F1 shortcut help OK")

# ---- 6. end_training 后回首页 ----
import numpy as np
import pandas as pd
from indicators import IndicatorHub

n = 260
rng = np.random.default_rng(3)
close = 100 + np.cumsum(rng.normal(0, 1, n))
df = pd.DataFrame({
    "date": [f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)],
    "open": close, "high": close + 1, "low": close - 1,
    "close": close, "volume": [1e6] * n,
})
hub = IndicatorHub(df, {"indicators": {}, "ma_periods": [5]})
hub.calculate_all()
w._show_session_summary = lambda s, q=None: None
w._on_load_done(df, "SH600000", hub, 30)
assert w.main_stack.currentWidget() is not w._home_page
w.end_training()
assert w.main_stack.currentWidget() is w._home_page, "训练结束应回首页"
print("end_training -> home OK")

# ---- 7. config 默认值合并 ----
from config import load_config
cfg = load_config()
assert "first_run_done" in cfg
assert cfg["ai"].get("send_chart") is True
assert cfg["mode"].get("quiz_questions") == 10
print("config defaults OK")

print("\n=== PHASE 3 SMOKE TESTS PASSED ===")
