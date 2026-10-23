"""独立战斗窗口的有界日志，只在可见时刷新。"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from qfluentwidgets import PlainTextEdit

from one_dragon.utils.log_utils import log
from one_dragon.yolo.log_utils import log as yolo_log

if TYPE_CHECKING:
    from PySide6.QtGui import QHideEvent, QShowEvent
    from PySide6.QtWidgets import QWidget


class BoundedLogBuffer(logging.Handler):
    """后台线程仅写入有限条数的纯文本，不操作界面。"""

    def __init__(self, capacity: int = 200) -> None:
        super().__init__()
        self.lines: deque[str] = deque(maxlen=capacity)
        self.revision: int = 0
        self.setFormatter(logging.Formatter('%(asctime)s  %(levelname)s  %(message)s', '%H:%M:%S'))

    def emit(self, record: logging.LogRecord) -> None:
        """限制单条长度，避免异常日志长期占用内存。"""
        self.acquire()
        try:
            self.lines.append(self.format(record)[:4000])
            self.revision += 1
        finally:
            self.release()

    def snapshot(self) -> tuple[int, tuple[str, ...]]:
        """在日志线程和界面线程之间传递不可变快照。"""
        self.acquire()
        try:
            return self.revision, tuple(self.lines)
        finally:
            self.release()


class BattleLogPanel(PlainTextEdit):
    """日志页隐藏时停止计时器，显示时批量更新。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.buffer: BoundedLogBuffer = BoundedLogBuffer()
        self.revision: int = -1
        self.disposed: bool = False
        self.setReadOnly(True)
        self.setPlaceholderText('运行记录会显示在这里。完整日志保存在本地日志目录。')
        self.timer: QTimer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.flush)
        for logger in (log, yolo_log):
            logger.addHandler(self.buffer)

    def flush(self) -> None:
        """没有新日志时不重绘；阅读历史时保留滚动位置。"""
        revision, lines = self.buffer.snapshot()
        if revision == self.revision:
            return
        scrollbar = self.verticalScrollBar()
        position = scrollbar.value()
        follow = position >= scrollbar.maximum() - 4
        self.setPlainText('\n'.join(lines))
        scrollbar.setValue(scrollbar.maximum() if follow else position)
        self.revision = revision

    def showEvent(self, event: QShowEvent) -> None:
        """进入日志页才开始刷新。"""
        super().showEvent(event)
        if not self.disposed:
            self.flush()
            self.timer.start()

    def hideEvent(self, event: QHideEvent) -> None:
        """隐藏页面后停止刷新。"""
        self.timer.stop()
        super().hideEvent(event)

    def stop(self) -> None:
        """窗口退出时移除日志处理器。"""
        self.disposed = True
        self.timer.stop()
        for logger in (log, yolo_log):
            logger.removeHandler(self.buffer)
        self.buffer.close()
