"""Scenes in the flyout: a row of scene buttons under the control panel.

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

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QContextMenuEvent,
    QEnterEvent,
    QFocusEvent,
    QFontMetrics,
    QKeyEvent,
    QPaintEvent,
    QPalette,
    QPen,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QFrame,
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

IN_VIEW = 3  # scene buttons in view; the others scroll
NOTICE_DURATION = 6000  # milliseconds a notice stays
MAX_NAME = 40
WHEEL_NOTCH = 120  # angle delta of one wheel notch
LINK_PADDING = 6
# Focus that comes back after a popup (the scene menu) or a window switch keeps its ring.
_FOCUS_RETURNS = (Qt.FocusReason.PopupFocusReason, Qt.FocusReason.ActiveWindowFocusReason)


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
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)  # width: the strip
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
        if event.reason() not in _FOCUS_RETURNS:
            self._focus_shown = event.reason() in keyboard  # not for a click, like Windows
        self.update()
        self.focused.emit()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        if event.reason() not in _FOCUS_RETURNS:
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


class SceneStrip(QScrollArea):
    """Scene buttons in one row, three in view; the others scroll sideways, a scene at a
    time. The scroll bar shows below the row only when there are more than three."""

    applied = Signal(object)  # Scene
    menu_requested = Signal(object, QPoint)  # Scene, global position

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.buttons: list[SceneButton] = []
        self._wheel = 0  # wheel movement not yet turned into a scene
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the buttons take the focus
        content = QWidget()
        self._row = QHBoxLayout(content)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(theme.SCENE_GAP)
        self.setWidget(content)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setStyleSheet(_SCROLL_STYLE)
        self.viewport().setAutoFillBackground(False)
        self.horizontalScrollBar().sliderReleased.connect(self._snap)
        self.set_scenes([])

    def scenes(self) -> list[Scene]:
        return [button.scene for button in self.buttons]

    def set_scenes(self, scenes: Sequence[Scene]) -> None:
        if self.buttons and self.scenes() == list(scenes):
            return  # unchanged: keep the buttons (and the focus)
        while (item := self._row.takeAt(0)) is not None:
            if (widget := item.widget()) is not None:
                widget.hide()  # not painted again until the deferred delete
                widget.deleteLater()
        self.buttons = []
        for index, scene in enumerate(scenes):
            button = SceneButton(scene)
            button.clicked.connect(lambda _=False, s=scene: self.applied.emit(s))
            button.menu_requested.connect(lambda at, s=scene: self.menu_requested.emit(s, at))
            button.focused.connect(partial(self.show_index, index))
            self._row.addWidget(button)
            self.buttons.append(button)
        if not scenes:
            empty = label(strings.NO_SCENES, theme.font(theme.CAPTION), theme.TEXT_SECONDARY)
            empty.setFixedHeight(theme.SCENE_HEIGHT)
            self._row.addWidget(empty)
        self._row.addStretch(1)  # fewer than three: they keep their width, on the left
        # Show and size the buttons now, not on the next event loop pass, so that a new
        # scene can be scrolled to at once.
        for item in map(self._row.itemAt, range(self._row.count())):
            if (widget := item.widget()) is not None:
                widget.setVisible(not self.widget().isHidden())
        self._fit()

    def show_scene(self, scene_id: str) -> None:
        """Scroll just enough for the scene to be in view."""
        for index, button in enumerate(self.buttons):
            if button.scene.id == scene_id:
                self.show_index(index)

    def show_index(self, index: int) -> None:
        first = self.first_index()
        if index < first:
            self.show_from(index)
        elif index >= first + IN_VIEW:
            self.show_from(index - IN_VIEW + 1)

    def show_from(self, index: int) -> None:
        """Put the scene at ``index`` on the left edge (as far as the row goes)."""
        self.horizontalScrollBar().setValue(index * self._step())

    def first_index(self) -> int:
        """The scene on the left edge."""
        return round(self.horizontalScrollBar().value() / self._step())

    def wheelEvent(self, event: QWheelEvent) -> None:
        """A scene per wheel notch (down or right goes on); a touchpad adds its small steps
        up to a notch."""
        delta = event.angleDelta()
        self._wheel += delta.y() or delta.x()  # positive: back (up or left)
        notches = int(self._wheel / WHEEL_NOTCH)  # towards zero
        if notches:
            self._wheel -= notches * WHEEL_NOTCH
            last = max(len(self.buttons) - IN_VIEW, 0)
            self.show_from(min(max(self.first_index() - notches, 0), last))
        event.accept()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit()

    def focusNextPrevChild(self, next: bool) -> bool:
        # QScrollArea would scroll the newly focused button into view with a margin; the
        # button scrolls just enough to be whole instead (``focused``).
        return QWidget.focusNextPrevChild(self, next)

    def _step(self) -> int:
        width = _column_width(self.width())
        return width + _gap(self.width(), width)

    def _fit(self) -> None:
        """Three buttons per width (the rounding goes to the gaps, so the third one ends on
        the edge); room for the scroll bar only when it is needed."""
        width = _column_width(self.width())
        self._row.setSpacing(_gap(self.width(), width))
        for button in self.buttons:
            button.setFixedWidth(width)
        overflow = len(self.buttons) > IN_VIEW
        self.setViewportMargins(0, 0, 0, theme.SCROLLBAR_GAP if overflow else 0)
        bar = theme.SCROLLBAR_GAP + theme.SCROLLBAR_WIDTH if overflow else 0
        self.setFixedHeight(theme.SCENE_HEIGHT + bar)
        self._row.activate()
        self.widget().resize(self.widget().sizeHint().width(), theme.SCENE_HEIGHT)
        self.horizontalScrollBar().setSingleStep(self._step())
        self.horizontalScrollBar().setPageStep(self._step() * IN_VIEW)

    def _snap(self) -> None:
        self.show_from(self.first_index())


def _column_width(width: int) -> int:
    """A button's width: three and their gaps fill ``width``."""
    return max((width - (IN_VIEW - 1) * theme.SCENE_GAP) // IN_VIEW, 1)


def _gap(width: int, column: int) -> int:
    return max((width - IN_VIEW * column) // (IN_VIEW - 1), theme.SCENE_GAP)


class LinkButton(PaintedButton):
    """Accent-coloured text that acts like a button (e.g. "+ Salvar atual", "Desfazer")."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(theme.font())
        width = metrics.horizontalAdvance(self.text()) + 2 * LINK_PADDING
        return QSize(width, theme.LINK_HEIGHT)

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
    """The inline field for a scene name: Enter or ✓ accepts it, Esc or ✕ cancels (Esc
    never reaches the flyout, which would close)."""

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
        # Qt's own menu (Undo, Cut, Copy...) would be in English: no translation is loaded.
        self.field.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        palette = self.field.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText, theme.TEXT_SECONDARY)
        self.field.setPalette(palette)
        self.save_button = IconButton(paint_check, strings.SAVE)
        self.cancel_button = IconButton(paint_close, strings.CANCEL)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.EDITOR_GAP)
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

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:  # e.g. on ✓ or ✕
            self.cancelled.emit()
            return
        super().keyPressEvent(event)

    def _sync(self) -> None:
        self.save_button.setEnabled(bool(self.field.text().strip()))

    def _accept(self) -> None:
        name = self.field.text().strip()
        if name:
            self.accepted.emit(name)


class Notice(QWidget):
    """A discreet line of text with an optional action link. It hides by itself, but not
    under the pointer: the flyout would shrink while the user reaches for the action."""

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

    def enterEvent(self, event: QEnterEvent) -> None:
        self.timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if self.isVisible():
            self.timer.start()
        super().leaveEvent(event)

    def _act(self) -> None:
        if self._callback is not None:
            self._callback()


class ScenesSection(QWidget):
    """ "Cenas": the header with "+ Salvar atual" (or the name field), a notice and the row
    of scenes.

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
        self._capturing = 0  # reads for "Salvar atual" / "Sobrescrever" still running
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
        self.strip = SceneStrip()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SCENE_GAP)
        layout.addWidget(self._top)
        layout.addWidget(self.notice)  # above the scenes: they stay under the pointer
        layout.addWidget(self.strip)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.save_link.clicked.connect(self._start_new)
        self.editor.accepted.connect(self._on_name)
        self.editor.cancelled.connect(self._close_editor)
        self.notice.timer.timeout.connect(self._hide_notice)
        self.strip.applied.connect(self.apply)
        self.strip.menu_requested.connect(self._show_menu)

    def reload(self) -> None:
        """Show the saved scenes, with no name being typed and no notice."""
        self._close_editor()
        self._hide_notice()
        self.strip.set_scenes(self._scenes())
        self.strip.show_from(0)
        self.update_actions()

    def update_actions(self) -> None:
        """Saving needs a target with devices and no other save running (a second click
        meanwhile would save the same suggested name twice)."""
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
        if renaming is not None:  # before closing, so the focus goes to the renamed button
            self._change(lambda book: book.rename(renaming.id, name))
        self._close_editor()
        if renaming is None:
            self._capture(name, partial(self._create, name))

    def _overwrite(self, scene: Scene) -> None:
        self._capture(scene.name, partial(self._replace, scene))

    def _delete(self, scene: Scene, *, had_focus: bool = False) -> None:
        """``had_focus``: the scene's button had the focus (keep it on the scenes)."""
        ids = [s.id for s in self._scenes()]
        index = ids.index(scene.id) if scene.id in ids else len(ids)
        if self._change(lambda book: book.delete(scene.id)):
            if had_focus and self.strip.buttons:
                self.strip.buttons[min(index, len(self.strip.buttons) - 1)].setFocus()
            undo = partial(self._undo_delete, scene, index)
            self._notify(strings.scene_deleted(scene.name), (strings.UNDO, undo))

    def _undo_delete(self, scene: Scene, index: int) -> None:
        self._hide_notice()
        if self._change(lambda book: book.restore(scene, index)):
            self.strip.show_scene(scene.id)

    def _show_menu(self, scene: Scene, position: QPoint) -> None:
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.addAction(strings.RENAME).triggered.connect(partial(self._start_rename, scene))
        overwrite = menu.addAction(strings.OVERWRITE)
        overwrite.setEnabled(self._can_capture())
        overwrite.triggered.connect(partial(self._overwrite, scene))
        # Whether the button has the focus is known now: once the menu closes, some
        # platforms do not give the focus back to it.
        delete = partial(self._delete, scene, had_focus=self._button_has_focus(scene))
        menu.addAction(strings.DELETE).triggered.connect(delete)
        menu.destroyed.connect(partial(self._forget_menu, menu))
        self.menu = menu
        menu.popup(position)

    def _forget_menu(self, menu: QMenu) -> None:
        if self.menu is menu:
            self.menu = None

    # --- editor and notice --------------------------------------------------------------------

    def _open_editor(self, text: str) -> None:
        self._top.setCurrentWidget(self.editor)
        self.editor.start(text)

    def _close_editor(self) -> None:
        typing = self.editor.isAncestorOf(self.window().focusWidget())
        self._top.setCurrentIndex(0)
        if typing:  # the focus would be lost with the hidden field
            renamed = self._renaming
            buttons = (b for b in self.strip.buttons if renamed and b.scene.id == renamed.id)
            next(buttons, self.save_link).setFocus()

    def _button_has_focus(self, scene: Scene) -> bool:
        """Whether the scene's button has the focus within the window (also while the window
        is not active, e.g. right after a popup on a platform that does not reactivate it)."""
        focused = self.window().focusWidget()
        return any(b.scene.id == scene.id and b is focused for b in self.strip.buttons)

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
        if self._capturing or target is None:
            return False
        return bool(self.service.members(target))

    def _capture(self, name: str, store: Callable[[dict[str, DeviceState]], bool]) -> None:
        """Read the target's devices, then ``store`` what answered."""
        target = self._target()
        if target is None:
            return
        members = [d.id for d in self.service.members(target)]
        future = self.service.capture(target)
        self._capturing += 1
        self.update_actions()
        self._bridge.when_done(future, partial(self._on_captured, name, members, store))

    def _on_captured(
        self,
        name: str,
        members: list[str],
        store: Callable[[dict[str, DeviceState]], bool],
        future: Future[dict[str, DeviceState]],
    ) -> None:
        self._capturing -= 1
        self.update_actions()
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
        self.strip.show_scene(self.strip.scenes()[-1].id)
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
        """Change the saved scenes and persist them. The row then shows what is saved: on a
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
            self.strip.set_scenes(self._scenes())
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


_SCROLL_STYLE = f"""
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: {theme.SCROLLBAR_WIDTH}px;
    margin: 0 2px; }}
QScrollBar::handle:horizontal {{ background: {theme.DEVICE_OFF.name()}; border-radius: 3px;
    min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}
"""

_FIELD_STYLE = f"""
QLineEdit {{
    background: {theme.SURFACE.name()}; color: {theme.TEXT.name()};
    border: 1px solid {theme.SURFACE_BORDER.name()}; border-radius: {theme.ROW_RADIUS}px;
    padding: 0 {theme.FIELD_PADDING}px;
    selection-background-color: {theme.ACCENT.name()}; selection-color: {theme.ON_ACCENT.name()};
}}
QLineEdit:focus {{ border-bottom: 2px solid {theme.ACCENT.name()}; }}
"""
