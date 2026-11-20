"""Data model and XLSX/project persistence for the flow visualizer.

The project file is an application document, not an import format for 1C.
IDs identify source objects independently of their presentation or level.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import json
import math
import os
import tempfile
import uuid


FORMAT_VERSION = 12
READABLE_FORMAT_VERSIONS = tuple(range(1, FORMAT_VERSION + 1))
ANNOTATION_KINDS = ('text', 'rectangle', 'rounded', 'ellipse', 'triangle', 'line', 'arrow', 'image')
LAYOUT_IDS = {
    'ПроизводствоБезГруппировки': 'none',
    'ГруппировкаПоКодуПереналадки': 'setup',
    'ПроизводствоСГруппировкойНазначениям': 'assignments',
    'ПроизводствоСГруппировкойПоИсточникуПотребности': 'demand',
}
WAREHOUSE_TYPES = ("", "ordinary", "workshop")
COLUMNS = (
    "kind", "id", "name", "code", "owner_id", "warehouse_id", "primary",
    "level", "provider_type", "rkt_algorithm", "department_id",
    "department_name", "extra_json",
)


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class Warehouse:
    id: str = field(default_factory=new_id)
    name: str = ""
    code: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    # Classification can be changed locally after import; the XLSX may carry
    # the verified 1C boolean ЦеховаяКладовая as extra.workshop_storage.
    warehouse_type: str = ""


@dataclass
class WarehouseLink:
    warehouse_id: str = ""
    primary: bool = False
    department_id: str = ""
    department_name: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Group:
    """A visual group; imported production divisions retain their identity."""
    id: str = field(default_factory=new_id)
    name: str = ""
    code: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Stage:
    id: str = field(default_factory=new_id)
    name: str = ""
    code: str = ""
    provider_type: str = ""
    rkt_algorithm: str = ""
    level: int | None = None
    x: float | None = None
    y: float | None = None
    inlets: list[WarehouseLink] = field(default_factory=list)
    stocks: list[WarehouseLink] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    group_id: str = ""
    # Diagram annotation only, not an inferred DD FLOW configuration flag.
    has_buffer: bool = False
    # Layout is imported when available; deficit remains a visual annotation.
    launch_layout: str = "none"
    deficit_launch: bool = False


@dataclass
class Edge:
    source: str = ""
    target: str = ""
    # Absolute intermediate points in each view. Missing/empty means the
    # automatic route; endpoints remain attached to their stage cards.
    routes: dict[str, list[list[float]]] = field(default_factory=dict)


@dataclass
class TextStyle:
    font_family: str = 'Segoe UI'
    bold: bool = False
    italic: bool = False
    alignment: str = 'left'
    text_color: str = '#263744'
    fill: str = ''
    stroke: str = '#263744'
    stroke_width: int = 3
    dashed: bool = False

    def __post_init__(self):
        if (self.alignment not in ('left', 'center', 'right')
                or not isinstance(self.font_family, str)
                or type(self.stroke_width) is not int or not 0 <= self.stroke_width <= 40
                or any(type(value) is not bool for value in (self.bold, self.italic, self.dashed))
                or any(not isinstance(color, str) or (color and
                       (len(color) != 7 or color[0] != '#' or any(c not in '0123456789abcdefABCDEF' for c in color[1:])))
                       for color in (self.text_color, self.fill, self.stroke))):
            raise ValueError('Некорректные параметры оформления текста или фигуры.')


def default_title_style():
    return TextStyle(bold=True, alignment='center', stroke_width=0)


@dataclass
class Annotation(TextStyle):
    id: str = field(default_factory=new_id)
    kind: str = 'text'
    x: float = 0
    y: float = 0
    # For lines and arrows these are the offsets from start to end.
    width: float = 260
    height: float = 100
    text: str = ''
    font_size: int = 20
    image_data: str = ''
    keep_aspect: bool = True

    def __post_init__(self):
        super().__post_init__()
        if (self.kind not in ANNOTATION_KINDS or not self.id
                or any(not isinstance(value, str) for value in (self.id, self.text, self.image_data))
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for value in (self.x, self.y, self.width, self.height))
                or (self.kind not in ('arrow', 'line') and min(self.width, self.height) < 12)
                or (self.kind in ('arrow', 'line') and math.hypot(self.width, self.height) < 12)
                or type(self.font_size) is not int or not 6 <= self.font_size <= 240
                or type(self.keep_aspect) is not bool):
            raise ValueError('Некорректные параметры элемента оформления.')


@dataclass
class Project:
    warehouses: list[Warehouse] = field(default_factory=list)
    stages: list[Stage] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    source: str = ""
    title: str = "Новая схема"
    rkt_options: list[str] = field(default_factory=list)
    provider_options: list[str] = field(default_factory=list)
    # Internal enumeration identifiers from 1C; names are user-facing labels.
    rkt_option_ids: dict[str, str] = field(default_factory=dict)
    provider_option_ids: dict[str, str] = field(default_factory=dict)
    groups: list[Group] = field(default_factory=list)
    # Two independent saved layouts keep user moves when the view changes.
    show_warehouses: bool = False
    view_positions: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    card_width: int = 230
    card_height: int = 74
    flow_font_size: int = 30
    title_font_size: int = 30
    group_font_size: int = 18
    colors: dict[str, str] = field(default_factory=dict)
    exchange_map_id: str = ""
    annotations: list[Annotation] = field(default_factory=list)
    auto_align: bool = False
    title_style: TextStyle = field(default_factory=default_title_style)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _flag(value: Any, row: int, warnings: list[str]) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, bool):
        return value
    text = _text(value).casefold()
    if text in {"1", "true", "истина", "да"}:
        return True
    if text in {"0", "false", "ложь", "нет"}:
        return False
    warnings.append(f"Строка {row}: непонятный признак основного склада «{value}»; принят Нет.")
    return False


def _level(value: Any, row: int, warnings: list[str]) -> int | None:
    if value is None or _text(value) == "":
        return None
    try:
        number = float(value)
        if not math.isfinite(number) or not number.is_integer() or number < 1:
            raise ValueError
        return int(number)
    except (ValueError, TypeError, OverflowError):
        warnings.append(f"Строка {row}: уровень «{value}» не является положительным целым; уровень не задан.")
        return None


def _extra(value: Any, row: int, warnings: list[str]) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    try:
        result = json.loads(str(value))
        if not isinstance(result, dict):
            raise ValueError("ожидался объект")
        return result
    except (ValueError, TypeError) as exc:
        warnings.append(f"Строка {row}: дополнительные данные не прочитаны ({exc}); исходный текст сохранён.")
        return {"raw_extra_json": str(value)}


def _add_option(options: list[str], value: str) -> None:
    if value and value not in options:
        options.append(value)


def _import_layout(extra: dict[str, Any], row: int, name: str, warnings: list[str]) -> str:
    state = extra.get('launch_layout_state')
    if state is None:  # legacy XLSX: no layout was exported
        return 'none'
    if state == 'empty':
        return 'none'
    ident = _text(extra.get('launch_layout_id'))
    if state == 'value' and ident in LAYOUT_IDS:
        return LAYOUT_IDS[ident]
    description = _text(extra.get('launch_layout_name')) or ident
    if state == 'missing':
        description = 'запись параметров отсутствует или недоступна'
    elif not description:
        description = 'значение не распознано'
    warnings.append(f'Строка {row}, передел «{name}»: макет плана запуска — {description}; выберите макет вручную.')
    return 'unknown'


def import_xlsx(path: str | os.PathLike[str]) -> tuple[Project, list[str]]:
    """Read a new project from the single-sheet typed 1C export.

    Returns the project and human-readable warnings. Fatal schema problems and
    duplicate IDs raise ValueError: silently merging objects would corrupt the
    diagram. References unresolved because of permissions remain visible.
    """
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("Для чтения Excel не установлен пакет openpyxl.") from exc
    book = load_workbook(filename=path, read_only=True, data_only=True)
    try:
        return import_rows(path, book.worksheets[0].iter_rows(values_only=True))
    finally:
        book.close()


def import_rows(path, rows) -> tuple[Project, list[str]]:
    """Read the common row representation used by the workbook and 1C JSON."""
    warnings: list[str] = []
    project = Project(source=str(Path(path).resolve()), title=Path(path).stem)
    try:
        header = next(rows)
    except StopIteration as exc:
        raise ValueError("Файл Excel пуст.") from exc
    names = [_text(v).casefold() for v in header]
    if len(set(n for n in names if n)) != len([n for n in names if n]):
        raise ValueError("В заголовке Excel есть повторяющиеся столбцы.")
    missing = [name for name in COLUMNS if name not in names]
    if missing:
        raise ValueError("Это не выгрузка визуализатора: отсутствуют столбцы " + ", ".join(missing))
    indices = {name: names.index(name) for name in COLUMNS}
    stages: dict[str, Stage] = {}
    warehouses: dict[str, Warehouse] = {}
    groups: dict[str, Group] = {}
    links: list[tuple[int, str, str, WarehouseLink]] = []
    option_ids: dict[str, dict[str, str]] = {"rkt_option": {}, "provider_option": {}}
    for row_number, values in enumerate(rows, 2):
        def value(key: str) -> Any:
            index = indices[key]
            return values[index] if index < len(values) else None
        kind = _text(value("kind")).casefold()
        if not kind and not any(v is not None and _text(v) for v in values):
            continue
        if kind in option_ids:
            ident, name = _text(value("id")), _text(value("name"))
            if ident:
                option_ids[kind][ident] = name
            _add_option(project.rkt_options if kind == "rkt_option" else project.provider_options, name)
            continue
        if kind == "group":
            ident, name = _text(value("id")), _text(value("name"))
            if not ident:
                warnings.append(f"Строка {row_number}: у подразделения отсутствует идентификатор; строка пропущена.")
                continue
            if ident in groups:
                raise ValueError(f"Строка {row_number}: повторный идентификатор подразделения: {ident}.")
            if not name:
                warnings.append(f"Строка {row_number}: у подразделения {ident} отсутствует наименование.")
            group = Group(id=ident, name=name, code=_text(value("code")),
                          extra=_extra(value("extra_json"), row_number, warnings))
            groups[ident] = group
            project.groups.append(group)
            continue
        if kind in {"warehouse", "stage"}:
            ident, name = _text(value("id")), _text(value("name"))
            if not ident:
                warnings.append(f"Строка {row_number}: у {kind} отсутствует идентификатор; строка пропущена.")
                continue
            collection = warehouses if kind == "warehouse" else stages
            if ident in collection:
                raise ValueError(f"Строка {row_number}: повторный идентификатор {kind}: {ident}.")
            if not name:
                warnings.append(f"Строка {row_number}: у {kind} {ident} отсутствует наименование.")
            extra = _extra(value("extra_json"), row_number, warnings)
            if kind == "warehouse":
                warehouse_type = ""
                if "workshop_storage" in extra:
                    storage_flag = extra["workshop_storage"]
                    if isinstance(storage_flag, bool):
                        warehouse_type = "workshop" if storage_flag else "ordinary"
                    else:
                        warnings.append(f"Строка {row_number}: признак цеховой кладовой не является булевым; тип склада не задан.")
                item = Warehouse(id=ident, name=name, code=_text(value("code")),
                                 extra=extra, warehouse_type=warehouse_type)
                warehouses[ident] = item
                project.warehouses.append(item)
            else:
                item = Stage(id=ident, name=name, code=_text(value("code")),
                             provider_type=_text(value("provider_type")),
                             rkt_algorithm=_text(value("rkt_algorithm")),
                             level=_level(value("level"), row_number, warnings), extra=extra,
                             launch_layout=_import_layout(extra, row_number, name, warnings),
                             deficit_launch=extra.get("deficit_launch") is True)
                stages[ident] = item
                project.stages.append(item)
                _add_option(project.provider_options, item.provider_type)
                _add_option(project.rkt_options, item.rkt_algorithm)
            continue
        if kind in {"inlet", "stock"}:
            owner, warehouse = _text(value("owner_id")), _text(value("warehouse_id"))
            if not owner:
                warnings.append(f"Строка {row_number}: отсутствует идентификатор передела; строка пропущена.")
                continue
            if not warehouse:
                warnings.append(f"Строка {row_number}: склад не указан; строка связи сохранена с дополнительными параметрами.")
            link = WarehouseLink(warehouse_id=warehouse, primary=_flag(value("primary"), row_number, warnings),
                                 department_id=_text(value("department_id")),
                                 department_name=_text(value("department_name")),
                                 extra=_extra(value("extra_json"), row_number, warnings))
            links.append((row_number, kind, owner, link))
            continue
        warnings.append(f"Строка {row_number}: неизвестный тип записи «{kind}»; строка пропущена.")
    for row, kind, owner, link in links:
        if owner not in stages:
            warnings.append(f"Строка {row}: передел {owner} недоступен; связь не включена в схему.")
            continue
        if link.warehouse_id and link.warehouse_id not in warehouses:
            warnings.append(f"Строка {row}: склад {link.warehouse_id} недоступен; идентификатор связи сохранён.")
        (stages[owner].inlets if kind == "inlet" else stages[owner].stocks).append(link)
    project.rkt_option_ids = option_ids["rkt_option"]
    project.provider_option_ids = option_ids["provider_option"]
    group_ids = set(groups)
    for stage in project.stages:
        parent = _text(stage.extra.get("catalog_parent_id"))
        if parent in group_ids:
            stage.group_id = parent
    return project, warnings


def save_project(project: Project, path: str | os.PathLike[str]) -> None:
    """Atomically save an editable project (never modifies the input workbook)."""
    save_json(project_data(project), path)


def project_data(project: Project) -> dict:
    return {"format": "flow-visualizer-project", "version": FORMAT_VERSION, "project": asdict(project)}


def save_json(data: dict, path: str | os.PathLike[str]) -> None:
    target = Path(path)
    encoded = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=target.parent,
                                         prefix=".flow-", suffix=".tmp", delete=False) as stream:
            temporary = stream.name
            stream.write(encoded)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def load_project(path: str | os.PathLike[str]) -> Project:
    """Load the exact version of the application project; reject other files."""
    with open(path, encoding="utf-8") as stream:
        return parse_project(json.load(stream))


def parse_project(data: dict) -> Project:
    if not isinstance(data, dict) or data.get("format") != "flow-visualizer-project":
        raise ValueError("Файл не является проектом визуализатора.")
    if data.get("version") not in READABLE_FORMAT_VERSIONS:
        raise ValueError(f"Версия проекта {data.get('version')} не поддерживается.")
    try:
        raw = data["project"]
        warehouses = [Warehouse(**item) for item in raw.get("warehouses", [])]
        groups = [Group(**item) for item in raw.get("groups", [])]
        stages = []
        for item in raw.get("stages", []):
            obj = dict(item)
            if obj.get('launch_layout', '') == '':
                obj['launch_layout'] = 'none'
            obj["inlets"] = [WarehouseLink(**link) for link in obj.get("inlets", [])]
            obj["stocks"] = [WarehouseLink(**link) for link in obj.get("stocks", [])]
            stages.append(Stage(**obj))
        edges = [Edge(**item) for item in raw.get("edges", [])]
        project = Project(warehouses=warehouses, stages=stages, edges=edges,
                          source=raw.get("source", ""), title=raw.get("title", "Новая схема"),
                          rkt_options=raw.get("rkt_options", []), provider_options=raw.get("provider_options", []),
                          rkt_option_ids=raw.get("rkt_option_ids", {}),
                          provider_option_ids=raw.get("provider_option_ids", {}), groups=groups,
                          show_warehouses=raw.get("show_warehouses", False) if data['version'] >= 5 else False,
                          view_positions=raw.get("view_positions", {}) if data['version'] >= 5 else {},
                          card_width=raw.get('card_width', 230), card_height=raw.get('card_height', 74),
                          flow_font_size=raw.get('flow_font_size', 30), title_font_size=raw.get('title_font_size', 30),
                          group_font_size=raw.get('group_font_size', 18),
                          colors=raw.get('colors', {}), exchange_map_id=raw.get('exchange_map_id', ''),
                          annotations=[Annotation(**item) for item in raw.get('annotations', [])],
                          auto_align=raw.get('auto_align', False),
                          title_style=TextStyle(**raw['title_style']) if 'title_style' in raw else default_title_style())
        if (type(project.auto_align) is not bool
                or len({item.id for item in project.annotations}) != len(project.annotations)):
            raise ValueError('Некорректные данные слоя оформления.')
        if (type(project.card_width) is not int or not 120 <= project.card_width <= 700
                or type(project.card_height) is not int or not 50 <= project.card_height <= 400):
            raise ValueError('Некорректный размер карточки.')
        if (type(project.flow_font_size) is not int or not 8 <= project.flow_font_size <= 72
                or type(project.title_font_size) is not int or not 8 <= project.title_font_size <= 72
                or type(project.group_font_size) is not int or not 8 <= project.group_font_size <= 72
                or not isinstance(project.colors, dict)
                or any(not isinstance(k, str) or not isinstance(v, str) or len(v) != 7
                       or not v.startswith('#') or any(c not in '0123456789abcdefABCDEF' for c in v[1:])
                       for k, v in project.colors.items())):
            raise ValueError('Некорректные настройки оформления.')
        if not isinstance(project.show_warehouses, bool) or not isinstance(project.view_positions, dict):
            raise ValueError('Некорректное состояние вида схемы.')
        for view, positions in project.view_positions.items():
            if view not in ('compact', 'detailed') or not isinstance(positions, dict):
                raise ValueError('Некорректные сохранённые координаты вида.')
            for ident, coordinates in positions.items():
                if (not isinstance(ident, str) or not isinstance(coordinates, list) or len(coordinates) != 2
                        or any(isinstance(value, bool) or not isinstance(value, (int, float))
                               or not math.isfinite(value) for value in coordinates)):
                    raise ValueError('Некорректные сохранённые координаты передела.')
        if len({item.id for item in stages}) != len(stages) or len({item.id for item in warehouses}) != len(warehouses):
            raise ValueError("В проекте повторяются идентификаторы объектов.")
        for warehouse in warehouses:
            if warehouse.warehouse_type not in WAREHOUSE_TYPES:
                raise ValueError(f"Неизвестный тип склада «{warehouse.name}»: {warehouse.warehouse_type!r}.")
        for stage in stages:
            if not isinstance(stage.has_buffer, bool):
                raise ValueError(f"Некорректный признак буфера передела «{stage.name}».")
            if stage.launch_layout not in ('none', 'product', 'setup', 'assignments', 'demand', 'unknown') or not isinstance(stage.deficit_launch, bool):
                raise ValueError(f"Некорректные обозначения передела «{stage.name}».")
            for coordinate in (stage.x, stage.y):
                if (coordinate is not None and (isinstance(coordinate, bool)
                        or not isinstance(coordinate, (int, float)) or not math.isfinite(coordinate))):
                    raise ValueError(f"Некорректные координаты передела «{stage.name}».")
        for edge in edges:
            if not isinstance(edge.routes, dict):
                raise ValueError('Некорректный маршрут связи.')
            for view, points in edge.routes.items():
                if view not in ('compact', 'detailed') or not isinstance(points, list):
                    raise ValueError('Некорректный маршрут связи.')
                for point in points:
                    if (not isinstance(point, list) or len(point) != 2
                            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                                   or not math.isfinite(value) for value in point)):
                        raise ValueError('Некорректные координаты маршрута связи.')
        group_ids = {group.id for group in groups}
        if "" in group_ids or len(group_ids) != len(groups):
            raise ValueError("В проекте пустые или повторяющиеся идентификаторы групп.")
        for stage in stages:
            if stage.group_id and stage.group_id not in group_ids:
                raise ValueError(f"Передел «{stage.name}» ссылается на отсутствующую группу {stage.group_id}.")
        if data['version'] < 5:
            # Versions 1–4 displayed detailed cards; their manual positions
            # belong to that view, not the new compact view.
            original = {stage.id: [stage.x, stage.y] for stage in stages
                        if stage.x is not None and stage.y is not None}
            if original:
                project.view_positions['detailed'] = original
                for stage in stages:
                    stage.x = stage.y = None
        return project
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Некорректные данные проекта: {exc}") from exc
