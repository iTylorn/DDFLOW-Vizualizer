"""Screen-scale-aware alignment of stage cards during a manual drag.

This module is pure geometry: it changes neither model nor scene.  The caller
draws the returned transient guides and applies the returned delta only to the
position proposed by the user.  Programmatic placement need not call it.
"""
from math import isfinite

from PySide6.QtCore import QLineF, QPointF, QRectF

try:
    from .selection_alignment import STANDARD_HORIZONTAL_GAP
except ImportError:
    from selection_alignment import STANDARD_HORIZONTAL_GAP


def _rect(value):
    rect = QRectF(value).normalized()
    if (rect.isEmpty() or not all(isfinite(v) for v in
            (rect.left(), rect.top(), rect.width(), rect.height()))):
        raise ValueError('Границы карточки должны быть конечными и непустыми.')
    return rect


def _area(a, b):
    intersection = a.intersected(b)
    return 0.0 if intersection.isEmpty() else intersection.width() * intersection.height()


def _candidates(card, others, tolerance, horizontal, gap, near_limit, moving_bounds, obstacle_bounds):
    if horizontal:
        positions = (card.left(), card.center().x(), card.right())
        references = lambda r: (r.left(), r.center().x(), r.right())
        distance = lambda r: abs(r.center().y() - card.center().y())
    else:
        positions = (card.top(), card.center().y(), card.bottom())
        references = lambda r: (r.top(), r.center().y(), r.bottom())
        distance = lambda r: abs(r.center().x() - card.center().x())
    result = []
    for index, other in enumerate(others):
        for alignment, (position, target) in enumerate(zip(positions, references(other))):
            delta = target - position
            if abs(delta) <= tolerance:
                result.append((abs(delta), distance(other), alignment, index, delta, target, other))
        # Besides equal edges/centres, allow adjoining cards with a small
        # screen-space gap. Restrict these guides to nearby perpendicular
        # spans so a distant card does not unexpectedly capture the pointer.
        if horizontal:
            perpendicular_gap = max(other.top() - card.bottom(), card.top() - other.bottom(), 0.0)
            left_overhang = max(0.0, card.left() - moving_bounds.left())
            right_overhang = max(0.0, moving_bounds.right() - card.right())
            neighbor = obstacle_bounds[index]
            adjacent = ((card.left(), other.right() + gap + left_overhang + max(0.0, neighbor.right() - other.right())),
                        (card.right(), other.left() - gap - right_overhang - max(0.0, other.left() - neighbor.left())))
        else:
            perpendicular_gap = max(other.left() - card.right(), card.left() - other.right(), 0.0)
            top_overhang = max(0.0, card.top() - moving_bounds.top())
            bottom_overhang = max(0.0, moving_bounds.bottom() - card.bottom())
            neighbor = obstacle_bounds[index]
            adjacent = ((card.top(), other.bottom() + gap + top_overhang + max(0.0, neighbor.bottom() - other.bottom())),
                        (card.bottom(), other.top() - gap - bottom_overhang - max(0.0, other.top() - neighbor.top())))
        if perpendicular_gap <= near_limit:
            for offset, (position, target) in enumerate(adjacent):
                delta = target - position
                if abs(delta) <= tolerance:
                    result.append((abs(delta), distance(other), 3 + offset, index, delta, target, other))
    result.sort(key=lambda item: item[:4])
    # A handful of the closest candidates is sufficient for fallback when
    # one would collide, and bounds the cost for large diagrams.
    unique = []
    for item in result:
        if not any(abs(item[4] - previous[4]) < 0.000001 for previous in unique):
            unique.append(item)
        if len(unique) == 4:
            break
    return unique


def snap_to_alignment(proposed_card, other_cards, scale, tolerance_px=9.0,
                      moving_bounds=None, other_bounds=None):
    """Return ``(delta: QPointF, guides: list[QLineF])`` for one drag event.

    Cards and optional collision bounds are scene-space QRectF instances at
    their proposed positions. ``scale`` is the current view's zoom factor; the
    snapping tolerance stays constant in physical viewport pixels.  The
    aligned left/center/right and top/center/bottom coordinates refer to the
    visible card, while optional collision bounds may include its buffer icon.
    Adjacent sides attract at the standard horizontal or vertical gap;
    collision overhangs such as buffer icons add to that gap as needed.

    A candidate never introduces a new overlap or worsens an existing one.
    Without a nearby valid alignment the delta and guides are empty.  The
    caller should bypass this function while Alt is pressed and clear guides
    on mouse release/cancel, and should never apply it to programmatic moves.
    """
    card = _rect(proposed_card)
    cards = [_rect(item) for item in other_cards]
    try:
        zoom, pixels = float(scale), float(tolerance_px)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('Масштаб и допуск должны быть конечными числами.') from exc
    if not isfinite(zoom) or zoom <= 0 or not isfinite(pixels) or pixels < 0:
        raise ValueError('Масштаб должен быть положительным, допуск — неотрицательным.')
    if not cards or pixels == 0:
        return QPointF(), []
    moving = _rect(moving_bounds) if moving_bounds is not None else card
    obstacles = [_rect(item) for item in other_bounds] if other_bounds is not None else cards
    if len(obstacles) != len(cards):
        raise ValueError('Для каждой карточки необходимы её границы столкновения.')
    tolerance = pixels / zoom
    xs = _candidates(card, cards, tolerance, True, STANDARD_HORIZONTAL_GAP, 64.0 / zoom, moving, obstacles)
    ys = _candidates(card, cards, tolerance, False, 24.0, 64.0 / zoom, moving, obstacles)
    baseline = [_area(moving, rect) for rect in obstacles]

    def safe(x, y):
        shifted = moving.translated(x, y)
        return all(_area(shifted, obstacle) <= previous + 0.000001
                   for obstacle, previous in zip(obstacles, baseline))

    # Prefer aligning both axes, then the smallest movement.  Always retain
    # the no-op candidate so that an unsafe alignment is never forced.
    choices = []
    for xc in [None, *xs]:
        for yc in [None, *ys]:
            if xc is None and yc is None:
                continue
            dx, dy = (xc[4] if xc else 0.0), (yc[4] if yc else 0.0)
            if safe(dx, dy):
                count = int(xc is not None) + int(yc is not None)
                choices.append((-count, abs(dx) + abs(dy), xc or (), yc or (), dx, dy))
    if not choices:
        return QPointF(), []
    _, _, xc, yc, dx, dy = min(choices)
    shifted_card = card.translated(dx, dy)
    margin = 20.0 / zoom
    guides = []
    if xc:
        reference, other = xc[5], xc[6]
        guides.append(QLineF(reference, min(shifted_card.top(), other.top()) - margin,
                             reference, max(shifted_card.bottom(), other.bottom()) + margin))
    if yc:
        reference, other = yc[5], yc[6]
        guides.append(QLineF(min(shifted_card.left(), other.left()) - margin, reference,
                             max(shifted_card.right(), other.right()) + margin, reference))
    return QPointF(dx, dy), guides


def _entry_exit(start_low, start_high, obstacle_low, obstacle_high, delta):
    if delta > 0:
        return (obstacle_low - start_high) / delta, (obstacle_high - start_low) / delta
    if delta < 0:
        return (obstacle_high - start_low) / delta, (obstacle_low - start_high) / delta
    if start_high <= obstacle_low or start_low >= obstacle_high:
        return float('inf'), -float('inf')
    return -float('inf'), float('inf')


def _first_contact(moving, obstacle, dx, dy):
    """Time of entry for a swept rectangle, or None if interiors do not meet."""
    x0, x1 = _entry_exit(moving.left(), moving.right(), obstacle.left(), obstacle.right(), dx)
    y0, y1 = _entry_exit(moving.top(), moving.bottom(), obstacle.top(), obstacle.bottom(), dy)
    entry, exit_time = max(x0, y0), min(x1, y1)
    if entry >= exit_time or exit_time <= 0 or entry >= 1:
        return None
    return max(0.0, entry)


def _overlap_peak(moving, obstacle, dx, dy):
    """Maximum overlap area along a linear drag, including interval extrema."""
    breaks = {0.0, 1.0}
    if dx:
        for edge in (moving.left(), moving.right()):
            for target in (obstacle.left(), obstacle.right()):
                t = (target - edge) / dx
                if 0 < t < 1:
                    breaks.add(t)
    if dy:
        for edge in (moving.top(), moving.bottom()):
            for target in (obstacle.top(), obstacle.bottom()):
                t = (target - edge) / dy
                if 0 < t < 1:
                    breaks.add(t)
    points = sorted(breaks)
    def overlap(t):
        return _area(moving.translated(dx * t, dy * t), obstacle)
    peak = 0.0
    for a, b in zip(points, points[1:]):
        first, middle, last = overlap(a), overlap((a + b) / 2), overlap(b)
        peak = max(peak, first, middle, last)
        # Area on this interval is quadratic: interpolate in u=(t-a)/(b-a).
        qa = 2 * (first + last - 2 * middle)
        qb = last - first - qa
        if qa < 0:
            u = -qb / (2 * qa)
            if 0 < u < 1:
                peak = max(peak, overlap(a + (b - a) * u))
    return peak


def constrain_movement(previous_bounds, proposed_bounds, other_bounds, gap=0.0, horizontal_gap=None):
    """Return a non-overlapping drag displacement in scene coordinates.

    This safety check must be called even when snapping is disabled or Alt is
    held. Pass gap=24 in magnetic mode and gap=0 for free placement. A fast
    drag stops at the requested clearance, not only when it hits the card.
    Obstacles include full buffer-icon extents and hidden cards, if provided by
    the caller. Existing overlaps or old gaps smaller than the requested gap
    may be reduced or left unchanged but cannot be worsened by the drag.
    """
    previous, proposed = _rect(previous_bounds), _rect(proposed_bounds)
    if abs(previous.width() - proposed.width()) > 0.000001 or abs(previous.height() - proposed.height()) > 0.000001:
        raise ValueError('Границы карточки при перетаскивании не должны менять размер.')
    try:
        gap = float(gap)
        horizontal_gap = gap if horizontal_gap is None else float(horizontal_gap)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('Зазор должен быть конечным неотрицательным числом.') from exc
    if not isfinite(gap) or gap < 0 or not isfinite(horizontal_gap) or horizontal_gap < 0:
        raise ValueError('Зазор должен быть конечным неотрицательным числом.')
    dx, dy = proposed.left() - previous.left(), proposed.top() - previous.top()
    obstacles = [_rect(item) for item in other_bounds]
    limit = 1.0
    existing = []
    for obstacle in obstacles:
        before = _area(previous, obstacle)
        if before > 0:
            existing.append((obstacle, before))
        else:
            contact = _first_contact(previous, obstacle, dx, dy)
            if contact is not None:
                # Leave a tiny scene-space gap to avoid floating-point
                # roundoff turning exact contact into an actual intersection.
                epsilon = 0.000001 / max(abs(dx), abs(dy), 1.0)
                limit = min(limit, max(0.0, contact - epsilon))
            if gap or horizontal_gap:
                clearance = obstacle.adjusted(-horizontal_gap, -gap, horizontal_gap, gap)
                before_clearance = _area(previous, clearance)
                if before_clearance > 0:
                    # Existing close placements remain editable: don't force
                    # a jump, but don't let an inward drag worsen the gap.
                    existing.append((clearance, before_clearance))
                else:
                    contact = _first_contact(previous, clearance, dx, dy)
                    if contact is not None:
                        epsilon = 0.000001 / max(abs(dx), abs(dy), 1.0)
                        limit = min(limit, max(0.0, contact - epsilon))
    dx, dy = dx * limit, dy * limit
    if any(_overlap_peak(previous, obstacle, dx, dy) > before + 0.000001
           for obstacle, before in existing):
        return QPointF()
    return QPointF(dx, dy)
