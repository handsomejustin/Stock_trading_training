"""
盘感训练器 - AI 复盘分析模块

支持双模式：API 调用（OpenAI/Anthropic/DeepSeek/自定义）
和导出 Prompt（供用户手动粘贴到 AI 工具）。
API 调用在 QThread 中异步执行，不阻塞 UI。
"""

import json

# PySide6/PyQt5 兼容
try:
    from PySide6.QtCore import QThread, Signal
except ImportError:
    from PyQt5.QtCore import QThread, pyqtSignal as Signal

import requests


# ============================================================
# 分析 Prompt 模板
# ============================================================
ANALYSIS_PROMPT_TEMPLATE = """你是一位专业的A股交易复盘分析教练。请基于以下盘感训练数据，从五个维度深入分析交易表现，给出具体可操作的建议。

## 分析维度

1. **交易决策评估**：分析每次买卖时机的合理性。结合当时的技术指标环境，判断入场和出场时机是否恰当。
2. **仓位管理评估**：分析分批建仓/减仓策略是否合理。仓位大小是否匹配当时的市场环境。
3. **风险控制评估**：分析止损/止盈策略的执行情况。最大回撤是否可控，风险敞口是否合理。
4. **指标运用评估**：分析技术指标信号是否被有效利用。是否存在忽略重要信号或误判的情况。
5. **改进建议**：给出具体的、可操作的改进方向，帮助提升交易盘感。

## 输出要求

- 用 Markdown 格式输出
- 每个维度单独一个二级标题
- 引用具体的数据和交易记录来支撑分析
- 改进建议要具体可操作，不要泛泛而谈
- 语言简洁专业，避免过度冗长

## 训练数据

{report_text}

## 交易总结

{trade_summary}
"""


class AIWorker(QThread):
    """
    后台 API 调用线程。

    在独立线程中执行 AI API 调用，
    通过 Signal 通知主线程结果。
    """
    finished = Signal(str)   # 成功：分析文本
    error = Signal(str)      # 失败：错误消息

    def __init__(self, config: dict, report_text: str, trade_summary: str):
        super().__init__()
        self.config = config
        self.report_text = report_text
        self.trade_summary = trade_summary

    def run(self) -> None:
        """执行 API 调用。"""
        try:
            prompt = ANALYSIS_PROMPT_TEMPLATE.format(
                report_text=self.report_text,
                trade_summary=self.trade_summary,
            )
            provider = self.config.get("ai", {}).get("provider", "")
            response = self._call_api(provider, prompt)
            self.finished.emit(response)
        except Exception as e:
            self.error.emit(str(e))

    def _call_api(self, provider: str, prompt: str) -> str:
        """根据 provider 路由到对应的 API 调用。"""
        ai_config = self.config.get("ai", {})
        api_key = ai_config.get("api_key", "")

        if provider in ("openai", "deepseek", "custom"):
            return self._call_openai_compat(ai_config, prompt)
        elif provider == "anthropic":
            return self._call_anthropic(api_key, ai_config, prompt)
        else:
            raise ValueError(f"未知的 AI provider: {provider}")

    def _call_openai_compat(self, ai_config: dict, prompt: str) -> str:
        """
        调用 OpenAI 兼容 API（覆盖 openai / deepseek / custom）。
        """
        provider = ai_config.get("provider", "")
        api_key = ai_config.get("api_key", "")
        model = ai_config.get("model", "")
        base_url = ai_config.get("base_url", "")

        # 默认 base_url
        if not base_url:
            if provider == "openai":
                base_url = "https://api.openai.com"
            elif provider == "deepseek":
                base_url = "https://api.deepseek.com"
            else:
                raise ValueError("自定义 provider 需要设置 base_url")

        # 默认 model
        if not model:
            if provider == "openai":
                model = "gpt-4o-mini"
            elif provider == "deepseek":
                model = "deepseek-chat"
            else:
                raise ValueError("自定义 provider 需要设置 model")

        url = f"{base_url.rstrip('/')}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 4000,
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        return data["choices"][0]["message"]["content"]

    def _call_anthropic(self, api_key: str, ai_config: dict,
                        prompt: str) -> str:
        """调用 Anthropic Claude API。"""
        model = ai_config.get("model", "claude-sonnet-4-6")
        base_url = ai_config.get("base_url", "") or "https://api.anthropic.com"

        # 鉴权方式：官方 API 用 x-api-key；部分中转网关（自带上游凭证）按
        # Authorization: Bearer 路由。由 auth_style 配置项决定，默认 x-api-key。
        auth_style = ai_config.get("auth_style", "x-api-key")

        url = f"{base_url.rstrip('/')}/v1/messages"
        headers = {
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        if auth_style == "bearer":
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            headers["x-api-key"] = api_key
        payload = {
            "model": model,
            "max_tokens": 4000,
            "messages": [
                {"role": "user", "content": prompt},
            ],
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        return data["content"][0]["text"]


class AIAnalyzer:
    """
    AI 分析控制器。

    管理 QThread 生命周期，提供同步/异步分析接口。
    """

    def __init__(self, config: dict):
        """
        Args:
            config: 应用配置字典（包含 ai 节）
        """
        self.config = config
        self.worker = None

    def is_configured(self) -> bool:
        """检查 AI 是否已配置（provider + api_key 非空）。"""
        ai = self.config.get("ai", {})
        provider = ai.get("provider", "")
        api_key = ai.get("api_key", "")
        return bool(provider and api_key)

    def analyze_async(self, report_text: str, trade_summary: str,
                      on_success, on_error) -> None:
        """
        异步分析（不阻塞 UI）。

        Args:
            report_text: 完整报告文本
            trade_summary: 交易总结文本
            on_success: 成功回调，参数为分析文本
            on_error: 失败回调，参数为错误消息
        """
        if not self.is_configured():
            on_error("AI 未配置，请先设置 provider 和 API Key")
            return

        # 如果有旧 worker 还在跑，等待结束
        if self.worker and self.worker.isRunning():
            self.worker.wait(5000)

        self.worker = AIWorker(self.config, report_text, trade_summary)
        self.worker.finished.connect(on_success)
        self.worker.error.connect(on_error)
        self.worker.start()

    def export_prompt(self, report_text: str, trade_summary: str) -> str:
        """
        导出分析 Prompt（供剪贴板复制）。

        Returns:
            str: 完整的 Prompt 文本
        """
        return ANALYSIS_PROMPT_TEMPLATE.format(
            report_text=report_text,
            trade_summary=trade_summary,
        )
