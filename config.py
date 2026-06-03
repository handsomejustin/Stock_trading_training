"""
盘感训练器 - 配置管理模块

负责读取和保存 config.yaml 配置文件。
当配置文件不存在时，自动生成默认配置。
"""

import os
import yaml
from pathlib import Path

# 配置文件路径（与本项目同目录）
_CONFIG_PATH = Path(__file__).parent / "config.yaml"

# 默认配置（硬编码，确保配置文件缺失时仍可运行）
_DEFAULT_CONFIG = {
    "tdx_home": "",
    "training_days": 120,
    "panel_count": 3,
    "default_sub_indicators": ["MACD", "KDJ", "RSI", "CCI", "BIAS"],
    "default_main_overlays": ["MA5", "MA20"],
    "ai": {
        "provider": "",       # openai / anthropic / deepseek / custom
        "api_key": "",
        "base_url": "",       # 自定义 API 端点
        "model": "",          # 模型名称
    },
    "trading": {
        "default_buy_ratio": 1.0,   # ↑ 键默认买入仓位
        "default_sell_ratio": 1.0,  # ↓ 键默认卖出仓位
        "stop_loss_pct": 0.0,       # 默认止损百分比（0 = 不启用）
        "take_profit_pct": 0.0,     # 默认止盈百分比
    },
    "indicators": {
        "MACD": {"SHORT": 12, "LONG": 26, "M": 9},
        "KDJ": {"N": 9, "M1": 3, "M2": 3},
        "RSI": {"N": 6},
        "CCI": {"N": 14},
        "OBV": {},
        "CR": {"N": 26},
        "TRIX": {"M1": 12, "M2": 20},
        "DMI": {"M1": 14, "M2": 6},
        "BIAS": {"L1": 6, "L2": 12, "L3": 24},
        "WR": {"N": 10, "N1": 6},
        "EXPMA": {"N1": 12, "N2": 50},
        "BBI": {"M1": 3, "M2": 6, "M3": 12, "M4": 20},
        "BOLL": {"N": 20, "P": 2},
        "捉妖大师": {"N1": 120, "N2": 60, "N3": 20, "M": 10},
        "MA30乖离": {"P": 10, "M": 30},
    },
}


def load_config() -> dict:
    """
    读取 config.yaml 配置文件。

    如果文件不存在，使用默认配置并自动生成文件。
    如果文件存在但缺少某些字段，用默认值补全。

    Returns:
        dict: 完整的配置字典
    """
    if _CONFIG_PATH.is_file():
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        # 用默认值补全缺失字段
        return _merge_config(cfg, _DEFAULT_CONFIG)
    else:
        # 配置文件不存在，创建默认配置文件
        save_config(_DEFAULT_CONFIG)
        return _DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> None:
    """
    将配置字典保存到 config.yaml。

    Args:
        cfg: 要保存的配置字典
    """
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _merge_config(user_cfg: dict, default_cfg: dict) -> dict:
    """
    递归合并用户配置与默认配置。

    用户配置中的值优先。对于字典类型的值，递归合并以确保
    新增的默认字段不会因用户配置文件版本旧而缺失。

    Args:
        user_cfg: 用户提供的配置
        default_cfg: 默认配置

    Returns:
        dict: 合并后的完整配置
    """
    result = default_cfg.copy()
    for key, value in user_cfg.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_config(value, result[key])
        else:
            result[key] = value
    return result


def get_indicator_params(config: dict, indicator_name: str) -> dict:
    """
    获取指定指标的参数配置。

    Args:
        config: 完整配置字典
        indicator_name: 指标名称（如 "MACD", "KDJ"）

    Returns:
        dict: 该指标的参数字典
    """
    return config.get("indicators", {}).get(indicator_name, {})
