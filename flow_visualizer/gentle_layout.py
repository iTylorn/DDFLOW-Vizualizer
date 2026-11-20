"""Выравнивание полос без перестроения нарисованной карты переделов.

Горизонтальные и вертикальные интервалы занятых карточек объединяются; только
пустые полосы между столбцами доводятся до стандартного интервала. Тот же перенос применяется к
ручным точкам стрелок текущего вида. Модель эта функция не изменяет.
"""
from math import isfinite

try:
    from .auto_layout import _positive_size
    from .selection_alignment import STANDARD_HORIZONTAL_GAP
except ImportError:
    from auto_layout import _positive_size
    from selection_alignment import STANDARD_HORIZONTAL_GAP


MIN_GAP = 45.0
GROUP_MARGIN = 20.0
GROUP_HORIZONTAL_MARGIN = 20.0  # group frame plus the card's scene padding



class CompactPositions(dict):
    """Новые позиции карточек и согласованное преобразование точек маршрута."""
    def __init__(self, positions, horizontal_gaps, vertical_gaps):
        super().__init__(positions)
        self.horizontal_gaps = tuple(horizontal_gaps)
        self.vertical_gaps = tuple(vertical_gaps)

    @staticmethod
    def _coordinate(value, gaps):
        value = float(value)
        if not isfinite(value):
            raise ValueError('Некорректная координата точки маршрута.')
        removed = 0.0
        for start, end, amount in gaps:
            if value >= end:
                removed += amount
            elif value > start:
                # Scale points inside a changed strip continuously; this
                # keeps a hand-drawn bend between its original neighbours.
                removed += amount * (value - start) / (end - start)
                break
            else:
                break
        return value - removed

    def transform_point(self, x, y):
        return (self._coordinate(x, self.horizontal_gaps),
                self._coordinate(y, self.vertical_gaps))


def _empty_strips(intervals, minimum=MIN_GAP, expand_small=False, split_touches=()):
    """Return original gaps and amount to remove, in axis order."""
    if not intervals:
        return []
    intervals = sorted(intervals)
    end = intervals[0][1]
    result = []
    for start, stop in intervals[1:]:
        split = start > end or (start == end and any(abs(start - x) < 1e-6 for x in split_touches))
        if split:
            distance = start - end
            if distance > minimum:
                result.append((end, start, distance - minimum))
            elif expand_small and distance < minimum:
                result.append((end, start, distance - minimum))
            end = stop
        else:
            end = max(end, stop)
    return result


def compact_existing(project, measure, measure_group=None, measure_group_header=None):
    """Return positions and ``transform_point(x, y)`` without model mutation.

    ``measure(stage)`` accepts the same two/five-value format as auto_layout.
    Bounds include the buffer icon, if any. Empty horizontal strips are set to
    the standard gap even before connections exist; vertical strips shrink;
    a group outline itself is never treated as a solid rectangle.
    """
    stages = list(project.stages)
    groups = {group.id: group for group in project.groups}
    rects = {}
    if len({stage.id for stage in stages}) != len(stages):
        raise ValueError('В проекте повторяются идентификаторы переделов.')
    for stage in stages:
        if (stage.x is None or stage.y is None or isinstance(stage.x, bool) or isinstance(stage.y, bool)
                or not isinstance(stage.x, (int, float)) or not isinstance(stage.y, (int, float))
                or not isfinite(stage.x) or not isfinite(stage.y)):
            raise ValueError('У передела не задано положение на схеме.')
        if stage.group_id and stage.group_id not in groups:
            raise ValueError('У передела не найдена группа.')
        width, height, ox, oy, _ = _positive_size(measure(stage))
        left, top = stage.x + ox, stage.y + oy
        rects[stage.id] = (left, top, left + width, top + height)

    ids = set(rects)
    if any(edge.source not in ids or edge.target not in ids for edge in project.edges):
        raise ValueError('Связь ссылается на отсутствующий передел.')
    x_intervals = [(r[0], r[2]) for r in rects.values()]
    y_intervals = [(r[1], r[3]) for r in rects.values()]
    group_joins = []
    # Protect group border and title extents, without treating the interior of
    # a frame as occupied. Thus whitespace *inside* a group can still shrink.
    for group in project.groups:
        members = [rects[s.id] for s in stages if s.group_id == group.id]
        if not members:
            continue
        left = min(r[0] for r in members)
        right = max(r[2] for r in members)
        top = min(r[1] for r in members)
        bottom = max(r[3] for r in members)
        label_width = float(measure_group(group)) if measure_group else len(group.name or '') * 9.0
        if not isfinite(label_width) or label_width < 0:
            raise ValueError('Некорректная ширина названия группы.')
        # A wrapped title is contained inside the group frame and can reflow
        # after compaction; its unwrapped width must not reserve space to the
        # right of the frame. Keep both borders and the actual heading height.
        x_intervals.extend(((left - GROUP_HORIZONTAL_MARGIN, left), (right, right + GROUP_HORIZONTAL_MARGIN)))
        group_joins.extend((left, right))
        if measure_group_header:
            header = max(float(measure_group_header(group, r[2] - r[0] + 36)) for r in members)
            if not isfinite(header) or header < 0:
                raise ValueError('Некорректная высота названия группы.')
        else:
            header = GROUP_MARGIN + 14
        y_intervals.extend(((top - header, top), (bottom, bottom + max(GROUP_MARGIN, header))))
    # Equal x coordinates shared by two columns count as a zero-width gap,
    # except where a group's border joins its own content.
    starts = {r[0] for r in rects.values()}
    ends = {r[2] for r in rects.values()}
    touches = [x for x in starts & ends if not any(abs(x - join) < 1e-6 for join in group_joins)]
    horizontal_gaps = _empty_strips(x_intervals, STANDARD_HORIZONTAL_GAP, True, touches)
    vertical_gaps = _empty_strips(y_intervals)
    result = CompactPositions({}, horizontal_gaps, vertical_gaps)
    for stage in stages:
        left, top, _, _ = rects[stage.id]
        new_left, new_top = result.transform_point(left, top)
        # The card remains rigid; only its position changes.
        result[stage.id] = (stage.x + new_left - left, stage.y + new_top - top)
    return result
