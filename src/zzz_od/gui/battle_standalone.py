from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QLockFile, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    Theme,
    setTheme,
    setThemeColor,
)

from one_dragon.base.operation.application import application_const
from one_dragon.base.operation.application.application_run_context import (
    ApplicationRunContextStateEventEnum,
    RunFinishReason,
)
from one_dragon.base.operation.one_dragon_context import ContextKeyboardEventEnum
from one_dragon.utils import os_utils
from one_dragon.utils.log_utils import log
from one_dragon_qt.utils.config_utils import get_prop_adapter
from one_dragon_qt.widgets.setting_card.combo_box_setting_card import (
    ComboBoxSettingCard,
)
from one_dragon_qt.widgets.setting_card.key_setting_card import KeySettingCard
from one_dragon_qt.widgets.setting_card.spin_box_setting_card import (
    DoubleSpinBoxSettingCard,
)
from one_dragon_qt.widgets.setting_card.switch_setting_card import SwitchSettingCard
from zzz_od.application.battle_assistant.auto_battle import auto_battle_const
from zzz_od.application.battle_assistant.auto_battle_config import (
    get_auto_battle_op_config_list,
)
from zzz_od.config.game_config import GameKeyAction
from zzz_od.context.battle_standalone_context import BattleStandaloneContext
from zzz_od.gui.battle_standalone_log import BattleLogPanel

if TYPE_CHECKING:
    from PySide6.QtGui import QCloseEvent

    from one_dragon.base.operation.context_event_bus import ContextEventItem


class BattleWorker(QThread):
    """将初始化和战斗运行移出界面线程，并保留错误原因。"""

    def __init__(
        self, ctx: BattleStandaloneContext, initialize: bool, parent: QWidget
    ) -> None:
        """保存任务类型与取消状态。"""
        super().__init__(parent)
        self.ctx: BattleStandaloneContext = ctx
        self.initialize: bool = initialize
        self.error: str = ''
        self.cancelled: threading.Event = threading.Event()

    def run(self) -> None:
        """运行一次任务；错误由主线程显示。"""
        try:
            if self.cancelled.is_set():
                return
            if self.initialize:
                self.ctx.init()
                if not self.ctx.ready_for_application:
                    raise RuntimeError('战斗资源初始化未完成，请查看日志')
            else:
                if not self.ctx.is_game_window_ready:
                    raise RuntimeError('未找到游戏窗口，请先打开绝区零并手动进入关卡')
                if self.cancelled.is_set():
                    return
                result = self.ctx.run_context.run_application(
                    auto_battle_const.APP_ID,
                    self.ctx.current_instance_idx,
                    application_const.DEFAULT_GROUP_ID,
                )
                if result.finish_reason in (
                    RunFinishReason.FAILED,
                    RunFinishReason.NOT_STARTED,
                ):
                    detail = self.ctx.run_context.last_application_result
                    self.error = (
                        detail.status
                        if detail is not None
                        else '启动失败，请查看日志页'
                    )
        except Exception as exc:
            log.exception('独立战斗助手运行失败')
            self.error = str(exc)
        finally:
            if not self.initialize:
                try:
                    self.ctx.run_context.stop_running()
                    if self.ctx.auto_battle_context.auto_op is not None:
                        self.ctx.auto_battle_context.stop_auto_battle()
                except Exception as exc:
                    log.exception('停止战斗时发生错误')
                    self.error = f'{self.error}\n释放战斗资源失败: {exc}'.strip()


class BattleWindow(QWidget):
    """只呈现战斗设置、运行状态和错误日志。"""

    key_pressed = Signal(str)
    state_changed = Signal()

    def __init__(self, ctx: BattleStandaloneContext) -> None:
        """创建窗口，稍后在后台准备战斗资源。"""
        super().__init__()
        self.ctx: BattleStandaloneContext = ctx
        self.worker: BattleWorker | None = None
        self.closing: bool = False
        self.stopping: bool = False
        self.editing_keys: bool = False
        self.last_message: str = '正在准备本地战斗资源…'
        self.setWindowTitle('ZZZ Battle · 绝区零战斗助手')
        self.resize(900, 600)
        self.setMinimumSize(820, 560)
        self.setObjectName('battleWindow')
        self.setStyleSheet(
            'QWidget {font-family: "Microsoft YaHei UI";}'
            'QWidget#battleWindow {background: #f5f6f8;}'
            'QFrame#sidebar {background: #eef0f4; border-right: 1px solid #e0e3e9;}'
            'QFrame#footer {background: white; border-top: 1px solid #e5e7eb;}'
            'QFrame#hero {background: #e7effb; border: 1px solid #d8e5f8; border-radius: 12px;}'
            'QPushButton[nav="true"] {text-align: left; padding: 10px 12px; border: none;'
            ' background: transparent; border-radius: 6px;}'
            'QPushButton[nav="true"]:checked {background: #dce8f8; color: #005a9e;}'
            'QPushButton[nav="true"]:hover {background: #e2e6ed;}'
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame(self)
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(160)
        navigation = QVBoxLayout(sidebar)
        navigation.setContentsMargins(14, 28, 14, 20)
        navigation.setSpacing(8)
        navigation.addWidget(SubtitleLabel('ZZZ Battle'))
        navigation.addWidget(BodyLabel('轻量战斗助手'))
        navigation.addSpacing(30)
        self.nav_group: QButtonGroup = QButtonGroup(self)
        self.pages: QStackedWidget = QStackedWidget(self)
        for index, (title, icon) in enumerate((
            ('自动战斗', FluentIcon.PLAY),
            ('设置', FluentIcon.SETTING),
            ('日志', FluentIcon.DOCUMENT),
        )):
            button = QPushButton(icon.icon(), f'  {title}')
            button.setMinimumHeight(40)
            button.setProperty('nav', 'true')
            button.setCheckable(True)
            self.nav_group.addButton(button, index)
            navigation.addWidget(button)
        self.nav_group.button(0).setChecked(True)
        self.nav_group.idClicked.connect(self.pages.setCurrentIndex)
        self.pages.currentChanged.connect(self.on_page_changed)
        navigation.addStretch(1)
        navigation.addWidget(BodyLabel('基于 OneDragon'))
        layout.addWidget(sidebar)
        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        layout.addLayout(main, 1)
        main.addWidget(self.pages, 1)

        home = QWidget()
        home_layout = QVBoxLayout(home)
        home_layout.setContentsMargins(28, 26, 28, 22)
        home_layout.setSpacing(14)
        home_layout.addWidget(SubtitleLabel('自动战斗'))
        hero = QFrame()
        hero.setObjectName('hero')
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(20, 18, 20, 18)
        hero_layout.addWidget(SubtitleLabel('进入关卡，随时开战'))
        tip = BodyLabel('你负责选关和移动，助手负责战斗。\n游戏保持前台，按热键即可开始、暂停或继续。')
        tip.setWordWrap(True)
        hero_layout.addWidget(tip)
        home_layout.addWidget(hero)
        self.settings: QWidget = QWidget(self)
        settings_layout = QVBoxLayout(self.settings)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(10)
        self.strategy: ComboBoxSettingCard = ComboBoxSettingCard(
            FluentIcon.GAME, '战斗策略',
            content='通用策略自动识别队伍',
            options_list=get_auto_battle_op_config_list('auto_battle'),
        )
        self.strategy.init_with_adapter(
            get_prop_adapter(ctx.battle_assistant_config, 'auto_battle_config')
        )
        settings_layout.addWidget(self.strategy)
        self.ultimate: SwitchSettingCard = SwitchSettingCard(
            FluentIcon.GAME, '自动释放终结技', content='关闭后可手动选择释放时机',
        )
        self.ultimate.init_with_adapter(
            get_prop_adapter(ctx.battle_assistant_config, 'auto_ultimate_enabled')
        )
        settings_layout.addWidget(self.ultimate)
        home_layout.addWidget(self.settings)
        home_layout.addStretch(1)
        note = BodyLabel('1920 × 1080 · 前台键鼠模式\n处理菜单和结算前请暂停；不要同时运行完整版助手。')
        note.setWordWrap(True)
        home_layout.addWidget(note)
        self.pages.addWidget(home)

        settings_page = QWidget()
        advanced = QVBoxLayout(settings_page)
        advanced.setContentsMargins(28, 26, 28, 22)
        advanced.setSpacing(14)
        advanced.addWidget(SubtitleLabel('设置'))
        advanced.addWidget(BodyLabel('停止战斗后可调整，修改自动保存。'))
        self.performance: QWidget = QWidget()
        performance_layout = QVBoxLayout(self.performance)
        performance_layout.setContentsMargins(0, 0, 0, 0)
        self.gpu: SwitchSettingCard = SwitchSettingCard(
            FluentIcon.SPEED_HIGH, 'GPU 闪光识别',
            content='推理出错或游戏掉帧时可关闭，改用 CPU',
        )
        self.gpu.init_with_adapter(get_prop_adapter(ctx.model_config, 'flash_classifier_gpu'))
        performance_layout.addWidget(self.gpu)
        self.interval: DoubleSpinBoxSettingCard = DoubleSpinBoxSettingCard(
            FluentIcon.SPEED_HIGH, '截图间隔（秒）',
            content='默认 0.02；调大可减轻负载，反应会变慢',
            minimum=0.02, maximum=0.1,
        )
        self.interval.init_with_adapter(
            get_prop_adapter(ctx.battle_assistant_config, 'screenshot_interval')
        )
        performance_layout.addWidget(self.interval)
        self.keys_button: PushButton = PushButton('检查 / 修改游戏键位')
        self.keys_button.clicked.connect(self.edit_keys)
        performance_layout.addWidget(self.keys_button)
        advanced.addWidget(self.performance)
        advanced.addStretch(1)
        self.pages.addWidget(settings_page)

        logs_page = QWidget()
        logs_layout = QVBoxLayout(logs_page)
        logs_layout.setContentsMargins(28, 26, 28, 22)
        logs_layout.setSpacing(14)
        logs_header = QHBoxLayout()
        logs_header.addWidget(SubtitleLabel('日志'), 1)
        self.logs_button: PushButton = PushButton('打开日志目录')
        self.logs_button.clicked.connect(self.open_logs)
        logs_header.addWidget(self.logs_button)
        logs_layout.addLayout(logs_header)
        logs_layout.addWidget(BodyLabel('最近 200 条 · 完整记录保存在本地'))
        self.log_card: BattleLogPanel = BattleLogPanel(self)
        logs_layout.addWidget(self.log_card, 1)
        self.pages.addWidget(logs_page)

        footer = QFrame()
        footer.setObjectName('footer')
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(28, 14, 28, 18)
        self.status: BodyLabel = BodyLabel(self.last_message)
        self.status.setWordWrap(True)
        footer_layout.addWidget(self.status)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.start_button: PrimaryPushButton = PrimaryPushButton('准备中…')
        self.start_button.setMinimumWidth(160)
        self.start_button.setFixedHeight(38)
        self.stop_button: PushButton = PushButton(f'停止 {ctx.key_stop_running.upper()}')
        self.stop_button.setFixedHeight(38)
        self.start_button.clicked.connect(self.toggle)
        self.stop_button.clicked.connect(self.stop)
        row.addWidget(self.start_button)
        row.addWidget(self.stop_button)
        row.addStretch(1)
        footer_layout.addLayout(row)
        main.addWidget(footer)
        self.key_pressed.connect(self.on_key)
        self.state_changed.connect(self.refresh)
        ctx.listen_event(ContextKeyboardEventEnum.PRESS.value, self.on_context_key)
        for state_event in ApplicationRunContextStateEventEnum:
            ctx.run_context.event_bus.listen_event(state_event.value, self.on_context_state)
        self.timer: QTimer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.settings.setEnabled(False)
        self.performance.setEnabled(False)
        QTimer.singleShot(0, self.initialize)

    def on_page_changed(self, index: int) -> None:
        """程序切换页面时也同步导航选中状态。"""
        self.nav_group.button(index).setChecked(True)

    def initialize(self) -> None:
        """启动初始化线程，也用于失败后的重试。"""
        if self.worker is not None or self.closing:
            return
        self.last_message = '正在准备本地战斗资源…'
        self.launch_worker(initialize=True)

    def launch_worker(self, initialize: bool) -> None:
        """保留线程引用直到 finished 信号，防止重复启动和提前销毁。"""
        self.worker = BattleWorker(self.ctx, initialize, self)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()
        self.refresh()

    def toggle(self) -> None:
        """在主线程处理开始、暂停和继续。"""
        if self.closing or self.stopping:
            return
        if self.worker is not None:
            if not self.worker.initialize:
                self.ctx.run_context.switch_context_pause_and_run()
            return
        if not self.ctx.ready_for_application:
            self.initialize()
            return
        available = {
            item.value for item in get_auto_battle_op_config_list('auto_battle')
        }
        if self.ctx.battle_assistant_config.auto_battle_config not in available:
            self.last_message = '所选策略文件不存在，请从列表重新选择战斗策略'
            self.refresh()
            return
        self.last_message = '正在加载战斗策略…'
        self.launch_worker(initialize=False)

    def stop(self) -> None:
        """标记取消，并持续要求正在退出的战斗停止。"""
        if self.worker is None or self.worker.initialize:
            return
        self.worker.cancelled.set()
        self.stopping = True
        self.timer.start()
        self.ctx.run_context.stop_running()
        self.refresh()

    def on_finished(self) -> None:
        """线程退出后才能恢复设置或关闭窗口。"""
        worker = self.worker
        if worker is None:
            return
        self.last_message = worker.error or (
            '已就绪，请进入关卡后开始' if worker.initialize else '已停止'
        )
        self.worker = None
        self.stopping = False
        self.timer.stop()
        worker.deleteLater()
        if self.closing:
            self.close()
        else:
            self.refresh()

    def refresh(self) -> None:
        """刷新状态；停止期间覆盖可能迟到的运行状态变更。"""
        busy = self.worker is not None
        initializing = busy and self.worker.initialize
        if self.stopping:
            self.ctx.run_context.stop_running()
        self.settings.setEnabled(not busy and not self.closing)
        self.performance.setEnabled(not busy and not self.closing)
        self.start_button.setEnabled(
            not initializing and not self.stopping and not self.closing
        )
        self.stop_button.setEnabled(busy and not initializing and not self.stopping)
        state = self.ctx.run_context
        if self.closing or self.stopping:
            message = '正在停止并释放按键，请稍候…'
        elif state.is_context_running:
            message = '战斗运行中 · 切换窗口或操作菜单前请先暂停'
        elif state.is_context_pause:
            message = '已暂停 · 可以手动操作，准备好后继续'
        else:
            message = self.last_message
        self.status.setText(message)
        action = (
            '暂停'
            if state.is_context_running
            else '继续'
            if state.is_context_pause
            else '开始'
        )
        if not self.ctx.ready_for_application:
            action = '准备中…' if initializing else '重试初始化'
        self.start_button.setText(f'{action} {self.ctx.key_start_running.upper()}')

    def on_context_state(self, event: ContextEventItem) -> None:
        """后台状态变化通过信号触发界面刷新，不持续轮询。"""
        self.state_changed.emit()

    def on_context_key(self, event: ContextEventItem) -> None:
        """将监听线程的按键事件转为 Qt 信号。"""
        self.key_pressed.emit(event.data)

    def on_key(self, key: str) -> None:
        """仅响应显示在界面上的运行热键。"""
        if self.editing_keys:
            return
        if key == self.ctx.key_start_running:
            self.toggle()
        elif key == self.ctx.key_stop_running:
            self.stop()

    def open_logs(self) -> None:
        """打开本地日志目录，便于排障。"""
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(Path(os_utils.get_work_dir()) / '.log'))
        )

    def edit_keys(self) -> None:
        """复用按键卡片，编辑独立助手的游戏键位。"""
        if self.worker is not None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('游戏键位 · 请与游戏内设置保持一致')
        dialog.resize(600, 620)
        layout = QVBoxLayout(dialog)
        tip = BodyLabel(
            '这里不会修改游戏内设置。连携左、右、取消建议在游戏中设为独立按键，再在这里对应设置。'
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)
        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)
        content = QWidget()
        cards_layout = QVBoxLayout(content)
        cards: list[KeySettingCard] = []
        for action in GameKeyAction:
            card = KeySettingCard(FluentIcon.GAME, action.value.label)
            card.init_with_adapter(
                self.ctx.game_config.get_prop_adapter(f'key_{action.value.value}')
            )
            cards_layout.addWidget(card)
            cards.append(card)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        done = PushButton('完成')
        done.clicked.connect(dialog.accept)
        layout.addWidget(done)
        self.editing_keys = True
        try:
            dialog.exec()
        finally:
            for card in cards:
                card._stop_listener()
            self.editing_keys = False
            dialog.deleteLater()

    def closeEvent(self, event: QCloseEvent) -> None:
        """等待线程结束后关闭，不在运行中强行销毁线程。"""
        self.closing = True
        if self.worker is not None:
            self.stop()
            event.ignore()
            self.refresh()
            return
        self.timer.stop()
        self.log_card.stop()
        self.ctx.unlisten_all_event(self)
        self.ctx.run_context.event_bus.unlisten_all_event(self)
        event.accept()


def main() -> int:
    """运行独立窗口，同一安装目录只允许启动一个。"""
    app = QApplication(sys.argv)
    setTheme(Theme.LIGHT)
    setThemeColor('#0067c0')
    lock_path = (
        Path(os_utils.get_path_under_work_dir('.log')) / 'battle_standalone.lock'
    )
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.information(
            None, '战斗助手已打开', '此目录的战斗助手已经运行，请使用已有窗口。'
        )
        return 0
    ctx = BattleStandaloneContext()
    try:
        window = BattleWindow(ctx)
        window.show()
        return app.exec()
    finally:
        ctx.after_app_shutdown()
        lock.unlock()


if __name__ == '__main__':
    raise SystemExit(main())
