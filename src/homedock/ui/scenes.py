"""Scenes in the flyout: a grid of scene buttons under the control panel.

A click applies a scene; a right click (or the menu key) offers Renomear | Sobrescrever com o
estado atual | Excluir. "+ Salvar atual" saves the state of the selected target's devices.
Names are typed in an inline field: a dialog would take the focus and close the flyout. A
discreet notice tells when offline devices were left out and offers to undo a deletion.
Scenes are generic: the control service sends each device only what it supports.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import Future
from functools import partial
from typing import Any

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QContextMenuEvent,
    QFocusEvent,
    QFontMetrics,
    QKeyEvent,
    QPaintEvent,
    QPalette,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from homedock.core import ControlService, Scene, SceneBook, ServiceClosedError, Target
from homedock.devices import DeviceState
from homedock.ui import strings, theme
from homedock.ui.bridge import ServiceBridge
from homedock.ui.icons import paint_check, paint_close
from homedock.ui.widgets import PaintedButton, draw_text, label

log = logging.getLogger(__name__)

COLUMNS = 3
NOTICE_DURATION = 6000  # milliseconds a notice stays
MAX_NAME = 40
WHEEL_NOTCH = 120  # angle delta of one wheel notch
LINK_PADDING = 6


class SceneButton(PaintedButton):
    """One scene: a click applies it; a right click or the menu key asks for its menu."""

    menu_requested = Signal(QPoint)  # global position
    focused = Signal()

    def __init__(self, scene: Scene, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.scene = scene
        self.setText(scene.name)
        self.setToolTip(scene.name)  # the name may be elided
        self.setFixedHeight(theme.SCENE_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._focus_shown = False

    def focus_shown(self) -> bool:
        return self._focus_shown

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        position = event.globalPos()
        if event.reason() == QContextMenuEvent.Reason.Keyboard:
            position = self.mapToGlobal(self.rect().center())
        self.menu_requested.emit(position)

    def focusInEvent(self, event: QFocusEvent) -> None:
        keyboard = (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)
        self._focus_shown = event.reason() in keyboard  # not for a click, like Windows
        self.update()
        self.focused.emit()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self._focus_shown = False
        self.update()
        super().focusOutEvent(event)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = self.painter()
        fill = theme.SURFACE
        if self.isDown():
            fill = theme.SELECTED
        elif self.hovered():
            fill = theme.HOVER
        if self._focus_shown:
            inset = theme.FOCUS_WIDTH / 2
            painter.setPen(QPen(theme.FOCUS, theme.FOCUS_WIDTH))
        else:
            inset = 0.5
            painter.setPen(QPen(theme.SURFACE_BORDER, 1))
        painter.setBrush(fill)
        frame = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        painter.drawRoundedRect(frame, theme.CONTROL_RADIUS, theme.CONTROL_RADIUS)
        text = QRectF(self.rect()).adjusted(theme.SPACING, 0, -theme.SPACING, 0)
        draw_text(painter, text, self.text(), theme.font(), align=Qt.AlignmentFlag.AlignHCenter)
        painter.end()


class SceneGrid(QScrollArea):
    """Scene buttons in rows of three. One row shows; the others scroll, a row at a time."""

    applied = Signal(object)  # Scene
    menu_requested = Signal(object, QPoint)  # Scene, global position

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.buttons: list[SceneButton] = []
        self._wheel = 0  # wheel movement not yet turned into a row
        content = QWidget()
        content.setAutoFillBackground(False)
        self._grid = QGridLayout(content)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(theme.SCENE_GAP)
        for column in range(COLUMNS):
            self._grid.setColumnStretch(column, 1)
        self.setWidget(content)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(_SCROLL_STYLE)
        self.viewport().setAutoFillBackground(False)
        self.setFixedHeight(theme.SCENE_HEIGHT)
        bar = self.verticalScrollBar()
        bar.setSingleStep(_ROW_STEP)
        bar.setPageStep(_ROW_STEP)
        bar.sliderReleased.connect(self._snap)
        self.set_scenes([])

    def scenes(self) -> list[Scene]:
        return [button.scene for button in self.buttons]

    def set_scenes(self, scenes: Sequence[Scene]) -> None:
        if self.buttons and self.scenes() == list(scenes):
            return  # unchanged: keep the buttons (and the focus)
        while (item := self._grid.takeAt(0)) is not None:
            if (widget := item.widget()) is not None:
                widget.hide()  # not painted again until the deferred delete
                widget.deleteLater()
        self.buttons = []
        for index, scene in enumerate(scenes):
            button = SceneButton(scene)
            button.clicked.connect(lambda _=False, s=scene: self.applied.emit(s))
            button.menu_requested.connect(lambda at, s=scene: self.menu_requested.emit(s, at))
            button.focused.connect(partial(self.show_row, index // COLUMNS))
            self._grid.addWidget(button, index // COLUMNS, index % COLUMNS)
            self.buttons.append(button)
        if not scenes:
            empty = label(strings.NO_SCENES, theme.font(theme.CAPTION), theme.TEXT_SECONDARY)
            empty.setFixedHeight(theme.SCENE_HEIGHT)
            self._grid.addWidget(empty, 0, 0, 1, COLUMNS)
        # Show and size the rows now, not on the next event loop pass, so that a new row can
        # be scrolled to at once.
        for item in map(self._grid.itemAt, range(self._grid.count())):
            item.widget().setVisible(not self.widget().isHidden())
        self._grid.activate()
        self.widget().resize(self.viewport().width(), self.widget().sizeHint().height())

    def show_scene(self, scene_id: str) -> None:
        """Scroll to the row of the scene."""
        for index, button in enumerate(self.buttons):
            if button.scene.id == scene_id:
                self.show_row(index // COLUMNS)

    def show_row(self, row: int) -> None:
        self.verticalScrollBar().setValue(row * _ROW_STEP)

    def first_row(self) -> int:
        """The row shown."""
        return round(self.verticalScrollBar().value() / _ROW_STEP)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """A row per wheel notch; a touchpad adds its small steps up to a notch."""
        self._wheel += event.angleDelta().y()
        rows = int(self._wheel / WHEEL_NOTCH)  # towards zero
        if rows:
            self._wheel -= rows * WHEEL_NOTCH
            self.show_row(max(self.first_row() - rows, 0))
        event.accept()

    def focusNextPrevChild(self, next: bool) -> bool:
        # QScrollArea would scroll the newly focused button into view with a margin; the
        # button scrolls to its whole row instead (``focused``).
        return QWidget.focusNextPrevChild(self, next)

    def _snap(self) -> None:
        self.show_row(self.first_row())


class LinkButton(PaintedButton):
    """Accent-coloured text that acts like a button (e.g. "+ Salvar atual", "Desfazer")."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(theme.font())
        return QSize(metrics.horizontalAdvance(self.text()) + 2 * LINK_PADDING, 28)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = self.painter()
        self.paint_hover(painter)
        color = theme.ACCENT if self.isEnabled() else theme.DEVICE_OFF
        draw_text(
            painter,
            QRectF(self.rect()),
            self.text(),
            theme.font(),
            color,
            Qt.AlignmentFlag.AlignHCenter,
        )
        painter.end()


class IconButton(PaintedButton):
    """A square button with a painted glyph (the name field's ✓ and ✕)."""

    def __init__(
        self,
        glyph: Callable[..., None],
        name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self.setFixedSize(theme.EDITOR_HEIGHT, theme.EDITOR_HEIGHT)
        self.setAccessibleName(name)
        self.setToolTip(name)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = self.painter()
        self.paint_hover(painter)
        glyph = QRectF(0, 0, theme.ICON, theme.ICON)
        glyph.moveCenter(QRectF(self.rect()).center())
        self._glyph(painter, glyph, theme.TEXT if self.isEnabled() else theme.DEVICE_OFF)
        painter.end()


class NameField(QLineEdit):
    """A text box where Esc cancels (instead of closing the flyout)."""

    cancelled = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)


class NameEditor(QWidget):
    """The inline field for a scene name: Enter or ✓ accepts it, Esc or ✕ cancels."""

    accepted = Signal(str)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.field = NameField()
        self.field.setFont(theme.font())
        self.field.setFixedHeight(theme.EDITOR_HEIGHT)
        self.field.setMaxLength(MAX_NAME)
        self.field.setPlaceholderText(strings.SCENE_NAME)
        self.field.setAccessibleName(strings.SCENE_NAME)
        self.field.setStyleSheet(_FIELD_STYLE)
        palette = self.field.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText, theme.TEXT_SECONDARY)
        self.field.setPalette(palette)
        self.save_button = IconButton(paint_check, strings.SAVE)
        self.cancel_button = IconButton(paint_close, strings.CANCEL)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.field, 1)
        layout.addWidget(self.save_button)
        layout.addWidget(self.cancel_button)

        self.field.returnPressed.connect(self._accept)
        self.field.textChanged.connect(self._sync)
        self.field.cancelled.connect(self.cancelled)
        self.save_button.clicked.connect(self._accept)
        self.cancel_button.clicked.connect(self.cancelled)

    def start(self, text: str) -> None:
        """Edit ``text``, all selected so typing replaces it."""
        self.field.setText(text)
        self.field.selectAll()
        self._sync()
        self.field.setFocus(Qt.FocusReason.OtherFocusReason)

    def _sync(self) -> None:
        self.save_button.setEnabled(bool(self.field.text().strip()))

    def _accept(self) -> None:
        name = self.field.text().strip()
        if name:
            self.accepted.emit(name)


class Notice(QWidget):
    """A discreet line of text with an optional action link; it hides by itself."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.text = label("", theme.font(theme.CAPTION), theme.TEXT_SECONDARY)
        self.text.setWordWrap(True)
        self.action = LinkButton("")
        self.action.hide()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(NOTICE_DURATION)
        self._callback: Callable[[], object] | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.action)
        self.action.clicked.connect(self._act)

    def set_message(self, text: str, action: tuple[str, Callable[[], object]] | None) -> None:
        self.text.setText(text)
        self.action.setVisible(action is not None)
        if action is not None:
            self.action.setText(action[0])
            self.action.updateGeometry()
        self._callback = action[1] if action is not None else None
        self.timer.start()

    def _act(self) -> None:
        if self._callback is not None:
            self._callback()


class ScenesSection(QWidget):
    """ "Cenas": the header with "+ Salvar atual" (or the name field), a notice and the grid.

    ``target`` gives the selected target (whose devices "Salvar atual" saves); ``scenes``
    gives the saved scenes and ``save_scenes`` persists them, raising ``OSError``.
    """

    layout_changed = Signal()

    def __init__(
        self,
        service: ControlService,
        bridge: ServiceBridge,
        *,
        target: Callable[[], Target | None],
        scenes: Callable[[], Sequence[Scene]],
        save_scenes: Callable[[Sequence[Scene]], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self._bridge = bridge
        self._target = target
        self._scenes = scenes
        self._save_scenes = save_scenes
        self._renaming: Scene | None = None  # None: the name field names a new scene
        self.menu: QMenu | None = None

        self.title = label(strings.SCENES, theme.font(), theme.TEXT)
        self.save_link = LinkButton(strings.SAVE_CURRENT)
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(self.title)
        header_layout.addStretch(1)
        header_layout.addWidget(self.save_link)
        self.editor = NameEditor()
        self._top = QStackedWidget()  # the header or the name field, at the same height
        self._top.addWidget(header)
        self._top.addWidget(self.editor)
        self._top.setFixedHeight(theme.EDITOR_HEIGHT)
        self.notice = Notice()
        self.notice.hide()
        self.grid = SceneGrid()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SCENE_GAP)
        layout.addWidget(self._top)
        layout.addWidget(self.notice)  # above the grid: the grid stays under the pointer
        layout.addWidget(self.grid)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.save_link.clicked.connect(self._start_new)
        self.editor.accepted.connect(self._on_name)
        self.editor.cancelled.connect(self._close_editor)
        self.notice.timer.timeout.connect(self._hide_notice)
        self.grid.applied.connect(self.apply)
        self.grid.menu_requested.connect(self._show_menu)

    def reload(self) -> None:
        """Show the saved scenes, with no name being typed and no notice."""
        self._close_editor()
        self._hide_notice()
        self.grid.set_scenes(self._scenes())
        self.update_actions()

    def update_actions(self) -> None:
        """Saving needs a target with devices."""
        self.save_link.setEnabled(self._can_capture())

    def editing(self) -> bool:
        return self._top.currentWidget() is self.editor

    # --- user actions -------------------------------------------------------------------------

    def apply(self, scene: Scene) -> None:
        future = self.service.apply_scene(scene)
        self._bridge.when_done(future, partial(self._on_applied, scene))

    def _start_new(self) -> None:
        self._renaming = None
        self._open_editor(strings.new_scene_name(s.name for s in self._scenes()))

    def _start_rename(self, scene: Scene) -> None:
        self._renaming = scene
        self._open_editor(scene.name)

    def _on_name(self, name: str) -> None:
        renaming = self._renaming
        self._close_editor()
        if renaming is None:
            self._capture(name, partial(self._create, name))
        else:
            self._change(lambda book: book.rename(renaming.id, name))

    def _overwrite(self, scene: Scene) -> None:
        self._capture(scene.name, partial(self._replace, scene))

    def _delete(self, scene: Scene) -> None:
        ids = [s.id for s in self._scenes()]
        index = ids.index(scene.id) if scene.id in ids else len(ids)
        if self._change(lambda book: book.delete(scene.id)):
            undo = partial(self._undo_delete, scene, index)
            self._notify(strings.scene_deleted(scene.name), (strings.UNDO, undo))

    def _undo_delete(self, scene: Scene, index: int) -> None:
        self._hide_notice()
        if self._change(lambda book: book.restore(scene, index)):
            self.grid.show_scene(scene.id)

    def _show_menu(self, scene: Scene, position: QPoint) -> None:
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.addAction(strings.RENAME).triggered.connect(partial(self._start_rename, scene))
        overwrite = menu.addAction(strings.OVERWRITE)
        overwrite.setEnabled(self._can_capture())
        overwrite.triggered.connect(partial(self._overwrite, scene))
        menu.addAction(strings.DELETE).triggered.connect(partial(self._delete, scene))
        self.menu = menu
        menu.popup(position)

    # --- editor and notice --------------------------------------------------------------------

    def _open_editor(self, text: str) -> None:
        self._top.setCurrentWidget(self.editor)
        self.editor.start(text)

    def _close_editor(self) -> None:
        self._top.setCurrentIndex(0)

    def _notify(self, text: str, action: tuple[str, Callable[[], object]] | None = None) -> None:
        self.notice.set_message(text, action)
        self.notice.show()
        self.layout_changed.emit()

    def _hide_notice(self) -> None:
        self.notice.timer.stop()
        if not self.notice.isHidden():
            self.notice.hide()
            self.layout_changed.emit()

    # --- device I/O and storage ---------------------------------------------------------------

    def _can_capture(self) -> bool:
        target = self._target()
        return target is not None and bool(self.service.members(target))

    def _capture(self, name: str, store: Callable[[dict[str, DeviceState]], bool]) -> None:
        """Read the target's devices, then ``store`` what answered."""
        target = self._target()
        if target is None:
            return
        members = [d.id for d in self.service.members(target)]
        future = self.service.capture(target)
        self._bridge.when_done(future, partial(self._on_captured, name, members, store))

    def _on_captured(
        self,
        name: str,
        members: list[str],
        store: Callable[[dict[str, DeviceState]], bool],
        future: Future[dict[str, DeviceState]],
    ) -> None:
        snapshot = _outcome(future)
        if snapshot is None:
            return
        missing = [i for i in members if i not in snapshot]
        if not snapshot:
            self._notify(strings.nothing_saved(len(missing), self._noun(missing)))
        elif store(snapshot) and missing:
            self._notify(strings.left_out(name, len(missing), self._noun(missing)))

    def _create(self, name: str, snapshot: dict[str, DeviceState]) -> bool:
        if not self._change(lambda book: book.create(name, snapshot)):
            return False
        self.grid.show_scene(self.grid.scenes()[-1].id)
        return True

    def _replace(self, scene: Scene, snapshot: dict[str, DeviceState]) -> bool:
        return self._change(lambda book: book.overwrite(scene.id, snapshot))

    def _on_applied(self, scene: Scene, future: Future[Any]) -> None:
        result = _outcome(future)
        if result is not None and result.failed:
            self._notify(
                strings.left_out(scene.name, len(result.failed), self._noun(result.failed))
            )

    def _change(self, change: Callable[[SceneBook], object]) -> bool:
        """Change the saved scenes and persist them. The grid then shows what is saved: on a
        failure, the scenes as they were."""
        book = SceneBook(self._scenes())
        try:
            change(book)
        except (KeyError, ValueError):  # e.g. the scene was deleted meanwhile
            return False
        try:
            self._save_scenes(book.all())
        except OSError as error:
            log.error("cannot save the scenes: %s", type(error).__name__)
            self._notify(strings.SAVE_FAILED)
            return False
        finally:
            self.grid.set_scenes(self._scenes())
        return True

    def _noun(self, device_ids: Iterable[str]) -> strings.Noun:
        """The words for these devices: their type's, or generic ones for mixed types."""
        ids = set(device_ids)
        types = {d.type for d in self.service.devices if d.id in ids}
        return strings.noun(types.pop() if len(types) == 1 else None)


def _outcome(future: Future[Any]) -> Any:
    """The future's result, or ``None`` when the service was shut down (the app is quitting)."""
    try:
        return future.result()
    except ServiceClosedError:
        return None


_ROW_STEP = theme.SCENE_HEIGHT + theme.SCENE_GAP

_SCROLL_STYLE = f"""
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 6px; margin: 2px 0 2px 2px; }}
QScrollBar::handle:vertical {{ background: {theme.DEVICE_OFF.name()}; border-radius: 2px;
    min-height: 12px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
"""

_FIELD_STYLE = f"""
QLineEdit {{
    background: {theme.SURFACE.name()}; color: {theme.TEXT.name()};
    border: 1px solid {theme.SURFACE_BORDER.name()}; border-radius: 4px; padding: 0 8px;
    selection-background-color: {theme.ACCENT.name()}; selection-color: {theme.ON_ACCENT.name()};
}}
QLineEdit:focus {{ border-bottom: 2px solid {theme.ACCENT.name()}; }}
"""
