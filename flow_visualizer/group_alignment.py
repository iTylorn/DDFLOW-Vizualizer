"""Align existing group columns without inventing a new arrangement."""
from collections import defaultdict


def align_group_columns(project, positions, measure):
    result = dict(positions)
    groups = defaultdict(list)
    sizes = {}
    for stage in project.stages:
        width, height, ox, oy, cy = measure(stage)
        sizes[stage.id] = (width, height, ox, oy, cy)
        if stage.group_id:
            groups[stage.group_id].append(stage)

    def rect(stage, point):
        width, height, ox, oy, _ = sizes[stage.id]
        x, y = point
        return (x + ox, y + oy, x + ox + width, y + oy + height)

    def area(a, b):
        return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))

    for members in groups.values():
        if len(members) < 2:
            continue
        def cx(s):
            w, _, ox, _, _ = sizes[s.id]
            return result[s.id][0] + ox + w / 2
        sorted_members = sorted(members, key=cx)
        columns = []
        x_tolerance = min(sizes[s.id][0] for s in members) * .4
        for stage in sorted_members:
            if not columns or abs(cx(stage) - cx(columns[-1][-1])) > x_tolerance:
                columns.append([stage])
            else:
                columns[-1].append(stage)
        candidate = {s.id: list(result[s.id]) for s in members}
        for column in columns:
            center = sum(cx(s) for s in column) / len(column)
            for stage in column:
                candidate[stage.id][0] += center - cx(stage)
        # Align nearby visual row centers between columns, never placing two
        # members of one column onto the same row.
        column_of = {s.id: i for i, col in enumerate(columns) for s in col}
        def cy(s):
            return result[s.id][1] + sizes[s.id][4]
        rows = []
        y_tolerance = min(sizes[s.id][1] for s in members) * .3
        for stage in sorted(members, key=cy):
            if (not rows or column_of[stage.id] in {column_of[s.id] for s in rows[-1]}
                    or abs(cy(stage) - cy(rows[-1][-1])) > y_tolerance):
                rows.append([stage])
            else:
                rows[-1].append(stage)
        for row in rows:
            center = sum(cy(s) for s in row) / len(row)
            for stage in row:
                candidate[stage.id][1] += center - cy(stage)
        valid = True
        for stage in members:
            after = rect(stage, candidate[stage.id])
            before = rect(stage, result[stage.id])
            for other in project.stages:
                if other.id == stage.id:
                    continue
                other_before = rect(other, result[other.id])
                other_after = rect(other, candidate.get(other.id, result[other.id]))
                if area(after, other_after) > area(before, other_before) + 1e-6:
                    valid = False
                    break
            if not valid:
                break
        if valid:
            result.update({key: tuple(value) for key, value in candidate.items()})
    return result
