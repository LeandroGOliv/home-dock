"""Placeholder flyout: a small window near the tray, replaced by the real flyout (issue #8)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor, QFont, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from homedock.ui import strings
from homedock.ui.placement import flyout_position

WIDTH = 360
MARGIN = 12  # gap to the screen edge / taskbar


class PlaceholderFlyout(QWidget):
    def __init__(self) -> None:
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(None, flags)
        self.setWindowTitle(strings.APP_NAME)
        self.setFixedWidth(WIDTH)
        title = QLabel(strings.APP_NAME)
        font = QFont(title.font())
        font.setPointSizeF(font.pointSizeF() * 1.4)
        font.setBold(True)
        title.setFont(font)
        message = QLabel(strings.FLYOUT_PLACEHOLDER)
        message.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.addWidget(title)
        layout.addWidget(message)

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.open()

    def open(self) -> None:
        """Show in the tray corner of the screen under the cursor, next to the taskbar."""
        self.adjustSize()
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        size = self.frameGeometry().size()
        self.move(flyout_position(screen.geometry(), screen.availableGeometry(), size, MARGIN))
        self.show()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)
