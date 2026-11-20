"""Standard alignment and distribution for explicitly selected cards."""
from PySide6.QtCore import QPointF, QRectF

ROUTE_PORT_OFFSET = 20.0
STANDARD_HORIZONTAL_GAP = ROUTE_PORT_OFFSET * 2 + 56.0
STANDARD_VERTICAL_GAP = 24.0


def align_selection(visuals, physicals, selected, mode, gap=STANDARD_VERTICAL_GAP,
                    horizontal_gap=STANDARD_HORIZONTAL_GAP):
    ids = list(dict.fromkeys(selected))
    if len(ids) < 2:
        raise ValueError('Выделите не менее двух переделов.')
    if any(ident not in visuals or ident not in physicals for ident in ids):
        raise ValueError('Один из выбранных переделов не найден.')
    rect = {ident: QRectF(visuals[ident]) for ident in ids}
    offsets = {ident: QPointF() for ident in ids}
    if mode in ('left', 'hcenter', 'right'):
        if mode == 'left':
            target = min(r.left() for r in rect.values())
            value = lambda r: r.left()
        elif mode == 'right':
            target = max(r.right() for r in rect.values())
            value = lambda r: r.right()
        else:
            target = (min(r.left() for r in rect.values()) + max(r.right() for r in rect.values())) / 2
            value = lambda r: r.center().x()
        for ident, r in rect.items():
            offsets[ident].setX(target - value(r))
    elif mode in ('top', 'vcenter', 'bottom'):
        if mode == 'top':
            target = min(r.top() for r in rect.values())
            value = lambda r: r.top()
        elif mode == 'bottom':
            target = max(r.bottom() for r in rect.values())
            value = lambda r: r.bottom()
        else:
            target = (min(r.top() for r in rect.values()) + max(r.bottom() for r in rect.values())) / 2
            value = lambda r: r.center().y()
        for ident, r in rect.items():
            offsets[ident].setY(target - value(r))
    elif mode in ('distribute_x', 'distribute_y', 'equal_gaps_x', 'equal_gaps_y', 'space_x', 'space_y'):
        horizontal = mode.endswith('_x')
        axis = lambda r: r.center().x() if horizontal else r.center().y()
        ordered = sorted(ids, key=lambda ident: (axis(rect[ident]), ident))
        if mode.startswith('distribute'):
            if len(ids) < 3:
                raise ValueError('Для распределения центров нужны хотя бы три передела.')
            first, last = axis(rect[ordered[0]]), axis(rect[ordered[-1]])
            step = (last - first) / (len(ordered) - 1)
            for i, ident in enumerate(ordered):
                offset = first + i * step - axis(rect[ident])
                offsets[ident] = QPointF(offset, 0) if horizontal else QPointF(0, offset)
        else:
            low = lambda r: r.left() if horizontal else r.top()
            high = lambda r: r.right() if horizontal else r.bottom()
            size = lambda r: r.width() if horizontal else r.height()
            if mode.startswith('equal_gaps'):
                available = high(rect[ordered[-1]]) - low(rect[ordered[0]])
                spacing = (available - sum(size(rect[ident]) for ident in ordered)) / (len(ordered) - 1)
                if spacing < 0:
                    raise ValueError('Недостаточно места для одинаковых промежутков.')
            else:
                spacing = horizontal_gap if horizontal else gap
            cursor = low(rect[ordered[0]])
            for ident in ordered:
                offset = cursor - low(rect[ident])
                offsets[ident] = QPointF(offset, 0) if horizontal else QPointF(0, offset)
                cursor += size(rect[ident]) + spacing
    else:
        raise ValueError('Неизвестная команда выравнивания.')

    def area(a, b):
        overlap = a.intersected(b)
        return 0 if overlap.isEmpty() else overlap.width() * overlap.height()
    for ident in ids:
        before = QRectF(physicals[ident])
        after = before.translated(offsets[ident])
        for other_id, other in physicals.items():
            if other_id == ident:
                continue
            other = QRectF(other)
            if area(after, other.translated(offsets.get(other_id, QPointF()))) > area(before, other) + 1e-6:
                raise ValueError('Выравнивание привело бы к наложению блоков. Освободите место или выберите другую команду.')
    return offsets
