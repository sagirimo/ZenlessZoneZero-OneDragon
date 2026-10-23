from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from one_dragon.base.config.yaml_config import YamlConfig
from one_dragon.base.operation.one_dragon_context import (
    ContextKeyboardEventEnum,
    OneDragonContext,
)
from one_dragon.utils import i18_utils
from zzz_od.application.battle_assistant.auto_battle.auto_battle_app import (
    AutoBattleApp,
)
from zzz_od.application.battle_assistant.auto_battle.auto_battle_app_factory import (
    AutoBattleAppFactory,
)
from zzz_od.application.battle_assistant.battle_assistant_config import (
    BattleAssistantConfig,
)
from zzz_od.auto_battle.auto_battle_operator import AutoBattleOperator
from zzz_od.config.game_config import GameConfig
from zzz_od.config.model_config import ModelConfig
from zzz_od.context.zzz_context import ZContext

if TYPE_CHECKING:
    from one_dragon.envs.repo_config import RepoConfig


class StandaloneBattleConfig(BattleAssistantConfig):
    """独立保存战斗设置，不覆盖完整助手的设置。"""

    def __init__(self, instance_idx: int) -> None:
        """首次借用原战斗设置的默认值，固定使用前台模式。"""
        YamlConfig.__init__(self, 'battle_standalone', instance_idx=instance_idx)
        original = BattleAssistantConfig(instance_idx)
        for key in (
            'auto_battle_config',
            'auto_ultimate_enabled',
            'screenshot_interval',
            'use_merged_file',
        ):
            self.data.setdefault(key, getattr(original, key))
        self.data['background_mode'] = False


class StandaloneBattleFactory(AutoBattleAppFactory):
    """复用战斗应用，禁止独立助手自动启动和登录游戏。"""

    def create_application(self, instance_idx: int, group_id: str) -> AutoBattleApp:
        """创建只接受已打开游戏的战斗应用。"""
        app = AutoBattleApp(self.ctx)
        app.op_to_enter_game = None
        return app


class StandaloneGameConfig(GameConfig):
    """复制已有键位到独立配置，保证首次运行也使用前台键鼠。"""

    def __init__(self, instance_idx: int) -> None:
        """只读原配置，后续修改写入专用文件。"""
        YamlConfig.__init__(self, 'battle_standalone_game', instance_idx=instance_idx)
        original = YamlConfig('game', instance_idx=instance_idx)
        for key, value in original.data.items():
            self.data.setdefault(key, value)
        self.data['background_mode'] = False


class StandaloneModelConfig(ModelConfig):
    """独立保存运算设备选择，复用已有本地模型文件。"""

    def __init__(self, repo_config: RepoConfig, instance_idx: int) -> None:
        """读取原模型配置作为默认值，不修改其文件。"""
        self.repo_config: RepoConfig = repo_config
        YamlConfig.__init__(self, 'battle_standalone_model', instance_idx=instance_idx)
        original = YamlConfig('model')
        for key, value in original.data.items():
            self.data.setdefault(key, value)


class BattleStandaloneContext(ZContext):
    """只准备手动战斗需要的服务。"""

    @cached_property
    def model_config(self) -> StandaloneModelConfig:
        """读取当前账号的独立模型设置。"""
        return StandaloneModelConfig(self.repo_config, self.current_instance_idx)

    @cached_property
    def game_config(self) -> StandaloneGameConfig:
        """读取专用键位配置，避免全局后台模式触发手柄依赖。"""
        return StandaloneGameConfig(self.current_instance_idx)

    @cached_property
    def battle_assistant_config(self) -> StandaloneBattleConfig:
        """读取当前账号的独立战斗设置。"""
        return StandaloneBattleConfig(self.current_instance_idx)

    def init(self) -> None:
        """初始化本地战斗资源，异常交给窗口显示。"""
        with self._init_lock:
            self.ready_for_application = False
            i18_utils.detect_and_set_default_language()
            if not self._application_registered:
                self.run_context.registry_application(StandaloneBattleFactory(self))
                self._application_registered = True
            self.screen_loader.reload()
            self.init_controller()
            if self.controller is None:
                raise RuntimeError('仅支持 Windows PC 游戏，请检查当前账号的平台设置')
            self.auto_battle_context.init_screen_area()
            self._start_btn_listener()
            self.ready_for_application = True

    def _on_key_press(self, key: str) -> None:
        """由 Qt 主线程统一处理开始和停止，避免线程间操作控件。"""
        self.dispatch_event(ContextKeyboardEventEnum.PRESS.value, key)

    def after_app_shutdown(self) -> None:
        """只清理已使用的战斗服务，避免关闭时加载空洞和遥测。"""
        try:
            self.auto_battle_context.after_app_shutdown()
            AutoBattleOperator.after_app_shutdown()
        finally:
            OneDragonContext.after_app_shutdown(self)
