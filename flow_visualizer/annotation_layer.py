"""Presentation elements placed independently of the flow diagram."""
from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from dataclasses import replace
from math import hypot

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, QSizeF, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QImage, QImageReader, QPainter, QPainterPath,
                           QPainterPathStroker, QPen, QPolygonF)
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QFontComboBox, QFormLayout, QGraphicsItem, QGraphicsObject, QPlainTextEdit,
                               QPushButton)

try:
    from .number_field import number_field
except ImportError:
    from number_field import number_field


LABELS = {
    'text': 'Текст', 'rectangle': 'Прямоугольник', 'rounded': 'Скруглённый прямоугольник',
    'ellipse': 'Эллипс', 'triangle': 'Треугольник', 'line': 'Линия',
    'arrow': 'Стрелка', 'image': 'Картинка',
}
LINES = ('arrow', 'line')
HANDLE_SIZE = 12


def read_picture(path):
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise ValueError(reader.errorString())
    encoded = QBuffer()
    if not encoded.open(QIODevice.WriteOnly) or not image.save(encoded, 'PNG'):
        raise ValueError('Не удалось сохранить изображение в проект.')
    return image, b64encode(bytes(encoded.data())).decode('ascii')


class AnnotationItem(QGraphicsObject):
    def __init__(self, annotation, changed, edit):
        super().__init__()
        self.annotation = annotation
        self.changed = changed
        self.edit = edit
        self._drag_handle = None
        self._gesture_start = None
        self._image = None
        if annotation.kind == 'image':
            try:
                self._image = QImage.fromData(b64decode(annotation.image_data, validate=True))
            except Base64Error:
                self._image = QImage()
        self.setPos(annotation.x, annotation.y)
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)

    @property
    def is_line(self):
        return self.annotation.kind in LINES

    def _end(self):
        return QPointF(self.annotation.width, self.annotation.height)

    def _rect(self):
        return QRectF(QPointF(), self._end()).normalized()

    def _handles(self):
        if self.is_line:
            return {'start': QPointF(), 'end': self._end()}
        return {'end': self._end()}

    def _arrow_head(self):
        end = self._end()
        distance = hypot(end.x(), end.y())
        unit = end / distance
        side = QPointF(-unit.y(), unit.x())
        length = min(distance * .55, max(14, self.annotation.stroke_width * 3.4))
        return QPolygonF([end, end - unit * length + side * (length * .43),
                          end - unit * length - side * (length * .43)])

    def boundingRect(self):
        bounds = self._rect()
        if self.annotation.kind == 'arrow':
            bounds = bounds.united(self._arrow_head().boundingRect())
        padding = max(HANDLE_SIZE, self.annotation.stroke_width / 2 + 1)
        return bounds.adjusted(-padding, -padding, padding, padding)

    def shape(self):
        path = QPainterPath()
        if self.is_line:
            path.moveTo(QPointF())
            path.lineTo(self._end())
            stroker = QPainterPathStroker()
            stroker.setWidth(max(18, self.annotation.stroke_width))
            path = stroker.createStroke(path)
            if self.annotation.kind == 'arrow':
                head = QPainterPath()
                head.addPolygon(self._arrow_head())
                path = path.united(head)
        else:
            path.addRect(self._rect())
        if self.isSelected():
            for point in self._handles().values():
                grip = QPainterPath()
                grip.addRect(self._handle_rect(point))
                path = path.united(grip)
        return path

    @staticmethod
    def _handle_rect(point):
        return QRectF(point - QPointF(HANDLE_SIZE / 2, HANDLE_SIZE / 2),
                      QSizeF(HANDLE_SIZE, HANDLE_SIZE))

    def paint(self, painter, option, widget=None):
        a = self.annotation
        rect = self._rect()
        painter.save()
        if a.stroke and a.stroke_width:
            pen = QPen(QColor(a.stroke), a.stroke_width)
            pen.setJoinStyle(Qt.RoundJoin)
            if a.dashed:
                pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
        else:
            painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(a.fill) if a.fill else Qt.NoBrush)
        if a.kind in ('text', 'rectangle'):
            painter.drawRect(rect)
        elif a.kind == 'rounded':
            painter.drawRoundedRect(rect, 12, 12)
        elif a.kind == 'ellipse':
            painter.drawEllipse(rect)
        elif a.kind == 'triangle':
            painter.drawPolygon(QPolygonF([QPointF(rect.center().x(), rect.top()),
                                           rect.bottomRight(), rect.bottomLeft()]))
        elif a.kind == 'image':
            if self._image is not None and not self._image.isNull():
                painter.setRenderHint(QPainter.SmoothPixmapTransform)
                painter.drawImage(rect, self._image)
            else:
                painter.setPen(QColor('#a12b31'))
                painter.drawText(rect, Qt.AlignCenter, 'Картинка недоступна')
        elif self.is_line and a.stroke_width and a.stroke:
            if a.kind == 'arrow':
                head = self._arrow_head()
                base = (head[1] + head[2]) / 2
                # Overlap the head slightly at its base. The shaft never
                # reaches the tip, even with a thick pen or a short arrow.
                shaft_end = base + (head[0] - base) * .08
                pen.setCapStyle(Qt.FlatCap)
                pen.setWidthF(min(pen.widthF(), .75 * hypot(head[1].x() - head[2].x(),
                                                           head[1].y() - head[2].y())))
                painter.setPen(pen)
                painter.drawLine(QPointF(), shaft_end)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(a.stroke))
                painter.drawPolygon(head)
            else:
                painter.drawLine(QPointF(), self._end())

        if a.text and a.kind not in (*LINES, 'image'):
            font = QFont(a.font_family, a.font_size)
            font.setBold(a.bold)
            font.setItalic(a.italic)
            painter.setFont(font)
            painter.setPen(QColor(a.text_color))
            content = rect.adjusted(8, 6, -8, -6)
            if not content.isEmpty():
                alignment = {'left': Qt.AlignLeft, 'center': Qt.AlignHCenter, 'right': Qt.AlignRight}
                painter.setClipRect(content)
                painter.drawText(content, alignment[a.alignment] | Qt.AlignVCenter | Qt.TextWordWrap, a.text)
        painter.restore()

        if self.isSelected() and widget is not None:
            painter.save()
            pen = QPen(QColor('#1572aa'), 1, Qt.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            if not self.is_line:
                painter.drawRect(rect)
            painter.setBrush(QColor('white'))
            for point in self._handles().values():
                painter.drawRect(self._handle_rect(point))
            painter.restore()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.annotation.x, self.annotation.y = value.x(), value.y()
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._gesture_start = (self.annotation.x, self.annotation.y,
                                   self.annotation.width, self.annotation.height)
            if self.isSelected():
                for name, point in self._handles().items():
                    if self._handle_rect(point).contains(event.pos()):
                        self._drag_handle = name
                        self._resize_start = event.scenePos()
                        event.accept()
                        return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_handle is not None:
            self._resize(event.scenePos() - self._resize_start)
            event.accept()
            return
        if event.buttons() & Qt.LeftButton and self.scene():
            for item in self.scene().selectedItems():
                if item is not self:
                    item.setSelected(False)
        super().mouseMoveEvent(event)

    def _resize(self, delta):
        x, y, width, height = self._gesture_start
        origin = QPointF(x, y)
        size = QPointF(width, height)
        if self.is_line:
            if self._drag_handle == 'start':
                origin += delta
                size -= delta
            else:
                size += delta
            if hypot(size.x(), size.y()) < 12:
                return
        elif self.annotation.kind == 'image' and self.annotation.keep_aspect:
            # Project the cursor motion onto the image diagonal to resize from its corner.
            scale = 1 + (delta.x() * width + delta.y() * height) / (width * width + height * height)
            size *= max(12 / min(width, height), scale)
        else:
            size = QPointF(max(12, width + delta.x()), max(12, height + delta.y()))
        self.prepareGeometryChange()
        self.annotation.width, self.annotation.height = size.x(), size.y()
        self.setPos(origin)
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_handle is not None:
            self._resize(event.scenePos() - self._resize_start)
            self._drag_handle = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)
        a = self.annotation
        if self._gesture_start is not None and self._gesture_start != (a.x, a.y, a.width, a.height):
            self.changed()
        self._gesture_start = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            event.accept()
            edit, ident = self.edit, self.annotation.id
            QTimer.singleShot(0, lambda: edit(ident))
            return
        super().mouseDoubleClickEvent(event)


def edit_annotation(parent, annotation, *, dialog_title=None, font_range=(6, 240)):
    dialog = QDialog(parent)
    dialog.setWindowTitle(dialog_title or LABELS[annotation.kind] + ' — оформление')
    dialog.setMinimumWidth(390)
    form = QFormLayout(dialog)
    readers = {}

    def checkbox(key, label):
        field = QCheckBox()
        field.setChecked(getattr(annotation, key))
        form.addRow(label, field)
        readers[key] = field.isChecked

    def number(key, label, low, high):
        field, row = number_field(key, getattr(annotation, key), low, high)
        form.addRow(label, row)
        readers[key] = field.value

    def color(key, label, transparent=False):
        button = QPushButton()
        button.setObjectName(key)

        def set_color(value):
            button.setProperty('color', value)
            button.setText(value or 'Прозрачный')

        def choose():
            selected = QColorDialog.getColor(QColor(button.property('color') or 'white'), dialog, label)
            if selected.isValid():
                set_color(selected.name())

        set_color(getattr(annotation, key))
        button.clicked.connect(choose)
        if transparent:
            button.setToolTip('Щелчок правой кнопкой убирает цвет')
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda _: set_color(''))
        form.addRow(label, button)
        readers[key] = lambda: button.property('color')

    if annotation.kind == 'image':
        checkbox('keep_aspect', 'Сохранять пропорции')
    else:
        if annotation.kind not in LINES:
            text = QPlainTextEdit(annotation.text)
            text.setPlaceholderText('Введите текст')
            form.addRow('Текст', text)
            readers['text'] = text.toPlainText
            font_family = QFontComboBox()
            font_family.setCurrentFont(QFont(annotation.font_family))
            form.addRow('Шрифт', font_family)
            readers['font_family'] = lambda: font_family.currentFont().family()
            number('font_size', 'Размер шрифта, пт', *font_range)
            checkbox('bold', 'Полужирный')
            checkbox('italic', 'Курсив')
            alignment = QComboBox()
            for caption, value in [('Слева', 'left'), ('По центру', 'center'), ('Справа', 'right')]:
                alignment.addItem(caption, value)
            alignment.setCurrentIndex(alignment.findData(annotation.alignment))
            form.addRow('Выравнивание текста', alignment)
            readers['alignment'] = alignment.currentData
            color('text_color', 'Цвет текста')
            color('fill', 'Заливка', transparent=True)
        color('stroke', 'Цвет линии')
        number('stroke_width', 'Толщина линии', 1 if annotation.kind in LINES else 0, 40)
        checkbox('dashed', 'Штриховая линия')

    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QDialog.Accepted:
        return None
    return replace(annotation, **{key: read() for key, read in readers.items()})
