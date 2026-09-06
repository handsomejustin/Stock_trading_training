"""Phase 2 冒烟测试:AI多模态载荷/降级/PNG导出/小结弹窗(离屏)。"""
import base64
import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    from PyQt5.QtWidgets import QApplication

app = QApplication([])

# ---- 1. AIWorker 多模态载荷(拦截网络) ----
import ai_analyzer
from unittest.mock import patch, MagicMock


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}
        self.raise_for_status = MagicMock(
            side_effect=None if status == 200 else __import__("requests").exceptions.HTTPError(
                f"{status}", response=self))

    def json(self):
        return self._body


captured = {}


def fake_post(url, headers=None, json=None, timeout=None):
    captured["url"] = url
    captured["json"] = json
    body = ({"choices": [{"message": {"content": "ok-openai"}}]}
            if "/chat/completions" in url
            else {"content": [{"text": "ok-anthropic"}]})
    return FakeResp(200, body)


cfg = {"ai": {"provider": "custom", "api_key": "k", "base_url": "http://x",
              "model": "m", "send_chart": True}}
png = b"\x89PNG-fake-bytes"
b64 = base64.b64encode(png).decode()

worker = ai_analyzer.AIWorker(cfg, "REPORT", "SUMMARY", chart_png=png)
with patch.object(ai_analyzer.requests, "post", fake_post):
    out = worker._call_api("custom", "PROMPT", b64)
    assert out == "ok-openai"
    content = captured["json"]["messages"][0]["content"]
    assert isinstance(content, list) and content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].endswith(b64)
    print("openai-compat multimodal payload OK")

    out = worker._call_api("anthropic", "PROMPT", b64)
    assert out == "ok-anthropic"
    content = captured["json"]["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["data"] == b64
    print("anthropic multimodal payload OK")

    # 纯文本回退:content 仍是纯字符串
    worker._call_api("custom", "PROMPT", None)
    assert captured["json"]["messages"][0]["content"] == "PROMPT"
    print("text-only fallback payload OK")

# ---- 2. 降级:视觉请求 400 → 纯文本重试 ----
calls = []


def fake_post_400(url, headers=None, json=None, timeout=None):
    calls.append(json["messages"][0]["content"])
    if isinstance(calls[-1], list):
        return FakeResp(400, {})
    body = {"choices": [{"message": {"content": "degraded-ok"}}]}
    return FakeResp(200, body)


worker2 = ai_analyzer.AIWorker(cfg, "R", "S", chart_png=png)
with patch.object(ai_analyzer.requests, "post", fake_post_400):
    worker2.run()
assert worker2.degraded and len(calls) == 2
# 第一次:多模态 list;重试:纯文本(格式化后的模板字符串)
assert isinstance(calls[0], list) and len(calls[0]) == 2
assert isinstance(calls[1], str) and "训练数据" in calls[1]
print("AIWorker.run() auto-degrade OK (visual 400 -> text retry)")

# ---- 3. 主窗口:导出PNG + 小结弹窗 ----
import numpy as np
import pandas as pd
import main as app_main
from indicators import IndicatorHub

w = app_main.MainWindow()
n = 300
rng = np.random.default_rng(2)
close = 100 + np.cumsum(rng.normal(0, 1, n))
df = pd.DataFrame({
    "date": [f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)],
    "open": close, "high": close + 1, "low": close - 1,
    "close": close, "volume": [1e6] * n,
})
hub = IndicatorHub(df, {"indicators": {}, "ma_periods": [5, 10]})
hub.calculate_all()
w.training_active = True
w._on_load_done(df, "SH600000", hub, 30)
assert not hasattr(w, "_last_chart_png") or w._last_chart_png == b""
print("pre-training no chart png (expected)")

# 小结弹窗构造(不 exec,避免阻塞)
stats = {"total_return": 3.21, "buy_hold": 1.10, "trade_count": 4, "win_count": 3}
dlg = app_main.SessionSummaryDialog(w, "SH600000", "classic", stats)
print("SessionSummaryDialog OK")

dlg2 = app_main.SessionSummaryDialog(
    w, "QUIZ", "quiz", stats,
    quiz_answers=[{"is_correct": True}, {"is_correct": False},
                  {"is_correct": True}])
print("SessionSummaryDialog(quiz) OK")

# end_training 收尾(弹窗被 mock 掉) + 训练模式小结算径
w._show_session_summary = lambda s, q=None: None
w.end_training()
assert not w.training_active
assert isinstance(w._last_chart_png, bytes) and len(w._last_chart_png) > 1000
assert w._last_chart_png[:4] == b"\x89PNG"
print(f"end_training + chart PNG export OK ({len(w._last_chart_png)} bytes)")

print("\n=== PHASE 2 SMOKE TESTS PASSED ===")
