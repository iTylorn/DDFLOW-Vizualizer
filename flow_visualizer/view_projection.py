"""Project an existing arrangement between compact and detailed cards."""
from PySide6.QtCore import QRectF


def project_positions(positions, source_bounds, target_bounds):
    """Scale positions just enough for larger cards, preserving their topology.

    Bounding-box centers share one affine transform per axis, so a column
    remains a column and a row remains a row. Choose expansion from the
    actual gaps between cards, rather than from the largest single card.
    """
    if not positions:
        return {}, (1.0, 1.0)
    keys = list(positions)
    if any(k not in source_bounds or k not in target_bounds for k in keys):
        raise ValueError('Не удалось измерить карточки в обоих режимах.')
    source = {k: QRectF(source_bounds[k]) for k in keys}
    target = {k: QRectF(target_bounds[k]) for k in keys}
    if any(source[k].isEmpty() or target[k].isEmpty() for k in keys):
        raise ValueError('Не удалось измерить размеры карточки.')
    centers = {k: (positions[k][0] + source[k].center().x(),
                   positions[k][1] + source[k].center().y()) for k in keys}
    anchor_x = min(v[0] for v in centers.values())
    anchor_y = min(v[1] for v in centers.values())
    extent_x = max(v[0] for v in centers.values()) - anchor_x
    extent_y = max(v[1] for v in centers.values()) - anchor_y
    constraints = []
    for index, a in enumerate(keys):
        a_source = source[a].translated(*positions[a])
        for b in keys[index + 1:]:
            b_source = source[b].translated(*positions[b])
            sep_x = a_source.right() <= b_source.left() + 1e-6 or b_source.right() <= a_source.left() + 1e-6
            sep_y = a_source.bottom() <= b_source.top() + 1e-6 or b_source.bottom() <= a_source.top() + 1e-6
            dx = abs(centers[a][0] - centers[b][0])
            dy = abs(centers[a][1] - centers[b][1])
            need_x = (target[a].width() + target[b].width()) / 2 + 12
            need_y = (target[a].height() + target[b].height()) / 2 + 12
            rx = need_x / dx if sep_x and dx > 1e-7 else float('inf')
            ry = need_y / dy if sep_y and dy > 1e-7 else float('inf')
            if rx == float('inf') and ry == float('inf'):
                raise ValueError('В текущем виде есть перекрывающиеся переделы.')
            constraints.append((rx, ry))
    scale_x = scale_y = 1.0
    # Mandatory row/column separations first, then choose the least disruptive
    # axis for diagonally placed cards.
    for rx, ry in constraints:
        if ry == float('inf'):
            scale_x = max(scale_x, rx)
        elif rx == float('inf'):
            scale_y = max(scale_y, ry)
    for rx, ry in constraints:
        if rx <= scale_x + 1e-7 or ry <= scale_y + 1e-7:
            continue
        cost_x = (rx - scale_x) * max(extent_x, 1.0)
        cost_y = (ry - scale_y) * max(extent_y, 1.0)
        if cost_x <= cost_y:
            scale_x = rx
        else:
            scale_y = ry
    result = {k: (anchor_x + (centers[k][0] - anchor_x) * scale_x - target[k].center().x(),
                  anchor_y + (centers[k][1] - anchor_y) * scale_y - target[k].center().y()) for k in keys}
    return result, (scale_x, scale_y)


def overlaps(positions, local_bounds):
    rects = sorted((QRectF(local_bounds[k]).translated(*position) for k, position in positions.items()),
                   key=lambda rect: rect.left())
    for i, rect in enumerate(rects):
        for other in rects[i + 1:]:
            if other.left() >= rect.right() - 1e-6:
                break
            if rect.intersects(other):
                intersection = rect.intersected(other)
                if intersection.width() > 1e-5 and intersection.height() > 1e-5:
                    return True
    return False
