"""The manage pages of the flyout: "Grupos e lâmpadas" and "Editar grupo".

The first lists the user's groups (with their members), the devices (status, rename) and
"Procurar lâmpadas novas", which reloads ``devices.json`` after a LAN scan. The second edits
a group: name, members (a device may be in many groups) and delete. Names are local (the
config), never written to ``devices.json``. Everything works on generic devices, by type.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from enum import Enum
from functools import partial

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from homedock.core import ControlService, Group, GroupBook, Target
from homedock.devices import Device
from homedock.storage import DeviceReload, ImportProblem
from homedock.ui import strings, theme
from homedock.ui.bridge import ServiceBridge
from homedock.ui.controls import (
    FIELD_STYLE,
    MAX_NAME,
    IconButton,
    LinkButton,
    NameEditor,
    Notice,
)
from homedock.ui.icons import paint_check, paint_chevron, paint_pencil, paint_refresh
from homedock.ui.selector import split_row
from homedock.ui.widgets import PaintedButton, draw_text, label

log = logging.getLogger(__name__)

BUTTON_PADDING = 16  # text inset of an action button


class Groups:
    """The user's groups: the control service's book, persisted through ``save`` (which
    raises ``OSError``)."""

    def __init__(self, service: ControlService, save: Callable[[Sequence[Group]], None]) -> None:
        self._service = service
        self._save = save

    def all(self) -> list[Group]:
        return self._service.groups.all()

    def change[T](self, change: Callable[[GroupBook], T]) -> T:
        """Apply ``change`` to a copy of the groups, persist it, then control the result.

        On any error (``OSError`` from saving, ``KeyError`` / ``ValueError`` from the
        change) nothing changes.
        """
        book = GroupBook(self.all())
        result = change(book)
        self._save(book.all())
        self._service.groups = book
        return result


class DeviceReloader(QObject):
    """Runs "Procurar lâmpadas novas" off the UI thread, one at a time. ``reload`` returns
    the future of the reload; ``finished`` gets its result (``None`` when it failed)."""

    started = Signal()
    finished = Signal(object)  # DeviceReload | None

    def __init__(
        self,
        bridge: ServiceBridge,
        reload: Callable[[], Future[DeviceReload]],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._reload = reload
        self._running = False

    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.started.emit()
        self._bridge.when_done(self._reload(), self._done)

    def _done(self, future: Future[DeviceReload]) -> None:
        self._running = False
        try:
            result = future.result()
        except Exception as error:  # e.g. the service was shut down meanwhile
            log.error("cannot reload the devices: %s", type(error).__name__)
            result = None
        self.finished.emit(result)


# --- widgets -----------------------------------------------------------------------------------


class BackButton(PaintedButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self.setAccessibleName(strings.BACK)
        self.setToolTip(strings.BACK)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = self.painter()
        self.paint_hover(painter)
        glyph = QRectF(0, 0, theme.ICON, theme.ICON)
        glyph.moveCenter(QRectF(self.rect()).center())
        paint_chevron(painter, glyph, theme.TEXT, Qt.Edge.LeftEdge)
        painter.end()


class PageHeader(QWidget):
    """The back button and the page title."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.back_button = BackButton()
        self.title = label(title, theme.font(theme.TITLE, bold=True), theme.TEXT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING)
        layout.addWidget(self.back_button)
        layout.addWidget(self.title, 1)


class ScrollBody(QScrollArea):
    """The middle of a page: as tall as its content, scrolling when the flyout would not fit
    the screen (the flyout caps its own height)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.content = QWidget()
        self.rows = QVBoxLayout(self.content)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(0)
        self.setWidget(self.content)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(_SCROLL_STYLE)
        self.viewport().setAutoFillBackground(False)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def sizeHint(self) -> QSize:
        # QScrollArea caps its hint at a few dozen lines: ask for the whole content.
        self.rows.activate()
        return QSize(theme.WIDTH, self.content.sizeHint().height())


class ButtonStyle(Enum):
    OUTLINE = "outline"
    ACCENT = "accent"
    DANGER = "danger"


class ActionButton(PaintedButton):
    """A full-height button: outlined ("Procurar lâmpadas novas"), accent-filled
    ("Salvar") or a destructive one ("Excluir grupo"), with an optional painted icon."""

    def __init__(
        self,
        text: str,
        style: ButtonStyle = ButtonStyle.OUTLINE,
        icon: Callable[[QPainter, QRectF, QColor], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setText(text)
        self._style = style
        self._icon = icon
        self.setFixedHeight(theme.BUTTON_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # a focus ring only from the keyboard

    def sizeHint(self) -> QSize:
        width = QFontMetrics(theme.font()).horizontalAdvance(self.text()) + 2 * BUTTON_PADDING
        return QSize(width, theme.BUTTON_HEIGHT)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = self.painter()
        if not self.isEnabled():
            painter.setOpacity(theme.DISABLED_OPACITY)
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._style is ButtonStyle.ACCENT:
            fill = theme.ACCENT.lighter(108) if self.hovered() else theme.ACCENT
            painter.setPen(QPen(fill, 1))
            painter.setBrush(fill)
            color = theme.ON_ACCENT
        else:
            painter.setPen(QPen(theme.SURFACE_BORDER, 1))
            painter.setBrush(theme.HOVER if self.hovered() else theme.WINDOW)
            color = theme.DANGER if self._style is ButtonStyle.DANGER else theme.TEXT
        if self.hasFocus():
            painter.setPen(QPen(theme.FOCUS, theme.FOCUS_WIDTH))
        painter.drawRoundedRect(frame, theme.CONTROL_RADIUS, theme.CONTROL_RADIUS)

        font = theme.font()
        text_width = QFontMetrics(font).horizontalAdvance(self.text())
        icon_width = theme.ICON + 8 if self._icon is not None else 0
        x = max((self.width() - text_width - icon_width) / 2, BUTTON_PADDING)
        if self._icon is not None:
            glyph = QRectF(x, (self.height() - theme.ICON) / 2, theme.ICON, theme.ICON)
            self._icon(painter, glyph, color)
            x += icon_width
        text = QRectF(x, 0, self.width() - x - BUTTON_PADDING, self.height())
        draw_text(painter, text, self.text(), font, color)
        painter.end()


class GroupCard(PaintedButton):
    """A group: its name, its members' names and a chevron (opens "Editar grupo")."""

    def __init__(self, group: Group, members: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group = group
        self.members = members
        self.setText(group.name)
        self.setAccessibleDescription(members)
        self.setFixedHeight(theme.CARD_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = self.painter()
        if self.hasFocus():
            inset = theme.FOCUS_WIDTH / 2
            painter.setPen(QPen(theme.FOCUS, theme.FOCUS_WIDTH))
        else:
            inset = 0.5
            painter.setPen(QPen(theme.SURFACE_BORDER, 1))
        frame = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        painter.setBrush(theme.HOVER if self.hovered() else theme.SURFACE)
        painter.drawRoundedRect(frame, theme.LIST_RADIUS, theme.LIST_RADIUS)

        pad = theme.ITEM_PADDING + 3
        chevron = QRectF(
            self.width() - pad - theme.ICON,
            (self.height() - theme.ICON) / 2,
            theme.ICON,
            theme.ICON,
        )
        paint_chevron(painter, chevron, theme.TEXT, Qt.Edge.RightEdge)
        title_font, caption_font = theme.font(bold=True), theme.font(theme.CAPTION)
        title_height = QFontMetrics(title_font).height()
        caption_height = QFontMetrics(caption_font).height()
        top = (self.height() - title_height - caption_height - 2) / 2
        width = chevron.left() - 8 - pad
        draw_text(painter, QRectF(pad, top, width, title_height), self.text(), title_font)
        line = QRectF(pad, top + title_height + 2, width, caption_height)
        draw_text(painter, line, self.members, caption_font, theme.TEXT_SECONDARY)
        painter.end()


class DeviceStatus(QWidget):
    """A device on the manage page: its status (green when reachable), name and "offline"."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = ""
        self.online: bool | None = None

    def set_device(self, name: str, online: bool | None) -> None:
        self.name, self.online = name, online
        self.setAccessibleName(strings.device_label(name, online))
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = QPointF(theme.DOT / 2, self.height() / 2)
        radius = theme.DOT / 2
        if self.online:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.DEVICE_ONLINE)
        else:
            painter.setPen(QPen(theme.DEVICE_OFF, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            radius -= 0.75
        painter.drawEllipse(centre, radius, radius)

        x = theme.DOT + 10
        font, caption = theme.font(), theme.font(theme.CAPTION)
        flag = f"{strings.SEPARATOR}{strings.OFFLINE}" if self.online is False else ""
        name_width, flag_width = (
            QFontMetrics(font).horizontalAdvance(self.name),
            QFontMetrics(caption).horizontalAdvance(flag),
        )
        name_space = min(name_width, max(self.width() - x - flag_width, 0))
        draw_text(painter, QRectF(x, 0, name_space, self.height()), self.name, font)
        if flag:
            rest = QRectF(x + name_space, 0, self.width() - x - name_space, self.height())
            draw_text(painter, rest, flag, caption, theme.TEXT_SECONDARY)
        painter.end()


class DeviceRow(QWidget):
    """A device and its rename button; renaming swaps in an inline name field."""

    rename_requested = Signal(object)  # Device
    renamed = Signal(object, str)  # Device, new name

    def __init__(self, device: Device, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.device = device
        self.setFixedHeight(theme.ITEM_HEIGHT)
        self.status = DeviceStatus()
        self.rename_button = IconButton(paint_pencil, strings.RENAME)
        shown = QWidget()
        shown_layout = QHBoxLayout(shown)
        shown_layout.setContentsMargins(theme.ITEM_PADDING, 0, theme.ITEM_PADDING - 6, 0)
        shown_layout.setSpacing(theme.SPACING)
        shown_layout.addWidget(self.status, 1)
        shown_layout.addWidget(self.rename_button)
        self.editor = NameEditor(strings.DEVICE_NAME)
        editing = QWidget()
        editing_layout = QHBoxLayout(editing)
        editing_layout.setContentsMargins(6, 0, 4, 0)
        editing_layout.addWidget(self.editor)
        self._stack = QStackedWidget()
        self._stack.addWidget(shown)
        self._stack.addWidget(editing)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self.rename_button.clicked.connect(lambda: self.rename_requested.emit(self.device))
        self.editor.accepted.connect(lambda name: self.renamed.emit(self.device, name))
        self.editor.cancelled.connect(lambda: self.stop_editing(focus=True))

    def set_device(self, name: str, online: bool | None) -> None:
        self.status.set_device(name, online)

    def editing(self) -> bool:
        return self._stack.currentIndex() == 1

    def start_editing(self) -> None:
        self._stack.setCurrentIndex(1)
        self.editor.start(self.status.name)

    def stop_editing(self, *, focus: bool = False) -> None:
        """``focus``: the field had the focus; give it to the rename button."""
        typing = self.editor.isAncestorOf(self.window().focusWidget())
        self._stack.setCurrentIndex(0)
        if focus or typing:
            self.rename_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.SURFACE)
        painter.drawRoundedRect(QRectF(self.rect()), theme.CONTROL_RADIUS, theme.CONTROL_RADIUS)
        painter.end()


class MemberRow(PaintedButton):
    """A device on the group page: a check box (member or not), its name and its other
    groups ("também em Quarto")."""

    def __init__(
        self, device: Device, name: str, others: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.device = device
        self.others = others
        self.setText(name)
        self.setCheckable(True)
        self.setAccessibleDescription(others)
        self.setFixedHeight(theme.ITEM_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = self.painter()
        painter.setPen(
            QPen(theme.FOCUS, theme.FOCUS_WIDTH) if self.hasFocus() else Qt.PenStyle.NoPen
        )
        painter.setBrush(theme.HOVER if self.hovered() else theme.SURFACE)
        inset = theme.FOCUS_WIDTH / 2 if self.hasFocus() else 0
        frame = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        painter.drawRoundedRect(frame, theme.CONTROL_RADIUS, theme.CONTROL_RADIUS)

        x = theme.ITEM_PADDING
        box = QRectF(x, (self.height() - theme.CHECKBOX) / 2, theme.CHECKBOX, theme.CHECKBOX)
        if self.isChecked():
            painter.setPen(QPen(theme.ACCENT, 1))
            painter.setBrush(theme.ACCENT)
        else:
            painter.setPen(QPen(theme.TEXT_SECONDARY, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        radius = theme.CHECKBOX_RADIUS
        painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        if self.isChecked():
            paint_check(painter, box.adjusted(2, 2, -2, -2), theme.ON_ACCENT)

        x = box.right() + theme.SPACING
        right = self.width() - theme.ITEM_PADDING
        font, caption = theme.font(), theme.font(theme.CAPTION)
        name_width, others_width = split_row(
            right - x,
            QFontMetrics(font).horizontalAdvance(self.text()),
            QFontMetrics(caption).horizontalAdvance(self.others),
        )
        draw_text(painter, QRectF(x, 0, name_width, self.height()), self.text(), font)
        others = QRectF(right - others_width, 0, others_width, self.height())
        draw_text(
            painter, others, self.others, caption, theme.TEXT_SECONDARY, Qt.AlignmentFlag.AlignRight
        )
        painter.end()


class Divider(QWidget):
    """A hairline between the groups and the devices."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), theme.SURFACE_BORDER)
        painter.end()


# --- pages -------------------------------------------------------------------------------------


class ManagePage(QWidget):
    """ "Grupos e lâmpadas": the groups, the devices and "Procurar lâmpadas novas".

    ``names`` gives the display names (device id → name) and ``save_names`` persists them,
    raising ``OSError``.
    """

    back_requested = Signal()
    edit_requested = Signal(object)  # Group, or None for a new one
    layout_changed = Signal()

    def __init__(
        self,
        service: ControlService,
        bridge: ServiceBridge,
        groups: Groups,
        reloader: DeviceReloader,
        *,
        names: Callable[[], Mapping[str, str]],
        save_names: Callable[[Mapping[str, str]], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self._groups = groups
        self._reloader = reloader
        self._names = names
        self._save_names = save_names
        self.cards: list[GroupCard] = []
        self.device_rows: dict[str, DeviceRow] = {}

        self.header = PageHeader(strings.MANAGE_TITLE)
        self.notice = Notice()
        self.notice.hide()
        self.new_group_link = LinkButton(strings.NEW_GROUP)
        self.body = ScrollBody()
        self.find_button = ActionButton(strings.FIND_DEVICES, icon=paint_refresh)
        groups_header = QHBoxLayout()
        groups_header.setContentsMargins(0, 0, 0, 0)
        groups_header.addWidget(_caption(strings.USER_GROUPS))
        groups_header.addStretch(1)
        groups_header.addWidget(self.new_group_link)
        self.body.rows.addLayout(groups_header)
        self.body.rows.addSpacing(theme.CARD_GAP)
        self._items = QVBoxLayout()  # rebuilt by reload()
        self._items.setContentsMargins(0, 0, 0, 0)
        self._items.setSpacing(0)
        self.body.rows.addLayout(self._items)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.PADDING, theme.PADDING, theme.PADDING, theme.PADDING)
        layout.setSpacing(theme.SPACING)
        layout.addWidget(self.header)
        layout.addWidget(self.notice)  # on top: the rest stays in place as the flyout grows
        layout.addWidget(self.body)
        layout.addSpacing(theme.SPACING)
        layout.addWidget(self.find_button)

        self.header.back_button.clicked.connect(self.back_requested)
        self.new_group_link.clicked.connect(lambda: self.edit_requested.emit(None))
        self.find_button.clicked.connect(lambda: reloader.start())
        self.notice.timer.timeout.connect(self._hide_notice)
        reloader.started.connect(self._sync_find)
        reloader.finished.connect(self._sync_find)
        bridge.state_changed.connect(self._sync)
        bridge.online_changed.connect(self._sync)
        self.reload()

    def reload(self) -> None:
        """Show the current groups and devices (e.g. after an edit or a reload)."""
        rows = self._items
        while (item := rows.takeAt(0)) is not None:
            if (widget := item.widget()) is not None:
                widget.hide()  # not painted again until the deferred delete
                widget.deleteLater()
        self.cards, self.device_rows = [], {}

        for group in self._groups.all():
            card = GroupCard(group, self._members_text(group))
            card.clicked.connect(lambda _=False, g=group: self.edit_requested.emit(g))
            rows.addWidget(card)
            rows.addSpacing(theme.CARD_GAP)
            self.cards.append(card)
        if not self.cards:
            rows.addWidget(_caption(strings.NO_GROUPS))
            rows.addSpacing(theme.CARD_GAP)
        hint = _caption(strings.AUTOMATIC_GROUP_HINT)
        hint.setWordWrap(True)
        hint.setContentsMargins(4, 0, 0, 0)
        rows.addWidget(hint)

        devices = self.service.devices
        for device_type in dict.fromkeys(d.type for d in devices):
            rows.addSpacing(theme.SECTION_GAP - theme.SPACING)
            rows.addWidget(Divider())
            rows.addSpacing(theme.SECTION_GAP - theme.SPACING)
            rows.addWidget(_caption(strings.noun(device_type).plural))
            rows.addSpacing(theme.CARD_GAP)
            for device in (d for d in devices if d.type == device_type):
                row = DeviceRow(device)
                row.rename_requested.connect(self._start_rename)
                row.renamed.connect(self._rename)
                rows.addWidget(row)
                rows.addSpacing(theme.ITEM_GAP)
                self.device_rows[device.id] = row
        # Show the new rows now, not on the next event loop pass: the flyout measures the
        # page right away and would leave them out.
        for item in map(rows.itemAt, range(rows.count())):
            if (widget := item.widget()) is not None:
                widget.setVisible(not self.body.content.isHidden())
        self._sync()
        self._sync_find()
        self.body.updateGeometry()
        self.layout_changed.emit()

    def offer_undo(self, group: Group, index: int) -> None:
        """Tell that ``group`` was deleted, with "Desfazer" to put it back at ``index``."""
        undo = partial(self._undo, group, index)
        self._notify(strings.group_deleted(group.name), (strings.UNDO, undo))

    def show_reload(self, result: DeviceReload | None) -> None:
        """Tell what "Procurar lâmpadas novas" found."""
        if result is None:
            self._notify(strings.SCAN_FAILED)
            return
        problem = result.devices.problem
        if problem is ImportProblem.MISSING:
            text = strings.DEVICES_MISSING
        elif problem is not None:
            text = strings.DEVICES_UNREADABLE
        elif result.scan_failed:
            text = strings.SCAN_FAILED
        else:
            devices = self.service.devices
            types = {d.type for d in devices}
            words = strings.noun(types.pop() if len(types) == 1 else None)
            text = strings.devices_reloaded(len(devices), result.updated_ips, words)
        if result.write_failed:
            text = f"{text}{strings.SEPARATOR}{strings.IPS_NOT_SAVED}"
        if result.not_imported:
            text = f"{text}. {strings.not_imported(result.not_imported)}"
        self._notify(text)

    # --- names -------------------------------------------------------------------------------

    def _name(self, device: Device) -> str:
        return self._names().get(device.id, device.name)

    def _members_text(self, group: Group) -> str:
        members = self.service.members(Target.group(group.id))
        return ", ".join(self._name(d) for d in members) or strings.EMPTY_GROUP

    def _start_rename(self, device: Device) -> None:
        for device_id, row in self.device_rows.items():
            if device_id != device.id and row.editing():
                row.stop_editing()
        self.device_rows[device.id].start_editing()

    def _rename(self, device: Device, name: str) -> None:
        """A local name only: ``devices.json`` is never touched. The wizard's name clears it."""
        names = dict(self._names())
        if name == device.name:
            names.pop(device.id, None)
        else:
            names[device.id] = name
        try:
            self._save_names(names)
        except OSError as error:
            log.error("cannot save the device names: %s", type(error).__name__)
            self._notify(strings.NAME_SAVE_FAILED)
        row = self.device_rows[device.id]
        row.stop_editing(focus=True)
        for card in self.cards:  # members show the new name too
            card.members = self._members_text(card.group)
            card.update()
        self._sync()

    # --- groups ------------------------------------------------------------------------------

    def _undo(self, group: Group, index: int) -> None:
        self._hide_notice()
        try:
            self._groups.change(lambda book: book.restore(group, index))
        except (OSError, KeyError, ValueError) as error:
            log.error("cannot restore the group: %s", type(error).__name__)
            self._notify(strings.GROUPS_SAVE_FAILED)
            return
        self.reload()

    # --- state -------------------------------------------------------------------------------

    def _sync(self, *_args: object) -> None:
        for device_id, row in self.device_rows.items():
            row.set_device(self._name(row.device), self.service.is_online(device_id))

    def _sync_find(self, *_args: object) -> None:
        running = self._reloader.running()
        self.find_button.setText(strings.FINDING_DEVICES if running else strings.FIND_DEVICES)
        self.find_button.setEnabled(not running)

    def _notify(self, text: str, action: tuple[str, Callable[[], object]] | None = None) -> None:
        self.notice.set_message(text, action)
        self.notice.show()
        self.layout_changed.emit()

    def _hide_notice(self) -> None:
        self.notice.timer.stop()
        if not self.notice.isHidden():
            self.notice.hide()
            self.layout_changed.emit()


class GroupPage(QWidget):
    """ "Editar grupo" (or "Novo grupo" when ``group`` is None): name, members, delete and
    save. Members no longer known (removed from ``devices.json``) are kept."""

    back_requested = Signal()
    saved = Signal()
    deleted = Signal(object, int)  # Group, its position (to undo)
    layout_changed = Signal()

    def __init__(
        self,
        service: ControlService,
        groups: Groups,
        group: Group | None,
        *,
        names: Mapping[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.group = group
        self._groups = groups
        self.member_rows: list[MemberRow] = []

        self.header = PageHeader(strings.EDIT_GROUP if group else strings.NEW_GROUP_TITLE)
        self.notice = Notice()
        self.notice.hide()
        self.name_field = QLineEdit(group.name if group else "")
        self.name_field.setFont(theme.font())
        self.name_field.setFixedHeight(theme.FIELD_HEIGHT)
        self.name_field.setMaxLength(MAX_NAME)
        self.name_field.setPlaceholderText(strings.GROUP_NAME)
        self.name_field.setAccessibleName(strings.GROUP_NAME)
        self.name_field.setStyleSheet(FIELD_STYLE)
        # Qt's own menu (Undo, Cut, Copy...) would be in English: no translation is loaded.
        self.name_field.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        palette = self.name_field.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText, theme.TEXT_SECONDARY)
        self.name_field.setPalette(palette)
        self.body = ScrollBody()
        self.delete_button = ActionButton(strings.DELETE_GROUP, ButtonStyle.DANGER)
        self.save_button = ActionButton(strings.SAVE, ButtonStyle.ACCENT)

        rows = self.body.rows
        rows.addWidget(_caption(strings.GROUP_NAME))
        rows.addSpacing(theme.CARD_GAP)
        rows.addWidget(self.name_field)
        members = set(group.members) if group else set()
        devices = service.devices
        for device_type in dict.fromkeys(d.type for d in devices):
            rows.addSpacing(theme.SECTION_GAP - theme.SPACING)
            rows.addWidget(_caption(strings.members_heading(strings.noun(device_type))))
            rows.addSpacing(theme.CARD_GAP)
            for device in (d for d in devices if d.type == device_type):
                others = [
                    g.name
                    for g in groups.all()
                    if device.id in g.members and (group is None or g.id != group.id)
                ]
                row = MemberRow(device, names.get(device.id, device.name), strings.also_in(others))
                row.setChecked(device.id in members)
                rows.addWidget(row)
                rows.addSpacing(theme.ITEM_GAP)
                self.member_rows.append(row)
        hint = _caption(strings.MANY_GROUPS_HINT)
        hint.setWordWrap(True)
        hint.setContentsMargins(4, theme.ITEM_GAP, 0, 0)
        rows.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.BUTTON_GAP)
        buttons.addWidget(self.delete_button)  # its own width; "Salvar" takes the rest
        buttons.addWidget(self.save_button, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.PADDING, theme.PADDING, theme.PADDING, theme.PADDING)
        layout.setSpacing(theme.SPACING)
        layout.addWidget(self.header)
        layout.addWidget(self.notice)
        layout.addWidget(self.body)
        layout.addSpacing(theme.SPACING)
        layout.addLayout(buttons)
        # Only now: shown before it has a parent, it would open as a window of its own.
        self.delete_button.setHidden(group is None)

        self.header.back_button.clicked.connect(self.back_requested)
        self.name_field.textChanged.connect(self._sync)
        self.name_field.returnPressed.connect(self.save)
        self.save_button.clicked.connect(self.save)
        self.delete_button.clicked.connect(self.delete)
        self.notice.timer.timeout.connect(self._hide_notice)
        self._sync()

    def members(self) -> list[str]:
        """The checked devices; the group's own order first, then the newly checked ones,
        and the members no longer known kept."""
        checked = [row.device.id for row in self.member_rows if row.isChecked()]
        known = {row.device.id for row in self.member_rows}
        original = self.group.members if self.group else ()
        kept = [m for m in original if m in checked or m not in known]
        return [*kept, *(m for m in checked if m not in kept)]

    def save(self) -> None:
        name = self.name_field.text().strip()
        if not name:
            return
        members = self.members()
        group = self.group

        def change(book: GroupBook) -> None:
            if group is None:
                book.create(name, members)
            else:
                book.rename(group.id, name)
                book.set_members(group.id, members)

        if self._change(change):
            self.saved.emit()

    def delete(self) -> None:
        group = self.group
        if group is None:
            return
        ids = [g.id for g in self._groups.all()]
        index = ids.index(group.id) if group.id in ids else len(ids)
        if self._change(lambda book: book.delete(group.id)):
            self.deleted.emit(group, index)

    def _change(self, change: Callable[[GroupBook], object]) -> bool:
        try:
            self._groups.change(change)
        except (OSError, KeyError, ValueError) as error:
            log.error("cannot save the groups: %s", type(error).__name__)
            self.notice.set_message(strings.GROUPS_SAVE_FAILED, None)
            self.notice.show()
            self.layout_changed.emit()
            return False
        return True

    def _sync(self) -> None:
        self.save_button.setEnabled(bool(self.name_field.text().strip()))

    def _hide_notice(self) -> None:
        self.notice.timer.stop()
        if not self.notice.isHidden():
            self.notice.hide()
            self.layout_changed.emit()


def _caption(text: str) -> QLabel:
    return label(text, theme.font(theme.CAPTION), theme.TEXT_SECONDARY)


_SCROLL_STYLE = f"""
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 6px; margin: 4px 0; }}
QScrollBar::handle:vertical {{ background: {theme.DEVICE_OFF.name()}; border-radius: 2px;
    min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
"""
