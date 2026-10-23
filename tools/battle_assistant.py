"""独立战斗助手入口，启动失败时保存完整日志并给出提示。"""

import ctypes
import sys
import traceback
from pathlib import Path


def main() -> int:
    """定位源码并启动窗口，不经过更新器。"""
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'src'))
    try:
        from zzz_od.gui.battle_standalone import main as run_window

        return run_window()
    except Exception:
        error = traceback.format_exc()
        log_dir = root / '.log'
        log_dir.mkdir(exist_ok=True)
        error_file = log_dir / 'battle_startup_error.txt'
        error_file.write_text(error, encoding='utf-8')
        ctypes.windll.user32.MessageBoxW(
            None,
            f'启动失败：\n{error[-1800:]}\n\n完整日志：{error_file}',
            '独立战斗助手',
            0x10,
        )
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
