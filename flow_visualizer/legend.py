"""Compact horizontal legend below the diagram and the material-flow arrow."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPen, QTextOption
from PySide6.QtWidgets import QGraphicsObject, QGraphicsRectItem, QGraphicsTextItem

try:
    from .symbols import warehouse_badge_html, draw_buffer, draw_algorithm, frame_pen, ALGORITHMS, LAYOUTS, LEGACY_LAYOUT, LEGACY_LAYOUT_LABEL, UNKNOWN_LAYOUT, UNKNOWN_LAYOUT_LABEL
    from .colors import COMPACT_RKT_COLOR, DEFAULT_COLORS, paint_stage_fill, supports_deficit_color
except ImportError:
    from symbols import warehouse_badge_html, draw_buffer, draw_algorithm, frame_pen, ALGORITHMS, LAYOUTS, LEGACY_LAYOUT, LEGACY_LAYOUT_LABEL, UNKNOWN_LAYOUT, UNKNOWN_LAYOUT_LABEL
    from colors import COMPACT_RKT_COLOR, DEFAULT_COLORS, paint_stage_fill, supports_deficit_color

STANDARD_TYPES = ('Производство', 'Покупка', 'Логистика', 'Промуслуги', 'Сборка / Разборка')
LEGEND_WIDTH = 560.0
LEGEND_GAP = 24.0


class BufferLegendIcon(QGraphicsObject):
    def boundingRect(self):
        return QRectF(0, 0, 27, 31.5)

    def paint(self, painter, option, widget=None):
        draw_buffer(painter, QRectF(1.5, 1.5, 24, 28.5))


class ReferenceLegendIcon(QGraphicsObject):
    def __init__(self, kind, value, size, width):
        super().__init__()
        self.kind, self.value, self.size = kind, value, size
        self.width = width

    def boundingRect(self):
        return QRectF(0, 0, self.width, self.size)

    def paint(self, painter, option, widget=None):
        if self.kind == 'algorithm':
            draw_algorithm(painter, self.boundingRect(), self.value)
        else:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(frame_pen(self.value))
            painter.drawRect(self.boundingRect().adjusted(4, 7, -4, -7))


class ColorLegendSwatch(QGraphicsObject):
    def __init__(self, color, width, height, deficit=False):
        super().__init__()
        self.color = color
        self.rect = QRectF(0, 0, width, height)
        self.deficit = deficit

    def boundingRect(self):
        return self.rect

    def paint(self, painter, option, widget=None):
        paint_stage_fill(painter, self.rect, self.color, self.deficit)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor('#aebac2'), .7))
        painter.drawRect(self.rect.adjusted(.5, .5, -.5, -.5))


def _text_item(text, x, y, width, *, bold=False, size=10):
    item = QGraphicsTextItem()
    font = QFont('Segoe UI', size)
    font.setBold(bold)
    item.setFont(font)
    item.setDefaultTextColor(QColor('#263744'))
    item.document().setDocumentMargin(0)
    option = item.document().defaultTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    item.document().setDefaultTextOption(option)
    item.setPlainText(text)
    item.setTextWidth(width)
    item.setPos(x, y)
    item.setZValue(21)
    item.setAcceptedMouseButtons(Qt.NoButton)
    return item


def legend_types(stages):
    result = list(STANDARD_TYPES)
    seen = {name.casefold() for name in result}
    no_type = False
    for stage in stages:
        name = (stage.provider_type or '').strip()
        if not name:
            no_type = True
        elif name.casefold() not in seen:
            result.append(name)
            seen.add(name.casefold())
    if no_type and 'тип не указан' not in seen:
        result.append('Тип не указан')
    return result


def draw_legend(scene, stages, color_for, content_bounds, compact=False,
                rkt_color=COMPACT_RKT_COLOR, legend_area=None,
                assembly_rkt_color=DEFAULT_COLORS['assembly_rkt']):
    content = QRectF(content_bounds)
    if content.isEmpty():
        content = QRectF(0, 0, 400, 200)
    if legend_area is None:
        x, y, width = content.left(), content.bottom() + LEGEND_GAP, max(LEGEND_WIDTH, content.width())
    else:
        x, y, width = legend_area
    width = max(LEGEND_WIDTH, float(width))
    font_size = max(13, min(20, round(width / 100.0)))
    items = [_text_item('Легенда', x + 12, y + 10, width - 24, bold=True, size=font_size + 2)]
    top = y + 12 + items[0].boundingRect().height() + 8
    rkt_types = [('Производство с РКТ', QColor(rkt_color), True),
                 ('Сборка / разборка с РКТ', QColor(assembly_rkt_color), True)]
    types = [(name, color_for('' if name == 'Тип не указан' else name), supports_deficit_color(name))
             for name in legend_types(stages)] + rkt_types
    warehouses = [('ordinary', 'Обычный / материальный склад'), ('workshop', 'Цеховая кладовая'),
                  ('', 'Тип склада не задан'), (None, '★ — основной склад')]
    algorithms = [('algorithm', kind, label) for label, _, kind in ALGORITHMS]
    algorithms.append(('algorithm', 'unknown', 'Другой алгоритм РКТ'))
    layouts = [('frame', key, caption) for key, _, caption in LAYOUTS]
    if any(getattr(stage, 'launch_layout', '') == LEGACY_LAYOUT for stage in stages):
        layouts.append(('frame', LEGACY_LAYOUT, LEGACY_LAYOUT_LABEL + ' — выберите актуальный макет'))
    if any(getattr(stage, 'launch_layout', '') == UNKNOWN_LAYOUT for stage in stages):
        layouts.append(('frame', UNKNOWN_LAYOUT, UNKNOWN_LAYOUT_LABEL + ' — выберите макет'))
    columns = 3 if width >= 1050 else 2
    column_width = (width - 24) / columns
    marker_size = max(31.0, font_size * 1.8)
    frame_width = marker_size * 1.85
    left = x + 12

    def text(caption, left, top, width, bold=False):
        item = _text_item(caption, left, top, width, size=font_size, bold=bold)
        items.append(item)
        return item

    def marker(item, left, top):
        item.setPos(left, top)
        item.setZValue(21)
        item.setAcceptedMouseButtons(Qt.NoButton)
        items.append(item)

    def symbols(heading, entries, left, cursor):
        cursor += text(heading, left, cursor, column_width - 14, bold=True).boundingRect().height() + 7
        for kind, value, caption in entries:
            marker_width = frame_width if kind == 'frame' else marker_size
            label = text(caption, left + marker_width + 8, cursor, column_width - marker_width - 14)
            marker(ReferenceLegendIcon(kind, value, marker_size, marker_width), left + 2, cursor)
            cursor += max(marker_size, label.boundingRect().height()) + 5
        return cursor

    algorithms_end = symbols('Алгоритмы расписания контрольной точки', algorithms, left, top)
    layout_left = left + column_width if columns == 3 else left
    layout_top = top if columns == 3 else algorithms_end + 10
    buffer_top = symbols('Макеты плана запуска', layouts, layout_left, layout_top) + 6
    buffer = BufferLegendIcon()
    buffer.setScale(marker_size / 27.0)
    marker(buffer, layout_left + (frame_width - marker_size) / 2, buffer_top)
    buffer_label = text('Буфер запаса', layout_left + frame_width + 8, buffer_top, column_width - frame_width - 14)
    layout_end = buffer_top + max(buffer.sceneBoundingRect().height(), buffer_label.boundingRect().height())

    type_left = left + (columns - 1) * column_width
    swatch_width, swatch_height = marker_size * 1.45, marker_size * .73
    font = QFont('Segoe UI', font_size)
    label_metrics = QFontMetricsF(font)
    usual_labels = [*STANDARD_TYPES, *(name for name, _, _ in rkt_types)]
    label_width = max(label_metrics.horizontalAdvance(name) for name in usual_labels) + 2
    font.setBold(True)
    heading_metrics = QFontMetricsF(font)
    heading_width = heading_metrics.horizontalAdvance('С дефицитом') + 5
    deficit_width = min(column_width * .37, heading_width)
    gap = 12
    normal_width = min(column_width - deficit_width - gap - 8,
                       max(swatch_width + 8 + label_width, heading_metrics.horizontalAdvance('Типы переделов') + 2))
    deficit_left = type_left + normal_width + gap
    heading = text('Типы переделов', type_left, top, normal_width, bold=True)
    deficit_heading = text('С дефицитом', deficit_left, top, deficit_width, bold=True)
    cursor = top + max(heading.boundingRect().height(), deficit_heading.boundingRect().height()) + 7
    for caption, color, supports_deficit in types:
        label = text(caption, type_left + swatch_width + 8, cursor, normal_width - swatch_width - 8)
        row_height = max(swatch_height, label.boundingRect().height())
        marker_top = cursor + (row_height - swatch_height) / 2
        marker(ColorLegendSwatch(color, swatch_width, swatch_height), type_left + 2, marker_top)
        if supports_deficit:
            item = ColorLegendSwatch(color, swatch_width, swatch_height, deficit=True)
            marker(item, deficit_left + 2, marker_top)
        cursor += row_height + 5

    def warehouse_label(kind, caption, left, top, width):
        label = text(caption, left, top, width)
        if kind is not None:
            label.setHtml(warehouse_badge_html(kind) + ' — ' + caption)
        return label.boundingRect().height()

    bottom = max(algorithms_end, layout_end, cursor)
    if not compact and columns == 3:
        footer_width = (width - 24) / len(warehouses)
        end = max(warehouse_label(kind, caption, left + index * footer_width, bottom + 10, footer_width - 10)
                  for index, (kind, caption) in enumerate(warehouses))
        bottom += 10 + end
    elif not compact:
        cursor += text('Склады', type_left, cursor + 7, column_width - 14, bold=True).boundingRect().height() + 12
        for kind, caption in warehouses:
            cursor += warehouse_label(kind, caption, type_left, cursor, column_width - 14) + 5
        bottom = max(bottom, cursor)

    bounds = QRectF(x, y, width, bottom - y + 12)
    background = QGraphicsRectItem(bounds)
    background.setPen(QPen(QColor('#b8c6cf'), .8))
    background.setBrush(QBrush(QColor('white')))
    background.setAcceptedMouseButtons(Qt.NoButton)
    background.setZValue(20)
    scene.addItem(background)
    for item in items:
        scene.addItem(item)
    return [background, *items], bounds
