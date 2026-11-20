"""Group outlines with wrapped headings contained inside their frames."""
from collections import defaultdict
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen, QTextOption
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsRectItem, QGraphicsTextItem


class GroupTitleItem(QGraphicsTextItem):
    def text(self):
        return self.toPlainText()


def _make_title(name, width, font_size):
    label = GroupTitleItem()
    font = QFont('Segoe UI', font_size)
    font.setBold(True)
    label.setFont(font)
    label.setDefaultTextColor(QColor('#526875'))
    label.document().setDocumentMargin(0)
    option = label.document().defaultTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    label.document().setDefaultTextOption(option)
    label.setPlainText(name or 'Группа без названия')
    label.setTextWidth(max(1.0, width))
    return label


def group_title_height(name, frame_width, font_size):
    """Measure the wrapped title by the same rules used to draw it."""
    return _make_title(name, max(1.0, frame_width - 22), font_size).boundingRect().height()


def _frame_geometry(content, name, font_size, below=False):
    frame = QRectF(content).adjusted(-18, 0, 18, 0)
    label = _make_title(name, max(1.0, frame.width() - 22), font_size)
    header = label.boundingRect().height() + 20
    if below:
        frame.setTop(content.top() - 18)
        frame.setBottom(content.bottom() + header)
        label.setPos(frame.left() + 11, content.bottom() + 8)
    else:
        frame.setTop(content.top() - header)
        frame.setBottom(content.bottom() + 18)
        label.setPos(frame.left() + 11, frame.top() + 8)
    return frame, label


def draw_group_frames(scene, groups, nodes, font_size=18):
    members = defaultdict(list)
    all_nodes = []
    for node in nodes.values():
        if node.isVisible():
            rect = node.sceneBoundingRect()
            all_nodes.append((node.stage.group_id, rect))
            if node.stage.group_id:
                members[node.stage.group_id].append(rect)
    result = []
    occupied = []
    for group in groups:
        rects = members.get(group.id)
        if not rects:
            continue
        content = QRectF(rects[0])
        for rect in rects[1:]:
            content = content.united(rect)
        foreign = [rect for ident, rect in all_nodes if ident != group.id]
        frame, _ = _frame_geometry(content, group.name, font_size)
        contents = rects if any(frame.intersects(rect) for rect in foreign) else [content]
        for content_rect in contents:
            frame, label = _frame_geometry(content_rect, group.name, font_size)
            title_rect = label.mapRectToScene(label.boundingRect())
            if any(title_rect.intersects(other) for other in [*foreign, *occupied]):
                alternate, alternate_label = _frame_geometry(content_rect, group.name, font_size, below=True)
                alternate_title = alternate_label.mapRectToScene(alternate_label.boundingRect())
                if not any(alternate_title.intersects(other) for other in [*foreign, *occupied]):
                    frame, label, title_rect = alternate, alternate_label, alternate_title
            occupied.append(title_rect)
            path = QPainterPath()
            path.addRoundedRect(frame, 12, 12)
            outline = QGraphicsPathItem(path)
            outline.setPen(QPen(QColor('#9aaab4'), 1.4))
            outline.setBrush(QBrush(QColor(224, 232, 236, 45)))
            outline.setZValue(-20)
            outline.setData(0, ('group', group.id))
            outline.setAcceptedMouseButtons(Qt.NoButton)
            scene.addItem(outline)
            backdrop = QGraphicsRectItem(title_rect.adjusted(-3, -2, 3, 2))
            backdrop.setPen(QPen(Qt.NoPen))
            backdrop.setBrush(QBrush(QColor('#f3f6f8')))
            backdrop.setAcceptedMouseButtons(Qt.NoButton)
            backdrop.setZValue(11)
            backdrop.setData(0, ('group', group.id))
            label.setAcceptedMouseButtons(Qt.NoButton)
            label.setZValue(12)
            label.setData(0, ('group', group.id))
            scene.addItem(backdrop)
            scene.addItem(label)
            result.extend((outline, backdrop, label))
    return result
