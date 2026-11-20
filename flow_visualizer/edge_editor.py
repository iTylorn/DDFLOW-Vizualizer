"""Interactive connector with an editable, persisted set of route points.

Coordinates are in scene space.  Only intermediate points belong to the
project; both ends are recalculated from the current card boundaries.
"""
from math import hypot

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QPainter, QPainterPath,
                           QPainterPathStroker, QPen, QPolygonF)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject


def _point(value):
    if isinstance(value, QPointF):
        return QPointF(value)
    return QPointF(float(value[0]), float(value[1]))


def _same(a, b):
    return abs(a.x() - b.x()) < 0.001 and abs(a.y() - b.y()) < 0.001


def _connection_rect(item):
    """Use the drawn card, excluding decorative icons and selection margins."""
    physical_rect = getattr(item, 'connection_rect', None)
    if callable(physical_rect):
        return QRectF(physical_rect())
    return QRectF(item.sceneBoundingRect())


def _simplify(points):
    """Remove repeated and collinear auto-router bends, not user bends."""
    clean = []
    for p in points:
        p = _point(p)
        if not clean or not _same(p, clean[-1]):
            clean.append(p)
    result = []
    for p in clean:
        while len(result) >= 2:
            a, b = result[-2:]
            cross = (b.x() - a.x()) * (p.y() - b.y()) - (b.y() - a.y()) * (p.x() - b.x())
            # Remove only intermediate points travelling in the same direction.
            dot = (b.x() - a.x()) * (p.x() - b.x()) + (b.y() - a.y()) * (p.y() - b.y())
            if abs(cross) > 0.001 or dot < 0:
                break
            result.pop()
        result.append(p)
    return result


def _anchor(rect, toward, fallback):
    """Intersect a ray from a node's center to a waypoint with its border."""
    rect = QRectF(rect)
    center = rect.center()
    point = _point(toward)
    dx, dy = point.x() - center.x(), point.y() - center.y()
    if rect.contains(point) or (abs(dx) < 0.0001 and abs(dy) < 0.0001):
        point = _point(fallback)
        dx, dy = point.x() - center.x(), point.y() - center.y()
    if abs(dx) < 0.0001 and abs(dy) < 0.0001:
        dx = 1.0
    sx = (rect.width() / 2.0 / abs(dx)) if abs(dx) > 0.0001 else float('inf')
    sy = (rect.height() / 2.0 / abs(dy)) if abs(dy) > 0.0001 else float('inf')
    scale = min(sx, sy)
    return QPointF(center.x() + dx * scale, center.y() + dy * scale)


class EditableEdgeItem(QGraphicsObject):
    """Scene connector selected with one click and edited by dragging handles.

    Args:
        edge: The model Edge; never mutated by this component.
        source, target: Existing scene node items; connection_rect() gives the
            visible card boundary, with sceneBoundingRect() as a fallback.
        view: 'compact' or 'detailed', passed back unchanged.
        auto_points: no-argument callable returning the entire auto-routed path.
        on_change: callback(edge, view, [[x, y], ...]); empty means reset.
        on_finish: optional no-argument callback after a drag or reset.
    """
    HANDLE_RADIUS = 7.0

    def __init__(self, edge, source, target, view, auto_points, on_change, on_finish=None):
        super().__init__()
        self.edge = edge
        self.source, self.target = source, target
        self.view, self.auto_points = view, auto_points
        self.on_change, self.on_finish = on_change, on_finish
        self._manual = [_point(point) for point in edge.routes.get(view, [])]
        self._points = []
        self._handles = []
        self._shape = QPainterPath()
        self._bounds = QRectF()
        self._head = QPolygonF()
        self._show_handles = True
        self._drag_index = None
        self._segment_drag = None
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('Перетащите участок линии параллельно или круглую точку. Двойной щелчок добавляет точку.')
        # Behind cards, so connection points never intercept node dragging.
        self.setZValue(1)
        self.update_endpoints()

    def boundingRect(self):
        return QRectF(self._bounds)

    def shape(self):
        stroker = QPainterPathStroker()
        stroker.setWidth(14.0)
        shape = stroker.createStroke(self._shape)
        if self.isSelected() and self._show_handles:
            for point in self._handles:
                shape.addEllipse(point, self.HANDLE_RADIUS + 2, self.HANDLE_RADIUS + 2)
        return shape

    def _recompute(self):
        source_rect, target_rect = _connection_rect(self.source), _connection_rect(self.target)
        if self._manual:
            points = [_anchor(source_rect, self._manual[0], target_rect.center())]
            points.extend(QPointF(p) for p in self._manual)
            points.append(_anchor(target_rect, self._manual[-1], source_rect.center()))
            handles = [QPointF(p) for p in self._manual]
        else:
            points = _simplify(self.auto_points())
            if len(points) < 2:
                points = [_anchor(source_rect, target_rect.center(), target_rect.center()),
                          _anchor(target_rect, source_rect.center(), source_rect.center())]
            handles = [QPointF(point) for point in points[1:-1]]
            if not handles:
                a, b = points[0], points[-1]
                handles = [QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)]

        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        end = points[-1]
        previous = next((point for point in reversed(points[:-1]) if not _same(point, end)), None)
        head = QPolygonF()
        if previous is not None:
            dx, dy = end.x() - previous.x(), end.y() - previous.y()
            length = hypot(dx, dy)
            ux, uy = dx / length, dy / length
            head = QPolygonF([end, QPointF(end.x()-ux*11-uy*5, end.y()-uy*11+ux*5),
                              QPointF(end.x()-ux*11+uy*5, end.y()-uy*11-ux*5)])

        self.prepareGeometryChange()
        self._points, self._handles, self._shape, self._head = points, handles, path, head
        bounds = path.boundingRect()
        if not head.isEmpty():
            bounds = bounds.united(head.boundingRect())
        # Hit-testing uses a 14-pixel-wide stroke; it must fit in the item's
        # bounds or thin connectors are unexpectedly difficult to select.
        pad = 8 if self._show_handles else 3
        bounds = bounds.adjusted(-pad, -pad, pad, pad)
        if self.isSelected() and self._show_handles:
            for point in handles:
                r = self.HANDLE_RADIUS + 2
                bounds = bounds.united(QRectF(point.x()-r, point.y()-r, 2*r, 2*r))
        self._bounds = bounds
        self.update()

    def update_endpoints(self):
        """Recompute attached endpoints and refresh automatic/manual path."""
        self._recompute()

    def set_edit_handles_visible(self, visible):
        """Hide editing marks and their bounds during print; restore afterward."""
        visible = bool(visible)
        if self._show_handles != visible:
            self._show_handles = visible
            self._recompute()

    def reset_route(self):
        """Return only this connector in this view to automatic routing."""
        self._manual = []
        self._recompute()
        self.on_change(self.edge, self.view, [])
        if self.on_finish is not None:
            self.on_finish()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._recompute()
        return super().itemChange(change, value)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Selection outlines and handles are editing aids, not print content.
        selected = self.isSelected() and self._show_handles
        color = QColor('#2878b8' if selected else '#536f83')
        painter.setPen(QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._shape)
        if not self._head.isEmpty():
            painter.setPen(QPen(color, 1))
            painter.setBrush(QBrush(color))
            painter.drawPolygon(self._head)
        if selected:
            painter.setPen(QPen(QColor('#2878b8'), 1.6))
            painter.setBrush(QBrush(QColor('white')))
            for point in self._handles:
                painter.drawEllipse(point, self.HANDLE_RADIUS - 1, self.HANDLE_RADIUS - 1)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isSelected() and self._show_handles:
            pos = event.pos()
            distances = [hypot(p.x()-pos.x(), p.y()-pos.y()) for p in self._handles]
            if distances and min(distances) <= self.HANDLE_RADIUS + 4:
                self._drag_index = distances.index(min(distances))
                if not self._manual:
                    self._manual = [QPointF(p) for p in self._handles]
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton and self._show_handles:
            pos = event.pos()
            best = self._nearest_segment(pos)
            if best is not None and best[0] <= 10:
                _, index, _ = best
                points = [QPointF(p) for p in self._points]
                a, b = points[index], points[index + 1]
                dx, dy = b.x() - a.x(), b.y() - a.y()
                length = hypot(dx, dy)
                if length > 0.001:
                    manual = [QPointF(p) for p in points[1:-1]]
                    if index == 0:
                        manual.insert(0, QPointF(a))
                        first = 0
                    else:
                        first = index - 1
                    if index == len(points) - 2:
                        manual.append(QPointF(b))
                    if not self.isSelected():
                        self.scene().clearSelection()
                        self.setSelected(True)
                    self._segment_drag = (first, first + 1, manual, QPointF(pos), QPointF(-dy / length, dx / length))
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._segment_drag is not None:
            first, second, original, start, normal = self._segment_drag
            offset = event.pos() - start
            amount = offset.x() * normal.x() + offset.y() * normal.y()
            self._manual = [QPointF(p) for p in original]
            self._manual[first] += normal * amount
            self._manual[second] += normal * amount
            self._recompute()
            self.on_change(self.edge, self.view, [[p.x(), p.y()] for p in self._manual])
            event.accept()
            return
        if self._drag_index is not None:
            self._manual[self._drag_index] = QPointF(event.pos())
            self._recompute()
            self.on_change(self.edge, self.view, [[p.x(), p.y()] for p in self._manual])
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._segment_drag is not None:
            self._segment_drag = None
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            if self.on_finish is not None:
                self.on_finish()
            event.accept()
            return
        if self._drag_index is not None:
            self._drag_index = None
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            if self.on_finish is not None:
                self.on_finish()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _nearest_segment(self, pos):
        best = None
        for index, (a, b) in enumerate(zip(self._points, self._points[1:])):
            dx, dy = b.x() - a.x(), b.y() - a.y()
            denominator = dx * dx + dy * dy
            ratio = max(0.0, min(1.0, ((pos.x()-a.x())*dx + (pos.y()-a.y())*dy) / denominator)) if denominator else 0.0
            projection = QPointF(a.x() + ratio*dx, a.y() + ratio*dy)
            distance = hypot(projection.x()-pos.x(), projection.y()-pos.y())
            if best is None or distance < best[0]:
                best = (distance, index, projection)
        return best

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self._show_handles:
            super().mouseDoubleClickEvent(event)
            return
        best = self._nearest_segment(event.pos())
        if best is None or best[0] > 10:
            super().mouseDoubleClickEvent(event)
            return
        if not self._manual:
            self._manual = [QPointF(point) for point in self._points[1:-1]]
        self._manual.insert(best[1], best[2])
        self.setSelected(True)
        self._recompute()
        self.on_change(self.edge, self.view, [[p.x(), p.y()] for p in self._manual])
        if self.on_finish is not None:
            self.on_finish()
        event.accept()
