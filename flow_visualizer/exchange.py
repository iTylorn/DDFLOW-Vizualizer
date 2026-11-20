"""Versioned interchange with the FlowExport external 1C processor."""
from copy import deepcopy
import json
from uuid import UUID

try:
    from . import model
except ImportError:
    import model


TO_ERP = "dd-flow-map"
FROM_ERP = "dd-flow-map-export"
VERSION = 1


def export_map(project, path, view_positions=None):
    if not project.stages:
        raise ValueError("Добавьте хотя бы один передел перед выгрузкой.")
    if any(not stage.name or not stage.provider_type for stage in project.stages):
        raise ValueError("Укажите название и тип у каждого передела.")
    data = model.project_data(project)
    data["version"] = 11  # Latest project schema shared with 1C.
    diagram = data["project"]
    diagram.pop("annotations")
    diagram.pop("auto_align")
    map_id = str(UUID(project.exchange_map_id)) if project.exchange_map_id else model.new_id()
    diagram["exchange_map_id"] = map_id
    diagram["source"] = ""
    if view_positions is not None:
        diagram["view_positions"] = deepcopy(view_positions)
    active = "detailed" if project.show_warehouses else "compact"
    positions = diagram["view_positions"].setdefault(active, {})
    for stage in project.stages:
        if stage.x is not None and stage.y is not None:
            positions[stage.id] = [stage.x, stage.y]

    def sort_key(stage):
        point = positions.get(stage.id)
        return (point[0], point[1]) if point is not None else (float("inf"), float("inf"))

    order = [stage.id for stage in sorted(project.stages, key=sort_key)]
    stages = {stage["id"]: stage for stage in diagram["stages"]}
    settings = []
    for ident in order:
        stage = stages[ident]
        stage_settings = {key: stage[key] for key in (
            "id", "name", "group_id", "provider_type", "rkt_algorithm", "launch_layout", "deficit_launch")}
        extra = stage["extra"]
        stage_settings.update({
            "provider_id": next((key for key, name in project.provider_option_ids.items()
                                 if name == stage["provider_type"]), ""),
            "rkt_id": next((key for key, name in project.rkt_option_ids.items()
                            if name == stage["rkt_algorithm"]), ""),
            "layout_id": (extra.get("launch_layout_id", "") if stage["launch_layout"] == "unknown" else
                          next((key for key, value in model.LAYOUT_IDS.items() if value == stage["launch_layout"]), "")),
            "dynamic": extra.get("dynamic") is True,
            "positions": [{"view": view, "x": layout[ident][0], "y": layout[ident][1]}
                          for view, layout in diagram["view_positions"].items() if ident in layout],
        })
        for collection in ("inlets", "stocks"):
            stage_settings[collection] = [
                dict(warehouse_id=link["warehouse_id"], primary=link["primary"],
                     department_id=link["department_id"], department_name=link["department_name"],
                     **{key: link["extra"].get(key, default) for key, default in (
                         ("parameter_type", ""), ("parameter_id", ""), ("parameter_name", ""),
                         ("ignore_on_launch", False), ("material_doc_type_id", ""))})
                for link in stage[collection]
            ]
        settings.append(stage_settings)

    model.save_json({"format": TO_ERP, "version": VERSION, "map_id": map_id,
                     "title": project.title, "active_view": active, "order": order,
                     "project": json.dumps(data, ensure_ascii=False, allow_nan=False),
                     "stages": settings,
                     "groups": [{"id": group.id, "name": group.name} for group in project.groups],
                     "warehouses": [{"id": warehouse.id, "name": warehouse.name}
                                    for warehouse in project.warehouses]}, path)
    return map_id


def import_map(path):
    with open(path, encoding="utf-8-sig") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or data.get("format") != FROM_ERP or data.get("version") != VERSION:
        raise ValueError("Выберите JSON, выгруженный из 1С обработкой FlowExport.")
    live, warnings = model.import_rows(path, iter([model.COLUMNS, *data["rows"]]))
    warnings = list(data.get("warnings", [])) + warnings
    snapshot = data.get("snapshot")
    if not snapshot:
        return live, warnings
    diagram = model.parse_project(json.loads(snapshot["project"]))
    bound = {entry["source"]: entry["target"] for entry in snapshot["bindings"]}
    if len(set(bound.values())) != len(bound):
        raise ValueError("Снимок карты содержит повторяющиеся ссылки 1С.")
    include_groups = data.get("include_groups", True)
    layout_groups = {stage.id: stage.group_id for stage in diagram.stages}
    active = "detailed" if diagram.show_warehouses else "compact"
    # The active view in older project snapshots can be represented by x/y only.
    positions = deepcopy(diagram.view_positions)
    active_positions = positions.setdefault(active, {})
    for stage in diagram.stages:
        if stage.id not in active_positions and stage.x is not None and stage.y is not None:
            active_positions[stage.id] = [stage.x, stage.y]
    original_stages = {stage.id: stage for stage in diagram.stages}
    live_stages = {stage.id: stage for stage in live.stages}
    reverse = {target: key for key, target in bound.items() if target in live_stages}
    missing = [stage.name for stage in diagram.stages if bound.get(stage.id) not in live_stages]
    if missing:
        warnings.append("Переделы карты больше не доступны в 1С: " + ", ".join(missing))

    # Preserve virtual group references in maps written to the catalog root.
    live_groups = {group.id: group for group in live.groups}
    visual_groups = {group.id: group for group in diagram.groups}
    for stage in live.stages:
        source_id = reverse.get(stage.id)
        if not include_groups:
            stage.group_id = ""
        elif not stage.group_id and not snapshot.get("published_groups") and source_id:
            stage.group_id = layout_groups.get(source_id, "")
        if source_id in original_stages:
            stage.has_buffer = original_stages[source_id].has_buffer
        coordinate = active_positions.get(source_id)
        if coordinate:
            stage.x, stage.y = coordinate
    represented = {layout_groups[key] for target, key in reverse.items() if live_stages[target].group_id
                   and live_stages[target].group_id != layout_groups.get(key)}
    for key in represented - {stage.group_id for stage in live.stages}:
        visual_groups.pop(key, None)
    diagram.groups = list((visual_groups | live_groups).values()) if include_groups else []
    diagram.view_positions = {
        view: {bound[key]: point for key, point in layout.items() if bound.get(key) in live_stages}
        for view, layout in positions.items()
    }
    diagram.edges = [
        model.Edge(bound[edge.source], bound[edge.target], edge.routes)
        for edge in diagram.edges
        if bound.get(edge.source) in live_stages and bound.get(edge.target) in live_stages
    ]
    diagram.stages = live.stages
    warehouse_bindings = {entry["source"]: entry["target"] for entry in snapshot["warehouse_bindings"]}
    live_warehouses = {warehouse.id: warehouse for warehouse in live.warehouses}
    for warehouse in diagram.warehouses:
        target = warehouse_bindings.get(warehouse.id)
        if warehouse.id not in live_warehouses and target not in live_warehouses:
            live_warehouses[warehouse.id] = warehouse
    diagram.warehouses = list(live_warehouses.values())
    diagram.provider_options = live.provider_options
    diagram.provider_option_ids = live.provider_option_ids
    diagram.rkt_options = live.rkt_options
    diagram.rkt_option_ids = live.rkt_option_ids
    diagram.source = live.source
    diagram.exchange_map_id = data["map_id"]
    return diagram, warnings
