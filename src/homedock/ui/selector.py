"""Target selector widgets: the current target button, the target list and the power button.

They only show what :mod:`homedock.ui.target_model` describes and emit what the user picks;
the flyout's main page talks to the control service.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from homedock.core import Target, TargetKind
from homedock.ui import strings, theme
from homedock.ui.icons import paint_chevron, paint_gear, paint_power
from homedock.ui.target_model import TargetEntry, TargetModel
from homedock.ui.widgets import PaintedButton, draw_text, label

TEXT_GAP = 12  # minimum gap between a row's title and its detail


class TargetButton(PaintedButton):
    """The selected target (title and subtitle); checked while the target list is open."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedHeight(theme.HEADER_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(strings.CHOOSE_TARGET)
        self._subtitle = ""

    def set_target(self, title: str, subtitle: str) -> None:
        self.setText(title)
        self._subtitle = subtitle
        self.setAccessibleDescription(subtitle)
        self.update()

    def subtitle(self) -> str:
        return self._subtitle

    def sizeHint(self) -> QSize:
        return QSize(200, theme.HEADER_HEIGHT)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = self.painter()
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(theme.ACCENT if self.isChecked() else theme.SURFACE_BORDER, 1))
        painter.setBrush(theme.HOVER if self.hovered() else theme.SURFACE)
        painter.drawRoundedRect(frame, theme.CONTROL_RADIUS, theme.CONTROL_RADIUS)

        pad = theme.SPACING
        icon_top = (self.height() - theme.ICON) / 2
        chevron = QRectF(self.width() - pad - theme.ICON, icon_top, theme.ICON, theme.ICON)
        direction = Qt.Edge.TopEdge if self.isChecked() else Qt.Edge.BottomEdge
        paint_chevron(painter, chevron, theme.TEXT, direction)

        title_font, caption_font = theme.font(bold=True), theme.font(theme.CAPTION)
        title_height = QFontMetrics(title_font).height()
        caption_height = QFontMetrics(caption_font).height() if self._subtitle else 0
        top = (self.height() - title_height - caption_height) / 2
        width = chevron.left() - 8 - pad
        draw_text(painter, QRectF(pad, top, width, title_height), self.text(), title_font)
        if self._subtitle:
            line = QRectF(pad, top + title_height, width, caption_height)
            draw_text(painter, line, self._subtitle, caption_font, theme.TEXT_SECONDARY)
        painter.end()


class PowerButton(PaintedButton):
    """Round power button; checked (accent) while the target is on."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(theme.HEADER_HEIGHT, theme.HEADER_HEIGHT)
        self.setAccessibleName(strings.POWER)
        self.setToolTip(strings.POWER)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = self.painter()
        circle = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if not self.isEnabled():
            fill, border, icon = theme.SURFACE, theme.SURFACE_BORDER, theme.DEVICE_OFF
        elif self.isChecked():
            fill, border, icon = theme.ACCENT, theme.ACCENT, theme.ON_ACCENT
            if self.hovered():
                fill = border = theme.ACCENT.lighter(108)
        else:
            fill, border, icon = theme.SURFACE, theme.SURFACE_BORDER, theme.TEXT
            if self.hovered():
                fill = theme.SELECTED
        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawEllipse(circle)
        glyph = QRectF(0, 0, theme.ICON, theme.ICON)
        glyph.moveCenter(circle.center())
        paint_power(painter, glyph, icon)
        painter.end()


class TargetRow(PaintedButton):
    """One target in the list: groups show their members, devices a dot (on/off) and their
    groups. The selected row has a highlight and an accent bar."""

    def __init__(self, entry: TargetEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(theme.ROW_HEIGHT)
        self._selected = False
        self.set_entry(entry)

    @property
    def entry(self) -> TargetEntry:
        return self._entry

    def set_entry(self, entry: TargetEntry) -> None:
        self._entry = entry
        self.setText(entry.title)
        self.setAccessibleDescription(entry.detail)
        self.update()

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = self.painter()
        if self._selected or self.hovered():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.SELECTED if self._selected else theme.HOVER)
            painter.drawRoundedRect(QRectF(self.rect()), theme.ROW_RADIUS, theme.ROW_RADIUS)

        x = theme.ROW_PADDING
        middle = self.height() / 2
        if self._selected:
            bar_width, bar_height = theme.SELECTION_BAR
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.ACCENT)
            bar = QRectF(x, middle - bar_height / 2, bar_width, bar_height)
            painter.drawRoundedRect(bar, bar_width / 2, bar_width / 2)
            x += bar_width + 8
        entry = self._entry
        title_color = theme.TEXT
        if entry.target.kind == TargetKind.DEVICE:
            _draw_dot(painter, QPointF(x + theme.DOT / 2, middle), entry.on)
            x += theme.DOT + 10
            if entry.online is False:
                title_color = theme.TEXT_SECONDARY

        right = self.width() - theme.ROW_PADDING
        title_font, detail_font = theme.font(), theme.font(theme.CAPTION)
        title_width, detail_width = split_row(
            right - x,
            QFontMetrics(title_font).horizontalAdvance(entry.title),
            QFontMetrics(detail_font).horizontalAdvance(entry.detail),
        )
        title = QRectF(x, 0, title_width, self.height())
        draw_text(painter, title, entry.title, title_font, title_color)
        detail = QRectF(right - detail_width, 0, detail_width, self.height())
        draw_text(
            painter,
            detail,
            entry.detail,
            detail_font,
            theme.TEXT_SECONDARY,
            Qt.AlignmentFlag.AlignRight,
        )
        painter.end()


class ManageLink(PaintedButton):
    """ "Gerenciar grupos e lâmpadas": a cog and an accent-coloured link."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(strings.MANAGE)
        self.setFixedHeight(theme.ROW_HEIGHT)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = self.painter()
        self.paint_hover(painter)
        x = theme.ROW_PADDING
        icon = QRectF(x, (self.height() - theme.ICON) / 2, theme.ICON, theme.ICON)
        paint_gear(painter, icon, theme.ACCENT)
        text = QRectF(icon.right() + 8, 0, self.width() - icon.right() - 8 - x, self.height())
        draw_text(painter, text, self.text(), theme.font(), theme.ACCENT)
        painter.end()


class TargetList(QFrame):
    """Every target, by section, plus the link to manage groups and devices."""

    chosen = Signal(object)  # Target
    manage_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: dict[Target, TargetRow] = {}
        self._shape: list[tuple[str, list[Target]]] = []
        self._max_height = theme.LIST_MAX_HEIGHT

        self._content = QWidget()
        self._rows = QVBoxLayout(self._content)
        self._rows.setContentsMargins(theme.ROW_INSET, 9, theme.ROW_INSET, 2)
        self._rows.setSpacing(theme.ROW_GAP)
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._content)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(_SCROLL_STYLE)
        self._scroll.viewport().setAutoFillBackground(False)
        self._content.setAutoFillBackground(False)

        self.manage_link = ManageLink()
        self.manage_link.clicked.connect(self.manage_requested)
        footer = QVBoxLayout()
        footer.setContentsMargins(theme.ROW_INSET, 0, theme.ROW_INSET, 3)
        footer.setSpacing(0)
        footer.addWidget(_Divider())
        footer.addWidget(self.manage_link)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)  # inside the border
        layout.setSpacing(0)
        layout.addWidget(self._scroll)
        layout.addLayout(footer)

    def set_model(self, model: TargetModel, selected: Target | None) -> None:
        shape = [(s.title, [e.target for e in s.entries]) for s in model.sections]
        if shape == self._shape:
            for entry in model.entries():
                self.rows[entry.target].set_entry(entry)
        else:
            self._rebuild(model)
            self._shape = shape
        for target, row in self.rows.items():
            row.set_selected(target == selected)

    def _rebuild(self, model: TargetModel) -> None:
        while (item := self._rows.takeAt(0)) is not None:
            if (widget := item.widget()) is not None:
                widget.hide()  # not painted again until the deferred delete
                widget.deleteLater()
        self.rows = {}
        for index, section in enumerate(model.sections):
            if index:
                self._rows.addWidget(_Divider())
            self._rows.addWidget(_section_label(section.title))
            for entry in section.entries:
                row = TargetRow(entry)
                row.clicked.connect(lambda _=False, t=entry.target: self.chosen.emit(t))
                self._rows.addWidget(row)
                self.rows[entry.target] = row
        self._rows.activate()
        self._fit_scroll()

    def set_max_height(self, height: int) -> None:
        """Keep the whole list (border and footer included) within ``height``; the rows
        scroll beyond it."""
        self._max_height = height
        self._fit_scroll()

    def _fit_scroll(self) -> None:
        content = self._content.sizeHint().height()
        footer = theme.ROW_HEIGHT + _Divider.HEIGHT + 3 + 2  # link, divider, margins, border
        self._scroll.setFixedHeight(max(min(content, self._max_height - footer), theme.ROW_HEIGHT))

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(theme.SURFACE_BORDER, 1))
        painter.setBrush(theme.SURFACE)
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(frame, theme.LIST_RADIUS, theme.LIST_RADIUS)
        painter.end()


def _section_label(text: str) -> QLabel:
    result = label(text, theme.font(theme.CAPTION), theme.TEXT_SECONDARY)
    result.setFixedHeight(26)
    result.setContentsMargins(theme.ROW_PADDING, 0, 0, 0)
    return result


class _Divider(QWidget):
    """A hairline between sections, with some air around it."""

    HEIGHT = 15

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(self.HEIGHT)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setPen(QPen(theme.SURFACE_BORDER, 1))
        y = self.height() // 2
        painter.drawLine(4, y, self.width() - 5, y)
        painter.end()


def _draw_dot(painter: QPainter, centre: QPointF, on: bool) -> None:
    radius = theme.DOT / 2
    if on:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.DEVICE_ON)
    else:
        painter.setPen(QPen(theme.DEVICE_OFF, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        radius -= 0.75
    painter.drawEllipse(centre, radius, radius)


def split_row(space: float, title: int, detail: int) -> tuple[float, float]:
    """Share a row between title and detail: both whole if they fit, else the title keeps
    at least half the row and the detail is elided first."""
    if title + TEXT_GAP + detail <= space:
        return title, detail
    title_space = min(title, max(space - TEXT_GAP - detail, space / 2))
    return title_space, max(space - TEXT_GAP - title_space, 0)


_SCROLL_STYLE = f"""
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 6px; margin: 4px 1px; }}
QScrollBar::handle:vertical {{ background: {theme.DEVICE_OFF.name()}; border-radius: 2px;
    min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
"""
