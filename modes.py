"""
盘感训练器 - 训练模式注册表

模式的唯一定义处：主窗口模式下拉、首页卡片、名称映射、页栈索引
全部从这里生成。新增模式 = 在 MODES 加一个条目 + 在 main.py 的
对应 hook（启动/组件/按键）里处理该模式特有逻辑。
"""

# (key, 中文名, 图标, 一句话说明)
MODES = [
    ("classic", "经典模式", "📈", "随机个股逐根揭开K线，手动买卖练盘感"),
    ("timed", "限时模式", "⏱", "每根K线倒计时，逼你快速决策"),
    ("multi_tf", "多周期模式", "📅", "日线+周线联动推演，看大做小"),
    ("sector", "板块联动", "🏭", "同板块多股同步对照，识别共振"),
    ("comprehensive", "综合训练", "🧠", "全要素训练 + 心理状态记录"),
    ("quiz", "答题模式", "🎯", "信号出现你怎么做？实际走势来判分"),
]

MODE_KEYS = [m[0] for m in MODES]

# 主窗口页栈索引（index 0 = 首页，index 1 = 训练页）
PAGE_HOME = 0
PAGE_TRAINING = 1


def mode_name(key: str) -> str:
    """模式 key 转中文名。"""
    for k, name, _icon, _desc in MODES:
        if k == key:
            return name
    return key
