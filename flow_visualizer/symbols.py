"""Reusable visual signs for warehouse category and inventory buffer."""
from PySide6.QtCore import QRectF, Qt, QPointF
from PySide6.QtGui import QColor, QPainterPath, QPen, QFont


# Labels and enum names match DD FLOW. Symbols are rendered by this module.
ALGORITHMS = (
    ('График запуска по пакетной спецификации', 'ГрафикЗапускаПоПакетнойСпецификации', 'batch'),
    ('График выпуска по номенклатурам', 'ГрафикВыпускаПоНоменклатурам', 'items'),
    ('График выпуска по номенклатурам и оборудованию', 'ГрафикВыпускаПоНоменклатурамИОборудованию', 'equipment'),
    ('График выпуска по плану производства', 'ГрафикВыпускаПоПлануПроизводства', 'plan'),
    ('График выпуска по сборке/разборке', 'ГрафикВыпускаПоСборкеРазборке', 'assembly'),
    ('График выпуска по расписанию APS', 'ГрафикВыпускаПоРасписаниюAPS', 'aps'),
)
# The labels are the actual values of Enum.Поток_МакетПланаЗапуска.
# The short form is used in the editor; the complete 1C label is in the legend.
LAYOUTS = (
    ('none', 'Без группировки', 'Производство без группировки'),
    ('setup', 'С группировкой по коду переналадки', 'Производство с группировкой по коду переналадки'),
    ('assignments', 'С группировкой по назначениям', 'Производство с группировкой по назначениям'),
    ('demand', 'Группировка по источнику потребности', 'Группировка по источнику потребности (производство)'),
)
LAYOUT_LABELS = {key: full for key, _, full in LAYOUTS}
LEGACY_LAYOUT = 'product'
LEGACY_LAYOUT_LABEL = 'По головному изделию (прежнее обозначение)'
UNKNOWN_LAYOUT = 'unknown'
UNKNOWN_LAYOUT_LABEL = 'Макет из 1С не распознан / недоступен'


def layout_label(value):
    if value == LEGACY_LAYOUT:
        return LEGACY_LAYOUT_LABEL
    if value == UNKNOWN_LAYOUT:
        return UNKNOWN_LAYOUT_LABEL
    return LAYOUT_LABELS.get(value or 'none', LAYOUT_LABELS['none'])


def algorithm_kind(value):
    normalized = ''.join((value or '').casefold().split())
    for label, ident, kind in ALGORITHMS:
        if normalized in (''.join(label.casefold().split()), ident.casefold()):
            return kind
    return 'unknown'


def is_retired_algorithm(value, option_ids=None):
    name = (value or '').strip()
    if name.casefold().startswith('удалить'):
        return True
    return any(str(ident).strip().casefold().startswith('удалить') and label == name
               for ident, label in (option_ids or {}).items())


def frame_pen(layout, selected=False):
    pen = QPen(QColor('#246aa0') if selected else QColor('#20262c'), 6.9 if selected else 6.0)
    if layout == 'assignments':
        pen.setStyle(Qt.DotLine)
    elif layout == 'setup':
        pen.setStyle(Qt.DashLine)
    elif layout == 'demand':
        pen.setStyle(Qt.DashDotLine)
    elif layout == LEGACY_LAYOUT:
        pen.setStyle(Qt.DashDotDotLine)
    elif layout == UNKNOWN_LAYOUT:
        pen.setColor(QColor('#ba3030'))
        pen.setStyle(Qt.DashDotDotLine)
    return pen


def draw_algorithm(painter, rect, kind):
    """Vector signs for the schedules, with a neutral fallback for others."""
    painter.save()
    rect = QRectF(rect)
    painter.translate(rect.left(), rect.top())
    painter.scale(rect.width() / 28.0, rect.height() / 28.0)
    labels = {'batch': ('ПС', '#285E75'), 'items': ('Н', '#254B89'),
              'equipment': ('НО', '#7D4831'), 'plan': ('ПП', '#356842')}
    if kind in labels:
        label, color = labels[kind]
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(QRectF(1, 1, 26, 26), 5, 5)
        font = QFont('Segoe UI')
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor('#ffffff'))
        painter.drawText(QRectF(1, 1, 26, 26), Qt.AlignCenter, label)
        painter.restore()
        return
    painter.setPen(QPen(QColor('#20262c'), 0.8))
    painter.setBrush(QColor('#f8f8f8'))
    painter.drawRect(QRectF(1, 1, 26, 26))
    painter.drawLine(QPointF(4, 4), QPointF(4, 24))
    painter.drawLine(QPointF(4, 24), QPointF(24, 24))
    if kind not in ('assembly', 'aps'):
        font = QFont('Segoe UI', 14); font.setBold(True)
        painter.setFont(font); painter.drawText(QRectF(5, 2, 20, 22), Qt.AlignCenter, '?')
    elif kind == 'assembly':
        painter.setPen(QPen(QColor('#263744'), 1.1))
        for box, color in ((QRectF(6, 5, 5, 5), '#00aeef'),
                           (QRectF(6, 17, 5, 5), '#e9bc35'),
                           (QRectF(19, 11, 6, 6), '#25a27a')):
            painter.setBrush(QColor(color)); painter.drawRect(box)
        painter.drawLine(QPointF(11, 8), QPointF(15, 13))
        painter.drawLine(QPointF(11, 19), QPointF(15, 15))
        painter.drawLine(QPointF(15, 13), QPointF(19, 13))
        painter.drawLine(QPointF(16, 15), QPointF(19, 15))
        painter.drawLine(QPointF(16, 15), QPointF(17.5, 16.5))
    elif kind == 'aps':
        for index, (x, width, color) in enumerate(((6, 9, '#00aeef'), (10, 12, '#e9bc35'), (7, 11, '#25a27a'))):
            painter.setBrush(QColor(color))
            painter.drawRect(QRectF(x, 5 + index * 4, width, 2.5))
        font = QFont('Segoe UI'); font.setPixelSize(7); font.setBold(True)
        painter.setFont(font); painter.setPen(QColor('#263744'))
        painter.drawText(QRectF(5, 17, 19, 7), Qt.AlignCenter, 'APS')
    painter.restore()


# These symbols show a warehouse's explicitly stored category. They do not
# derive the category from its role as a stage's inlet or stock location.
WAREHOUSE_BADGES = {
    'ordinary': ('М', '#2878b8'),
    'workshop': ('Ц', '#bd702b'),
    '': ('?', '#73838f'),
}


def warehouse_badge_html(warehouse_type):
    """An inline, measured QTextDocument sign for cards and legend."""
    letter, color = WAREHOUSE_BADGES.get(warehouse_type, WAREHOUSE_BADGES[''])
    return ('<span style="background-color:' + color
            + '; color:#ffffff; font-weight:bold;">&nbsp;' + letter + '&nbsp;</span>')


def draw_buffer(painter, rect):
    """Draw the original green/yellow/red stock-buffer trapezoid."""
    rect = QRectF(rect)
    path = QPainterPath()
    path.moveTo(rect.left(), rect.top())
    path.lineTo(rect.right(), rect.top())
    path.lineTo(rect.right() - rect.width() * 0.18, rect.bottom())
    path.lineTo(rect.left() + rect.width() * 0.18, rect.bottom())
    path.closeSubpath()
    painter.save()
    painter.setClipPath(path)
    height = rect.height() / 3.0
    for index, color in enumerate(('#2ECC71', '#F1C40F', '#E74C3C')):
        painter.fillRect(QRectF(rect.left(), rect.top() + index * height,
                                rect.width(), height + 0.1), QColor(color))
    painter.restore()
    painter.save()
    painter.setPen(QPen(QColor('#20262c'), 1.0))
    painter.setBrush(QColor(0, 0, 0, 0))
    painter.drawPath(path)
    painter.restore()
