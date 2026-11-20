import tempfile
import unittest
import json
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QApplication
from flow_visualizer import gui, model
from flow_visualizer.view_projection import project_positions, overlaps

APP = QApplication.instance() or QApplication([])


class ViewProjectionTests(unittest.TestCase):
    def test_projection_preserves_rows_columns_and_nonoverlap_with_different_sizes(self):
        positions = {'a': (0, 0), 'b': (0, 120), 'c': (300, 0), 'd': (600, 120)}
        old = {key: QRectF(0, 0, 200, 70) for key in positions}
        new = {'a': QRectF(0, 0, 300, 300), 'b': QRectF(0, 0, 250, 180),
               'c': QRectF(0, 0, 260, 100), 'd': QRectF(0, 0, 310, 250)}
        result, scale = project_positions(positions, old, new)
        self.assertFalse(overlaps(result, new))
        centers = {key: QRectF(new[key]).translated(*result[key]).center() for key in result}
        self.assertAlmostEqual(centers['a'].x(), centers['b'].x())
        self.assertAlmostEqual(centers['a'].y(), centers['c'].y())
        self.assertLess(centers['a'].x(), centers['c'].x())
        self.assertLess(centers['c'].x(), centers['d'].x())
        self.assertLess(centers['a'].y(), centers['b'].y())
        self.assertGreater(scale[1], 1)


class ViewSwitchUI(unittest.TestCase):
    def setUp(self):
        self.group = model.Group(name='Цех')
        self.warehouses = [model.Warehouse(name='Обычный склад', warehouse_type='ordinary'),
                           model.Warehouse(name='Главный склад', warehouse_type='workshop')]
        self.stages = [model.Stage(name='Резка', provider_type='Производство', rkt_algorithm='По ресурсам',
                                   group_id=self.group.id, x=50, y=50,
                                   inlets=[model.WarehouseLink(warehouse_id=self.warehouses[0].id),
                                           model.WarehouseLink(warehouse_id=self.warehouses[1].id, primary=True)]),
                       model.Stage(name='Покраска', provider_type='Производство', group_id=self.group.id,
                                   x=50, y=190),
                       model.Stage(name='Отгрузка', provider_type='Логистика', x=420, y=50)]
        self.project = model.Project(groups=[self.group], stages=self.stages, warehouses=self.warehouses,
                                     edges=[model.Edge(source=self.stages[0].id, target=self.stages[2].id)])
        self.window = gui.MainWindow()
        self.window.set_project(self.project)
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        self.window.dirty = False
        self.window.close()
        APP.processEvents()

    def test_first_switch_preserves_composition_and_round_trip_positions(self):
        # The RKT card is wider to keep its title font and icon readable.
        # Align the actual card centres before testing column preservation.
        first = self.window.nodes[self.stages[0].id]
        second = self.window.nodes[self.stages[1].id]
        first.setPos(first.pos().x() + second.connection_rect().center().x()
                     - first.connection_rect().center().x(), first.pos().y())
        compact = [(s.x, s.y) for s in self.stages]
        self.window.show_warehouses_action.setChecked(True)
        a, b, c = [self.window.nodes[s.id].connection_rect().center() for s in self.stages]
        self.assertAlmostEqual(a.x(), b.x(), delta=.01)
        self.assertLess(a.y(), b.y())
        self.assertAlmostEqual(a.y(), c.y(), delta=.01)
        self.assertLess(a.x(), c.x())
        self.assertFalse(self.window.nodes[self.stages[0].id].sceneBoundingRect().intersects(
            self.window.nodes[self.stages[1].id].sceneBoundingRect()))
        self.assertTrue(self.window.edge_items)
        self.window.show_warehouses_action.setChecked(False)
        for stage, (x, y) in zip(self.stages, compact):
            self.assertAlmostEqual(stage.x, x, delta=.001)
            self.assertAlmostEqual(stage.y, y, delta=.001)

    def test_changes_propagate_both_ways_and_stale_view_is_not_restored(self):
        self.project.view_positions['detailed'] = {s.id: [5000 + i * 600, 4000] for i, s in enumerate(self.stages)}
        before = [(s.x, s.y) for s in self.stages]
        self.window.show_warehouses_action.setChecked(True)
        self.assertLess(self.stages[0].x, 1000)
        self.assertLess(self.stages[0].y, self.stages[1].y)
        node = self.window.nodes[self.stages[2].id]
        node.setPos(node.pos().x() + 200, node.pos().y())
        self.window.show_warehouses_action.setChecked(False)
        self.assertAlmostEqual(self.stages[0].x, before[0][0], delta=.01)
        self.assertGreater(self.stages[2].x, before[2][0])
        compact_changed = self.stages[2].x
        self.window.nodes[self.stages[2].id].setPos(compact_changed + 100, self.stages[2].y)
        self.window.show_warehouses_action.setChecked(True)
        after = self.stages[2].x
        self.window.show_warehouses_action.setChecked(False)
        self.assertAlmostEqual(self.stages[2].x, compact_changed + 100, delta=.01)
        self.window.show_warehouses_action.setChecked(True)
        self.assertAlmostEqual(self.stages[2].x, after, delta=.01)

    def test_rkt_and_primary_warehouse_are_clear_in_detailed_card(self):
        self.window.show_warehouses_action.setChecked(True)
        stage = self.stages[0]
        node = self.window.nodes[stage.id]
        self.assertEqual(gui.compact_color_for_stage(stage, self.project.colors).name(), '#c6a0de')
        self.assertLessEqual(node.algorithm_rect().height(), node.header_height - 16)
        plain = node.body.toPlainText()
        html = node.body.toHtml().casefold()
        self.assertIn('алгоритм ркт', plain.casefold())
        self.assertIn('настройки передела', plain.casefold())
        self.assertIn('входные стеллажи', plain.casefold())
        self.assertIn('склады остатков в работе', plain.casefold())
        self.assertGreaterEqual(html.count('<hr'), 2)
        self.assertEqual(len(node.section_dividers), 2)
        self.assertIn('font-weight:700', html)
        self.assertLess(plain.index('Главный склад'), plain.index('Обычный склад'))
        self.assertFalse(stage.inlets[0].primary)  # Presentation must not reorder source rows.
        self.window.nodes[stage.id].setSelected(True)
        APP.processEvents()
        self.assertEqual(self.window.inlets.item(0, 0).data(gui.Qt.UserRole), self.warehouses[1].id)

    def test_primary_warehouse_moves_to_first_row_after_user_change(self):
        stage = self.stages[0]
        self.window.nodes[stage.id].setSelected(True)
        APP.processEvents()
        table = self.window.inlets
        old_row = next(i for i in range(table.rowCount())
                       if table.item(i, 0).data(Qt.UserRole) == self.warehouses[1].id)
        table.item(old_row, 1).setCheckState(Qt.Unchecked)
        APP.processEvents()
        new_row = next(i for i in range(table.rowCount())
                       if table.item(i, 0).data(Qt.UserRole) == self.warehouses[0].id)
        table.item(new_row, 1).setCheckState(Qt.Checked)
        APP.processEvents()
        self.assertEqual(table.item(0, 0).data(Qt.UserRole), self.warehouses[0].id)
        self.window.show_warehouses_action.setChecked(True)
        text = self.window.nodes[stage.id].body.toPlainText()
        self.assertLess(text.index('Обычный склад'), text.index('Главный склад'))

    def test_new_stage_keeps_current_structure_when_switching(self):
        self.window.show_warehouses_action.setChecked(True)
        self.window.add_stage()
        self.window.name_input.setText('Новый этап')
        self.window.type_input.setCurrentIndex(self.window.type_input.findData('Производство'))
        self.window.show_warehouses_action.setChecked(False)
        a, b, c = self.stages[:3]
        self.assertLess(a.y, b.y)
        self.assertLess(a.x, c.x)
        self.assertGreater(self.project.stages[-1].x, c.x)
        bounds = [self.window._stage_bounds(stage) for stage in self.project.stages]
        self.assertTrue(all(not x.intersects(y) for i, x in enumerate(bounds) for y in bounds[i+1:]))

    def test_manual_route_tracks_moved_blocks_without_losing_bends(self):
        edge = self.project.edges[0]
        edge.routes['compact'] = [[280.0, 300.0], [410.0, 300.0]]
        self.window.render_scene()
        self.window.show_warehouses_action.setChecked(True)
        self.window.nodes[self.stages[2].id].setPos(self.stages[2].x + 200, self.stages[2].y + 60)
        self.window.show_warehouses_action.setChecked(False)
        self.assertEqual(len(edge.routes['compact']), 2)
        self.assertGreater(edge.routes['compact'][1][0], 410)
        self.assertEqual(edge.source, self.stages[0].id)
        self.assertEqual(edge.target, self.stages[2].id)
        self.assertEqual(self.window.edge_items[0]._head[0], self.window.edge_items[0]._points[-1])

    def test_save_and_reopen_still_uses_current_composition(self):
        self.window.show_warehouses_action.setChecked(True)
        self.window.nodes[self.stages[2].id].setPos(self.stages[2].x + 180, self.stages[2].y + 140)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'view.flow.json'
            self.window.path = str(path)
            self.assertTrue(self.window.save())
            loaded = model.load_project(path)
            self.window.set_project(loaded, str(path))
            self.assertTrue(self.window.show_warehouses_action.isChecked())
            self.window.show_warehouses_action.setChecked(False)
            a, b, c = loaded.stages
            self.assertLess(a.y, b.y)
            self.assertLess(a.x, c.x)
            self.assertGreater(c.y, a.y)

    def test_legacy_overlapping_project_opens_without_destroying_coordinates(self):
        old = model.Project(stages=[model.Stage(name='A', provider_type='Покупка', x=20, y=50),
                                    model.Stage(name='B', provider_type='Покупка', x=20, y=50)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.json'
            model.save_project(old, path)
            data = json.loads(path.read_text(encoding='utf-8'))
            data['version'] = 4
            path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            loaded = model.load_project(path)
            self.window.set_project(loaded, str(path))
            self.assertTrue(self.window.show_warehouses_action.isChecked())
            self.assertEqual([(s.x, s.y) for s in loaded.stages], [(20, 50), (20, 50)])
