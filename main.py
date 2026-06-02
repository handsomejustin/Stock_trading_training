"""
盘感训练器 - 主窗口模块

整合所有模块，构建 PyQt5 主窗口。
包含：暗色主题、左右布局、键盘/按钮事件、操作日志。
"""

import sys
from pathlib import Path
from datetime import datetime

# 兼容 PyQt5（本地开发）与 PySide6（CI 多平台构建）
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
        QLabel, QLineEdit, QPushButton, QSpinBox, QComboBox, QTextEdit,
        QFileDialog, QGroupBox, QStatusBar, QCheckBox,
        QMessageBox, QSplitter,
    )
    from PySide6.QtCore import Qt, QDateTime
    from PySide6.QtGui import QPalette, QColor, QFont, QIcon
except ImportError:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
        QLabel, QLineEdit, QPushButton, QSpinBox, QComboBox, QTextEdit,
        QFileDialog, QGroupBox, QStatusBar, QCheckBox,
        QMessageBox, QSplitter,
    )
    from PyQt5.QtCore import Qt, QDateTime
    from PyQt5.QtGui import QPalette, QColor, QFont, QIcon

from config import load_config, save_config
from data_loader import DataLoader
from indicators import IndicatorHub, SUB_INDICATOR_NAMES
from chart_canvas import ChartCanvas
from trade_manager import TradeManager
from report_generator import generate_report


class MainWindow(QMainWindow):
    """盘感训练器主窗口。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("盘感训练器 - K线推演模拟交易")
        self.resize(1500, 900)

        # ---- 窗口图标 ----
        icon_path = Path(__file__).parent / "logo.ico"
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

        # ---- 暗色主题 ----
        self._apply_dark_theme()

        # ---- 状态变量 ----
        self.config = load_config()
        self.data_loader: DataLoader = None
        self.indicator_hub: IndicatorHub = None
        self.trade_manager = TradeManager()
        self.df = None              # 当前训练数据
        self.cursor = 0             # 当前推演位置
        self.stock_code = ""        # 当前股票代码
        self.training_active = False
        self.min_warmup = 30        # 指标预热最小根数

        # ---- 构建 UI ----
        self._build_ui()

        # ---- 安装全局事件过滤器 ----
        # 确保焦点在子控件时，训练快捷键仍然生效
        self._install_key_filter()

        # ---- 初始化数据加载器 ----
        self._init_data_loader()

    # ============================================================
    # 暗色主题
    # ============================================================
    def _apply_dark_theme(self):
        """应用深色调色板。"""
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#2b2b2b"))
        palette.setColor(QPalette.WindowText, QColor("#cccccc"))
        palette.setColor(QPalette.Base, QColor("#1e1e1e"))
        palette.setColor(QPalette.AlternateBase, QColor("#2b2b2b"))
        palette.setColor(QPalette.ToolTipBase, QColor("#2b2b2b"))
        palette.setColor(QPalette.ToolTipText, QColor("#cccccc"))
        palette.setColor(QPalette.Text, QColor("#cccccc"))
        palette.setColor(QPalette.Button, QColor("#3c3c3c"))
        palette.setColor(QPalette.ButtonText, QColor("#cccccc"))
        palette.setColor(QPalette.BrightText, QColor("#ff4444"))
        palette.setColor(QPalette.Highlight, QColor("#4a9eff"))
        palette.setColor(QPalette.HighlightedText, QColor("#000000"))
        QApplication.instance().setPalette(palette)

    # ============================================================
    # 快捷键事件过滤器
    # ============================================================
    def _install_key_filter(self):
        """
        对所有可聚焦子控件安装事件过滤器。

        QTextEdit/QComboBox/QSpinBox 等控件会拦截键盘事件，
        导致 MainWindow.keyPressEvent 收不到。
        过滤器在子控件处理之前拦截训练快捷键。
        """
        for widget in self.findChildren(QWidget):
            widget.installEventFilter(self)

    # ============================================================
    # UI 构建
    # ============================================================
    def _build_ui(self):
        """构建主窗口 UI 布局。"""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # ---- 上部：图表 + 控制面板（水平分割） ----
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：图表画布
        self.chart = ChartCanvas(parent=self)
        splitter.addWidget(self.chart)

        # 右侧：控制面板
        right_panel = self._build_right_panel()
        splitter.addWidget(right_panel)

        # 设置分割比例（图表:面板 = 4:1）
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1100, 300])

        main_layout.addWidget(splitter, stretch=1)

        # ---- 底部：操作按钮栏 ----
        bottom_bar = self._build_bottom_bar()
        main_layout.addWidget(bottom_bar)

        # ---- 状态栏 ----
        self.statusBar().showMessage("就绪 - 请选择通达信目录并开始训练")
        self.statusBar().setStyleSheet("color: #cccccc;")

    def _build_right_panel(self) -> QWidget:
        """构建右侧控制面板。"""
        panel = QWidget()
        panel.setMaximumWidth(350)
        panel.setMinimumWidth(250)
        layout = QVBoxLayout(panel)
        layout.setSpacing(6)

        # ---- 快捷键说明 ----
        keys_group = QGroupBox("⌨ 快捷键说明")
        keys_layout = QVBoxLayout(keys_group)
        keys_text = (
            "→ 逐根前进  |  ← 逐根后退\n"
            "PgDn 快进10根  |  Space 观望\n"
            "↑ 买入  |  ↓ 卖出  |  Esc 结束训练"
        )
        keys_label = QLabel(keys_text)
        keys_label.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        keys_label.setWordWrap(True)
        keys_layout.addWidget(keys_label)
        layout.addWidget(keys_group)

        # ---- 训练配置 ----
        config_group = QGroupBox("⚙ 训练配置")
        config_layout = QVBoxLayout(config_group)

        # 通达信目录
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("TDX目录:"))
        self.tdx_path_edit = QLineEdit()
        self.tdx_path_edit.setPlaceholderText("自动检测或手动选择...")
        self.tdx_path_edit.setText(self.config.get("tdx_home", ""))
        dir_layout.addWidget(self.tdx_path_edit, stretch=1)
        self.btn_browse = QPushButton("浏览")
        self.btn_browse.clicked.connect(self._on_browse_tdx)
        dir_layout.addWidget(self.btn_browse)
        config_layout.addLayout(dir_layout)

        # 训练天数
        days_layout = QHBoxLayout()
        days_layout.addWidget(QLabel("训练天数:"))
        self.spin_days = QSpinBox()
        self.spin_days.setRange(30, 500)
        self.spin_days.setValue(self.config.get("training_days", 120))
        days_layout.addWidget(self.spin_days)
        config_layout.addLayout(days_layout)

        # 副图面板数量
        panel_layout = QHBoxLayout()
        panel_layout.addWidget(QLabel("副图数量:"))
        self.spin_panel_count = QSpinBox()
        self.spin_panel_count.setRange(3, 5)
        self.spin_panel_count.setValue(self.config.get("panel_count", 3))
        self.spin_panel_count.valueChanged.connect(self._on_panel_count_changed)
        panel_layout.addWidget(self.spin_panel_count)
        config_layout.addLayout(panel_layout)

        # 副图指标选择（最多5个下拉框，根据面板数量显示/隐藏）
        self.combo_subs = []
        self.sub_indicator_widgets = []  # 每组的容器 QWidget
        default_subs = self.config.get("default_sub_indicators",
                                       ["MACD", "KDJ", "RSI", "CCI", "BIAS"])
        for i in range(5):
            # 用一个 QWidget 容器包裹 label+combo，方便整体隐藏
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(QLabel(f"副图{i+1}:"))
            combo = QComboBox()
            combo.addItems(SUB_INDICATOR_NAMES)
            if i < len(default_subs):
                idx = combo.findText(default_subs[i])
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.currentTextChanged.connect(self._on_indicator_changed)
            row.addWidget(combo)
            config_layout.addWidget(container)
            self.combo_subs.append(combo)
            self.sub_indicator_widgets.append(container)

        # 根据面板数量显示/隐藏
        self._update_combo_visibility()

        # 主图叠加指标（复选框）
        overlay_layout = QHBoxLayout()
        overlay_layout.addWidget(QLabel("主图叠加:"))
        self.chk_ma5 = QCheckBox("MA5")
        self.chk_ma5.setChecked("MA5" in self.config.get("default_main_overlays", []))
        overlay_layout.addWidget(self.chk_ma5)
        self.chk_ma20 = QCheckBox("MA20")
        self.chk_ma20.setChecked("MA20" in self.config.get("default_main_overlays", []))
        overlay_layout.addWidget(self.chk_ma20)
        self.chk_bbi = QCheckBox("BBI")
        self.chk_bbi.setChecked(False)
        overlay_layout.addWidget(self.chk_bbi)
        self.chk_expma = QCheckBox("EXPMA")
        self.chk_expma.setChecked(False)
        overlay_layout.addWidget(self.chk_expma)
        self.chk_boll = QCheckBox("BOLL")
        self.chk_boll.setChecked(False)
        overlay_layout.addWidget(self.chk_boll)

        for chk in [self.chk_ma5, self.chk_ma20, self.chk_bbi, self.chk_expma, self.chk_boll]:
            chk.stateChanged.connect(self._on_overlay_changed)

        config_layout.addLayout(overlay_layout)

        # 开始训练按钮
        self.btn_start = QPushButton("🚀 开始新训练")
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: #2d7d46;
                color: white;
                font-size: 16px;
                font-weight: bold;
                padding: 10px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #3a9e5a;
            }
            QPushButton:pressed {
                background-color: #256e3c;
            }
        """)
        self.btn_start.clicked.connect(self.start_training)
        config_layout.addWidget(self.btn_start)

        layout.addWidget(config_group)

        # ---- 操作日志 ----
        log_group = QGroupBox("📋 操作日志")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                color: #cccccc;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 12px;
                border: 1px solid #3c3c3c;
            }
        """)
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_group, stretch=1)

        return panel

    def _build_bottom_bar(self) -> QWidget:
        """构建底部操作按钮栏。"""
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(4, 2, 4, 2)

        btn_style = """
            QPushButton {
                background-color: #3c3c3c;
                color: #cccccc;
                padding: 6px 16px;
                border: 1px solid #555555;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #505050;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
        """
        btn_buy_style = """
            QPushButton {
                background-color: #5a2020;
                color: #ff6666;
                padding: 6px 16px;
                border: 1px solid #ff4444;
                border-radius: 4px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7a3030;
            }
        """
        btn_sell_style = """
            QPushButton {
                background-color: #1a4a1a;
                color: #66ff66;
                padding: 6px 16px;
                border: 1px solid #00cc00;
                border-radius: 4px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2a6a2a;
            }
        """

        buttons = [
            ("⏪ 前一天", self.prev_day, btn_style),
            ("⏩ 后一天", self.next_day, btn_style),
            ("⏭ 快进10", self.fast_forward, btn_style),
            ("⏹ 结束训练", self.end_training, btn_style),
            ("📈 买入", self.do_buy, btn_buy_style),
            ("📉 卖出", self.do_sell, btn_sell_style),
        ]

        for text, slot, style in buttons:
            btn = QPushButton(text)
            btn.setStyleSheet(style)
            btn.clicked.connect(slot)
            layout.addWidget(btn)

        return bar

    # ============================================================
    # 数据加载器初始化
    # ============================================================
    def _init_data_loader(self):
        """尝试初始化数据加载器。"""
        tdx_home = self.tdx_path_edit.text().strip()
        try:
            self.data_loader = DataLoader(tdx_home or None)
            if self.data_loader.is_available():
                self.log(f"✅ 通达信目录: {self.data_loader.tdx_home}")
                self.tdx_path_edit.setText(str(self.data_loader.tdx_home))
            else:
                self.log("⚠ 未找到通达信数据目录，请手动选择")
        except Exception as e:
            self.log(f"⚠ 初始化失败: {e}")

    def _on_browse_tdx(self):
        """浏览选择通达信安装目录。"""
        path = QFileDialog.getExistingDirectory(self, "选择通达信安装目录")
        if path:
            self.tdx_path_edit.setText(path)
            self.data_loader = DataLoader(path)
            if self.data_loader.is_available():
                self.log(f"✅ 已选择: {path}")
                self.config["tdx_home"] = path
                save_config(self.config)
            else:
                self.log(f"⚠ 目录无效: {path}")

    # ============================================================
    # 训练控制
    # ============================================================
    def start_training(self):
        """开始新的训练会话。"""
        # 检查数据加载器
        if not self.data_loader or not self.data_loader.is_available():
            # 尝试用当前输入框路径初始化
            path = self.tdx_path_edit.text().strip()
            if path:
                self.data_loader = DataLoader(path)
            else:
                self.data_loader = DataLoader()

            if not self.data_loader.is_available():
                QMessageBox.warning(
                    self, "数据源不可用",
                    "未找到通达信数据目录。\n"
                    "请在右侧面板选择通达信安装目录，"
                    "或设置 TDX_HOME 环境变量。"
                )
                return

        # 重置状态
        self.trade_manager.reset()
        days = self.spin_days.value()

        try:
            # 扫描并随机选股
            self.log("🔍 正在扫描股票数据...")
            stocks = self.data_loader.scan_stocks()
            self.log(f"📊 共扫描到 {len(stocks)} 只股票")

            self.log(f"🎰 随机选取 {days} 天训练数据...")
            self.df, self.stock_code = self.data_loader.random_pick(days)
            self.log(f"✅ 选中: {self.stock_code}, 数据量: {len(self.df)} 根K线")

            # 计算所有指标
            self.indicator_hub = IndicatorHub(self.df, self.config)
            self.indicator_hub.calculate_all()
            self.log("📈 指标计算完成")

            # 设置初始推演位置（预热期）
            self.min_warmup = self.indicator_hub.get_min_warmup()
            self.cursor = self.min_warmup

            # 设置画布数据
            self.chart.set_data(self.df, self.indicator_hub, self.trade_manager)
            # 设置副图面板数量
            self.chart.setup_panels(self.spin_panel_count.value())
            overlays = self._get_enabled_overlays()
            sub_inds = self._get_sub_indicators()
            self.chart.render(
                self.cursor,
                sub_inds,
                overlays,
            )

            self.training_active = True
            self.log(f"🎮 训练开始! 当前可见 {self.cursor}/{len(self.df)} 根K线")
            self.statusBar().showMessage(
                f"训练中 | {self.stock_code} | 进度: {self.cursor}/{len(self.df)}"
            )

        except Exception as e:
            self.log(f"❌ 启动训练失败: {e}")
            QMessageBox.critical(self, "启动失败", str(e))

    def next_day(self):
        """推演下一天（→键）。"""
        if not self.training_active or self.df is None:
            return
        if self.cursor < len(self.df):
            self.cursor += 1
            self._refresh_chart()
            self.statusBar().showMessage(
                f"训练中 | {self.stock_code} | 进度: {self.cursor}/{len(self.df)}"
            )
            # 到达最后一根，自动结束
            if self.cursor >= len(self.df):
                self.log("🏁 已到达最后一根K线")
                self.end_training()

    def prev_day(self):
        """回退前一天（←键）。"""
        if not self.training_active or self.df is None:
            return
        if self.cursor > self.min_warmup:
            self.cursor -= 1
            self._refresh_chart()
            self.statusBar().showMessage(
                f"训练中 | {self.stock_code} | 进度: {self.cursor}/{len(self.df)}"
            )

    def fast_forward(self):
        """快进10天（PgDn键）。"""
        if not self.training_active or self.df is None:
            return
        self.cursor = min(self.cursor + 10, len(self.df))
        self._refresh_chart()
        self.statusBar().showMessage(
            f"训练中 | {self.stock_code} | 进度: {self.cursor}/{len(self.df)}"
        )
        if self.cursor >= len(self.df):
            self.log("🏁 已到达最后一根K线")
            self.end_training()

    def do_buy(self):
        """模拟买入（↑键）。"""
        if not self.training_active or self.df is None:
            return
        price = self.df.iloc[self.cursor - 1]["close"]
        date = self.df.iloc[self.cursor - 1]["date"]
        if self.trade_manager.buy(self.cursor - 1, price, date):
            self.log(f"📈 买入 @ {price:.2f} ({date})")
            self._refresh_chart()
        else:
            self.log("⚠ 已持仓，无法重复买入")

    def do_sell(self):
        """模拟卖出（↓键）。"""
        if not self.training_active or self.df is None:
            return
        price = self.df.iloc[self.cursor - 1]["close"]
        date = self.df.iloc[self.cursor - 1]["date"]
        if self.trade_manager.sell(self.cursor - 1, price, date):
            self.log(f"📉 卖出 @ {price:.2f} ({date})")
            self._refresh_chart()
        else:
            self.log("⚠ 当前空仓，无法卖出")

    def end_training(self):
        """结束训练（Esc键）。"""
        if not self.training_active:
            return
        self.training_active = False

        # 显示全部 K 线
        self.cursor = len(self.df)
        self._refresh_chart()

        # 打印收益总结
        last_price = self.df.iloc[-1]["close"]
        summary = self.trade_manager.summary(last_price)
        self.log(summary)

        # 生成并保存详细训练报告
        try:
            report_path = generate_report(
                stock_code=self.stock_code,
                df=self.df,
                indicator_hub=self.indicator_hub,
                trade_manager=self.trade_manager,
                cursor=self.cursor,
                config=self.config,
            )
            self.log(f"训练报告已保存: {report_path}")
            self.statusBar().showMessage(
                f"训练结束 | {self.stock_code} | 报告: {report_path}"
            )
        except Exception as e:
            self.log(f"报告生成失败: {e}")
            self.statusBar().showMessage(
                f"训练结束 | {self.stock_code} | 总K线: {len(self.df)}"
            )

    # ============================================================
    # 图表刷新辅助
    # ============================================================
    def _refresh_chart(self):
        """刷新图表（保留当前指标选择）。"""
        overlays = self._get_enabled_overlays()
        sub_inds = self._get_sub_indicators()
        self.chart.render(
            self.cursor,
            sub_inds,
            overlays,
        )

    def _get_sub_indicators(self) -> list:
        """获取当前各副图选中的指标名称列表。"""
        count = self.spin_panel_count.value()
        result = []
        for i in range(min(count, len(self.combo_subs))):
            result.append(self.combo_subs[i].currentText())
        return result

    def _get_enabled_overlays(self) -> list:
        """获取当前启用的主图叠加指标列表。"""
        overlays = []
        if self.chk_ma5.isChecked():
            overlays.append("MA5")
        if self.chk_ma20.isChecked():
            overlays.append("MA20")
        if self.chk_bbi.isChecked():
            overlays.append("BBI")
        if self.chk_expma.isChecked():
            overlays.append("EXPMA")
        if self.chk_boll.isChecked():
            overlays.append("BOLL")
        return overlays

    # ============================================================
    # 事件回调
    # ============================================================
    def _update_combo_visibility(self):
        """根据面板数量显示/隐藏副图指标下拉框。"""
        count = self.spin_panel_count.value()
        for i, widget in enumerate(self.sub_indicator_widgets):
            widget.setVisible(i < count)

    def _on_panel_count_changed(self, value: int):
        """副图面板数量变化回调。"""
        self._update_combo_visibility()
        if self.training_active or self.df is not None:
            self.chart.setup_panels(value)
            self._refresh_chart()

    def _on_indicator_changed(self, name: str):
        """副图指标切换回调。"""
        if self.training_active or self.df is not None:
            self._refresh_chart()

    def _on_overlay_changed(self):
        """主图叠加指标切换回调。"""
        if self.training_active or self.df is not None:
            self._refresh_chart()

    def keyPressEvent(self, event):
        """键盘事件分发。"""
        if self._handle_key(event.key()):
            event.accept()
        else:
            super().keyPressEvent(event)

    def _handle_key(self, key) -> bool:
        """
        统一处理按键逻辑。

        被 keyPressEvent 和 eventFilter 共同调用。
        返回 True 表示已处理，False 表示未处理。
        """
        if key == Qt.Key_Right:
            self.next_day()
            return True
        elif key == Qt.Key_Left:
            self.prev_day()
            return True
        elif key == Qt.Key_PageDown:
            self.fast_forward()
            return True
        elif key == Qt.Key_Up:
            self.do_buy()
            return True
        elif key == Qt.Key_Down:
            self.do_sell()
            return True
        elif key == Qt.Key_Space:
            if self.training_active:
                self.log("观望")
            return True
        elif key == Qt.Key_Escape:
            self.end_training()
            return True
        return False

    def eventFilter(self, obj, event):
        """
        全局事件过滤器。

        当焦点在 QTextEdit/QComboBox/QSpinBox 等子控件时，
        这些控件会拦截按键事件，导致 MainWindow.keyPressEvent 收不到。
        此过滤器拦截关键快捷键，直接交给 _handle_key 处理。
        """
        if event.type() == event.KeyPress:
            key = event.key()
            # 仅拦截训练相关的快捷键，其他按键交给控件自行处理
            if key in (Qt.Key_Right, Qt.Key_Left, Qt.Key_PageDown,
                       Qt.Key_Up, Qt.Key_Down, Qt.Key_Space, Qt.Key_Escape):
                if self._handle_key(key):
                    return True  # 事件已处理，不再传播
        return super().eventFilter(obj, event)

    # ============================================================
    # 日志
    # ============================================================
    def log(self, msg: str):
        """
        在操作日志中追加带时间戳的消息。

        Args:
            msg: 日志消息文本
        """
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self.log_text.append(f"[{timestamp}] {msg}")
        # 自动滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


# ============================================================
# 入口
# ============================================================
def main():
    """应用入口函数。"""

    # ===================== 使用期限 =====================
    # 硬编码过期日期，到期后程序拒绝启动
    # 修改下方日期即可延长使用期限
    EXPIRE_DATE = datetime(2026, 12, 31)
    # ===================================================

    if datetime.now() > EXPIRE_DATE:
        app = QApplication(sys.argv)
        QMessageBox.critical(
            None, "使用期限已到",
            f"本程序使用期限已于 {EXPIRE_DATE.strftime('%Y-%m-%d')} 到期。\n"
            "请联系开发者获取更新版本。"
        )
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec_() if hasattr(app, 'exec_') else app.exec())


if __name__ == "__main__":
    main()
