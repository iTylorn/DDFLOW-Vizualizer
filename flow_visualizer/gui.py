"""Interactive desktop editor for a DD FLOW diagram.

The project model is intentionally separate from the scene.  A scene is rebuilt
from the model, so all edits (including node positions) survive a save/open.
"""
from __future__ import annotations

import math
import os
import sys
from html import escape
from copy import copy, deepcopy
from dataclasses import asdict, replace
from collections import defaultdict

# Frozen Windows applications must make both Qt and Shiboken DLL directories
# visible to the Windows loader before importing the extension modules.
_dll_directories = []
if getattr(sys, 'frozen', False) and sys.platform == 'win32':
    for _subdir in ('PySide6', 'shiboken6'):
        _directory = os.path.join(sys._MEIPASS, _subdir)
        if os.path.isdir(_directory):
            _dll_directories.append(os.add_dll_directory(_directory))
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QSignalBlocker, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QKeySequence, QShortcut,
                           QPen, QPolygonF, QTextDocument, QTextOption,
                           QAbstractTextDocumentLayout, QPalette, QFontMetricsF)
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QGraphicsItem,
    QGraphicsObject, QGraphicsPathItem, QGraphicsPolygonItem, QGraphicsScene, QGraphicsTextItem,
    QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit,
    QColorDialog, QInputDialog, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

try:
    from . import model, exchange
    from .group_graph import draw_group_frames, group_title_height
    from .legend import draw_legend
    from .symbols import warehouse_badge_html, draw_buffer, draw_algorithm, algorithm_kind, is_retired_algorithm, frame_pen, layout_label, ALGORITHMS, LAYOUTS, LEGACY_LAYOUT, LEGACY_LAYOUT_LABEL, UNKNOWN_LAYOUT, UNKNOWN_LAYOUT_LABEL
    from .alignment_snap import snap_to_alignment, constrain_movement
    from .shift_push import push_in_direction
    from .auto_layout import arrange_stages
    from .gentle_layout import compact_existing
    from .group_alignment import align_group_columns
    from .selection_alignment import align_selection, ROUTE_PORT_OFFSET, STANDARD_HORIZONTAL_GAP
    from .view_projection import project_positions, overlaps as view_overlaps
    from .colors import (compact_color_for_type, compact_color_for_stage, DEFAULT_COLORS, DEFICIT_COLOR,
                         paint_stage_fill, supports_deficit_color)
    from .edge_editor import EditableEdgeItem
    from .annotation_layer import AnnotationItem, LABELS as ANNOTATION_LABELS, edit_annotation, read_picture
    from .number_field import number_field
except ImportError:
    import model
    import exchange
    from group_graph import draw_group_frames, group_title_height
    from legend import draw_legend
    from symbols import warehouse_badge_html, draw_buffer, draw_algorithm, algorithm_kind, is_retired_algorithm, frame_pen, layout_label, ALGORITHMS, LAYOUTS, LEGACY_LAYOUT, LEGACY_LAYOUT_LABEL, UNKNOWN_LAYOUT, UNKNOWN_LAYOUT_LABEL
    from alignment_snap import snap_to_alignment, constrain_movement
    from shift_push import push_in_direction
    from auto_layout import arrange_stages
    from gentle_layout import compact_existing
    from group_alignment import align_group_columns
    from selection_alignment import align_selection, ROUTE_PORT_OFFSET, STANDARD_HORIZONTAL_GAP
    from view_projection import project_positions, overlaps as view_overlaps
    from colors import (compact_color_for_type, compact_color_for_stage, DEFAULT_COLORS, DEFICIT_COLOR,
                        paint_stage_fill, supports_deficit_color)
    from edge_editor import EditableEdgeItem
    from annotation_layer import AnnotationItem, LABELS as ANNOTATION_LABELS, edit_annotation, read_picture
    from number_field import number_field


COLORS = {"производ": "#3e83b4", "покуп": "#e6a04a", "логист": "#d35d55",
          "услуг": "#7caace", "сбор": "#8a78b1", "разбор": "#8a78b1"}


def group_label(group):
    """Distinguish imported departments with equal names by their 1C code."""
    name = group.name or 'Без названия'
    code = getattr(group, 'code', '')
    return f'{name} [{code}]' if code else name


def color_for(provider):
    key = (provider or "").lower()
    return QColor(next((v for k, v in COLORS.items() if k in key), "#70818e"))


def contrast_text_color(background):
    color = QColor(background)
    def linear(value):
        value /= 255.0
        return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
    luminance = .2126 * linear(color.red()) + .7152 * linear(color.green()) + .0722 * linear(color.blue())
    return QColor('black' if luminance >= .179 else 'white')


def warehouse_lines(links, warehouses, rich=False):
    if not links:
        return "—"
    lines = []
    # Stable sort keeps 1C's row order while showing all primary entries first.
    for link in sorted(links, key=lambda link: not link.primary):
        parameter = str(link.extra.get("parameter_name") or "").strip()
        warehouse = warehouses.get(link.warehouse_id)
        if link.warehouse_id:
            name = warehouse.name if warehouse else "Не найден: " + link.warehouse_id
            if parameter:
                name += " — " + parameter
        else:
            name = "Склад по параметру: " + parameter if parameter else "Склад не указан"
        prefix = "★ " if link.primary else "• "
        suffix = " (" + link.department_name + ")" if link.department_name else ""
        if rich:
            badge = warehouse_badge_html(warehouse.warehouse_type if warehouse else '')
            lines.append(escape(prefix) + badge + ' ' + escape(name + suffix))
        else:
            lines.append(prefix + name + suffix)
    return ('<br>' if rich else '\n').join(lines)


class StageItem(QGraphicsObject):
    """Movable card with text measured by Qt rather than character counts."""
    WIDTH = 260.0

    def __init__(self, stage, names, changed, compact=False, snap=None, snap_finished=None,
                 card_width=230, card_height=74, palette=None):
        super().__init__()
        self.stage, self.names, self.changed = stage, names, changed
        self._snap, self._snap_finished = snap, snap_finished
        self._drag_active = False
        self._drag_modifiers = Qt.NoModifier
        self.compact = compact
        self.palette = palette or {}
        self.width = float(card_width) if compact else self.WIDTH
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setCursor(Qt.OpenHandCursor)
        self.setZValue(10)
        self.title_x = 12.0 if compact else (59.0 if stage.has_buffer else 12.0)
        if compact:
            # A whole word must never be broken. Very long single words can
            # widen the card after reaching the smallest readable font.
            text = stage.name or 'Новый передел'
            # Grow the card for long words so they can be read at a useful
            # minimum size, rather than squeezing the entire title to 6–10 pt.
            min_font = QFont('Segoe UI', 15)
            min_font.setBold(True)
            self.width = max(self.width, max((QFontMetricsF(min_font).horizontalAdvance(word)
                                               for word in text.split()), default=0) + 24)
            self.title = self._document(text, 15, True, self.width - 24)
            # Reserve room for two lines when the title contains words. This
            # lets the fitter choose wrapping instead of reducing the font to
            # keep an entire phrase on one line.
            two_lines = 2 * QFontMetricsF(min_font).lineSpacing() if len(text.split()) > 1 else 0
            available = max(16.0, float(card_height) - 24,
                            self.title.size().height(), two_lines)
            low, high = 16, 72
            while low <= high:
                size = (low + high) // 2
                trial = self._document(text, size, True, self.width - 24)
                font = QFont('Segoe UI', size)
                font.setBold(True)
                max_word = max((QFontMetricsF(font).horizontalAdvance(word) for word in text.split()), default=0)
                if trial.size().height() > available + 0.01 or max_word > self.width - 24:
                    high = size - 1
                else:
                    self.title = trial
                    low = size + 1
            option = self.title.defaultTextOption()
            option.setAlignment(Qt.AlignHCenter)
            self.title.setDefaultTextOption(option)
            self.height = max(float(card_height), self.title.size().height() + 24)
            if stage.rkt_algorithm:
                # Keep the text document and fitted font unchanged; the icon
                # gets its own space to the right of the existing title area.
                self.width += self.height * .70 + 16
            self.header_height = self.height
            self.body = None
            return
        title_font = QFont('Segoe UI', 11)
        title_font.setBold(True)
        longest = max((QFontMetricsF(title_font).horizontalAdvance(word)
                       for word in (stage.name or '').split()), default=0)
        self.rkt_tag_width = 31.0 if stage.rkt_algorithm else 0.0
        self.width = max(self.width, longest + self.title_x + 12)
        body_text = ' '.join((stage.provider_type or '', stage.rkt_algorithm or '',
                              warehouse_lines(stage.inlets, names), warehouse_lines(stage.stocks, names)))
        body_metrics = QFontMetricsF(QFont('Segoe UI', 10))
        self.width = max(self.width, max((body_metrics.horizontalAdvance(word)
                                          for word in body_text.split()), default=0) + 24)
        self.title = self._document(stage.name or "Новый передел", 11, True,
                                    self.width - self.title_x - 12)
        self.body_width = self.width - 24
        self.body = self._document(self._body(), 10, False, self.body_width, rich=True)
        self.header_height = max(47.0, self.title.size().height() + 22, 68.0 if stage.has_buffer else 0)
        if stage.rkt_algorithm:
            # Reserve space beside the heading without changing its wrapping.
            self.width += self.rkt_tag_width
            self.body_width = self.width - 24
            self.body.setTextWidth(self.body_width)
        self.height = self.header_height + self.body.size().height() + 21
        self.section_dividers = []
        block = self.body.begin()
        while block.isValid():
            if not block.text() and block.previous().isValid() and block.next().isValid():
                self.section_dividers.append(self.body.documentLayout().blockBoundingRect(block).center().y())
            block = block.next()

    @staticmethod
    def _document(text, size, bold, width, rich=False):
        doc = QTextDocument()
        font = QFont("Segoe UI", size)
        font.setBold(bold)
        doc.setDefaultFont(font)
        doc.setDocumentMargin(0)
        option = doc.defaultTextOption()
        option.setWrapMode(QTextOption.WordWrap)
        doc.setDefaultTextOption(option)
        if rich:
            doc.setHtml(text)
        else:
            doc.setPlainText(text)
        doc.setTextWidth(width)
        return doc

    def _body(self):
        flag = "Алгоритм РКТ: " + self.stage.rkt_algorithm if self.stage.rkt_algorithm else "Обычный передел"
        return ("<b>Настройки передела</b><br>Тип: " + escape(self.stage.provider_type or "не указан")
                + "<br>" + escape(flag)
                + "<br>Макет запуска: " + escape(layout_label(self.stage.launch_layout))
                + ("<br>Запуск с дефицитом" if self.stage.deficit_launch else "")
                + "<hr><b>Входные стеллажи</b><br>" + warehouse_lines(self.stage.inlets, self.names, rich=True)
                + "<hr><b>Склады остатков в работе</b><br>" + warehouse_lines(self.stage.stocks, self.names, rich=True))

    def boundingRect(self):
        top = -43.0 if self.compact and self.stage.has_buffer else -2.0
        return QRectF(-2, top, self.width + 4, self.height - top + 2)

    def algorithm_rect(self):
        if not self.stage.rkt_algorithm:
            return QRectF()
        size = self.height * .70 if self.compact else min(31.0, self.header_height - 16.0)
        return QRectF(self.width - size - 8, (self.header_height - size) / 2, size, size)

    def connection_rect(self):
        """The visible card border, excluding selection padding and buffer icon."""
        return self.mapRectToScene(QRectF(0, 0, self.width, self.height))

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0, 0, self.width, self.height)
        if not self.compact:
            painter.fillRect(rect, QColor('#ffffff'))
        header = QRectF(0, 0, self.width, self.header_height)
        header_color = compact_color_for_stage(self.stage, self.palette)
        striped = self.stage.deficit_launch and supports_deficit_color(self.stage.provider_type)
        stripe = paint_stage_fill(painter, header, header_color, striped)
        self._draw_title(painter, header, header_color, stripe)
        painter.save()
        painter.setBrush(Qt.NoBrush)
        painter.setPen(frame_pen(self.stage.launch_layout, self.isSelected()))
        painter.drawRect(rect.adjusted(2, 2, -2, -2))
        painter.restore()
        if self.stage.has_buffer:
            draw_buffer(painter, QRectF(12, -41, 36, 39) if self.compact else QRectF(12, 7, 36, 54))
        if self.stage.rkt_algorithm:
            draw_algorithm(painter, self.algorithm_rect(), algorithm_kind(self.stage.rkt_algorithm))
        if self.compact:
            return
        painter.save()
        painter.translate(12, self.header_height + 10)
        body_context = QAbstractTextDocumentLayout.PaintContext()
        body_context.palette.setColor(QPalette.Text, QColor('#263744'))
        self.body.documentLayout().draw(painter, body_context)
        painter.setPen(QPen(QColor('#9babb6'), 1.0))
        for y in self.section_dividers:
            painter.drawLine(QPointF(0, y), QPointF(self.body_width, y))
        painter.restore()

    def _draw_title(self, painter, header, color, stripe):
        title_y = (self.height - self.title.size().height()) / 2 if self.compact else 10
        foreground = contrast_text_color(color)
        stripe_foreground = contrast_text_color(DEFICIT_COLOR)

        def draw(text_color, clip):
            painter.save()
            painter.setClipRect(clip, Qt.IntersectClip)
            painter.translate(self.title_x, title_y)
            context = QAbstractTextDocumentLayout.PaintContext()
            context.palette.setColor(QPalette.Text, text_color)
            self.title.documentLayout().draw(painter, context)
            painter.restore()

        if stripe.isEmpty() or foreground == stripe_foreground:
            draw(foreground, header)
        else:
            draw(stripe_foreground, stripe)
            main = QRectF(header)
            main.setLeft(stripe.right())
            draw(foreground, main)

    def itemChange(self, change, value):
        if (change == QGraphicsItem.ItemPositionChange and self._drag_active
                and self._snap is not None and self.scene() is not None):
            return self._snap(self, QPointF(value), self._drag_modifiers)
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene() is not None:
            self.stage.x, self.stage.y = float(value.x()), float(value.y())
            self.changed()
        return super().itemChange(change, value)

    def mouseMoveEvent(self, event):
        # Moving one card must never implicitly move other selected cards.
        selected = self.scene().selectedItems() if self.scene() else [self]
        for item in selected:
            if item is not self and isinstance(item, (StageItem, AnnotationItem)) and event.buttons() & Qt.LeftButton:
                item.setSelected(False)
        self._drag_active = bool(event.buttons() & Qt.LeftButton)
        self._drag_modifiers = event.modifiers()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        for item in self.scene().selectedItems() if self.scene() else [self]:
            if isinstance(item, StageItem):
                item._drag_active = False
                item._drag_modifiers = Qt.NoModifier
        self._drag_active = False
        self._drag_modifiers = Qt.NoModifier
        if self._snap_finished is not None:
            self._snap_finished()


class DiagramTitle(QGraphicsTextItem):
    activated = Signal()

    def __init__(self, name, size, style, maximum_width):
        super().__init__(name)
        self.appearance = style
        font = QFont(style.font_family, size)
        font.setBold(style.bold)
        font.setItalic(style.italic)
        self.setFont(font)
        self.setDefaultTextColor(QColor(style.text_color))
        self.document().setDocumentMargin(8 if style.fill or style.stroke_width else 0)
        option = self.document().defaultTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        option.setAlignment({'left': Qt.AlignLeft, 'center': Qt.AlignHCenter, 'right': Qt.AlignRight}[style.alignment])
        self.document().setDefaultTextOption(option)
        self.setTextWidth(min(maximum_width, math.ceil(self.document().idealWidth()) + 1))
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Щёлкните, чтобы изменить название и оформление')

    def paint(self, painter, option, widget=None):
        painter.save()
        style = self.appearance
        bounds = self.boundingRect()
        if style.fill:
            painter.fillRect(bounds, QColor(style.fill))
        if style.stroke_width and style.stroke:
            # Keep the full border inside the measured title rectangle.
            width = min(style.stroke_width, bounds.width() / 2, bounds.height() / 2)
            pen = QPen(QColor(style.stroke), width, Qt.DashLine if style.dashed else Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            inset = width / 2
            painter.drawRect(bounds.adjusted(inset, inset, -inset, -inset))
        painter.restore()
        super().paint(painter, option, widget)

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        if (self.contains(event.pos()) and
                (event.screenPos() - event.buttonDownScreenPos(Qt.LeftButton)).manhattanLength()
                < QApplication.startDragDistance()):
            self.activated.emit()
        event.accept()


class DiagramView(QGraphicsView):
    link_stage_clicked = Signal(str)
    link_cancel_requested = Signal()

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#f3f6f8"))
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self._pan = None
        self.link_mode = False
        self.alignment_guides = []

    def set_alignment_guides(self, guides):
        self.alignment_guides = list(guides)
        self.viewport().update()

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if not self.alignment_guides:
            return
        painter.save()
        pen = QPen(QColor('#e17a2d'), 1, Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLines(self.alignment_guides)
        painter.restore()

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        if 0.12 <= self.transform().m11() * factor <= 4.0:
            self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._pan = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if self.link_mode and event.button() == Qt.LeftButton:
            item = next((item for item in self.items(event.position().toPoint())
                         if isinstance(item, StageItem)), None)
            if item is not None:
                self.link_stage_clicked.emit(item.stage.id)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if self.link_mode and event.key() == Qt.Key_Escape:
            self.link_cancel_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan is not None:
            now = event.position().toPoint()
            diff = now - self._pan
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - diff.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - diff.y())
            self._pan = now
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._pan is not None:
            self._pan = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)


def _segment_hits(a, b, rect):
    """Axis-aligned route segment intersects an expanded obstacle interior."""
    if abs(a.y() - b.y()) < .01:
        return rect.top() < a.y() < rect.bottom() and max(a.x(), b.x()) > rect.left() and min(a.x(), b.x()) < rect.right()
    return rect.left() < a.x() < rect.right() and max(a.y(), b.y()) > rect.top() and min(a.y(), b.y()) < rect.bottom()


def route_points(source, target, obstacle_rects):
    # Choose a clear horizontal lane; if none exists, choose the least obstructed.
    sr, tr = source.connection_rect(), target.connection_rect()
    forward = sr.center().x() <= tr.center().x()
    a = QPointF(sr.right() if forward else sr.left(), sr.center().y())
    b = QPointF(tr.left() if forward else tr.right(), tr.center().y())
    direction = 1 if forward else -1
    clearance = direction * (b.x() - a.x())
    outset = min(ROUTE_PORT_OFFSET, clearance / 3) if clearance > 0 else ROUTE_PORT_OFFSET
    a1, b1 = QPointF(a.x() + outset * direction, a.y()), QPointF(b.x() - outset * direction, b.y())
    ys = [a.y(), b.y(), (a.y()+b.y())/2]
    ys += [r.top() - 18 for r in obstacle_rects] + [r.bottom() + 18 for r in obstacle_rects]
    candidates = [[a, a1, QPointF(a1.x(), y), QPointF(b1.x(), y), b1, b] for y in ys]
    def score(points):
        collisions = sum(_segment_hits(p, q, rect) for p, q in zip(points, points[1:]) for rect in obstacle_rects)
        length = sum(abs(p.x()-q.x()) + abs(p.y()-q.y()) for p, q in zip(points, points[1:]))
        return collisions, length
    return min(candidates, key=score)


class WarehouseEditor(QTableWidget):
    def __init__(self):
        super().__init__(0, 2)
        self.setHorizontalHeaderLabels(["Склад", "Основной"])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self._existing = {}

    def load(self, warehouses, links):
        self._existing = defaultdict(list)
        for link in links:
            self._existing[link.warehouse_id].append(link)
        known = {warehouse.id for warehouse in warehouses}
        missing = [model.Warehouse(id=ident, name=("Не найден: " + ident if ident else "Условные стеллажи / склад не указан"))
                   for ident in self._existing if ident not in known]
        all_warehouses = warehouses + missing
        self.setRowCount(len(all_warehouses))
        for row, wh in enumerate(sorted(all_warehouses,
                key=lambda v: (not any(link.primary for link in self._existing.get(v.id, [])),
                               v.name.casefold(), v.code))):
            current = self._existing.get(wh.id)
            item = QTableWidgetItem(wh.name + (f" [{wh.code}]" if wh.code else ""))
            item.setData(Qt.UserRole, wh.id)
            item.setData(Qt.UserRole + 1, item.text())
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if current else Qt.Unchecked)
            self.setItem(row, 0, item)
            primary = QTableWidgetItem("")
            primary.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            primary.setCheckState(Qt.Checked if current and any(link.primary for link in current) else Qt.Unchecked)
            self.setItem(row, 1, primary)

    def links(self):
        if sum(1 for row in range(self.rowCount()) if self.item(row, 1).checkState() == Qt.Checked) > 1:
            raise ValueError("В каждой группе можно выбрать только один основной склад.")
        result = []
        for row in range(self.rowCount()):
            cell, main = self.item(row, 0), self.item(row, 1)
            selected = cell.checkState() == Qt.Checked
            is_main = main.checkState() == Qt.Checked
            if is_main and not selected:
                raise ValueError("Основной склад должен быть отмечен в списке складов.")
            if selected:
                key = cell.data(Qt.UserRole)
                entries = deepcopy(self._existing.get(key)) or [model.WarehouseLink(warehouse_id=key)]
                primary_index = next((i for i, entry in enumerate(entries) if entry.primary), 0)
                for index, entry in enumerate(entries):
                    entry.primary = is_main and index == primary_index
                    result.append(entry)
        return result

    def set_unavailable(self, ids, reason, location):
        """Keep imported conflicting selections editable so users can repair them."""
        with QSignalBlocker(self):
            for row in range(self.rowCount()):
                item, primary = self.item(row, 0), self.item(row, 1)
                conflict = bool(item.data(Qt.UserRole)) and item.data(Qt.UserRole) in ids
                blocked = conflict and item.checkState() != Qt.Checked
                original = item.data(Qt.UserRole + 1)
                item.setText(('Недоступен: ' + original + ' (' + location + ')') if blocked else
                             (original + ' (выбран в обоих списках)' if conflict else original))
                for cell in (item, primary):
                    cell.setFlags((Qt.ItemIsUserCheckable if blocked else Qt.ItemIsEnabled | Qt.ItemIsUserCheckable))
                    cell.setToolTip(reason if conflict else '')
                    cell.setForeground(QBrush(QColor('#808a91' if blocked else '#263744')))
                    cell.setBackground(QBrush(QColor('#e1e5e8' if blocked else '#fff3d6' if conflict else '#ffffff')))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project = model.Project()
        self.path = None
        self.dirty = False
        self.loading = False
        self.nodes = {}
        self.edge_items = []
        self.flow_items = []
        self.level_items = []
        self.group_items = []
        self.legend_items = []
        self.title_items = []
        self.annotation_items = {}
        self._stage_drag_changed = False
        self._auto_align_timer = QTimer(self, singleShot=True, interval=250)
        self._auto_align_timer.timeout.connect(self.auto_layout)
        self._active_view = 'compact'
        self._view_bridge = None
        self.selected_id = None
        self.selected_kind = None
        self.selected_ref = None
        self.tree_loading = False
        self.link_source = None
        self.setWindowTitle("Визуализатор потока")
        self.resize(1450, 850)
        self.scene = QGraphicsScene(self)
        self.view = DiagramView(self.scene)
        self.view.link_stage_clicked.connect(self.link_stage_clicked)
        self.view.link_cancel_requested.connect(self.cancel_link_creation)
        self.scene.selectionChanged.connect(self.selection_changed)
        self._create_ui()
        self.render_scene()

    def _create_ui(self):
        self.setStyleSheet("""
          QMainWindow, QWidget { font-family: 'Segoe UI'; font-size: 10pt; }
          QPushButton { padding: 5px 9px; }
          QLineEdit, QComboBox, QSpinBox { padding: 4px; }
          QTableWidget { background: white; color: #263744; gridline-color: #e3e9ed; }
        """)
        toolbar = self.addToolBar("Действия")
        toolbar.setMovable(False)
        for title, handler in [("Выгрузка 1С…", self.import_excel), ("Открыть проект…", self.open_project),
                               ("Выгрузить переделы в 1С…", self.export_erp),
                               ("Сохранить", self.save), ("Сохранить как…", self.save_as),
                               ("Название схемы…", self.edit_project_title),
                               ("Оформление…", self.edit_card_size),
                               ("Печать / PDF…", self.print_pdf)]:
            action = QAction(title, self)
            action.triggered.connect(handler)
            toolbar.addAction(action)
        toolbar.addSeparator()
        self.tree_toggle = QAction("Объекты", self)
        self.tree_toggle.setCheckable(True)
        self.tree_toggle.setChecked(True)
        toolbar.addAction(self.tree_toggle)
        self.panel_toggle = QAction("Свойства", self)
        self.panel_toggle.setCheckable(True)
        self.panel_toggle.setChecked(True)
        toolbar.addAction(self.panel_toggle)
        self.show_warehouses_action = QAction('Склады на схеме', self)
        self.show_warehouses_action.setCheckable(True)
        self.show_warehouses_action.setChecked(False)
        self.show_warehouses_action.setToolTip('Показать подробные списки складов внутри карточек')
        toolbar.addAction(self.show_warehouses_action)
        self.link_action = QAction('Создать связь мышью', self)
        self.link_action.setCheckable(True)
        self.link_action.setToolTip('Выберите отправителя и получателя; Esc отменяет режим')
        self.link_action.toggled.connect(self.link_mode_toggled)
        toolbar.addAction(self.link_action)
        self.diagram_group_action = QAction('Группировать…', self)
        self.diagram_group_action.setToolTip('Выберите блоки Ctrl+щелчком или рамкой и объедините их')
        self.diagram_group_action.triggered.connect(self.group_diagram_selection)
        toolbar.addAction(self.diagram_group_action)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self.diagram_context_menu)
        self.link_escape = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.link_escape.setEnabled(False)
        self.link_escape.activated.connect(self.cancel_link_creation)
        self.snap_action = QAction('Привязка', self)
        self.snap_action.setCheckable(True)
        self.snap_action.setChecked(True)
        self.snap_action.setToolTip('Привязка к соседним карточкам; Alt отключает привязку, Shift раздвигает цепочку')
        self.snap_action.toggled.connect(lambda _: self.view.set_alignment_guides([]))
        toolbar.addAction(self.snap_action)
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 6, 8, 6)
        self.search = QLineEdit()
        self.search.setMaximumWidth(self.width() // 3)
        self.search.setPlaceholderText("Поиск передела или склада")
        self.search.textChanged.connect(self.render_scene)
        self.type_filter = QComboBox()
        self.type_filter.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.type_filter.addItem("Все типы", "")
        self.type_filter.currentIndexChanged.connect(self.render_scene)
        row.addWidget(self.search, 1)
        row.addWidget(self.type_filter)
        for title, handler in [("+ Передел", self.add_stage), ("+ Связь", self.add_edge),
                               ("Удалить связь", self.remove_edge), ("Выровнять", self.auto_layout),
                               ("Показать всё", self.fit_all)]:
            button = QPushButton(title)
            button.clicked.connect(handler)
            row.addWidget(button)
        self.auto_align_check = QCheckBox('Автовыравнивание')
        self.auto_align_check.setToolTip('Применять «Выровнять» после изменения передела')
        self.auto_align_check.toggled.connect(self.set_auto_align)
        row.addWidget(self.auto_align_check)
        row.addSpacing(10)
        for label, kind in [('+ Текст', 'text'), ('+ Фигура', None),
                            ('+ Стрелка', 'arrow'), ('+ Картинка…', 'image')]:
            button = QPushButton(label)
            if kind:
                button.clicked.connect(lambda checked=False, key=kind: self.add_annotation(key))
            else:
                menu = QMenu(button)
                for key in ('rectangle', 'rounded', 'ellipse', 'triangle', 'line'):
                    menu.addAction(ANNOTATION_LABELS[key], lambda name=key: self.add_annotation(name))
                button.setMenu(menu)
            row.addWidget(button)
        row.addStretch()
        delete_annotation = QShortcut(QKeySequence(Qt.Key_Delete), self.view)
        delete_annotation.setContext(Qt.WidgetWithChildrenShortcut)
        delete_annotation.activated.connect(self.remove_selected_annotation)

        self.objects_panel = QWidget()
        self.objects_panel.setMinimumWidth(240)
        left = QVBoxLayout(self.objects_panel)
        left.setContentsMargins(6, 6, 6, 6)
        left.addWidget(QLabel("<b>Объекты</b>"))
        buttons = QHBoxLayout()
        for title, callback, tip in [('+ Передел', self.add_stage, 'Добавить передел в выбранную группу'),
                                      ('+ Группа', self.add_group, 'Создать группу переделов'),
                                      ('+ Склад', self.add_warehouse, 'Добавить склад в проект')]:
            button = QPushButton(title)
            button.setToolTip(tip)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        left.addLayout(buttons)
        self.stage_list_mode = QComboBox()
        self.stage_list_mode.addItem('Переделы: по группам', 'grouped')
        self.stage_list_mode.addItem('Переделы: все списком', 'flat')
        self.stage_list_mode.setToolTip('Показывать переделы по используемым группам или общим списком')
        self.stage_list_mode.currentIndexChanged.connect(lambda _: self.refresh_tree(expand_stages=True))
        left.addWidget(self.stage_list_mode)
        self.object_tree = QTreeWidget()
        self.object_tree.setHeaderHidden(True)
        self.object_tree.setMinimumWidth(220)
        self.object_tree.currentItemChanged.connect(self.tree_selection_changed)
        self.object_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.object_tree.customContextMenuRequested.connect(self.show_tree_context_menu)
        left.addWidget(self.object_tree, 1)

        self.panel = QWidget()
        panel = QVBoxLayout(self.panel)
        self.panel.setMinimumWidth(350)
        self.properties_title = QLabel("<b>Свойства</b>")
        panel.addWidget(self.properties_title)
        self.empty_label = QLabel("Выберите объект слева или передел на схеме.")
        self.empty_label.setWordWrap(True)
        panel.addWidget(self.empty_label)
        self.form_widget = QWidget()
        editor = QVBoxLayout(self.form_widget)
        editor.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.name_input = QLineEdit()
        self.type_input = QComboBox()
        self.group_input = QComboBox()
        self.rkt_enabled = QCheckBox("Расписание контрольной точки (РКТ)")
        self.rkt_input = QComboBox()
        self.rkt_input.setEditable(False)
        self.rkt_legacy_label = QLabel()
        self.rkt_legacy_label.setWordWrap(True)
        self.rkt_legacy_label.setStyleSheet('color:#c57c20')
        self.launch_layout_input = QComboBox()
        for key, caption, _ in LAYOUTS:
            self.launch_layout_input.addItem(caption, key)
        self.layout_legacy_label = QLabel()
        self.layout_legacy_label.setWordWrap(True)
        self.layout_legacy_label.setStyleSheet('color:#c57c20')
        self.deficit_enabled = QCheckBox('Запуск с дефицитом')
        self.deficit_enabled.setToolTip('Красная полоса на карточках производства и сборки / разборки.')
        self.launch_layout_input.setToolTip('Заполняется из новой выгрузки 1С; можно изменить в проекте.')
        self.buffer_enabled = QCheckBox('Буфер запаса')
        form.addRow("Название", self.name_input)
        form.addRow("Тип", self.type_input)
        form.addRow("Группа", self.group_input)
        form.addRow(self.rkt_enabled)
        form.addRow("Алгоритм РКТ", self.rkt_input)
        form.addRow(self.rkt_legacy_label)
        form.addRow("Макет плана запуска", self.launch_layout_input)
        form.addRow(self.layout_legacy_label)
        form.addRow(self.deficit_enabled)
        form.addRow(self.buffer_enabled)
        editor.addLayout(form)
        warehouse_hint = QLabel('Серым — склад выбран в другом списке. Чтобы перенести его, сначала снимите прежнюю отметку.')
        warehouse_hint.setWordWrap(True)
        editor.addWidget(warehouse_hint)
        editor.addWidget(QLabel("Входные стеллажи"))
        self.inlets = WarehouseEditor()
        editor.addWidget(self.inlets, 1)
        editor.addWidget(QLabel("Склады остатков в работе"))
        self.stocks = WarehouseEditor()
        editor.addWidget(self.stocks, 1)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color:#b43432")
        self.error_label.setWordWrap(True)
        editor.addWidget(self.error_label)
        self.remove_button = QPushButton("Удалить передел со схемы")
        self.remove_button.clicked.connect(self.remove_stage)
        editor.addWidget(self.remove_button)
        panel.addWidget(self.form_widget, 1)
        self.form_widget.hide()
        self.group_form = QWidget()
        group_layout = QVBoxLayout(self.group_form)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_fields = QFormLayout()
        self.group_name_input = QLineEdit()
        group_fields.addRow('Название', self.group_name_input)
        group_layout.addLayout(group_fields)
        group_help = QLabel('Группа объединяет переделы рамкой на схеме. Удаление группы оставляет переделы в проекте.')
        group_help.setWordWrap(True)
        group_layout.addWidget(group_help)
        self.group_remove_button = QPushButton('Удалить группу')
        self.group_remove_button.clicked.connect(self.remove_group)
        group_layout.addWidget(self.group_remove_button)
        group_layout.addStretch(1)
        panel.addWidget(self.group_form, 1)
        self.group_form.hide()
        self.warehouse_form = QWidget()
        warehouse_layout = QVBoxLayout(self.warehouse_form)
        warehouse_layout.setContentsMargins(0, 0, 0, 0)
        warehouse_fields = QFormLayout()
        self.warehouse_name_input = QLineEdit()
        self.warehouse_code_input = QLineEdit()
        self.warehouse_type_input = QComboBox()
        self.warehouse_type_input.addItem('Не задан', '')
        self.warehouse_type_input.addItem('Обычный (материальный)', 'ordinary')
        self.warehouse_type_input.addItem('Цеховая кладовая', 'workshop')
        warehouse_fields.addRow('Название', self.warehouse_name_input)
        warehouse_fields.addRow('Код', self.warehouse_code_input)
        warehouse_fields.addRow('Тип склада', self.warehouse_type_input)
        warehouse_layout.addLayout(warehouse_fields)
        warehouse_help = QLabel('Склад изменяется только в проекте визуализатора; данные 1С не меняются.')
        warehouse_help.setWordWrap(True)
        warehouse_layout.addWidget(warehouse_help)
        self.warehouse_remove_button = QPushButton('Удалить склад из проекта')
        self.warehouse_remove_button.clicked.connect(self.remove_warehouse)
        warehouse_layout.addWidget(self.warehouse_remove_button)
        warehouse_layout.addStretch(1)
        panel.addWidget(self.warehouse_form, 1)
        self.warehouse_form.hide()
        self.edge_form = QWidget()
        edge_layout = QVBoxLayout(self.edge_form)
        edge_layout.setContentsMargins(0, 0, 0, 0)
        self.edge_title = QLabel()
        self.edge_title.setWordWrap(True)
        edge_layout.addWidget(self.edge_title)
        edge_help = QLabel('Перетаскивайте участок линии или круглые точки. Двойной щелчок по линии добавляет точку. Начало и конец остаются прикреплены к переделам.')
        edge_help.setWordWrap(True)
        edge_layout.addWidget(edge_help)
        self.edge_reset_button = QPushButton('Автомаршрут выбранной связи')
        self.edge_reset_button.clicked.connect(self.reset_selected_edge)
        edge_layout.addWidget(self.edge_reset_button)
        self.edge_delete_button = QPushButton('Удалить выбранную связь')
        self.edge_delete_button.clicked.connect(self.delete_selected_edge)
        edge_layout.addWidget(self.edge_delete_button)
        edge_layout.addStretch(1)
        panel.addWidget(self.edge_form, 1)
        self.edge_form.hide()
        self.annotation_form = QWidget()
        annotation_layout = QVBoxLayout(self.annotation_form)
        annotation_layout.setContentsMargins(0, 0, 0, 0)
        self.annotation_title = QLabel()
        annotation_layout.addWidget(self.annotation_title)
        annotation_help = QLabel('Перетаскивайте элемент за середину, а для изменения размера потяните за угол или конец линии.')
        annotation_help.setWordWrap(True)
        annotation_layout.addWidget(annotation_help)
        annotation_edit = QPushButton('Изменить оформление…')
        annotation_edit.clicked.connect(lambda: self.edit_annotation(self.selected_ref))
        annotation_layout.addWidget(annotation_edit)
        annotation_layout.addStretch()
        panel.addWidget(self.annotation_form, 1)
        self.annotation_form.hide()
        self.splitter = QSplitter()
        self.splitter.addWidget(self.objects_panel)
        self.splitter.addWidget(self.view)
        self.splitter.addWidget(self.panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([280, 780, 390])
        self.tree_toggle.toggled.connect(self.objects_panel.setVisible)
        self.panel_toggle.toggled.connect(self.panel.setVisible)
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(bar)
        layout.addWidget(self.splitter, 1)
        self.setCentralWidget(wrapper)
        self.statusBar().showMessage("Загрузите выгрузку 1С или откройте сохранённый проект.")
        self.name_input.textChanged.connect(self.on_edit)
        self.type_input.currentIndexChanged.connect(self.on_edit)
        self.group_input.currentIndexChanged.connect(self.on_edit)
        self.rkt_enabled.toggled.connect(self.on_edit)
        self.rkt_input.currentIndexChanged.connect(self.on_edit)
        self.launch_layout_input.currentIndexChanged.connect(self.on_edit)
        self.deficit_enabled.toggled.connect(self.on_edit)
        self.buffer_enabled.toggled.connect(self.on_edit)
        self.inlets.itemChanged.connect(lambda item: self.on_warehouse_link_changed(self.inlets, self.stocks, item))
        self.stocks.itemChanged.connect(lambda item: self.on_warehouse_link_changed(self.stocks, self.inlets, item))
        self.show_warehouses_action.toggled.connect(self.on_view_toggled)
        self.group_name_input.textChanged.connect(self.on_group_edit)
        self.warehouse_name_input.textChanged.connect(self.on_warehouse_edit)
        self.warehouse_code_input.textChanged.connect(self.on_warehouse_edit)
        self.warehouse_type_input.currentIndexChanged.connect(self.on_warehouse_edit)
        self.refresh_tree()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'search'):
            self.search.setMaximumWidth(max(100, self.width() // 3))

    def refresh_tree(self, expand_stages=False):
        """Rebuild the object list without losing the edited object's selection."""
        tree = self.object_tree
        expanded = set()
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            if top.isExpanded():
                expanded.add(tuple(top.data(0, Qt.UserRole)))
            for j in range(top.childCount()):
                child = top.child(j)
                if child.isExpanded():
                    expanded.add(tuple(child.data(0, Qt.UserRole)))
        first = tree.topLevelItemCount() == 0
        self.tree_loading = True
        tree.clear()
        found = None

        def add(parent, text, kind, ident=''):
            nonlocal found
            item = QTreeWidgetItem(parent, [text])
            item.setData(0, Qt.UserRole, (kind, ident))
            if kind == self.selected_kind and ident == self.selected_ref and found is None:
                found = item
            if ((kind, ident) in expanded
                    or (first and kind in ('stages_root', 'group', 'ungrouped', 'warehouses_root'))
                    or (expand_stages and kind in ('stages_root', 'group', 'ungrouped'))):
                item.setExpanded(True)
            return item

        stages_root = add(tree, 'Переделы', 'stages_root')
        stages = sorted(self.project.stages, key=lambda obj: obj.name.casefold())
        if self.stage_list_mode.currentData() == 'flat':
            for stage in stages:
                add(stages_root, stage.name or 'Без названия', 'stage', stage.id)
        else:
            groups_by_id = {}
            used_group_ids = {stage.group_id for stage in stages if stage.group_id}
            known_group_ids = {group.id for group in self.project.groups}
            ungrouped = (add(stages_root, 'Без группы', 'ungrouped')
                         if any(stage.group_id not in known_group_ids for stage in stages) else None)
            for group in sorted(self.project.groups, key=lambda obj: obj.name.casefold()):
                if group.id in used_group_ids:
                    groups_by_id[group.id] = add(stages_root, group_label(group), 'group', group.id)
            for stage in stages:
                add(groups_by_id.get(stage.group_id, ungrouped), stage.name or 'Без названия', 'stage', stage.id)
        warehouses_root = add(tree, 'Склады', 'warehouses_root')
        for warehouse in sorted(self.project.warehouses, key=lambda obj: (obj.name.casefold(), obj.code)):
            label = warehouse.name or 'Без названия'
            if warehouse.code:
                label += ' [' + warehouse.code + ']'
            add(warehouses_root, label, 'warehouse', warehouse.id)
        groups_root = add(tree, 'Группы', 'groups_root')
        for group in sorted(self.project.groups, key=lambda obj: obj.name.casefold()):
            add(groups_root, group_label(group), 'group', group.id)
        if found is not None:
            if self.selected_kind == 'stage' and found.parent() is not None:
                found.parent().setExpanded(True)
                stages_root.setExpanded(True)
            elif self.selected_kind == 'group':
                found.setExpanded(True)
            tree.setCurrentItem(found)
        self.tree_loading = False

    def tree_selection_changed(self, current, previous=None):
        if self.tree_loading or self.loading or current is None:
            return
        kind, ident = current.data(0, Qt.UserRole)
        self.selected_kind, self.selected_ref = kind, ident
        self.selected_id = ident if kind == 'stage' else None
        self.loading = True
        self.scene.clearSelection()
        if kind == 'stage' and ident in self.nodes:
            self.nodes[ident].setSelected(True)
        self.loading = False
        if kind == 'stage' and ident not in self.nodes:
            self.search.clear()
            self.type_filter.setCurrentIndex(0)
            self.render_scene()
        if kind == 'stage' and ident in self.nodes:
            self.view.ensureVisible(self.nodes[ident], 50, 50)
        self.show_properties()

    def build_stage_context_menu(self, stage_id):
        """Create actions for the clicked stage without changing the model."""
        stage = next((s for s in self.project.stages if s.id == stage_id), None)
        if stage is None:
            return None
        menu = QMenu(self.object_tree)
        groups = menu.addMenu('Назначить группу')
        no_group = groups.addAction('Без группы')
        no_group.setCheckable(True)
        no_group.setChecked(not stage.group_id)
        no_group.triggered.connect(lambda: self.assign_stage_group(stage_id, ''))
        for group in sorted(self.project.groups, key=lambda obj: (obj.name.casefold(), obj.id)):
            action = groups.addAction(group_label(group))
            action.setCheckable(True)
            action.setChecked(stage.group_id == group.id)
            action.setData(group.id)
            action.triggered.connect(lambda checked=False, ident=group.id: self.assign_stage_group(stage_id, ident))
        groups.addSeparator()
        new_group = groups.addAction('Создать группу…')
        new_group.triggered.connect(lambda: self.create_group_for_stage(stage_id))
        menu.addSeparator()
        copy_stage = menu.addAction('Копировать передел')
        copy_stage.triggered.connect(lambda: self.copy_stage(stage_id))
        delete_stage = menu.addAction('Удалить передел')
        delete_stage.triggered.connect(self.remove_stage)
        return menu

    def diagram_context_menu(self, position):
        item = self.view.itemAt(position)
        if isinstance(item, AnnotationItem):
            self.scene.clearSelection()
            item.setSelected(True)
            menu = self.annotation_menu(item.annotation.id)
            menu.exec(self.view.viewport().mapToGlobal(position))
            menu.deleteLater()
            return
        if isinstance(item, StageItem) and not item.isSelected():
            self.scene.clearSelection()
            item.setSelected(True)
        ids = [node.stage.id for node in self.scene.selectedItems() if isinstance(node, StageItem)]
        marker = item.data(0) if item is not None else None
        group_id = item.stage.group_id if isinstance(item, StageItem) else (
            marker[1] if isinstance(marker, (tuple, list)) and len(marker) == 2 and marker[0] == 'group' else '')
        if not ids and not group_id:
            return
        menu = QMenu(self.view)
        if len(ids) >= 2:
            self._add_alignment_menu(menu, ids, 'Выровнять выделенные')
        if group_id:
            group_ids = [stage.id for stage in self.project.stages if stage.group_id == group_id]
            if len(group_ids) >= 2:
                self._add_alignment_menu(menu, group_ids, 'Выровнять всю группу')
        if ids:
            group_action = menu.addAction('Объединить в группу…')
            group_action.triggered.connect(self.group_diagram_selection)
        if any(s.id in ids and s.group_id for s in self.project.stages):
            ungroup = menu.addAction('Убрать из группы')
            ungroup.triggered.connect(lambda: self._assign_diagram_group(ids, ''))
        menu.exec(self.view.viewport().mapToGlobal(position))

    def _add_alignment_menu(self, parent, ids, title):
        menu = parent.addMenu(title)
        for label, mode in [('По левому краю', 'left'), ('По центру по горизонтали', 'hcenter'),
                            ('По правому краю', 'right'), ('По верхнему краю', 'top'),
                            ('По центру по вертикали', 'vcenter'), ('По нижнему краю', 'bottom'),
                            ('Распределить центры по горизонтали', 'distribute_x'),
                            ('Распределить центры по вертикали', 'distribute_y'),
                            ('Равные промежутки по горизонтали', 'equal_gaps_x'),
                            ('Равные промежутки по вертикали', 'equal_gaps_y'),
                            ('Стандартный интервал по горизонтали', 'space_x'),
                            ('Стандартный интервал по вертикали', 'space_y')]:
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, mode=mode, ids=tuple(ids): self.align_objects(ids, mode))
        return menu

    def align_objects(self, ids, mode):
        stages = {stage.id: stage for stage in self.project.stages}
        visuals, physicals = {}, {}
        for stage in self.project.stages:
            item = self._stage_item(stage, lambda: None)
            visuals[stage.id] = QRectF(stage.x or 0, stage.y or 0, item.width, item.height)
            physicals[stage.id] = self._stage_bounds(stage)
        try:
            offsets = align_selection(visuals, physicals, ids, mode)
        except ValueError as exc:
            QMessageBox.warning(self, 'Выравнивание', str(exc))
            return False
        selected = [node.stage.id for node in self.scene.selectedItems() if isinstance(node, StageItem)]
        self._translate_internal_routes(offsets)
        for ident, delta in offsets.items():
            stage = stages[ident]
            stage.x += delta.x()
            stage.y += delta.y()
        self._capture_view_positions()
        self.dirty = True
        self.render_scene()
        self.loading = True
        for ident in selected:
            if ident in self.nodes:
                self.nodes[ident].setSelected(True)
        self.loading = False
        self.statusBar().showMessage('Выравнивание выполнено.', 5000)
        return True

    def group_diagram_selection(self):
        ids = [node.stage.id for node in self.scene.selectedItems() if isinstance(node, StageItem)]
        if not ids:
            QMessageBox.information(self, 'Группа', 'Выделите переделы на схеме с помощью Ctrl или рамки.')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Объединить переделы')
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        choice = QComboBox()
        choice.addItem('Создать новую группу', '')
        for group in sorted(self.project.groups, key=lambda obj: (obj.name.casefold(), obj.id)):
            choice.addItem(group_label(group), group.id)
        name = QLineEdit()
        name.setPlaceholderText('Название новой группы')
        choice.currentIndexChanged.connect(lambda _: name.setEnabled(not choice.currentData()))
        form.addRow('Группа', choice)
        form.addRow('Название', name)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        ident = choice.currentData()
        new_group = not ident
        if new_group:
            title = name.text().strip()
            if not title:
                QMessageBox.warning(self, 'Группа', 'Укажите название группы.')
                return
            group = model.Group(name=title)
            self.project.groups.append(group)
            ident = group.id
        self._assign_diagram_group(ids, ident, stack=new_group)

    def _assign_diagram_group(self, ids, group_id, stack=False):
        members = [stage for stage in self.project.stages if stage.id in ids]
        if not members or (group_id and not any(group.id == group_id for group in self.project.groups)):
            return False
        for stage in members:
            stage.group_id = group_id
        arranged = self._stack_new_group(members) if stack and len(members) > 1 else True
        self.selected_id = members[0].id
        self.selected_kind, self.selected_ref = 'stage', self.selected_id
        self.dirty = True
        self.refresh_tree()
        self.render_scene()
        self.show_properties()
        self.queue_auto_align()
        if not arranged:
            self.statusBar().showMessage('Группа создана. Расставьте её переделы с Shift: рядом недостаточно места.', 10000)
        return True

    def _stack_new_group(self, members):
        ids = {stage.id for stage in members}
        members = sorted(members, key=lambda stage: (stage.y or 0, stage.x or 0))
        first = members[0]
        center_x = (first.x or 0) + self._stage_item(first, lambda: None).width / 2
        top = min(self._stage_bounds(stage).top() for stage in members)
        proposed = {}
        outsiders = [self._stage_bounds(stage) for stage in self.project.stages if stage.id not in ids]
        for stage in members:
            bounds = self._stage_bounds(stage)
            width = self._stage_item(stage, lambda: None).width
            x = center_x - width / 2
            y = (stage.y or 0) + top - bounds.top()
            target = bounds.translated(x - (stage.x or 0), y - (stage.y or 0))
            if any(target.intersects(other) for other in outsiders):
                return False
            proposed[stage.id] = (x, y)
            top = target.bottom() + 24
        for stage in members:
            stage.x, stage.y = proposed[stage.id]
        return True

    def show_tree_context_menu(self, position):
        item = self.object_tree.itemAt(position)
        if item is None:
            return
        kind, ident = item.data(0, Qt.UserRole)
        if kind not in ('stage', 'group', 'warehouse'):
            return
        self.object_tree.setCurrentItem(item)
        if kind == 'stage':
            menu = self.build_stage_context_menu(ident)
        else:
            menu = QMenu(self.object_tree)
            if kind == 'group':
                ids = [stage.id for stage in self.project.stages if stage.group_id == ident]
                if len(ids) >= 2:
                    self._add_alignment_menu(menu, ids, 'Выровнять всю группу')
            action = menu.addAction('Удалить группу' if kind == 'group' else 'Удалить склад')
            action.triggered.connect(self.remove_group if kind == 'group' else self.remove_warehouse)
        if menu is not None:
            menu.exec(self.object_tree.viewport().mapToGlobal(position))

    def assign_stage_group(self, stage_id, group_id):
        stage = next((s for s in self.project.stages if s.id == stage_id), None)
        if stage is None or (group_id and not any(g.id == group_id for g in self.project.groups)):
            return False
        if stage.group_id == group_id:
            return True
        stage.group_id = group_id
        self.selected_kind, self.selected_ref, self.selected_id = 'stage', stage.id, stage.id
        self.dirty = True
        self.refresh_tree()
        self.render_scene()
        self.show_properties()
        self.queue_auto_align()
        return True

    def create_group_for_stage(self, stage_id):
        if not any(stage.id == stage_id for stage in self.project.stages):
            return
        name, accepted = QInputDialog.getText(self, 'Новая группа', 'Название группы:')
        if not accepted:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, 'Новая группа', 'Укажите название группы.')
            return
        if any(group.name.casefold() == name.casefold() for group in self.project.groups):
            QMessageBox.information(self, 'Новая группа', 'Такая группа уже существует. Выберите её в меню.')
            return
        group = model.Group(name=name)
        self.project.groups.append(group)
        self.assign_stage_group(stage_id, group.id)

    def copy_stage(self, stage_id):
        source = next((stage for stage in self.project.stages if stage.id == stage_id), None)
        if source is None:
            return None
        stage = deepcopy(source)
        stage.id = model.new_id()
        stage.code = ''
        # Keep type/routing and warehouse reference identifiers as properties;
        # remove only source-object identity and mark a new copy as active.
        identity = {'id', 'uuid', 'guid', 'ref', 'reference', 'source_id', 'source_uuid',
                    'source_guid', 'one_c_id', '1c_id', 'source_ref'}
        stage.extra = {key: value for key, value in stage.extra.items() if key.casefold() not in identity}
        if 'deletion_mark' in stage.extra:
            stage.extra['deletion_mark'] = False
        names = {item.name.casefold() for item in self.project.stages}
        base = source.name.strip() or 'Передел'
        name = f'{base} (копия)'
        number = 2
        while name.casefold() in names:
            name = f'{base} (копия {number})'
            number += 1
        stage.name = name
        own = self._stage_item(stage, lambda: None).boundingRect()
        source_x = source.x if source.x is not None else 50.0
        source_y = source.y if source.y is not None else 90.0
        x, y = (source_x, source_y + own.height() + 45) if source.group_id else (source_x + own.width() + 90, source_y)
        occupied = []
        for other in self.project.stages:
            if other.x is not None and other.y is not None:
                rect = self._stage_item(other, lambda: None).boundingRect().translated(other.x, other.y)
                occupied.append(rect.adjusted(-10, -10, 10, 10))
        # Move in the same direction until the card no longer intersects any
        # existing block. This does not move the original or any other item.
        while True:
            candidate = own.translated(x, y)
            collisions = [rect for rect in occupied if candidate.intersects(rect)]
            if not collisions:
                break
            if source.group_id:
                y = max(rect.bottom() for rect in collisions) - own.top() + 45
            else:
                x = max(rect.right() for rect in collisions) - own.left() + 90
        stage.x, stage.y = x, y
        self.project.stages.append(stage)
        self.selected_id = stage.id
        self.selected_kind, self.selected_ref = 'stage', stage.id
        self.dirty = True
        self.refresh_tree()
        self.render_scene()
        self.show_properties()
        self.name_input.setFocus()
        self.name_input.selectAll()
        self.queue_auto_align()
        return stage

    def find_annotation(self, ident):
        return next((annotation for annotation in self.project.annotations if annotation.id == ident), None)

    def add_annotation(self, kind):
        width, height = (180, 0) if kind in ('arrow', 'line') else (260, 100)
        image_data = ''
        if kind == 'image':
            path, _ = QFileDialog.getOpenFileName(self, 'Вставить картинку', '',
                'Изображения (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff);;Все файлы (*)')
            if not path:
                return
            try:
                image, image_data = read_picture(path)
            except ValueError as exc:
                QMessageBox.warning(self, 'Вставка картинки', str(exc))
                return
            short_side = min(image.width(), image.height())
            long_side = max(image.width(), image.height())
            scale = max(12 / short_side, min(1, 320 / long_side))
            width, height = image.width() * scale, image.height() * scale
        center = self.view.mapToScene(self.view.viewport().rect().center())
        annotation = model.Annotation(kind=kind, x=center.x() - width / 2, y=center.y() - height / 2,
                                     width=width, height=height, image_data=image_data,
                                     fill='' if kind in ('text', 'line', 'arrow', 'image') else '#ffffff',
                                     stroke_width=0 if kind in ('text', 'image') else 3)
        if kind == 'text':
            annotation = edit_annotation(self, annotation)
            if annotation is None or not annotation.text.strip():
                return
        self.project.annotations.append(annotation)
        self.select_annotation(annotation.id)

    def select_annotation(self, ident):
        self.selected_kind, self.selected_ref, self.selected_id = 'annotation', ident, None
        self.dirty = True
        self.refresh_tree()
        self.render_scene()
        self.show_properties()
        self.view.setFocus()

    def annotation_moved(self):
        self.dirty = True
        self.update_scene_rect()

    def edit_annotation(self, ident):
        annotation = self.find_annotation(ident)
        if annotation is None:
            return
        changed = edit_annotation(self, annotation)
        if changed is not None and changed != annotation:
            self.project.annotations[self.project.annotations.index(annotation)] = changed
            self.select_annotation(ident)

    def annotation_menu(self, ident):
        menu = QMenu(self.view)
        menu.addAction('Изменить оформление…', lambda: self.edit_annotation(ident))
        menu.addAction('Копировать', lambda: self.copy_annotation(ident))
        menu.addSeparator()
        menu.addAction('На передний план', lambda: self.reorder_annotation(ident, front=True))
        menu.addAction('На задний план слоя', lambda: self.reorder_annotation(ident, front=False))
        menu.addSeparator()
        menu.addAction('Удалить', self.remove_selected_annotation)
        return menu

    def copy_annotation(self, ident):
        original = self.find_annotation(ident)
        if original is not None:
            annotation = replace(original, id=model.new_id(), x=original.x + 24, y=original.y + 24)
            self.project.annotations.append(annotation)
            self.select_annotation(annotation.id)

    def reorder_annotation(self, ident, *, front):
        annotation = self.find_annotation(ident)
        items = self.project.annotations
        if annotation is not None and annotation is not items[-1 if front else 0]:
            items.remove(annotation)
            items.insert(len(items) if front else 0, annotation)
            self.select_annotation(ident)

    def remove_selected_annotation(self):
        annotation = self.find_annotation(self.selected_ref) if self.selected_kind == 'annotation' else None
        if annotation is not None:
            self.project.annotations.remove(annotation)
            self.selected_kind, self.selected_ref = None, None
            self.dirty = True
            self.render_scene()
            self.show_properties()

    def show_properties(self):
        kind, ident = self.selected_kind, self.selected_ref
        stage = next((s for s in self.project.stages if s.id == ident), None) if kind == 'stage' else None
        group = next((g for g in self.project.groups if g.id == ident), None) if kind == 'group' else None
        warehouse = next((w for w in self.project.warehouses if w.id == ident), None) if kind == 'warehouse' else None
        edge = next((e for e in self.project.edges if (e.source, e.target) == ident), None) if kind == 'edge' else None
        annotation = self.find_annotation(ident) if kind == 'annotation' else None
        self.form_widget.setVisible(stage is not None)
        self.group_form.setVisible(group is not None)
        self.warehouse_form.setVisible(warehouse is not None)
        self.edge_form.setVisible(edge is not None)
        self.annotation_form.setVisible(annotation is not None)
        self.empty_label.setVisible(all(item is None for item in (stage, group, warehouse, edge, annotation)))
        title = {'stage': 'передела', 'group': 'группы', 'warehouse': 'склада',
                 'edge': 'связи', 'annotation': 'элемента оформления'}.get(kind, '')
        self.properties_title.setText('<b>Свойства ' + title + '</b>')
        self.loading = True
        if group:
            self.group_name_input.setText(group.name)
        elif warehouse:
            self.warehouse_name_input.setText(warehouse.name)
            self.warehouse_code_input.setText(warehouse.code)
            self.warehouse_type_input.setCurrentIndex(max(0, self.warehouse_type_input.findData(warehouse.warehouse_type)))
        elif edge:
            names = {s.id: s.name for s in self.project.stages}
            self.edge_title.setText(f"{names.get(edge.source, edge.source)} → {names.get(edge.target, edge.target)}")
        elif annotation:
            self.annotation_title.setText(ANNOTATION_LABELS[annotation.kind])
        self.loading = False
        if stage:
            self.populate_stage(stage)

    def add_group(self):
        group = model.Group(name='Новая группа')
        self.project.groups.append(group)
        self.selected_kind, self.selected_ref, self.selected_id = 'group', group.id, None
        self.loading = True
        self.scene.clearSelection()
        self.loading = False
        self.dirty = True
        self.refresh_tree()
        self.show_properties()
        self.group_name_input.setFocus()
        self.group_name_input.selectAll()

    def on_group_edit(self, text):
        if self.loading or self.selected_kind != 'group':
            return
        group = next((g for g in self.project.groups if g.id == self.selected_ref), None)
        if group is None:
            return
        group.name = text.strip()
        self.dirty = True
        self.refresh_tree()
        self.render_scene()

    def remove_group(self):
        group = next((g for g in self.project.groups if g.id == self.selected_ref), None)
        if group is None:
            return
        if QMessageBox.question(self, 'Удалить группу', f'Удалить группу «{group.name}»? Переделы останутся в проекте без группы.') != QMessageBox.Yes:
            return
        for stage in self.project.stages:
            if stage.group_id == group.id:
                stage.group_id = ''
        self.project.groups.remove(group)
        self.selected_kind, self.selected_ref = None, None
        self.dirty = True
        self.refresh_tree()
        self.render_scene()
        self.show_properties()
        self.queue_auto_align()

    def add_warehouse(self):
        warehouse = model.Warehouse(name='Новый склад')
        self.project.warehouses.append(warehouse)
        self.selected_kind, self.selected_ref, self.selected_id = 'warehouse', warehouse.id, None
        self.loading = True
        self.scene.clearSelection()
        self.loading = False
        self.dirty = True
        self.refresh_tree()
        self.show_properties()
        self.warehouse_name_input.setFocus()
        self.warehouse_name_input.selectAll()

    def on_warehouse_edit(self, *args):
        if self.loading or self.selected_kind != 'warehouse':
            return
        warehouse = next((w for w in self.project.warehouses if w.id == self.selected_ref), None)
        if warehouse is None:
            return
        warehouse.name = self.warehouse_name_input.text().strip()
        warehouse.code = self.warehouse_code_input.text().strip()
        warehouse.warehouse_type = self.warehouse_type_input.currentData() or ''
        self.dirty = True
        self.refresh_tree()
        self.render_scene()

    def remove_warehouse(self):
        warehouse = next((w for w in self.project.warehouses if w.id == self.selected_ref), None)
        if warehouse is None:
            return
        if any(link.warehouse_id == warehouse.id for stage in self.project.stages for link in stage.inlets + stage.stocks):
            QMessageBox.warning(self, 'Удаление склада', 'Этот склад привязан к переделу. Сначала снимите привязку.')
            return
        if QMessageBox.question(self, 'Удалить склад', f'Удалить «{warehouse.name}» из проекта? Данные 1С не изменятся.') != QMessageBox.Yes:
            return
        self.project.warehouses.remove(warehouse)
        self.selected_kind, self.selected_ref = None, None
        self.dirty = True
        self.refresh_tree()
        self.render_scene()
        self.show_properties()

    def confirm_discard(self):
        if not self.dirty:
            return True
        choice = QMessageBox.question(self, "Несохранённые изменения", "Сохранить изменения проекта?",
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if choice == QMessageBox.Save:
            return self.save()
        return choice == QMessageBox.Discard

    def closeEvent(self, event):
        if self.confirm_discard():
            event.accept()
        else:
            event.ignore()

    def link_mode_toggled(self, active):
        self.link_source = None
        self.view.link_mode = active
        self.link_escape.setEnabled(active)
        if active:
            self.view.setFocus()
            self.statusBar().showMessage('Создание связи: выберите передел-отправитель. Esc отменяет режим.')
        else:
            self.statusBar().showMessage('Режим создания связи выключен.', 5000)

    def cancel_link_creation(self):
        if self.link_action.isChecked():
            self.link_action.setChecked(False)
        else:
            self.link_source = None
            self.view.link_mode = False

    def link_stage_clicked(self, stage_id):
        if not self.link_action.isChecked() or stage_id not in self.nodes:
            return
        if self.link_source is None:
            self.link_source = stage_id
            self.scene.clearSelection()
            self.nodes[stage_id].setSelected(True)
            name = self.nodes[stage_id].stage.name
            self.statusBar().showMessage(f'Отправитель: {name}. Выберите получателя; Esc отменяет режим.')
            return
        source = self.link_source
        self.link_source = None
        if self.create_edge(source, stage_id):
            self.statusBar().showMessage('Связь создана. Выберите отправителя следующей связи; Esc завершает режим.')
        else:
            self.statusBar().showMessage('Выберите отправителя новой связи; Esc завершает режим.')

    def set_project(self, project, path=None, dirty=False, ordered=False):
        self.cancel_link_creation()
        self._auto_align_timer.stop()
        self._stage_drag_changed = False
        self.project, self.path, self.dirty = project, path, dirty
        self._view_bridge = None
        self._active_view = 'detailed' if project.show_warehouses else 'compact'
        with QSignalBlocker(self.show_warehouses_action):
            self.show_warehouses_action.setChecked(project.show_warehouses)
        with QSignalBlocker(self.auto_align_check):
            self.auto_align_check.setChecked(project.auto_align)
        self.selected_id = None
        self.selected_kind, self.selected_ref = None, None
        self._refresh_filter()
        # Versions 1–4 stored positions only for the detailed view. Project
        # those actual positions into the compact view instead of discarding
        # the old diagram composition.
        old_detailed = project.view_positions.get('detailed', {})
        old_ids = {stage.id for stage in project.stages}
        legacy = (self._active_view == 'compact' and old_ids and set(old_detailed) == old_ids
                  and all(stage.x is None and stage.y is None for stage in project.stages))
        legacy_overlap = False
        if legacy:
            detailed = {key: tuple(value) for key, value in old_detailed.items()}
            try:
                compact, scale = project_positions(detailed, self._view_local_bounds('detailed'),
                                                   self._view_local_bounds('compact'))
                for stage in project.stages:
                    stage.x, stage.y = compact[stage.id]
                self._view_bridge = {'positions': {'detailed': detailed, 'compact': compact},
                                     'scale': {'detailed': (1.0, 1.0), 'compact': scale}}
            except ValueError:
                for stage in project.stages:
                    stage.x, stage.y = detailed[stage.id]
                self._active_view = 'detailed'
                with QSignalBlocker(self.show_warehouses_action):
                    self.show_warehouses_action.setChecked(True)
                legacy_overlap = True
        else:
            self._initial_positions(ordered)
        repaired = self._resolve_compact_overlaps() if not legacy_overlap else False
        self.dirty = self.dirty or repaired
        self._capture_view_positions()
        if project.exchange_map_id:
            self._restore_exchange_views()
        self.refresh_tree()
        self.render_scene()
        self.show_properties()
        QTimer.singleShot(0, self.fit_all)
        if repaired:
            self.statusBar().showMessage('Некоторые блоки сдвинуты, чтобы увеличенный текст не вызвал наложение.', 12000)
        elif legacy_overlap:
            self.statusBar().showMessage('Старый проект открыт в исходном виде: исправьте перекрывающиеся блоки.', 12000)

    def edit_project_title(self):
        current = model.Annotation(text=self.project.title, font_size=self.project.title_font_size,
                                   **asdict(self.project.title_style))
        edited = edit_annotation(self, current, dialog_title='Название схемы', font_range=(8, 72))
        if edited is None:
            return
        name = edited.text.strip()
        if not name:
            QMessageBox.warning(self, 'Название схемы', 'Укажите название схемы.')
            return
        style = model.TextStyle(**{key: getattr(edited, key) for key in asdict(self.project.title_style)})
        if (name, edited.font_size, style) != (self.project.title, self.project.title_font_size,
                                              self.project.title_style):
            self.project.title = name
            self.project.title_font_size = edited.font_size
            self.project.title_style = style
            self.dirty = True
            self.render_scene()

    def edit_card_size(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Оформление схемы')
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        width, width_row = number_field('card_width', self.project.card_width, 120, 700)
        height, height_row = number_field('card_height', self.project.card_height, 50, 400)
        flow_font, flow_row = number_field('flow_font', self.project.flow_font_size, 8, 72)
        title_font, title_row = number_field('title_font', self.project.title_font_size, 8, 72)
        group_font, group_row = number_field('group_font', self.project.group_font_size, 8, 72)
        form.addRow('Ширина компактного блока', width_row)
        form.addRow('Высота компактного блока', height_row)
        form.addRow('Шрифт стрелок потоков', flow_row)
        form.addRow('Шрифт заголовка', title_row)
        form.addRow('Шрифт названий групп', group_row)
        layout.addLayout(form)
        layout.addWidget(QLabel('Цвета типов переделов'))
        color_form = QFormLayout()
        palette = dict(self.project.colors)
        for key, name in [('production', 'Производство'), ('purchase', 'Покупка'),
                          ('logistics', 'Логистика'), ('services', 'Промуслуги'), ('assembly', 'Сборка / разборка'),
                          ('rkt', 'Производство с РКТ'), ('assembly_rkt', 'Сборка / разборка с РКТ'),
                          ('other', 'Другой тип')]:
            button = QPushButton()
            def update_button(button=button, key=key):
                value = palette.get(key, DEFAULT_COLORS[key])
                button.setText(value)
                button.setStyleSheet(f'background-color: {value}; color: ' +
                                     ('black' if QColor(value).lightness() > 150 else 'white'))
            def choose(checked=False, button=button, key=key, update=update_button):
                color = QColorDialog.getColor(QColor(palette.get(key, DEFAULT_COLORS[key])), dialog, 'Цвет блока')
                if color.isValid():
                    palette[key] = color.name()
                    update()
            update_button()
            button.clicked.connect(choose)
            color_form.addRow(name, button)
        layout.addLayout(color_form)
        help_label = QLabel('Текст внутри компактного блока подбирается автоматически. Длинное слово не разрывается.')
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted:
            self.apply_appearance(width.value(), height.value(), flow_font.value(), title_font.value(), palette,
                                  group_font.value())

    def apply_appearance(self, width, height, flow_font, title_font, palette, group_font=None):
        size_changed = (width, height) != (self.project.card_width, self.project.card_height)
        self.project.card_width, self.project.card_height = width, height
        self.project.flow_font_size, self.project.title_font_size = flow_font, title_font
        if group_font is not None:
            self.project.group_font_size = group_font
        self.project.colors = dict(palette)
        if size_changed:
            # Resize only the compact view and retain its composition. Cards
            # whose new bounds overlap are moved just far enough to the right.
            if self._active_view == 'compact':
                positions = {s.id: [s.x or 0, s.y or 0] for s in self.project.stages}
            else:
                positions = self.project.view_positions.get('compact', {})
            occupied = []
            for stage in sorted(self.project.stages, key=lambda s: (positions.get(s.id, [0, 0])[0],
                                                                    positions.get(s.id, [0, 0])[1])):
                if stage.id not in positions:
                    continue
                x, y = positions[stage.id]
                item = StageItem(stage, self._names(), lambda: None, True,
                                 card_width=width, card_height=height)
                rect = item.boundingRect().adjusted(2, 2, -2, -2).translated(x, y)
                while True:
                    collisions = [other for other in occupied if rect.intersects(other.adjusted(-24, -24, 24, 24))]
                    if not collisions:
                        break
                    shift = max(other.right() + 24 - rect.left() for other in collisions)
                    rect.translate(shift, 0)
                    x += shift
                positions[stage.id] = [x, y]
                occupied.append(rect)
                if self._active_view == 'compact':
                    stage.x, stage.y = x, y
            if self._active_view != 'compact' and positions:
                self.project.view_positions['compact'] = positions
        self.dirty = True
        self.render_scene()

    def import_excel(self):
        if not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Выберите выгрузку 1С", "", "Выгрузка 1С (*.xlsx *.json)")
        if not path:
            return
        try:
            json_exchange = Path(path).suffix.lower() == ".json"
            project, warnings = exchange.import_map(path) if json_exchange else model.import_xlsx(path)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка чтения выгрузки", str(exc))
            return
        conflicts = [s.name for s in project.stages
                     if {x.warehouse_id for x in s.inlets if x.warehouse_id}
                     & {x.warehouse_id for x in s.stocks if x.warehouse_id}]
        if conflicts:
            warnings.append('В обоих списках выбран один склад: ' + ', '.join(conflicts[:10])
                            + (' и другие.' if len(conflicts) > 10 else '.')
                            + ' Перед сохранением снимите лишние отметки.')
        self.set_project(project, dirty=True, ordered=json_exchange)
        if warnings:
            QMessageBox.warning(self, "Замечания к выгрузке", "\n".join(warnings[:50]) + ("\n…" if len(warnings) > 50 else ""))
        self.statusBar().showMessage(f"Загружено переделов: {len(project.stages)}, складов: {len(project.warehouses)}", 12000)

    def export_erp(self):
        self.flush_auto_align()
        directory, _ = QFileDialog.getSaveFileName(self, "Выгрузить переделы в 1С",
                                                    "Карта.ddflow.json", "JSON (*.json)")
        if not directory:
            return
        self._capture_view_positions()
        try:
            views = dict(self.project.view_positions)
            active = self._active_view
            other = "compact" if active == "detailed" else "detailed"
            current = {key: tuple(point) for key, point in views[active].items()}
            other_bounds = self._view_local_bounds(other)
            alternate = views.get(other, {})
            if current and (set(alternate) != set(current) or view_overlaps(alternate, other_bounds)):
                alternate, _ = project_positions(current, self._view_local_bounds(active), other_bounds)
            views[other] = alternate
            ident = exchange.export_map(self.project, directory, views)
        except (ValueError, OSError) as exc:
            QMessageBox.critical(self, "Ошибка выгрузки", str(exc))
            return
        if self.project.exchange_map_id != ident:
            self.project.exchange_map_id = ident
            self.dirty = True
        self.statusBar().showMessage("Файл сохранён. Откройте его в режиме «Загрузить в 1С» обработки FlowExport.", 12000)

    def open_project(self):
        if not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Открыть проект", "", "Проект потока (*.flow.json);;JSON (*.json)")
        if not path:
            return
        try:
            project = model.load_project(path)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка открытия", str(exc))
            return
        self.set_project(project, path)

    def save(self):
        self.flush_auto_align()
        if self.error_label.isVisible() and self.error_label.text():
            QMessageBox.warning(self, "Проверьте передел", self.error_label.text())
            return False
        for kind, collection in [('group', self.project.groups), ('warehouse', self.project.warehouses)]:
            invalid_object = next((obj for obj in collection if not obj.name.strip()), None)
            if invalid_object:
                self.selected_kind, self.selected_ref, self.selected_id = kind, invalid_object.id, None
                self.refresh_tree()
                self.show_properties()
                QMessageBox.warning(self, 'Проверьте название', 'Укажите название группы или склада.')
                return False
        invalid = next((stage for stage in self.project.stages if not stage.name or not stage.provider_type), None)
        if invalid:
            self.selected_id = invalid.id
            self.render_scene()
            self.selection_changed()
            QMessageBox.warning(self, "Проверьте передел", "У каждого передела должны быть название и тип.")
            return False
        conflict = next((stage for stage in self.project.stages
                         if {link.warehouse_id for link in stage.inlets if link.warehouse_id}
                         & {link.warehouse_id for link in stage.stocks if link.warehouse_id}), None)
        if conflict:
            self.selected_kind, self.selected_ref, self.selected_id = 'stage', conflict.id, conflict.id
            self.refresh_tree()
            self.render_scene()
            self.show_properties()
            QMessageBox.warning(self, 'Проверьте склады',
                                f'В переделе «{conflict.name}» один склад выбран в обоих списках. Снимите одну отметку.')
            return False
        if not self.path:
            return self.save_as()
        self._capture_view_positions()
        try:
            model.save_project(self.project, self.path)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка сохранения", str(exc))
            return False
        self.dirty = False
        self.statusBar().showMessage("Проект сохранён", 5000)
        return True

    def save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить проект", self.project.title + ".flow.json", "Проект потока (*.flow.json)")
        if not path:
            return False
        if not path.lower().endswith(".json"):
            path += ".flow.json"
        old_path, self.path = self.path, path
        if self.save():
            return True
        self.path = old_path
        return False

    def print_pdf(self):
        self.flush_auto_align()
        for item in self.edge_items:
            item.set_edit_handles_visible(False)
        try:
            try:
                from .print_export import show_preview
            except ImportError:
                from print_export import show_preview
            show_preview(self.scene, self)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка печати", str(exc))
        finally:
            for item in self.edge_items:
                item.set_edit_handles_visible(True)

    def _refresh_filter(self):
        value = self.type_filter.currentData() or ""
        self.type_filter.blockSignals(True)
        self.type_filter.clear()
        self.type_filter.addItem("Все типы", "")
        for name in sorted(set(self.project.provider_options + [s.provider_type for s in self.project.stages]) - {""}):
            self.type_filter.addItem(name, name)
        index = self.type_filter.findData(value)
        self.type_filter.setCurrentIndex(max(index, 0))
        self.type_filter.blockSignals(False)

    def _initial_positions(self, ordered=False):
        stages = self.project.stages
        if not stages:
            return
        if not ordered and all(stage.x is None and stage.y is None for stage in stages):
            try:
                positions = self._layout_positions()
            except ValueError:
                # A legacy project may contain cyclic links and no saved
                # positions. Keep every object visible without changing edges;
                # an explicit alignment can later explain the conflicting links.
                positions = {}
                x = 50.0
                for stage in stages:
                    positions[stage.id] = (x, 90.0)
                    x += self._stage_item(stage, lambda: None).boundingRect().width() + 90
            for stage in stages:
                stage.x, stage.y = positions[stage.id]
            return
        # Retain manual positions in an existing project. Put only missing
        # positions to the right so they cannot overwrite a placed card.
        right = max((stage.x + self._stage_item(stage, lambda: None).boundingRect().width()
                     for stage in stages if stage.x is not None and stage.y is not None), default=-40.0)
        for stage in stages:
            if stage.x is None or stage.y is None:
                stage.x, stage.y = right + 90.0, 90.0
                right = stage.x + self._stage_item(stage, lambda: None).boundingRect().width()

    def _restore_exchange_views(self):
        layouts = {}
        for view in ('compact', 'detailed'):
            stored = self.project.view_positions.get(view, {})
            if not stored:
                return
            sizes = self._view_local_bounds(view)
            layout = {key: tuple(pos) for key, pos in stored.items() if key in sizes}
            right = max((pos[0] + sizes[key].right() for key, pos in layout.items()), default=-40.0)
            for stage in self.project.stages:
                if stage.id not in layout:
                    layout[stage.id] = (right + 90.0, 90.0)
                    right = layout[stage.id][0] + sizes[stage.id].right()
            if view_overlaps(layout, sizes):
                return
            layouts[view] = layout
        self.project.view_positions.update({view: {key: list(pos) for key, pos in layout.items()}
                                            for view, layout in layouts.items()})
        self._view_bridge = {'positions': layouts, 'scale': {'compact': (1, 1), 'detailed': (1, 1)}}

    def _names(self):
        return {w.id: w for w in self.project.warehouses}

    def _capture_view_positions(self):
        self.project.view_positions[self._active_view] = {
            stage.id: [stage.x, stage.y] for stage in self.project.stages
            if stage.x is not None and stage.y is not None
        }
        self.project.show_warehouses = self._active_view == 'detailed'

    def _invalidate_other_view(self):
        other = 'compact' if self._active_view == 'detailed' else 'detailed'
        self.project.view_positions.pop(other, None)

    def _positions_overlap(self, positions):
        # Sorted sweep avoids comparing every pair in a long horizontal flow.
        bounds = []
        for stage in self.project.stages:
            x, y = positions[stage.id]
            rect = self._stage_item(stage, lambda: None).boundingRect().translated(x, y)
            bounds.append(rect)
        bounds.sort(key=lambda rect: rect.left())
        for index, rect in enumerate(bounds):
            for other in bounds[index + 1:]:
                if other.left() >= rect.right():
                    break
                if rect.intersects(other):
                    return True
        return False

    def _view_local_bounds(self, view):
        names = self._names()
        return {stage.id: StageItem(stage, names, lambda: None, view == 'compact',
                    card_width=self.project.card_width, card_height=self.project.card_height,
                    palette=self.project.colors).boundingRect().adjusted(2, 2, -2, -2)
                for stage in self.project.stages}

    def _project_changed_routes(self, view, old, new, local_bounds):
        """Move existing manual bends with their endpoints, without losing them."""
        for edge in self.project.edges:
            points = edge.routes.get(view)
            if not points or edge.source not in old or edge.target not in old:
                continue
            if edge.source not in new or edge.target not in new:
                continue
            a0, b0 = old[edge.source], old[edge.target]
            a1, b1 = new[edge.source], new[edge.target]
            da = QPointF(a1[0] - a0[0], a1[1] - a0[1])
            db = QPointF(b1[0] - b0[0], b1[1] - b0[1])
            if abs(da.x()) + abs(da.y()) + abs(db.x()) + abs(db.y()) < 1e-7:
                continue
            ac = QPointF(*a0) + local_bounds[edge.source].center()
            bc = QPointF(*b0) + local_bounds[edge.target].center()
            vector = bc - ac
            squared = vector.x() ** 2 + vector.y() ** 2
            transformed = []
            for x, y in points:
                point = QPointF(x, y)
                relative = point - ac
                fraction = max(0.0, min(1.0, (relative.x() * vector.x() + relative.y() * vector.y()) / squared)) if squared else .5
                delta = da * (1 - fraction) + db * fraction
                transformed.append([x + delta.x(), y + delta.y()])
            edge.routes[view] = transformed

    def on_view_toggled(self, checked):
        target = 'detailed' if checked else 'compact'
        if target == self._active_view:
            return
        if self._auto_align_timer.isActive():
            with QSignalBlocker(self.show_warehouses_action):
                self.show_warehouses_action.setChecked(self._active_view == 'detailed')
                self.flush_auto_align()
                self.show_warehouses_action.setChecked(checked)
        previous = self._active_view
        self._capture_view_positions()
        current = {stage.id: (stage.x, stage.y) for stage in self.project.stages}
        stored = self.project.view_positions.get(target, {})
        required = set(current)
        try:
            source_bounds = self._view_local_bounds(previous)
            target_bounds = self._view_local_bounds(target)
            bridge = self._view_bridge
            usable = (bridge is not None and previous in bridge['positions'] and target in bridge['positions']
                      and set(bridge['positions'][previous]) == required
                      and set(bridge['positions'][target]) == required)
            if usable:
                source_base, target_base = bridge['positions'][previous], bridge['positions'][target]
                previous_scale, target_scale = bridge['scale'][previous], bridge['scale'][target]
                factor = (target_scale[0] / previous_scale[0], target_scale[1] / previous_scale[1])
                positions = {key: (target_base[key][0] + (pos[0] - source_base[key][0]) * factor[0],
                                   target_base[key][1] + (pos[1] - source_base[key][1]) * factor[1])
                             for key, pos in current.items()}
                if view_overlaps(positions, target_bounds):
                    usable = False
            if not usable:
                positions, factor = project_positions(current, source_bounds, target_bounds)
            if view_overlaps(positions, target_bounds):
                raise ValueError('Недостаточно места для карточек. Уберите наложения в текущем виде.')
        except ValueError as exc:
            with QSignalBlocker(self.show_warehouses_action):
                self.show_warehouses_action.setChecked(previous == 'detailed')
            QMessageBox.warning(self, 'Режим схемы',
                                'Не удалось разместить карточки: ' + str(exc)
                                + '\nПредыдущее расположение сохранено.')
            return
        self._project_changed_routes(target, stored, positions, target_bounds)
        for stage in self.project.stages:
            stage.x, stage.y = positions[stage.id]
        self._active_view = target
        self._view_bridge = {'positions': {previous: current, target: dict(positions)},
                             'scale': {previous: (1.0, 1.0), target: factor}}
        self._capture_view_positions()
        self.dirty = True
        self.render_scene()
        if required:
            self.statusBar().showMessage('Вид переключён с сохранением расположения переделов.', 5000)

    def _stage_item(self, stage, changed):
        return StageItem(stage, self._names(), changed, not self.show_warehouses_action.isChecked(),
                         self._snap_stage_position, self._finish_stage_drag,
                         self.project.card_width, self.project.card_height, self.project.colors)

    @staticmethod
    def _intersection_area(a, b):
        intersection = a.intersected(b)
        return 0.0 if intersection.isEmpty() else intersection.width() * intersection.height()

    def _stage_bounds(self, stage):
        # Exclude the graphics selection padding, retain a possible buffer icon.
        item = self._stage_item(stage, lambda: None)
        return item.boundingRect().adjusted(2, 2, -2, -2).translated(stage.x or 0, stage.y or 0)

    def _resolve_compact_overlaps(self):
        """Resolve overlaps caused by larger cards with the smallest forward move."""
        placed = []
        moved = False
        for stage in sorted(self.project.stages, key=lambda s: (s.y or 0, s.x or 0)):
            rect = self._stage_bounds(stage)
            while True:
                collisions = [other for other in placed if rect.intersects(other)]
                if not collisions:
                    break
                overlap_x = max(other.right() - rect.left() for other in collisions)
                overlap_y = max(other.bottom() - rect.top() for other in collisions)
                if overlap_x <= overlap_y:
                    dx = overlap_x + STANDARD_HORIZONTAL_GAP
                    stage.x = (stage.x or 0) + dx
                    rect.translate(dx, 0)
                else:
                    dy = overlap_y + 24
                    stage.y = (stage.y or 0) + dy
                    rect.translate(0, dy)
                moved = True
            placed.append(rect)
        return moved

    def _finish_stage_drag(self):
        self._hidden_drag_bounds = None
        self._shift_drag_axis = None
        self.view.set_alignment_guides([])
        self.update_scene_rect()
        if self._stage_drag_changed:
            self._stage_drag_changed = False
            self.queue_auto_align()

    def _other_stage_bounds(self, stage, cache_hidden=False):
        if cache_hidden and getattr(self, '_hidden_drag_bounds', None) is None:
            self._hidden_drag_bounds = {other.id: self._stage_bounds(other) for other in self.project.stages
                                        if other.id not in self.nodes and other.x is not None and other.y is not None}
        result = []
        for other in self.project.stages:
            if other is stage or other.x is None or other.y is None:
                continue
            node = self.nodes.get(other.id)
            if node is not None:
                bounds = node.sceneBoundingRect().adjusted(2, 2, -2, -2)
            elif cache_hidden:
                bounds = self._hidden_drag_bounds[other.id]
            else:
                bounds = self._stage_bounds(other)
            result.append((other, bounds))
        return result

    def _nearest_free_offset(self, own, others, previous=None):
        def allowed(rect):
            return all(self._intersection_area(rect, bounds) <=
                       (self._intersection_area(previous, bounds) if previous is not None else 0) + 1e-6
                       for bounds in others)
        if allowed(own):
            return None
        conflicting = [bounds for bounds in others
                       if self._intersection_area(own, bounds) >
                       (self._intersection_area(previous, bounds) if previous is not None else 0) + 1e-6]
        # Bound the local candidate set even in a damaged, dense old project.
        conflicting.sort(key=lambda bounds: ((bounds.center().x() - own.center().x()) ** 2
                                              + (bounds.center().y() - own.center().y()) ** 2))
        offsets = set()
        for bounds in conflicting[:16]:
            offsets.update(((bounds.left() - own.right(), 0.0), (bounds.right() - own.left(), 0.0),
                            (0.0, bounds.top() - own.bottom()), (0.0, bounds.bottom() - own.top())))
        offsets.add((max(bounds.right() for bounds in others) - own.left(), 0.0))
        for dx, dy in sorted(offsets, key=lambda p: p[0] * p[0] + p[1] * p[1]):
            if allowed(own.translated(dx, dy)):
                return dx, dy
        return None

    def _nearest_free_position(self, stage, previous=None):
        """Move only this card to the closest collision-free edge position."""
        offset = self._nearest_free_offset(self._stage_bounds(stage),
                                           [bounds for _, bounds in self._other_stage_bounds(stage)], previous)
        if offset is None:
            return False
        stage.x, stage.y = (stage.x or 0) + offset[0], (stage.y or 0) + offset[1]
        return True

    def _repair_hidden_view_after_edit(self, stage, old_stage):
        other_view = 'compact' if self._active_view == 'detailed' else 'detailed'
        positions = self.project.view_positions.get(other_view)
        if not isinstance(positions, dict) or stage.id not in positions:
            return
        names = self._names()
        def bounds(obj, position):
            item = StageItem(obj, names, lambda: None, other_view == 'compact',
                             card_width=self.project.card_width, card_height=self.project.card_height)
            return item.boundingRect().adjusted(2, 2, -2, -2).translated(*position)
        previous = bounds(old_stage, positions[stage.id])
        current = bounds(stage, positions[stage.id])
        obstacles = [bounds(other, positions[other.id]) for other in self.project.stages
                     if other is not stage and other.id in positions]
        offset = self._nearest_free_offset(current, obstacles, previous)
        if offset is not None:
            x, y = positions[stage.id]
            positions[stage.id] = [x + offset[0], y + offset[1]]
            return True
        return False

    def _snap_stage_position(self, item, proposed, modifiers):
        others = [node for node in self.nodes.values() if node is not item]
        current = item.sceneBoundingRect().adjusted(2, 2, -2, -2)
        modifiers = modifiers | QApplication.keyboardModifiers()
        members = [stage for stage in self.project.stages if item.stage.group_id
                   and stage.group_id == item.stage.group_id]
        if len(members) > 1 and not modifiers & Qt.ShiftModifier:
            return self._move_group_with_member(item, proposed, members, modifiers)
        if modifiers & Qt.ShiftModifier and not item.stage.group_id:
            diff = proposed - item.pos()
            axis = getattr(self, '_shift_drag_axis', None)
            threshold = 4.0 / max(self.view.transform().m11(), .01)
            if axis is None and max(abs(diff.x()), abs(diff.y())) >= threshold:
                axis = 'x' if abs(diff.x()) >= abs(diff.y()) else 'y'
                self._shift_drag_axis = axis
            if axis is None:
                return item.pos()
            horizontal = axis == 'x'
            amount = diff.x() if horizontal else diff.y()
            displacement = QPointF(amount, 0) if horizontal else QPointF(0, amount)
            obstacles = self._other_stage_bounds(item.stage, cache_hidden=True)
            shifts = push_in_direction(current, amount, [(s.id, r) for s, r in obstacles], horizontal,
                                       group_ids={s.id: s.group_id for s, _ in obstacles})
            self.view.set_alignment_guides([])
            if shifts is None:
                safe_move = constrain_movement(current, current.translated(displacement),
                                               [bounds for _, bounds in obstacles], gap=24)
                return item.pos() + safe_move
            previous_loading = self.loading
            self.loading = True
            try:
                by_id = {s.id: s for s, _ in obstacles}
                for ident, delta in shifts.items():
                    node = self.nodes.get(ident)
                    if node is not None:
                        node.setPos(node.pos() + delta)
                    else:
                        stage = by_id[ident]
                        stage.x += delta.x()
                        stage.y += delta.y()
                        if self._hidden_drag_bounds is not None:
                            self._hidden_drag_bounds[ident].translate(delta)
                if any(ident not in self.nodes for ident in shifts):
                    self.statusBar().showMessage('При сдвиге затронут скрытый фильтром передел.', 6000)
                self._translate_internal_routes({**shifts, item.stage.id: displacement})
            finally:
                self.loading = previous_loading
            return item.pos() + displacement
        self._shift_drag_axis = None
        snap_enabled = (self.snap_action.isChecked()
                        and not modifiers & Qt.AltModifier)
        gap = 24.0 if snap_enabled else 0.0
        obstacles = self._other_stage_bounds(item.stage, cache_hidden=True)
        all_bounds = [bounds for _, bounds in obstacles]
        requested_bounds = current.translated(proposed - item.pos())

        def safe(candidate):
            # Legacy overlapping projects can be edited without increasing
            # their existing overlap, but newly created overlap is forbidden.
            return all(self._intersection_area(candidate, obstacle)
                       <= self._intersection_area(current, obstacle) + 1e-6 for obstacle in all_bounds)

        if safe(requested_bounds):
            # A clear destination stays accessible even if the pointer passed
            # over another block; otherwise an invisible wall traps the drag.
            move = proposed - item.pos()
        else:
            move = constrain_movement(current, requested_bounds, all_bounds, gap=gap,
                                      horizontal_gap=STANDARD_HORIZONTAL_GAP if snap_enabled else 0.0)
            if any(stage.id not in self.nodes and self._intersection_area(requested_bounds, bounds) > 0
                   for stage, bounds in obstacles):
                self.statusBar().showMessage('Здесь находится скрытый фильтром передел.', 7000)
        if snap_enabled and others:
            try:
                delta, guides = snap_to_alignment(
                    item.connection_rect().translated(move),
                    [node.connection_rect() for node in others],
                    self.view.transform().m11(), moving_bounds=current.translated(move),
                    other_bounds=[node.sceneBoundingRect().adjusted(2, 2, -2, -2) for node in others])
                desired = move + delta
                if safe(current.translated(desired)):
                    move = desired
                else:
                    guides = []
                self.view.set_alignment_guides(guides)
            except ValueError:
                self.view.set_alignment_guides([])
        else:
            self.view.set_alignment_guides([])
        return item.pos() + move

    def _move_group_with_member(self, item, proposed, members, modifiers):
        """Move all group members together, without moving other objects."""
        ids = {s.id for s in members}
        bounds = {s.id: (self.nodes[s.id].sceneBoundingRect().adjusted(2, 2, -2, -2)
                         if s.id in self.nodes else self._stage_bounds(s)) for s in members}
        obstacles = [rect for stage, rect in self._other_stage_bounds(item.stage, cache_hidden=True)
                     if stage.id not in ids]
        desired = proposed - item.pos()
        def safe(delta):
            return all(self._intersection_area(rect.translated(delta), other)
                       <= self._intersection_area(rect, other) + 1e-6
                       for rect in bounds.values() for other in obstacles)
        if not safe(desired):
            magnitude = max(abs(desired.x()), abs(desired.y()))
            ratio = 1.0
            if magnitude:
                for rect in bounds.values():
                    allowed = constrain_movement(rect, rect.translated(desired), obstacles)
                    ratio = min(ratio, max(abs(allowed.x()), abs(allowed.y())) / magnitude)
            desired *= ratio
        visible_others = [node for node in self.nodes.values() if node.stage.id not in ids]
        if self.snap_action.isChecked() and not modifiers & Qt.AltModifier and visible_others:
            delta, guides = snap_to_alignment(item.connection_rect().translated(desired),
                [node.connection_rect() for node in visible_others], self.view.transform().m11(),
                moving_bounds=bounds[item.stage.id].translated(desired),
                other_bounds=[node.sceneBoundingRect().adjusted(2, 2, -2, -2) for node in visible_others])
            if safe(desired + delta):
                desired += delta
                self.view.set_alignment_guides(guides)
            else:
                self.view.set_alignment_guides([])
        else:
            self.view.set_alignment_guides([])
        previous_loading = self.loading
        self.loading = True
        try:
            for stage in members:
                if stage.id == item.stage.id:
                    continue
                node = self.nodes.get(stage.id)
                if node is not None:
                    node.setPos(node.pos() + desired)
                else:
                    stage.x += desired.x()
                    stage.y += desired.y()
                    if self._hidden_drag_bounds is not None:
                        self._hidden_drag_bounds[stage.id].translate(desired)
            self._translate_internal_routes({stage.id: desired for stage in members})
        finally:
            self.loading = previous_loading
        return item.pos() + desired

    def _translate_internal_routes(self, shifts):
        """Move manual bends with a pair of endpoints that move together."""
        items = {id(item.edge): item for item in self.edge_items}
        for edge in self.project.edges:
            a, b = shifts.get(edge.source), shifts.get(edge.target)
            points = edge.routes.get(self._active_view)
            if a is None or b is None or not points:
                continue
            if abs(a.x() - b.x()) > 1e-6 or abs(a.y() - b.y()) > 1e-6:
                continue
            edge.routes[self._active_view] = [[x + a.x(), y + a.y()] for x, y in points]
            graphic = items.get(id(edge))
            if graphic is not None:
                graphic._manual = [QPointF(x, y) for x, y in edge.routes[self._active_view]]

    def matches(self, stage):
        q = self.search.text().strip().casefold()
        text = " ".join([stage.name, stage.code, stage.provider_type, warehouse_lines(stage.inlets + stage.stocks, self._names())]).casefold()
        return (not q or q in text) and (not self.type_filter.currentData() or stage.provider_type == self.type_filter.currentData())

    def render_scene(self, *args):
        selected = self.selected_id
        self.view.set_alignment_guides([])
        self._hidden_drag_bounds = None
        self.loading = True
        previous_annotations = self.annotation_items
        for item in previous_annotations.values():
            self.scene.removeItem(item)
        self.scene.clear()
        self.nodes = {}
        self.edge_items = []
        self.flow_items = []
        self.level_items = []
        self.group_items = []
        self.legend_items = []
        self.title_items = []
        for stage in self.project.stages:
            if not self.matches(stage):
                continue
            node = self._stage_item(stage, self.node_moved)
            node.setPos(stage.x or 0, stage.y or 0)
            self.scene.addItem(node)
            self.nodes[stage.id] = node
            if stage.id == selected:
                node.setSelected(True)
        if self.link_source is not None and self.link_source not in self.nodes:
            self.cancel_link_creation()
        self._draw_edges()
        self._draw_groups()
        self._draw_levels()
        self._draw_legend()
        self._draw_flow()
        self.annotation_items = {}
        for index, annotation in enumerate(self.project.annotations):
            item = previous_annotations.get(annotation.id)
            if item is None or item.annotation is not annotation:
                item = AnnotationItem(annotation, self.annotation_moved, self.edit_annotation)
            item.setZValue(40 + index)
            self.scene.addItem(item)
            self.annotation_items[annotation.id] = item
            item.setSelected(self.selected_kind == 'annotation' and annotation.id == self.selected_ref)
        self.loading = False
        self.update_scene_rect()

    def update_scene_rect(self):
        rect = self.scene.itemsBoundingRect()
        self.scene.setSceneRect(rect.adjusted(-120, -100, 120, 120) if not rect.isNull() else QRectF(0, 0, 1000, 700))

    def _diagram_bounds(self):
        # Never include the old arrows, legend or scene rectangle: doing so
        # would make the diagram grow at each drag or redraw.
        content = None
        for item in list(self.nodes.values()) + self.edge_items + self.group_items + self.level_items:
            if item.isVisible():
                rect = item.sceneBoundingRect()
                if not rect.isEmpty():
                    content = QRectF(rect) if content is None else content.united(rect)
        return content if content is not None else QRectF(0, 0, 600, 300)

    def _draw_legend(self):
        for item in self.legend_items:
            self.scene.removeItem(item)
        compact = not self.show_warehouses_action.isChecked()
        content, left, right, height, _ = self._flow_geometry()
        self.legend_items, _ = draw_legend(
            self.scene, [node.stage for node in self.nodes.values()],
            lambda provider: compact_color_for_type(provider, self.project.colors),
            content, compact=compact,
            rkt_color=self.project.colors.get('rkt', DEFAULT_COLORS['rkt']),
            assembly_rkt_color=self.project.colors.get('assembly_rkt', DEFAULT_COLORS['assembly_rkt']),
            legend_area=(left, content.bottom() + 28 + height + 24, right - left))

    def _flow_geometry(self):
        content = self._diagram_bounds()
        left, right = content.left(), content.right()
        font = QFont('Segoe UI', self.project.flow_font_size)
        font.setBold(True)
        required_width = max(QFontMetricsF(font).horizontalAdvance(text)
                             for text in ('Информационный поток', 'Материальный поток')) + 90
        if right - left < max(560, required_width):
            center = (left + right) / 2
            left, right = center - max(560, required_width) / 2, center + max(560, required_width) / 2
        height = max(34.0, QFontMetricsF(font).height() + 12)
        return content, left, right, height, font

    def _draw_flow(self):
        content, left, right, height, font = self._flow_geometry()
        tip = max(27.0, height * .65)

        def arrow(text, y, points):
            shape = QGraphicsPolygonItem(QPolygonF([QPointF(x, yy) for x, yy in points]))
            shape.setPen(QPen(Qt.PenStyle.NoPen))
            shape.setBrush(QBrush(QColor('#20262c')))
            shape.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            shape.setZValue(20)
            self.scene.addItem(shape)
            label = QGraphicsSimpleTextItem(text)
            label.setFont(font)
            label.setBrush(QBrush(QColor('white')))
            label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            label.setZValue(21)
            label.setPos((left + right - label.boundingRect().width()) / 2,
                         y + (height - label.boundingRect().height()) / 2)
            self.scene.addItem(label)
            self.flow_items.extend((shape, label))

        top = content.top() - height - 28
        bottom = content.bottom() + 28
        arrow('Информационный поток', top,
              [(left, top + height / 2), (left + tip, top), (right, top),
               (right, top + height), (left + tip, top + height)])
        arrow('Материальный поток', bottom,
              [(left, bottom), (right - tip, bottom), (right, bottom + height / 2),
               (right - tip, bottom + height), (left, bottom + height)])
        for item in self.title_items:
            self.scene.removeItem(item)
        style = self.project.title_style
        title = DiagramTitle(self.project.title or 'Новая схема', self.project.title_font_size, style, right - left)
        title_width = title.boundingRect().width()
        x = {'left': left, 'center': (left + right - title_width) / 2, 'right': right - title_width}
        title.setPos(x[style.alignment], top - title.boundingRect().height() - 20)
        title.activated.connect(self.edit_project_title, Qt.QueuedConnection)
        title.setZValue(21)
        self.scene.addItem(title)
        self.title_items = [title]

    def _draw_groups(self):
        for item in self.group_items:
            self.scene.removeItem(item)
        self.group_items = draw_group_frames(self.scene, self.project.groups, self.nodes,
                                             font_size=self.project.group_font_size)

    def _draw_levels(self):
        # Group columns are independent: the same level can occur at different
        # horizontal positions. Each card displays its own level instead of a
        # misleading global column heading.
        return

    def _draw_edges(self):
        for item in self.edge_items:
            self.scene.removeItem(item)
        self.edge_items = []
        for edge in self.project.edges:
            a, b = self.nodes.get(edge.source), self.nodes.get(edge.target)
            if a is None or b is None or a is b:
                continue
            def automatic_route(a=a, b=b):
                obstacles = [n.sceneBoundingRect().adjusted(-8, -8, 8, 8)
                             for n in self.nodes.values() if n not in (a, b)]
                return route_points(a, b, obstacles)
            item = EditableEdgeItem(edge, a, b, self._active_view, automatic_route,
                                    self.edge_route_changed, self.edge_route_finished)
            self.scene.addItem(item)
            self.edge_items.append(item)
            if self.selected_kind == 'edge' and self.selected_ref == (edge.source, edge.target):
                item.setSelected(True)

    def edge_route_changed(self, edge, view, points):
        if points:
            edge.routes[view] = points
        else:
            edge.routes.pop(view, None)
        self.dirty = True

    def edge_route_finished(self):
        for item in self.flow_items:
            self.scene.removeItem(item)
        self.flow_items = []
        self._draw_legend()
        self._draw_flow()
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-120, -100, 120, 120))

    def reset_selected_edge(self):
        selected = next((item for item in self.edge_items if item.isSelected()), None)
        if selected is not None:
            selected.reset_route()

    def delete_selected_edge(self):
        selected = next((item for item in self.edge_items if item.isSelected()), None)
        if selected is None:
            return
        if QMessageBox.question(self, 'Удалить связь', 'Удалить выбранную связь?') != QMessageBox.Yes:
            return
        self.project.edges.remove(selected.edge)
        self.selected_kind, self.selected_ref, self.selected_id = None, None, None
        self.dirty = True
        self.render_scene()
        self.show_properties()

    def node_moved(self):
        if self.loading:
            return
        self.dirty = True
        for item in self.edge_items:
            item.update_endpoints()
        self._draw_groups()
        for item in self.flow_items:
            self.scene.removeItem(item)
        self.flow_items = []
        for item in self.level_items:
            self.scene.removeItem(item)
        self.level_items = []
        self._draw_levels()
        self._draw_legend()
        self._draw_flow()
        if any(node._drag_active for node in self.nodes.values()):
            self._stage_drag_changed = True
            self._auto_align_timer.stop()
        else:
            self.update_scene_rect()

    def _layout_measurements(self):
        names = self._names()
        def measure(stage):
            item = StageItem(stage, names, lambda: None, not self.show_warehouses_action.isChecked(),
                             card_width=self.project.card_width, card_height=self.project.card_height)
            bounds = item.boundingRect()
            # Horizontal gaps are measured between visible card edges. The
            # two-unit scene padding on either side is only paint padding.
            return bounds.width() - 4, bounds.height(), bounds.x() + 2, bounds.y(), item.height / 2
        font = QFont('Segoe UI', self.project.group_font_size)
        font.setBold(True)
        metrics = QFontMetricsF(font)
        return measure, lambda group: metrics.horizontalAdvance(group.name or 'Без названия')

    def _layout_positions(self):
        # Keep legacy level data for round-tripping, but do not use it for the
        # layout of a new diagram; the user now places the cards directly.
        project = copy(self.project)
        project.stages = [copy(stage) for stage in self.project.stages]
        for stage in project.stages:
            stage.level = None
        measure, _ = self._layout_measurements()
        # Group captions wrap within the frame, so their unwrapped width must
        # not add an artificial empty column to the new diagram.
        return arrange_stages(project, measure, lambda group: 0.0)

    def set_auto_align(self, checked):
        self.project.auto_align = checked
        self.dirty = True
        if not checked:
            self._auto_align_timer.stop()

    def queue_auto_align(self):
        if self.project.auto_align and self.project.stages:
            self._auto_align_timer.start()

    def flush_auto_align(self):
        if self._auto_align_timer.isActive():
            self.auto_layout()

    def auto_layout(self):
        self._auto_align_timer.stop()
        try:
            measure, group_measure = self._layout_measurements()
            if any(stage.x is None or stage.y is None for stage in self.project.stages):
                raise ValueError('У передела не задано положение на схеме.')
            initial = {stage.id: (stage.x, stage.y) for stage in self.project.stages}
            aligned = align_group_columns(self.project, initial, measure)
            working = copy(self.project)
            working.stages = [copy(stage) for stage in self.project.stages]
            for stage in working.stages:
                stage.x, stage.y = aligned[stage.id]
            positions = compact_existing(working, measure, group_measure,
                lambda group, width: group_title_height(group.name, width, self.project.group_font_size) + 20)
            routes = []
            for edge in self.project.edges:
                if self._active_view not in edge.routes:
                    continue
                a = (aligned[edge.source][0] - initial[edge.source][0], aligned[edge.source][1] - initial[edge.source][1])
                b = (aligned[edge.target][0] - initial[edge.target][0], aligned[edge.target][1] - initial[edge.target][1])
                same = abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6
                points = [list(positions.transform_point(x + (a[0] if same else 0), y + (a[1] if same else 0)))
                          for x, y in edge.routes[self._active_view]]
                routes.append((edge, points))
        except ValueError as exc:
            QMessageBox.warning(self, 'Выравнивание',
                                'Не удалось автоматически выровнять схему: ' + str(exc)
                                + '\nСвязи и прежние координаты сохранены.')
            return False
        for stage in self.project.stages:
            stage.x, stage.y = positions[stage.id]
        for edge, points in routes:
            edge.routes[self._active_view] = points
        self._capture_view_positions()
        self.dirty = True
        self.render_scene()
        self.fit_all()
        return True

    def fit_all(self):
        bounds = self.scene.itemsBoundingRect()
        if not bounds.isEmpty():
            self.view.fitInView(bounds.adjusted(-30, -30, 30, 30), Qt.KeepAspectRatio)

    def selection_changed(self):
        if self.loading:
            return
        selected = self.scene.selectedItems()
        stages = [item for item in selected if isinstance(item, StageItem)]
        edges = [item for item in selected if isinstance(item, EditableEdgeItem)]
        annotations = [item for item in selected if isinstance(item, AnnotationItem)]
        if stages:
            self.selected_id = stages[0].stage.id
            self.selected_kind, self.selected_ref = 'stage', self.selected_id
        elif edges:
            self.selected_id = None
            self.selected_kind, self.selected_ref = 'edge', (edges[0].edge.source, edges[0].edge.target)
        elif annotations:
            self.selected_id = None
            self.selected_kind, self.selected_ref = 'annotation', annotations[0].annotation.id
        elif self.selected_kind in ('stage', 'edge', 'annotation'):
            self.selected_id = None
            self.selected_kind, self.selected_ref = None, None
        self.refresh_tree()
        self.show_properties()

    def populate_stage(self, stage):
        self.loading = True
        self.error_label.clear()
        self.name_input.setText(stage.name)
        self.type_input.clear()
        self.type_input.addItem("Выберите тип", "")
        # The regular DD FLOW types must always remain available.  Importing a
        # project with only one type, or creating the first typed stage, must
        # not turn that one value into the whole choice list.
        options = list(dict.fromkeys(
            ["Производство", "Покупка", "Промуслуги", "Логистика", "Сборка / Разборка"]
            + self.project.provider_options
            + [s.provider_type for s in self.project.stages if s.provider_type]
        ))
        for option in options:
            self.type_input.addItem(option, option)
        self.type_input.setCurrentIndex(max(self.type_input.findData(stage.provider_type), 0))
        self.group_input.clear()
        self.group_input.addItem('Без группы', '')
        for group in sorted(self.project.groups, key=lambda obj: obj.name.casefold()):
            self.group_input.addItem(group_label(group), group.id)
        self.group_input.setCurrentIndex(max(self.group_input.findData(stage.group_id), 0))
        self.rkt_enabled.setChecked(bool(stage.rkt_algorithm))
        self.rkt_input.clear()
        self.rkt_input.addItem("Выберите алгоритм", "")
        for option in dict.fromkeys(self.project.rkt_options + [s.rkt_algorithm for s in self.project.stages if s.rkt_algorithm] + [entry[0] for entry in ALGORITHMS]):
            if option and not is_retired_algorithm(option, self.project.rkt_option_ids):
                self.rkt_input.addItem(option, option)
        self.rkt_input.setCurrentIndex(max(self.rkt_input.findData(stage.rkt_algorithm), 0))
        self.rkt_input.setEnabled(bool(stage.rkt_algorithm))
        self._show_legacy_algorithm(stage.rkt_algorithm)
        self.launch_layout_input.clear()
        for key, caption, _ in LAYOUTS:
            self.launch_layout_input.addItem(caption, key)
        if stage.launch_layout in (LEGACY_LAYOUT, UNKNOWN_LAYOUT):
            caption = LEGACY_LAYOUT_LABEL if stage.launch_layout == LEGACY_LAYOUT else UNKNOWN_LAYOUT_LABEL
            if stage.launch_layout == UNKNOWN_LAYOUT:
                original = stage.extra.get('launch_layout_name') or stage.extra.get('launch_layout_id')
                if original:
                    caption += ': ' + str(original)
            self.launch_layout_input.addItem(caption, stage.launch_layout)
            legacy_index = self.launch_layout_input.count() - 1
            self.launch_layout_input.model().item(legacy_index).setEnabled(False)
            self.launch_layout_input.view().setRowHidden(legacy_index, True)
        self.launch_layout_input.setCurrentIndex(max(self.launch_layout_input.findData(stage.launch_layout or 'none'), 0))
        self._show_legacy_layout(stage.launch_layout)
        self.deficit_enabled.setChecked(stage.deficit_launch)
        self.buffer_enabled.setChecked(stage.has_buffer)
        self.inlets.load(self.project.warehouses, stage.inlets)
        self.stocks.load(self.project.warehouses, stage.stocks)
        self.update_warehouse_availability()
        if ({link.warehouse_id for link in stage.inlets if link.warehouse_id}
                & {link.warehouse_id for link in stage.stocks if link.warehouse_id}):
            self.error_label.setText('Один склад выбран в обоих списках. Снимите одну отметку.')
        self.loading = False

    def _show_legacy_algorithm(self, value):
        retired = is_retired_algorithm(value, self.project.rkt_option_ids)
        self.rkt_legacy_label.setText(('Устаревший алгоритм: ' + value + '. Выберите новый алгоритм.') if retired else '')
        self.rkt_legacy_label.setVisible(retired)

    def _show_legacy_layout(self, value):
        message = ('Ранее выбран «по головному изделию». Укажите соответствующий макет из 1С.' if value == LEGACY_LAYOUT
                   else 'Макет из 1С не поддерживается или запись недоступна. Выберите подходящий вариант вручную.' if value == UNKNOWN_LAYOUT else '')
        self.layout_legacy_label.setText(message)
        self.layout_legacy_label.setVisible(bool(message))

    def update_warehouse_availability(self):
        def checked(editor):
            return {editor.item(row, 0).data(Qt.UserRole) for row in range(editor.rowCount())
                    if editor.item(row, 0).checkState() == Qt.Checked}
        self.inlets.set_unavailable(checked(self.stocks), 'Уже выбран в складах остатков в работе. Сначала снимите отметку там.', 'в остатках в работе')
        self.stocks.set_unavailable(checked(self.inlets), 'Уже выбран во входных стеллажах. Сначала снимите отметку там.', 'во входных стеллажах')

    def on_warehouse_link_changed(self, editor, other, item):
        if self.loading:
            return
        if item.column() == 0 and item.checkState() == Qt.Unchecked:
            with QSignalBlocker(editor):
                editor.item(item.row(), 1).setCheckState(Qt.Unchecked)
        if item.column() == 0 and item.checkState() == Qt.Checked and item.data(Qt.UserRole):
            ident = item.data(Qt.UserRole)
            if any(other.item(row, 0).data(Qt.UserRole) == ident
                   and other.item(row, 0).checkState() == Qt.Checked for row in range(other.rowCount())):
                with QSignalBlocker(editor):
                    item.setCheckState(Qt.Unchecked)
                self.statusBar().showMessage('Этот склад уже выбран в другом списке. Сначала снимите прежнюю отметку.', 10000)
                return
        self.update_warehouse_availability()
        self.on_edit()
        if item.column() == 1:
            stage = next((s for s in self.project.stages if s.id == self.selected_id), None)
            if stage is not None:
                try:
                    editor.links()
                except ValueError:
                    return
                def refresh_primary_order():
                    if self.selected_id != stage.id or self.loading:
                        return
                    self.loading = True
                    try:
                        editor.load(self.project.warehouses, stage.inlets if editor is self.inlets else stage.stocks)
                        self.update_warehouse_availability()
                    finally:
                        self.loading = False
                QTimer.singleShot(0, refresh_primary_order)

    def on_edit(self, *args):
        if self.loading:
            return
        stage = next((s for s in self.project.stages if s.id == self.selected_id), None)
        if stage is None:
            return
        previous_bounds = self._stage_bounds(stage)
        self.rkt_input.setEnabled(self.rkt_enabled.isChecked())
        old_stage = deepcopy(stage)
        stage.name = self.name_input.text().strip()
        stage.provider_type = self.type_input.currentData() or ""
        stage.group_id = self.group_input.currentData() or ""
        selected_algorithm = self.rkt_input.currentData() or ""
        if self.rkt_enabled.isChecked():
            stage.rkt_algorithm = selected_algorithm or (stage.rkt_algorithm if is_retired_algorithm(stage.rkt_algorithm, self.project.rkt_option_ids) else "")
        else:
            stage.rkt_algorithm = ""
        self._show_legacy_algorithm(stage.rkt_algorithm)
        stage.launch_layout = self.launch_layout_input.currentData() or "none"
        self._show_legacy_layout(stage.launch_layout)
        stage.deficit_launch = self.deficit_enabled.isChecked()
        stage.has_buffer = self.buffer_enabled.isChecked()
        try:
            inlets, stocks = self.inlets.links(), self.stocks.links()
            stage.inlets, stage.stocks = inlets, stocks
            issue = ""
            duplicate = ({link.warehouse_id for link in inlets if link.warehouse_id}
                         & {link.warehouse_id for link in stocks if link.warehouse_id})
            if not stage.name:
                issue = "Укажите название передела."
            elif not stage.provider_type:
                issue = "Выберите тип передела."
            elif self.rkt_enabled.isChecked() and not stage.rkt_algorithm:
                issue = "Выберите алгоритм расписания РКТ."
            elif duplicate:
                issue = 'Один и тот же склад выбран во входных стеллажах и остатках в работе. Снимите одну из отметок.'
            self.error_label.setText(issue)
        except ValueError as exc:
            self.error_label.setText(str(exc))
        moved = self._nearest_free_position(stage, previous_bounds)
        moved_other = self._repair_hidden_view_after_edit(stage, old_stage)
        self.dirty = True
        self.refresh_tree()
        self.render_scene()
        self.statusBar().showMessage("Положение карточки изменено, чтобы избежать наложения." if moved or moved_other else "Изменения показаны на схеме.", 7000)
        if stage != old_stage:
            self.queue_auto_align()

    def add_stage(self):
        group_id = self.selected_ref if self.selected_kind == 'group' else ''
        if self.selected_kind == 'stage':
            current = next((s for s in self.project.stages if s.id == self.selected_ref), None)
            group_id = current.group_id if current else ''
        stage = model.Stage(name="Новый передел", group_id=group_id)
        existing = list(self.project.stages)
        self.project.stages.append(stage)
        members = [s for s in existing if group_id and s.group_id == group_id]
        if members:
            stage.x = min(s.x if s.x is not None else 50.0 for s in members)
            stage.y = max((s.y or 0) + self._stage_item(s, lambda: None).height + 45 for s in members)
        elif existing:
            stage.x = max((s.x or 0) + self._stage_item(s, lambda: None).boundingRect().width()
                          for s in existing) + 90
            stage.y = 90.0
        else:
            stage.x, stage.y = 50.0, 90.0
        self._nearest_free_position(stage)
        self.selected_id = stage.id
        self.selected_kind, self.selected_ref = 'stage', stage.id
        self.dirty = True
        self.refresh_tree()
        self.render_scene()
        self.show_properties()
        self.name_input.setFocus()
        self.name_input.selectAll()
        self.queue_auto_align()

    def remove_stage(self):
        stage = next((s for s in self.project.stages if s.id == self.selected_id), None)
        if stage is None:
            return
        if QMessageBox.question(self, "Удаление со схемы", f"Убрать «{stage.name}» и его связи из проекта? Данные 1С не изменятся.") != QMessageBox.Yes:
            return
        self.project.stages.remove(stage)
        self.project.edges = [edge for edge in self.project.edges if stage.id not in (edge.source, edge.target)]
        self.selected_id = None
        self.selected_kind, self.selected_ref = None, None
        self.dirty = True
        self.refresh_tree()
        self.render_scene()
        self.show_properties()
        self.queue_auto_align()

    def _edge_dialog(self, remove=False):
        stages = {stage.id: stage.name for stage in self.project.stages}
        dialog = QDialog(self)
        dialog.setWindowTitle("Удалить связь" if remove else "Добавить связь")
        layout = QVBoxLayout(dialog)
        if remove:
            pick = QComboBox()
            for edge in self.project.edges:
                pick.addItem(f"{stages.get(edge.source, edge.source)} → {stages.get(edge.target, edge.target)}", edge)
            layout.addWidget(pick)
        else:
            form = QFormLayout()
            source, target = QComboBox(), QComboBox()
            for stage in self.project.stages:
                source.addItem(stage.name, stage.id)
                target.addItem(stage.name, stage.id)
            if self.selected_id:
                source.setCurrentIndex(max(0, source.findData(self.selected_id)))
            form.addRow("От передела", source)
            form.addRow("К переделу", target)
            layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        if remove:
            edge = pick.currentData()
            if edge:
                self.project.edges.remove(edge)
        else:
            a, b = source.currentData(), target.currentData()
            self.create_edge(a, b)
            return
        self.dirty = True
        self.render_scene()

    def create_edge(self, source, target):
        ids = {stage.id for stage in self.project.stages}
        if not source or not target or source == target or source not in ids or target not in ids:
            QMessageBox.warning(self, 'Связь', 'Выберите два разных передела.')
            return False
        if any(edge.source == source and edge.target == target for edge in self.project.edges):
            QMessageBox.information(self, 'Связь', 'Такая связь уже существует.')
            return False
        self.project.edges.append(model.Edge(source=source, target=target))
        self.dirty = True
        # Preserve the user's existing composition and intentional return
        # links. A new directed arrow must not globally rearrange the diagram.
        self.render_scene()
        return True

    def add_edge(self):
        if len(self.project.stages) < 2:
            QMessageBox.information(self, "Связь", "Для связи нужны как минимум два передела.")
            return
        self._edge_dialog()

    def remove_edge(self):
        if not self.project.edges:
            QMessageBox.information(self, "Связь", "В проекте пока нет отдельных связей.")
            return
        self._edge_dialog(remove=True)


def smoke_test(directory):
    """Exercise the frozen application and bundled Qt, Excel and PDF dependencies."""
    from openpyxl import Workbook
    try:
        from .print_export import export_pdf
    except ImportError:
        from print_export import export_pdf

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(model.COLUMNS)
    def row(**values):
        sheet.append([values.get(key, "") for key in model.COLUMNS])
    row(kind="provider_option", id="production", name="Производство")
    row(kind="warehouse", id="warehouse-smoke", name="Входной склад", code="001")
    row(kind="stage", id="stage-a", name="Производственный передел", provider_type="Производство", level=1)
    row(kind="stage", id="stage-b", name="Следующий передел", provider_type="Производство", level=2)
    row(kind="inlet", owner_id="stage-a", warehouse_id="warehouse-smoke", primary=1)
    xlsx = directory / "input.xlsx"
    workbook.save(xlsx)
    project, warnings = model.import_xlsx(xlsx)
    if warnings or len(project.stages) != 2 or len(project.warehouses) != 1:
        raise AssertionError(f"Excel: {warnings}")
    project.edges.append(model.Edge(source="stage-a", target="stage-b"))
    window = MainWindow()
    window.set_project(project)
    window.show_warehouses_action.setChecked(True)
    window.show()
    app.processEvents()
    window.nodes["stage-a"].setSelected(True)
    app.processEvents()
    window.name_input.setText("Проверенный передел")
    window.nodes["stage-a"].setPos(180, 700)
    app.processEvents()
    window.add_group()
    window.group_name_input.setText('Цех резки')
    group = project.groups[-1]
    window.add_stage()
    created = project.stages[-1]
    if created.group_id != group.id:
        raise AssertionError('Новый передел не добавлен в выбранную группу.')
    window.name_input.setText('Новый сгруппированный передел')
    window.type_input.setCurrentIndex(window.type_input.findData('Производство'))
    if hasattr(window, 'level_input'):
        raise AssertionError('Уровень больше не должен отображаться в интерфейсе.')
    window.group_input.setCurrentIndex(0)
    if created.group_id:
        raise AssertionError('Передел не удалён из группы.')
    window.group_input.setCurrentIndex(window.group_input.findData(group.id))
    if created.group_id != group.id or not window.group_items:
        raise AssertionError('Передел не помещён в группу или рамка не построена.')
    # The tree and the canvas must select the same stage in both directions.
    tree = window.object_tree
    root = tree.topLevelItem(0)
    group_item = next(root.child(i) for i in range(root.childCount())
                      if root.child(i).data(0, Qt.UserRole) == ('group', group.id))
    child = next(group_item.child(i) for i in range(group_item.childCount())
                 if group_item.child(i).data(0, Qt.UserRole) == ('stage', created.id))
    tree.setCurrentItem(child)
    if window.selected_id != created.id or not window.nodes[created.id].isSelected():
        raise AssertionError('Выбор дерева не синхронизирован со схемой.')
    window.scene.clearSelection()
    window.nodes['stage-b'].setSelected(True)
    if window.selected_id != 'stage-b' or window.object_tree.currentItem().data(0, Qt.UserRole) != ('stage', 'stage-b'):
        raise AssertionError('Выбор схемы не синхронизирован с деревом.')
    window.add_warehouse()
    window.warehouse_name_input.setText('Новый тестовый склад')
    if project.warehouses[-1].name != 'Новый тестовый склад':
        raise AssertionError('Редактирование склада не сохранилось.')
    window.warehouse_type_input.setCurrentIndex(window.warehouse_type_input.findData('workshop'))
    if project.warehouses[-1].warehouse_type != 'workshop':
        raise AssertionError('Не сохранился тип склада.')
    warehouse_id = project.warehouses[-1].id
    root = tree.topLevelItem(0)
    group_item = next(root.child(i) for i in range(root.childCount())
                      if root.child(i).data(0, Qt.UserRole) == ('group', group.id))
    child = next(group_item.child(i) for i in range(group_item.childCount())
                 if group_item.child(i).data(0, Qt.UserRole) == ('stage', created.id))
    tree.setCurrentItem(child)
    window.buffer_enabled.setChecked(True)
    if not created.has_buffer or window.nodes[created.id].title_x <= 12:
        raise AssertionError('Не установлен и не отображён буфер запаса.')
    warehouse_row = next(i for i in range(window.inlets.rowCount())
                         if window.inlets.item(i, 0).data(Qt.UserRole) == warehouse_id)
    window.inlets.item(warehouse_row, 0).setCheckState(Qt.Checked)
    if not any(link.warehouse_id == warehouse_id for link in created.inlets):
        raise AssertionError('Новый склад не привязался к переделу.')
    if '#bd702b' not in window.nodes[created.id].body.toHtml().lower():
        raise AssertionError('В блоке передела не показан тип склада.')
    window.tree_toggle.setChecked(False)
    window.panel_toggle.setChecked(False)
    if window.objects_panel.isVisible() or window.panel.isVisible():
        raise AssertionError('Боковые панели не скрылись.')
    window.tree_toggle.setChecked(True)
    window.panel_toggle.setChecked(True)
    if not window.objects_panel.isVisible() or not window.panel.isVisible():
        raise AssertionError('Боковые панели не восстановились.')
    def change_title():
        dialog = app.activeModalWidget()
        dialog.findChild(QPlainTextEdit).setPlainText('Производственный поток')
        dialog.findChild(QPushButton, 'font_size_up').click()
        dialog.accept()

    QTimer.singleShot(0, change_title)
    window.edit_project_title()
    if (project.title != 'Производственный поток' or window.title_items[0].toPlainText() != project.title
            or window.title_items[0].font().pointSize() != 31):
        raise AssertionError('Заголовок схемы не обновлён.')
    file = directory / "project.flow.json"
    model.save_project(project, file)
    saved = model.load_project(file)
    if (saved.stages[0].name != "Проверенный передел" or saved.stages[0].x != 180 or len(saved.edges) != 1
            or len(saved.groups) != 1 or saved.stages[-1].group_id != saved.groups[0].id
            or saved.warehouses[-1].name != 'Новый тестовый склад'
            or saved.warehouses[-1].warehouse_type != 'workshop' or not saved.stages[-1].has_buffer
            or not any(link.warehouse_id == warehouse_id for link in saved.stages[-1].inlets)):
        raise AssertionError("Не сохранены свойства, положение или связь.")
    export_pdf(window.scene, directory / "one-page.pdf", tiled=False)
    export_pdf(window.scene, directory / "pages.pdf", tiled=True)
    for name in ("one-page.pdf", "pages.pdf"):
        if not (directory / name).read_bytes().startswith(b"%PDF"):
            raise AssertionError(f"Не создан PDF: {name}")
    before_detailed = (created.x, created.y)
    before_compact = (len(created.inlets), created.has_buffer)
    window.show_warehouses_action.setChecked(False)
    if not window.nodes[created.id].compact or window.nodes[created.id].body is not None:
        raise AssertionError('Компактная схема не скрыла списки складов.')
    if (len(created.inlets), created.has_buffer) != before_compact:
        raise AssertionError('Изменение вида не должно менять данные схемы.')
    export_pdf(window.scene, directory / 'compact.pdf', tiled=False)
    if not (directory / 'compact.pdf').read_bytes().startswith(b'%PDF'):
        raise AssertionError('Не создан компактный PDF.')
    window.show_warehouses_action.setChecked(True)
    if (created.x, created.y) != before_detailed:
        raise AssertionError('Подробное размещение не восстановлено после смены вида.')
    positions_before_copy = [(stage.x, stage.y) for stage in project.stages]
    copied = window.copy_stage(created.id)
    if (copied is None or copied.id == created.id or copied.code or copied.group_id != created.group_id
            or copied.level != created.level or not copied.has_buffer or not copied.inlets
            or copied.inlets[0] is created.inlets[0]
            or [(stage.x, stage.y) for stage in project.stages[:-1]] != positions_before_copy):
        raise AssertionError('Копирование передела не сохранило независимые свойства.')
    root = tree.topLevelItem(0)
    group_item = next(root.child(i) for i in range(root.childCount())
                      if root.child(i).data(0, Qt.UserRole) == ('group', group.id))
    tree.setCurrentItem(group_item)
    original_question = QMessageBox.question
    try:
        QMessageBox.question = staticmethod(lambda *args: QMessageBox.Yes)
        window.remove_group()
    finally:
        QMessageBox.question = original_question
    if project.groups or created not in project.stages or created.group_id or copied.group_id:
        raise AssertionError('Удаление группы должно оставлять передел в проекте.')
    source = model.Stage(name='Источник', provider_type='Производство', x=900, y=90)
    target = model.Stage(name='Получатель', provider_type='Производство', x=20, y=90)
    linked = model.Project(stages=[source, target])
    window.set_project(linked)
    if not window.create_edge(source.id, target.id) or (source.x, target.x) != (900, 20):
        raise AssertionError('Создание связи изменило существующее расположение.')
    warnings = []
    old_warning = QMessageBox.warning
    try:
        QMessageBox.warning = staticmethod(lambda *args: warnings.append(args[-1]))
        window.create_edge(target.id, source.id)
    finally:
        QMessageBox.warning = old_warning
    if (len(linked.edges) != 2 or warnings
            or {(edge.source, edge.target) for edge in linked.edges}
            != {(source.id, target.id), (target.id, source.id)}):
        raise AssertionError('Обратная причинная связь не сохранена.')
    image_file = directory / 'annotation.png'
    image = QImage(40, 30, QImage.Format_RGB32)
    image.fill(QColor('#cb8240'))
    if not image.save(str(image_file)):
        raise AssertionError('Не удалось создать проверочную картинку.')
    _, encoded = read_picture(image_file)
    window.add_annotation('arrow')
    linked.annotations.append(model.Annotation(kind='image', x=350, y=240,
                                              width=80, height=60, image_data=encoded))
    linked.annotations.append(model.Annotation(kind='text', x=350, y=330,
                                              text='Комментарий к схеме', bold=True, font_size=24))
    window.render_scene()
    app.processEvents()
    annotation_path = directory / 'annotations.flow.json'
    model.save_project(linked, annotation_path)
    if len(model.load_project(annotation_path).annotations) != 3:
        raise AssertionError('Элементы оформления не сохранились в проекте.')
    export_pdf(window.scene, directory / 'annotated.pdf')
    if b'/Subtype /Image' not in (directory / 'annotated.pdf').read_bytes():
        raise AssertionError('В PDF нет добавленной картинки.')
    exchange.export_map(linked, directory / 'exchange.json')
    if 'image_data' in (directory / 'exchange.json').read_text(encoding='utf-8'):
        raise AssertionError('В JSON для 1С попали элементы оформления.')
    window.dirty = False
    window.close()
    (directory / "success.txt").write_text("OK: XLSX, GUI, movement, project, A4 PDF, annotations, 1C JSON\n",
                                           encoding="utf-8")
    return 0


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        return smoke_test(sys.argv[2])
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
