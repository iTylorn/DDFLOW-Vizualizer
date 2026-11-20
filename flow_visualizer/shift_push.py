"""Move cards on the contacted side of a row or stack together."""
from PySide6.QtCore import QPointF, QRectF


def push_in_direction(moving, delta, obstacles, horizontal=True, gap=24.0, group_ids=None):
    """Return equal per-card shifts, or None if another row would overlap.

    When the dragged card contacts a neighbor, the entire half of the diagram
    on that side moves together, including other rows. Existing groups move as
    units. Their internal layout and mutual distances remain unchanged.
    """
    moving = QRectF(moving)
    delta = float(delta)
    if abs(delta) < 1e-7:
        return {}
    sign = 1 if delta > 0 else -1
    originals = {key: QRectF(rect) for key, rect in obstacles}
    def cross_overlap(a, b):
        return (min(a.bottom(), b.bottom()) - max(a.top(), b.top()) if horizontal
                else min(a.right(), b.right()) - max(a.left(), b.left())) > 1e-6
    def low(rect):
        return rect.left() if horizontal else rect.top()
    def high(rect):
        return rect.right() if horizontal else rect.bottom()
    final_moving = moving.translated(delta if horizontal else 0, 0 if horizontal else delta)
    def safe_without_push():
        for rect in originals.values():
            new = final_moving.intersected(rect)
            old = moving.intersected(rect)
            new_area = 0 if new.isEmpty() else new.width() * new.height()
            old_area = 0 if old.isEmpty() else old.width() * old.height()
            if new_area > old_area + 1e-6:
                return False
        return True
    contacts = [(key, rect) for key, rect in originals.items() if cross_overlap(moving, rect)
             and ((low(rect) >= high(moving) - 1e-6) if sign > 0
                  else (high(rect) <= low(moving) + 1e-6))]
    if not contacts:
        return {} if safe_without_push() else None
    nearest = min((low(rect) - high(moving) if sign > 0 else low(moving) - high(rect))
                  for _, rect in contacts)
    amount = sign * max(0.0, abs(delta) - max(0.0, nearest - gap))
    if abs(amount) < 1e-7:
        return {} if safe_without_push() else None
    displacement = QPointF(amount, 0) if horizontal else QPointF(0, amount)
    center = (low(moving) + high(moving)) / 2
    selected = {key for key, rect in originals.items()
                if sign * ((low(rect) + high(rect)) / 2 - center) > 1e-6}
    groups = group_ids or {}
    selected_groups = {groups.get(key) for key in selected} - {None, ''}
    selected.update(key for key in originals if groups.get(key) in selected_groups)
    shifts = {key: QPointF(displacement) for key in selected}
    final = [final_moving] + [rect.translated(shifts.get(key, QPointF())) for key, rect in originals.items()]
    before = [moving, *originals.values()]
    active = [0] + [i for i, key in enumerate(originals, 1) if key in shifts]
    checked = set()
    for i in active:
        for j in range(len(final)):
            if i == j or (min(i, j), max(i, j)) in checked:
                continue
            checked.add((min(i, j), max(i, j)))
            overlap = final[i].intersected(final[j])
            old_overlap = before[i].intersected(before[j])
            area = 0 if overlap.isEmpty() else overlap.width() * overlap.height()
            old_area = 0 if old_overlap.isEmpty() else old_overlap.width() * old_overlap.height()
            if area > old_area + 1e-6:
                return None
    return shifts
