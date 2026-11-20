import json
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from flow_visualizer import exchange, gui, model


APP = QApplication.instance() or QApplication([])


def stage_row(ident, name):
    data = {"kind": "stage", "id": ident, "name": name, "provider_type": "Производство",
            "extra_json": '{"launch_layout_state":"empty","deficit_launch":true}'}
    return [data.get(key, "") for key in model.COLUMNS]


class ExchangeTests(unittest.TestCase):
    def test_map_round_trip_rebinds_routes_and_appends_unmarked_stages(self):
        group = model.Group(id="g", name="Цех")
        project = model.Project(title="Тест", groups=[group],
                                title_style=model.TextStyle(bold=True, alignment='right', text_color='#ab4620'),
                                stages=[model.Stage(id="b", name="Б", provider_type="Производство", x=450, y=40),
                                        model.Stage(id="a", name="А", provider_type="Производство", x=-20, y=60,
                                                    group_id="g", has_buffer=True)],
                                edges=[model.Edge("a", "b", {"compact": [[300, 150]], "detailed": [[360, 120]]})],
                                view_positions={"detailed": {"a": [-50, -10], "b": [400, 25]}})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.json"
            map_id = exchange.export_map(project, path)
            package = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(package["order"], ["a", "b"])
            self.assertEqual([row["id"] for row in package["stages"]], package["order"])
            payload = {"format": exchange.FROM_ERP, "version": 1, "map_id": map_id,
                       "snapshot": {"project": package["project"], "published_groups": False,
                                    "bindings": [{"source": "a", "target": "1"}, {"source": "b", "target": "2"}],
                                    "warehouse_bindings": []},
                       "rows": [stage_row("1", "Живое А"), stage_row("2", "Живое Б"),
                                stage_row("3", "Добавлен в 1С")]}
            model.save_json(payload, path)
            restored, warnings = exchange.import_map(path)
            exchange.export_map(restored, path)
            exported_again = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(exported_again["order"], ["1", "2", "3"])
        self.assertFalse(warnings)
        self.assertEqual(restored.exchange_map_id, map_id)
        self.assertEqual(restored.title_style, project.title_style)
        self.assertEqual([stage.name for stage in restored.stages], ["Живое А", "Живое Б", "Добавлен в 1С"])
        self.assertTrue(restored.stages[0].deficit_launch)
        self.assertTrue(restored.stages[0].has_buffer)
        self.assertEqual(restored.stages[0].group_id, "g")
        self.assertEqual(restored.edges, [model.Edge("1", "2", project.edges[0].routes)])
        window = gui.MainWindow()
        self.addCleanup(window.deleteLater)
        window.set_project(restored, ordered=True)
        self.assertEqual([s.x for s in restored.stages[:2]], [-20, 450])
        self.assertGreater(restored.stages[2].x, restored.stages[1].x + window.nodes["2"].width)
        window.show_warehouses_action.setChecked(True)
        self.assertEqual([s.x for s in restored.stages[:2]], [-50, 400])
        self.assertEqual(restored.edges[0].routes["detailed"], [[360, 120]])
