"""Regression for switching diagram detail without obscuring stage cards."""
import json
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from flow_visualizer import gui, model


APP = QApplication.instance() or QApplication([])


class DiagramAcceptanceTests(unittest.TestCase):
    def test_compact_to_detailed_view_keeps_group_cards_readable(self):
        group = model.Group(name='Производственный цех')
        warehouse = model.Warehouse(name='Длинное наименование входного склада', warehouse_type='ordinary')
        first = model.Stage(name='Резка', provider_type='Производство', group_id=group.id, level=1,
                            inlets=[model.WarehouseLink(warehouse_id=warehouse.id)], has_buffer=True)
        second = model.Stage(name='Штамповка', provider_type='Производство', group_id=group.id, level=1)
        project = model.Project(groups=[group], warehouses=[warehouse], stages=[first, second])
        window = gui.MainWindow()
        window.set_project(project)
        window.show()
        APP.processEvents()
        try:
            window.auto_layout()
            APP.processEvents()
            compact_positions = [(s.x, s.y) for s in project.stages]
            self.assertFalse(window.nodes[first.id].sceneBoundingRect().intersects(
                window.nodes[second.id].sceneBoundingRect()))
            window.show_warehouses_action.setChecked(True)
            APP.processEvents()
            self.assertFalse(window.nodes[first.id].sceneBoundingRect().intersects(
                window.nodes[second.id].sceneBoundingRect()), 'Карточки перекрылись при включении складов')
            self.assertIn(warehouse.name, window.nodes[first.id].body.toPlainText())
            self.assertEqual(first.inlets[0].warehouse_id, warehouse.id)
            window.nodes[first.id].setPos(first.x + 35, first.y)
            APP.processEvents()
            detailed_positions = [(s.x, s.y) for s in project.stages]
            window.show_warehouses_action.setChecked(False)
            APP.processEvents()
            synced_compact = [(s.x, s.y) for s in project.stages]
            self.assertGreater(synced_compact[0][0], compact_positions[0][0])
            self.assertEqual(synced_compact[1], compact_positions[1])
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'project.flow.json'
                window.path = str(path)
                self.assertTrue(window.save())
                loaded = model.load_project(path)
                another = gui.MainWindow()
                another.set_project(loaded)
                another.show()
                APP.processEvents()
                try:
                    self.assertEqual([(s.x, s.y) for s in loaded.stages], synced_compact)
                    another.show_warehouses_action.setChecked(True)
                    APP.processEvents()
                    self.assertEqual(len(loaded.stages), len(detailed_positions))
                    self.assertEqual(loaded.stages[0].group_id, loaded.stages[1].group_id)
                    self.assertFalse(another.nodes[loaded.stages[0].id].sceneBoundingRect().intersects(
                        another.nodes[loaded.stages[1].id].sceneBoundingRect()))
                finally:
                    another.dirty = False
                    another.close()
        finally:
            window.dirty = False
            window.close()
            APP.processEvents()

    def test_old_project_coordinates_are_the_detailed_layout(self):
        for version in (1, 2, 3, 4):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                stage = model.Stage(name='Резка', provider_type='Производство', x=321.0, y=654.0)
                project = model.Project(stages=[stage])
                path = Path(directory) / 'legacy.flow.json'
                model.save_project(project, path)
                data = json.loads(path.read_text(encoding='utf-8'))
                data['version'] = version
                data['project'].pop('show_warehouses', None)
                data['project'].pop('view_positions', None)
                path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
                loaded = model.load_project(path)
                self.assertEqual(loaded.view_positions['detailed'][stage.id], [321.0, 654.0])
                window = gui.MainWindow()
                window.set_project(loaded)
                window.show()
                APP.processEvents()
                try:
                    self.assertFalse(window.show_warehouses_action.isChecked())
                    window.show_warehouses_action.setChecked(True)
                    self.assertEqual((loaded.stages[0].x, loaded.stages[0].y), (321.0, 654.0))
                    window.show_warehouses_action.setChecked(False)
                    window.show_warehouses_action.setChecked(True)
                    self.assertEqual((loaded.stages[0].x, loaded.stages[0].y), (321.0, 654.0))
                finally:
                    window.dirty = False
                    window.close()
                    APP.processEvents()

    def test_cycle_and_intergroup_return_edges_keep_original_direction(self):
        first_group = model.Group(name='Первый цех')
        second_group = model.Group(name='Второй цех')
        stages = [model.Stage(name='A', provider_type='Производство', group_id=first_group.id),
                  model.Stage(name='B', provider_type='Производство', group_id=second_group.id),
                  model.Stage(name='C', provider_type='Производство', group_id=first_group.id)]
        project = model.Project(groups=[first_group, second_group], stages=stages)
        window = gui.MainWindow()
        window.set_project(project)
        window.show()
        APP.processEvents()
        try:
            for left, right in ((0, 1), (1, 2), (2, 0)):
                self.assertTrue(window.create_edge(stages[left].id, stages[right].id))
            self.assertEqual([(e.source, e.target) for e in project.edges],
                             [(stages[a].id, stages[b].id) for a, b in ((0, 1), (1, 2), (2, 0))])
            self.assertEqual(len(window.edge_items), 3)
            for index, edge in enumerate(project.edges):
                source = window.nodes[edge.source].connection_rect()
                target = window.nodes[edge.target].connection_rect()
                item = window.edge_items[index]
                start, end = item._points[0], item._points[-1]
                forwards = source.center().x() <= target.center().x()
                self.assertAlmostEqual(start.x(), source.right() if forwards else source.left())
                self.assertAlmostEqual(end.x(), target.left() if forwards else target.right())
                self.assertEqual(item._head[0], end)
        finally:
            window.dirty = False
            window.close()
            APP.processEvents()

    def test_new_link_preserves_both_saved_views_and_direction(self):
        a = model.Stage(name='A', provider_type='Производство')
        b = model.Stage(name='B', provider_type='Производство')
        project = model.Project(stages=[a, b])
        window = gui.MainWindow()
        window.set_project(project)
        window.show()
        APP.processEvents()
        try:
            window.auto_layout()
            self.assertLess(a.x, b.x)
            window.show_warehouses_action.setChecked(True)
            detailed_positions = [(s.x, s.y) for s in project.stages]
            window.show_warehouses_action.setChecked(False)
            compact_positions = [(s.x, s.y) for s in project.stages]
            self.assertTrue(window.create_edge(b.id, a.id))
            self.assertEqual([(s.x, s.y) for s in project.stages], compact_positions)
            window.show_warehouses_action.setChecked(True)
            APP.processEvents()
            self.assertEqual([(s.x, s.y) for s in project.stages], detailed_positions)
            self.assertEqual([(e.source, e.target) for e in project.edges], [(b.id, a.id)])
            item = window.edge_items[0]
            self.assertEqual(item._head[0], item._points[-1])
        finally:
            window.dirty = False
            window.close()
            APP.processEvents()


if __name__ == '__main__':
    unittest.main()
