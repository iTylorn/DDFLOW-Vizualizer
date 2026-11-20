"""Разложить группы и одиночные переделы по горизонтали.

Координаты вычисляются отдельно от модели: вызывающий применяет результат
только по явной команде «Выровнять». Ручные перемещения не сбрасываются при
открытии проекта, фильтрации или перерисовке.
"""
from collections import defaultdict
from heapq import heappop, heappush
from math import ceil, isfinite, sqrt

try:
    from .selection_alignment import STANDARD_HORIZONTAL_GAP
except ImportError:
    from selection_alignment import STANDARD_HORIZONTAL_GAP


ORIGIN_X = 50.0
ORIGIN_Y = 90.0
COLUMN_GAP = STANDARD_HORIZONTAL_GAP
ROW_GAP = 45.0
CONTAINER_GAP = STANDARD_HORIZONTAL_GAP + 40.0  # includes group outlines


class LayoutError(ValueError):
    """The existing connections cannot be arranged left to right."""


def _positive_size(size):
    values = tuple(map(float, size))
    if len(values) == 2:
        width, height = values
        offset_x, offset_y, anchor_y = 0.0, 0.0, height / 2
    elif len(values) == 5:
        width, height, offset_x, offset_y, anchor_y = values
    else:
        raise ValueError('Размер передела должен содержать два или пять чисел.')
    if not all(isfinite(v) for v in (width, height, offset_x, offset_y, anchor_y)) or width <= 0 or height <= 0:
        raise ValueError('Размер передела должен быть положительным и конечным.')
    if not offset_y <= anchor_y <= offset_y + height:
        raise ValueError('Ось выравнивания должна находиться внутри границ передела.')
    return width, height, offset_x, offset_y, anchor_y


def _dag_order(keys, edges, priority):
    """A deterministic Kahn sort of an already acyclic graph."""
    successors = {key: set() for key in keys}
    indegree = {key: 0 for key in keys}
    for source, target in edges:
        if target not in successors[source]:
            successors[source].add(target)
            indegree[target] += 1
    ready = []
    for key in keys:
        if indegree[key] == 0:
            heappush(ready, (priority[key], key))
    order = []
    while ready:
        _, key = heappop(ready)
        order.append(key)
        for target in successors[key]:
            indegree[target] -= 1
            if indegree[target] == 0:
                heappush(ready, (priority[target], target))
    if len(order) != len(keys):
        raise LayoutError('Не удалось определить порядок связанных элементов.')
    return order


def _order_component(component, successors, priority):
    """Order a cyclic component to keep as many causal edges forward as practical.

    Sources are placed left, sinks right. If a cycle remains, choose the item
    with the largest excess of outgoing over incoming edges; level and original
    project order break ties. This is deterministic and never reverses an edge.
    """
    remaining = set(component)
    left, right = [], []
    while remaining:
        incoming = {key: 0 for key in remaining}
        outgoing = {key: 0 for key in remaining}
        for source in remaining:
            for target in successors[source]:
                if target in remaining and target != source:
                    outgoing[source] += 1
                    incoming[target] += 1
        sinks = [key for key in remaining if outgoing[key] == 0]
        if sinks:
            chosen = min(sinks, key=lambda key: priority[key])
            right.append(chosen)
        else:
            sources = [key for key in remaining if incoming[key] == 0]
            if sources:
                chosen = min(sources, key=lambda key: priority[key])
            else:
                chosen = min(remaining, key=lambda key: (-(outgoing[key] - incoming[key]), priority[key]))
            left.append(chosen)
        remaining.remove(chosen)
    return left + list(reversed(right))


def _causal_order(keys, edges, priority):
    """SCC condensation order and the subset of edges directed forward in it.

    All edges across components point forward. Inside a cyclic component a
    deterministic order keeps the original directions, allowing the remaining
    backwards edges to be rendered as such rather than discarded or flipped.
    """
    successors = {key: set() for key in keys}
    predecessors = {key: set() for key in keys}
    for source, target in edges:
        successors[source].add(target)
        predecessors[target].add(source)

    # Iterative Kosaraju avoids hitting Python's recursion limit on big graphs.
    visited, finish = set(), []
    for first in sorted(keys, key=lambda key: priority[key]):
        if first in visited:
            continue
        visited.add(first)
        stack = [(first, iter(sorted(successors[first], key=lambda key: priority[key])))]
        while stack:
            node, children = stack[-1]
            try:
                child = next(children)
            except StopIteration:
                finish.append(node)
                stack.pop()
                continue
            if child not in visited:
                visited.add(child)
                stack.append((child, iter(sorted(successors[child], key=lambda key: priority[key]))))

    component_of, components = {}, []
    for first in reversed(finish):
        if first in component_of:
            continue
        index = len(components)
        component = []
        stack = [first]
        component_of[first] = index
        while stack:
            node = stack.pop()
            component.append(node)
            for parent in sorted(predecessors[node], key=lambda key: priority[key], reverse=True):
                if parent not in component_of:
                    component_of[parent] = index
                    stack.append(parent)
        components.append(component)

    component_edges = {(component_of[source], component_of[target]) for source, target in edges
                       if component_of[source] != component_of[target]}
    component_priority = {index: min(priority[key] for key in component)
                          for index, component in enumerate(components)}
    component_order = _dag_order(list(range(len(components))), component_edges, component_priority)
    order = []
    for index in component_order:
        order.extend(_order_component(components[index], successors, priority))
    position = {key: index for index, key in enumerate(order)}
    forward_successors = {source: {target for target in targets if position[source] < position[target]}
                          for source, targets in successors.items()}
    return order, forward_successors


def _group_columns(stages, internal_edges):
    """Choose columns by level and ensure each directed edge moves right."""
    by_id = {stage.id: stage for stage in stages}
    level_values = sorted({stage.level for stage in stages if stage.level is not None})
    level_rank = {value: index for index, value in enumerate(level_values)}
    no_level = [stage for stage in stages if stage.level is None]
    grid_width = ceil(sqrt(len(no_level))) if no_level else 0
    no_level_rank = {stage.id: len(level_values) + index % grid_width
                     for index, stage in enumerate(no_level)}
    base = {stage.id: (level_rank[stage.level] if stage.level is not None else no_level_rank[stage.id])
            for stage in stages}
    priority = {stage.id: (base[stage.id], index) for index, stage in enumerate(stages)}
    order, successors = _causal_order(list(by_id), internal_edges, priority)
    ranks = dict(base)
    for source in order:
        for target in successors[source]:
            ranks[target] = max(ranks[target], ranks[source] + 1)
    by_column = defaultdict(list)
    for key in order:
        by_column[ranks[key]].append(by_id[key])
    return [by_column[index] for index in sorted(by_column)]


def arrange_stages(project, measure, measure_group=None):
    """Return {stage.id: (x, y)} without changing `project`.

    `measure(stage)` returns either width and height or width, height, local
    bounding-box offsets x/y, and the local vertical center of the visible card.
    `measure_group(group)` optionally returns the width of its displayed name.
    Ungrouped stages each get their own horizontal slot; inside groups levels
    and compact grids provide an initial order. All directed connections take
    precedence over levels where possible: all edges between strongly connected
    components point left-to-right. Groups stay contiguous; cycles keep their
    original edges, with some going backwards. Original coordinates and edges
    are never changed. Invalid references raise LayoutError.
    """
    groups = {group.id: group for group in project.groups}
    stage_by_id = {stage.id: stage for stage in project.stages}
    if len(stage_by_id) != len(project.stages):
        raise LayoutError('В проекте есть переделы с одинаковым идентификатором.')
    edges = []
    for edge in project.edges:
        if edge.source not in stage_by_id or edge.target not in stage_by_id:
            raise LayoutError('Связь ссылается на отсутствующий передел; выровнять схему невозможно.')
        edges.append((edge.source, edge.target))
    containers = {}
    stage_container = {}
    for index, stage in enumerate(project.stages):
        if stage.group_id and stage.group_id not in groups:
            raise LayoutError(f'Группа передела «{stage.name}» не найдена; выровнять схему невозможно.')
        key = ('group', stage.group_id) if stage.group_id else ('stage', stage.id)
        if key not in containers:
            containers[key] = {'index': index, 'group': groups.get(stage.group_id), 'stages': []}
        containers[key]['stages'].append(stage)
        stage_container[stage.id] = key

    container_priority = {}
    for key, container in containers.items():
        levels = [stage.level for stage in container['stages'] if stage.level is not None]
        earliest = min(levels) if levels else None
        container_priority[key] = (earliest is None, earliest or 0, container['index'])
    external_edges = [(stage_container[source], stage_container[target]) for source, target in edges
                      if stage_container[source] != stage_container[target]]
    container_order, _ = _causal_order(list(containers), external_edges, container_priority)

    internal_edges = defaultdict(list)
    for source, target in edges:
        key = stage_container[source]
        if key == stage_container[target]:
            internal_edges[key].append((source, target))

    sizes = {stage.id: _positive_size(measure(stage)) for stage in project.stages}
    result = {}
    # Arrange each group around one shared visual axis. Per-row extents include
    # buffers and other decorations, while the anchor refers to the card body.
    # This keeps different-height cards aligned without overlapping their icons.
    plans = {}
    for key in container_order:
        group = containers[key]['group']
        stages = containers[key]['stages']
        columns = [[stages[0]]] if group is None else _group_columns(stages, internal_edges[key])
        widths = [max(sizes[stage.id][0] for stage in column) for column in columns]
        row_count = max(len(column) for column in columns)
        row_above = [max(sizes[column[row].id][4] - sizes[column[row].id][3]
                         for column in columns if row < len(column)) for row in range(row_count)]
        row_below = [max(sizes[column[row].id][3] + sizes[column[row].id][1] - sizes[column[row].id][4]
                         for column in columns if row < len(column)) for row in range(row_count)]
        # Use centers of the visible card bodies for the shared flow axis.
        # The buffer symbol can extend above a card, but must not tilt the
        # entire neighboring row by shifting this axis.
        cursor_y = 0.0
        centers = []
        for above, below in zip(row_above, row_below):
            centers.append(cursor_y + above)
            cursor_y += above + below + ROW_GAP
        axis = (centers[0] + centers[-1]) / 2
        plans[key] = (columns, widths, row_above, row_below, axis)
    shared_axis = max((plan[4] for plan in plans.values()), default=0.0)
    x = ORIGIN_X
    for key in container_order:
        group = containers[key]['group']
        columns, widths, row_above, row_below, axis = plans[key]
        column_x = x
        for column, width in zip(columns, widths):
            row_y = ORIGIN_Y + shared_axis - axis
            for row, stage in enumerate(column):
                _, _, offset_x, _, anchor_y = sizes[stage.id]
                result[stage.id] = (column_x - offset_x, row_y + row_above[row] - anchor_y)
                row_y += row_above[row] + row_below[row] + ROW_GAP
            column_x += width + COLUMN_GAP
        group_width = sum(widths) + COLUMN_GAP * (len(widths) - 1)
        label_width = (float(measure_group(group)) if measure_group else len(group.name or '') * 9.0) if group else 0.0
        if not isfinite(label_width) or label_width < 0:
            raise ValueError('Размер подписи группы должен быть конечным и неотрицательным.')
        x += max(group_width, label_width + 12.0) + CONTAINER_GAP
    return result
