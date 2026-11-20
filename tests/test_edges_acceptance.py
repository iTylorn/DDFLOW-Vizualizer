"""End-to-end mouse interaction and persistence for user-adjusted arrows."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from flow_visualizer import gui, model, print_export
from flow_visualizer.edge_editor import EditableEdgeItem


APP = QApplication.instance() or QApplication([])


class EdgeAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.a = model.Stage(name='Поставка', provider_type='Покупка', level=1)
        self.b = model.Stage(name='Резка', provider_type='Производство', level=2)
        self.project = model.Project(title='Проверка связей', stages=[self.a, self.b])
        self.window = gui.MainWindow()
        self.window.set_project(self.project)
        self.window.show()
        APP.processEvents()
        self.window.fit_all()
        APP.processEvents()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        APP.processEvents()

    def click_node(self, stage_id):
        self.window.view.ensureVisible(self.window.nodes[stage_id], 20, 20)
        APP.processEvents()
        position = self.window.view.mapFromScene(self.window.nodes[stage_id].sceneBoundingRect().center())
        QTest.mouseClick(self.window.view.viewport(), Qt.LeftButton, Qt.NoModifier, position)
        APP.processEvents()

    def test_link_mode_click_order_and_escape(self):
        self.window.link_action.setChecked(True)
        self.click_node(self.a.id)
        self.assertEqual(self.window.link_source, self.a.id)
        QTest.keyClick(self.window.view, Qt.Key_Escape)
        APP.processEvents()
        self.assertFalse(self.window.link_action.isChecked())
        self.assertFalse(self.project.edges)
        self.window.link_action.setChecked(True)
        previous = [(stage.x, stage.y) for stage in self.project.stages]
        self.click_node(self.b.id)
        self.click_node(self.a.id)
        self.assertEqual([(e.source, e.target) for e in self.project.edges], [(self.b.id, self.a.id)])
        self.assertTrue(self.window.link_action.isChecked())
        self.click_node(self.a.id)
        self.click_node(self.b.id)
        self.assertEqual([(e.source, e.target) for e in self.project.edges],
                         [(self.b.id, self.a.id), (self.a.id, self.b.id)])
        self.assertTrue(self.window.link_action.isChecked())
        QTest.keyClick(self.window.view, Qt.Key_Escape)
        self.assertFalse(self.window.link_action.isChecked())
        self.assertEqual([(stage.x, stage.y) for stage in self.project.stages], previous)
        self.assertGreater(self.b.x, self.a.x)  # backward arrow, same requested direction

    def test_drag_routes_persist_with_attached_endpoints_and_print(self):
        self.assertTrue(self.window.create_edge(self.a.id, self.b.id))
        APP.processEvents()
        item = self.window.edge_items[0]
        self.assertIsInstance(item, EditableEdgeItem)
        # Real selection through the viewport, then drag its visible handle.
        mid = item._points[0] + (item._points[-1] - item._points[0]) / 2
        QTest.mouseClick(self.window.view.viewport(), Qt.LeftButton, Qt.NoModifier,
                         self.window.view.mapFromScene(mid))
        APP.processEvents()
        self.assertTrue(item.isSelected())
        handle = self.window.view.mapFromScene(item._handles[0])
        QTest.mousePress(self.window.view.viewport(), Qt.LeftButton, Qt.NoModifier, handle)
        QTest.mouseMove(self.window.view.viewport(), handle + QPoint(0, 65), 20)
        QTest.mouseRelease(self.window.view.viewport(), Qt.LeftButton, Qt.NoModifier, handle + QPoint(0, 65))
        APP.processEvents()
        edge = self.project.edges[0]
        self.assertTrue(edge.routes.get('compact'))
        saved_route = [list(p) for p in edge.routes['compact']]
        previous_start, previous_end = QPointF(item._points[0]), QPointF(item._points[-1])
        self.window.nodes[self.a.id].setPos(self.a.x + 35, self.a.y + 22)
        self.window.nodes[self.b.id].setPos(self.b.x + 20, self.b.y + 17)
        APP.processEvents()
        self.assertNotEqual(item._points[0], previous_start)
        self.assertNotEqual(item._points[-1], previous_end)
        self.assertEqual(edge.routes['compact'], saved_route)
        # The preview hides editing aids and restores them on return.
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / 'diagram.pdf'
            def fake_preview(scene, parent):
                self.assertFalse(item._show_handles)
                print_export.export_pdf(scene, pdf)
            with patch.object(print_export, 'show_preview', fake_preview):
                self.window.print_pdf()
            self.assertTrue(pdf.read_bytes().startswith(b'%PDF'))
            self.assertTrue(item._show_handles)
            path = Path(directory) / 'project.flow.json'
            model.save_project(self.project, path)
            loaded = model.load_project(path)
            self.assertEqual(loaded.edges[0].routes['compact'], saved_route)
            self.window.show_warehouses_action.setChecked(True)
            self.window.show_warehouses_action.setChecked(False)
            APP.processEvents()
            self.assertEqual(edge.routes['compact'], saved_route)
            self.assertEqual(len(self.window.edge_items), 1)

    def test_manual_routes_survive_new_connections_and_remain_view_specific(self):
        third = model.Stage(name='Сборка', provider_type='Производство', level=3)
        self.project.stages.append(third)
        self.window.set_project(self.project)
        APP.processEvents()
        self.assertTrue(self.window.create_edge(self.a.id, self.b.id))
        edge = self.project.edges[0]
        first = self.window.edge_items[0]
        first._manual = [QPointF(175, 250)]
        first._recompute()
        first.on_change(edge, 'compact', [[175, 250]])
        self.assertTrue(self.window.create_edge(self.b.id, third.id))
        self.assertEqual(edge.routes['compact'], [[175, 250]], 'Новая связь не должна удалять ручной маршрут')
        first = next(item for item in self.window.edge_items if item.edge is edge)
        self.assertEqual((first._manual[0].x(), first._manual[0].y()), (175, 250))
        self.window.show_warehouses_action.setChecked(True)
        APP.processEvents()
        first = next(item for item in self.window.edge_items if item.edge is edge)
        first._manual = [QPointF(200, 300)]
        first._recompute()
        first.on_change(edge, 'detailed', [[200, 300]])
        self.window.show_warehouses_action.setChecked(False)
        APP.processEvents()
        first = next(item for item in self.window.edge_items if item.edge is edge)
        self.assertEqual((first._manual[0].x(), first._manual[0].y()), (175, 250))
        self.window.show_warehouses_action.setChecked(True)
        APP.processEvents()
        first = next(item for item in self.window.edge_items if item.edge is edge)
        self.assertEqual((first._manual[0].x(), first._manual[0].y()), (200, 300))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'project.flow.json'
            model.save_project(self.project, path)
            restored = model.load_project(path)
            self.assertEqual(restored.edges[0].routes,
                             {'compact': [[175, 250]], 'detailed': [[200, 300]]})

    def test_return_arrow_keeps_source_and_target_when_edited(self):
        self.assertTrue(self.window.create_edge(self.a.id, self.b.id))
        self.assertTrue(self.window.create_edge(self.b.id, self.a.id))
        edge = self.project.edges[-1]
        self.assertEqual((edge.source, edge.target), (self.b.id, self.a.id))
        item = next(item for item in self.window.edge_items if item.edge is edge)
        item._manual = [QPointF(self.b.x + 50, self.b.y - 150),
                        QPointF(self.a.x + 50, self.a.y - 150)]
        item._recompute()
        item.on_change(edge, 'compact', [[p.x(), p.y()] for p in item._manual])
        self.assertEqual(item._head[0], item._points[-1])

        def on_border(point, rect):
            near_x = min(abs(point.x() - rect.left()), abs(point.x() - rect.right())) < .01
            near_y = min(abs(point.y() - rect.top()), abs(point.y() - rect.bottom())) < .01
            within_x = rect.left() - .01 <= point.x() <= rect.right() + .01
            within_y = rect.top() - .01 <= point.y() <= rect.bottom() + .01
            return (near_x and within_y) or (near_y and within_x)

        self.assertTrue(on_border(item._points[0], self.window.nodes[self.b.id].connection_rect()))
        self.assertTrue(on_border(item._points[-1], self.window.nodes[self.a.id].connection_rect()))
        self.window.nodes[self.a.id].setPos(self.a.x + 45, self.a.y + 35)
        APP.processEvents()
        self.assertTrue(on_border(item._points[-1], self.window.nodes[self.a.id].connection_rect()))
        self.assertEqual(item._head[0], item._points[-1])

    def test_arrow_anchors_to_card_instead_of_buffer_icon_bounds(self):
        self.a.has_buffer = True
        self.window.render_scene()
        self.assertTrue(self.window.create_edge(self.a.id, self.b.id))
        item = self.window.edge_items[0]
        node = self.window.nodes[self.a.id]
        # The green/yellow/red icon is above the card. An upward connector
        # must start on the card's upper edge, not at its larger item bounds.
        point = QPointF(self.a.x + node.width / 2, self.a.y - 100)
        item._manual = [point]
        item._recompute()
        self.assertAlmostEqual(item._points[0].y(), self.a.y, delta=2)

    def test_auto_route_anchors_to_actual_card_border(self):
        self.a.has_buffer = True
        self.window.render_scene()
        self.assertTrue(self.window.create_edge(self.a.id, self.b.id))
        item = self.window.edge_items[0]
        source, target = self.window.nodes[self.a.id], self.window.nodes[self.b.id]
        self.assertAlmostEqual(item._points[0].x(), self.a.x + source.width, delta=.01)
        self.assertAlmostEqual(item._points[-1].x(), self.b.x, delta=.01)
        self.assertGreaterEqual(item._points[0].y(), self.a.y)
        self.assertLessEqual(item._points[0].y(), self.a.y + source.height)
        self.assertGreaterEqual(item._points[-1].y(), self.b.y)
        self.assertLessEqual(item._points[-1].y(), self.b.y + target.height)


if __name__ == '__main__':
    unittest.main()
