import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from flow_visualizer.model import (
    COLUMNS, FORMAT_VERSION, Edge, Group, Project, Stage, Warehouse, WarehouseLink,
    import_xlsx, load_project, save_project,
)


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def workbook(self, rows, header=COLUMNS):
        path = self.root / "выгрузка.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.append(list(header))
        for row in rows:
            sheet.append([row.get(column) for column in header])
        book.save(path)
        book.close()
        return path

    def test_import_launch_layouts_and_unrecognized_values(self):
        values = [
            ('ПроизводствоБезГруппировки', 'none'),
            ('ГруппировкаПоКодуПереналадки', 'setup'),
            ('ПроизводствоСГруппировкойНазначениям', 'assignments'),
            ('ПроизводствоСГруппировкойПоИсточникуПотребности', 'demand'),
            ('Логистика_ГруппировкаПоСкладу', 'unknown'),
        ]
        rows = [dict(kind='stage', id=str(i), name='Передел ' + str(i), provider_type='Производство',
                     extra_json=json.dumps({'launch_layout_state': 'value', 'launch_layout_id': ident,
                                            'launch_layout_name': 'Исходное имя ' + str(i)}, ensure_ascii=False))
                for i, (ident, _) in enumerate(values)]
        rows += [dict(kind='stage', id='empty', name='Пустой', provider_type='Производство',
                      extra_json='{"launch_layout_state":"empty","launch_layout_id":""}'),
                 dict(kind='stage', id='missing', name='Нет записи', provider_type='Производство',
                      extra_json='{"launch_layout_state":"missing"}'),
                 dict(kind='stage', id='old', name='Старый файл', provider_type='Производство')]
        project, warnings = import_xlsx(self.workbook(rows))
        self.assertEqual([s.launch_layout for s in project.stages],
                         [key for _, key in values] + ['none', 'unknown', 'none'])
        self.assertEqual(len(warnings), 2)
        self.assertIn('Исходное имя 4', warnings[0])
        self.assertIn('отсутствует или недоступна', warnings[1])
        self.assertEqual(project.stages[4].extra['launch_layout_id'], values[4][0])
        output = self.root / 'макеты.flow.json'
        save_project(project, output)
        self.assertEqual(load_project(output), project)

    def test_import_and_save_round_trip(self):
        path = self.workbook([
            # Links may precede the objects they point to.
            {"kind": "inlet", "owner_id": "stage-1", "warehouse_id": "wh-1", "primary": "Истина",
             "extra_json": '{"НеУчитыватьПриЗапуске": true}'},
            {"kind": "stock", "owner_id": "stage-1", "warehouse_id": "wh-1", "primary": 1,
             "department_id": "dept-1", "department_name": "Цех № 1"},
            {"kind": "stage", "id": "stage-1", "name": "Обработка", "provider_type": "Производство",
             "rkt_algorithm": "Выпуск", "code": "001", "level": 2},
            {"kind": "warehouse", "id": "wh-1", "name": "Склад", "code": "002"},
            {"kind": "rkt_option", "id": "release", "name": "Выпуск"},
            {"kind": "rkt_option", "id": "start", "name": "Запуск"},
            {"kind": "provider_option", "id": "purchase", "name": "Покупка"},
        ])
        project, warnings = import_xlsx(path)
        self.assertEqual(warnings, [])
        self.assertEqual(project.warehouses[0].warehouse_type, "")
        self.assertFalse(project.stages[0].has_buffer)
        self.assertEqual(project.stages[0].level, 2)
        self.assertTrue(project.stages[0].inlets[0].primary)
        self.assertTrue(project.stages[0].inlets[0].extra["НеУчитыватьПриЗапуске"])
        self.assertEqual(project.stages[0].stocks[0].department_name, "Цех № 1")
        self.assertEqual(set(project.rkt_options), {"Выпуск", "Запуск"})
        self.assertIn("Покупка", project.provider_options)
        self.assertEqual(project.rkt_option_ids["release"], "Выпуск")
        self.assertEqual(project.provider_option_ids["purchase"], "Покупка")
        new = Stage(name="Новый", provider_type="Покупка", x=12.5, y=-3)
        project.stages.append(new)
        project.edges.append(Edge(source="stage-1", target=new.id))
        output = self.root / "схема.flow"
        save_project(project, output)
        self.assertEqual(project, load_project(output))
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["version"], FORMAT_VERSION)

    def test_group_round_trip_and_legacy_project(self):
        project = Project(groups=[Group(id="g1", name="Цех 1"), Group(id="g2", name="Цех 2")],
                          stages=[Stage(id="s1", name="Резка", group_id="g1"),
                                  Stage(id="s2", name="Сборка", group_id="g1"),
                                  Stage(id="s3", name="Покупка")])
        path = self.root / "groups.flow"
        save_project(project, path)
        self.assertEqual(load_project(path), project)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], FORMAT_VERSION)
        # Version 1 documents had no groups or group_id fields.
        data["version"] = 1
        data["project"].pop("groups")
        for stage in data["project"]["stages"]:
            stage.pop("group_id")
            stage.pop("has_buffer")
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        legacy = load_project(path)
        self.assertEqual(legacy.groups, [])
        self.assertTrue(all(stage.group_id == "" for stage in legacy.stages))
        self.assertEqual([stage.id for stage in legacy.stages], ["s1", "s2", "s3"])

    def test_warehouse_type_buffer_and_legacy_data(self):
        project = Project(
            warehouses=[Warehouse(id="material", name="Материальный", warehouse_type="ordinary", extra={"from_1c": "id"}),
                        Warehouse(id="shop", name="Кладовая", warehouse_type="workshop")],
            stages=[Stage(id="stage", name="Передел", has_buffer=True,
                          inlets=[WarehouseLink(warehouse_id="material", extra={"parameter_name": "Лист"})],
                          stocks=[WarehouseLink(warehouse_id="shop", department_name="Цех 1")])],
        )
        path = self.root / "types.flow"
        save_project(project, path)
        self.assertEqual(load_project(path), project)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], FORMAT_VERSION)
        self.assertEqual(data["project"]["warehouses"][0]["warehouse_type"], "ordinary")
        self.assertEqual(data["project"]["warehouses"][1]["warehouse_type"], "workshop")
        self.assertTrue(data["project"]["stages"][0]["has_buffer"])
        # Previous versions have no recorded global warehouse classification or buffer flag.
        data["version"] = 2
        for warehouse in data["project"]["warehouses"]:
            warehouse.pop("warehouse_type")
        for stage in data["project"]["stages"]:
            stage.pop("has_buffer")
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        legacy = load_project(path)
        self.assertEqual([w.warehouse_type for w in legacy.warehouses], ["", ""])
        self.assertFalse(legacy.stages[0].has_buffer)
        self.assertEqual(legacy.warehouses[0].extra, {"from_1c": "id"})
        self.assertEqual(legacy.stages[0].inlets[0].extra, {"parameter_name": "Лист"})
        self.assertEqual(legacy.stages[0].stocks[0].department_name, "Цех 1")

    def test_verified_xlsx_warehouse_flag(self):
        path = self.workbook([
            {"kind": "warehouse", "id": "shop", "name": "Цех", "extra_json": '{"workshop_storage": true, "source": "1C"}'},
            {"kind": "warehouse", "id": "ordinary", "name": "Материальный", "extra_json": '{"workshop_storage": false}'},
            {"kind": "warehouse", "id": "missing", "name": "Старый формат", "extra_json": '{}'},
            {"kind": "warehouse", "id": "invalid", "name": "Ошибка", "extra_json": '{"workshop_storage": "false"}'},
        ])
        project, warnings = import_xlsx(path)
        self.assertEqual([warehouse.warehouse_type for warehouse in project.warehouses],
                         ["workshop", "ordinary", "", ""])
        self.assertEqual(len(warnings), 1)
        self.assertIn("не является булевым", warnings[0])
        self.assertEqual(project.warehouses[0].extra, {"workshop_storage": True, "source": "1C"})
        output = self.root / "imported.flow"
        save_project(project, output)
        self.assertEqual(load_project(output), project)

    def test_production_division_groups_keep_id_and_do_not_assign_stages(self):
        path = self.workbook([
            {"kind": "group", "id": "division-a", "name": "Цех", "code": "000000057",
             "extra_json": '{"parent_id":"division-parent","status":"Действует"}'},
            {"kind": "group", "id": "division-b", "name": "Цех", "code": "000000058"},
            {"kind": "stage", "id": "stage", "name": "Передел"},
        ])
        project, warnings = import_xlsx(path)
        self.assertEqual(warnings, [])
        self.assertEqual([(g.id, g.name, g.code) for g in project.groups],
                         [("division-a", "Цех", "000000057"), ("division-b", "Цех", "000000058")])
        self.assertEqual(project.groups[0].extra["parent_id"], "division-parent")
        self.assertEqual(project.stages[0].group_id, "")
        output = self.root / "groups.flow"
        save_project(project, output)
        self.assertEqual(load_project(output), project)
        duplicate = self.workbook([{"kind": "group", "id": "x"}, {"kind": "group", "id": "x"}])
        with self.assertRaisesRegex(ValueError, "повторный идентификатор подразделения"):
            import_xlsx(duplicate)

    def test_invalid_warehouse_type_or_buffer_rejected(self):
        path = self.root / "invalid.flow"
        project = Project(warehouses=[Warehouse(name="Склад")], stages=[Stage(name="Передел")])
        save_project(project, path)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["project"]["warehouses"][0]["warehouse_type"] = "other"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Неизвестный тип склада"):
            load_project(path)
        data["project"]["warehouses"][0]["warehouse_type"] = "ordinary"
        data["project"]["stages"][0]["has_buffer"] = "false"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "признак буфера"):
            load_project(path)

    def test_bad_group_reference_is_not_silently_discarded(self):
        path = self.root / "badgroup.flow"
        project = Project(groups=[Group(id="g", name="A")], stages=[Stage(id="s", group_id="missing")])
        save_project(project, path)
        with self.assertRaisesRegex(ValueError, "отсутствующую группу"):
            load_project(path)
        project.stages[0].group_id = "g"
        project.groups.append(Group(id="g", name="B"))
        save_project(project, path)
        with self.assertRaisesRegex(ValueError, "повторяющиеся идентификаторы групп"):
            load_project(path)

    def test_reference_and_value_warnings(self):
        path = self.workbook([
            {"kind": "stage", "id": "s", "name": "S", "level": "oops"},
            {"kind": "inlet", "owner_id": "s", "warehouse_id": "missing", "primary": "maybe",
             "extra_json": "not json"},
            {"kind": "stock", "owner_id": "unknown", "warehouse_id": "w"},
        ])
        project, warnings = import_xlsx(path)
        self.assertEqual(len(warnings), 5)
        self.assertIsNone(project.stages[0].level)
        self.assertEqual(project.stages[0].inlets[0].warehouse_id, "missing")
        self.assertEqual(project.stages[0].inlets[0].extra["raw_extra_json"], "not json")

    def test_empty_warehouse_keeps_parameterized_rows(self):
        path = self.workbook([
            {"kind": "stage", "id": "stage", "name": "Резка"},
            {"kind": "inlet", "owner_id": "stage", "warehouse_id": "",
             "extra_json": '{"parameter_type":"СправочникСсылка.Назначения","parameter_name":"Материалы"}'},
            {"kind": "inlet", "owner_id": "stage", "warehouse_id": "",
             "extra_json": '{"parameter_name":"Другое"}'},
        ])
        project, warnings = import_xlsx(path)
        self.assertEqual(len(warnings), 2)
        self.assertEqual(len(project.stages[0].inlets), 2)
        self.assertEqual(project.stages[0].inlets[0].warehouse_id, "")
        self.assertEqual(project.stages[0].inlets[0].extra["parameter_name"], "Материалы")
        output = self.root / "saved.flow"
        save_project(project, output)
        self.assertEqual(project, load_project(output))

    def test_duplicate_ids_and_wrong_file_are_rejected(self):
        path = self.workbook([{"kind": "stage", "id": "s"}, {"kind": "stage", "id": "s"}])
        with self.assertRaisesRegex(ValueError, "повторный идентификатор"):
            import_xlsx(path)
        path = self.workbook([], header=("kind", "id"))
        with self.assertRaisesRegex(ValueError, "отсутствуют столбцы"):
            import_xlsx(path)
        bad = self.root / "bad.flow"
        bad.write_text('{"format":"other","version":1}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "не является"):
            load_project(bad)

    def test_dataclass_defaults_are_not_shared(self):
        first, second = Project(), Project()
        first.warehouses.append(Warehouse(name="A"))
        first.stages.append(Stage(inlets=[WarehouseLink(warehouse_id="A")]))
        self.assertEqual(second.warehouses, [])
        self.assertEqual(second.stages, [])

    def test_edge_routes_roundtrip_and_old_project_default(self):
        project = Project(stages=[Stage(id='a'), Stage(id='b')], edges=[
            Edge('a', 'b', routes={'compact': [[40.5, -12], [100, 22]], 'detailed': [[80, 60]]}),
            Edge('b', 'a'),
        ])
        path = self.root / 'routes.flow'
        save_project(project, path)
        self.assertEqual(load_project(path), project)
        data = json.loads(path.read_text(encoding='utf-8'))
        data['version'] = 5
        for edge in data['project']['edges']:
            edge.pop('routes')
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        old = load_project(path)
        self.assertEqual([edge.routes for edge in old.edges], [{}, {}])
        old.edges[0].routes['compact'] = [[1, 2]]
        self.assertEqual(old.edges[1].routes, {})

    def test_invalid_edge_route_is_not_silently_discarded(self):
        path = self.root / 'bad-routes.flow'
        project = Project(edges=[Edge('a', 'b')])
        save_project(project, path)
        data = json.loads(path.read_text(encoding='utf-8'))
        for routes in ({'wrong-view': [[0, 1]]}, {'compact': [[1]]},
                       {'compact': [[True, 1]]}, {'compact': [[float('inf'), 1]]}):
            data['project']['edges'][0]['routes'] = routes
            path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'маршрут'):
                load_project(path)


if __name__ == "__main__":
    unittest.main()
