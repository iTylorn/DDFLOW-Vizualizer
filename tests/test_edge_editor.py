import math
import unittest

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsRectItem, QGraphicsScene, QGraphicsView

from flow_visualizer.edge_editor import EditableEdgeItem
from flow_visualizer.model import Edge


class EditableEdgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.scene = QGraphicsScene()
        self.source = QGraphicsRectItem(QRectF(0, 0, 80, 80))
        self.target = QGraphicsRectItem(QRectF(0, 0, 80, 80))
        self.target.setPos(300, 0)
        self.scene.addItem(self.source)
        self.scene.addItem(self.target)
        self.model = Edge(source='s', target='t')
        self.calls = []

        def auto():
            a = self.source.sceneBoundingRect()
            b = self.target.sceneBoundingRect()
            return [QPointF(a.right(), a.center().y()), QPointF(b.left(), b.center().y())]

        def on_change(edge, view, points):
            self.calls.append((view, points))
            if points:
                edge.routes[view] = points
            else:
                edge.routes.pop(view, None)

        self.item = EditableEdgeItem(self.model, self.source, self.target, 'compact', auto, on_change)
        self.scene.addItem(self.item)

    def test_attached_manual_points_move_and_reset_only_active_view(self):
        self.model.routes['detailed'] = [[150, 140]]
        # Same state as a user dragging a visible control point.
        self.item._manual = [QPointF(180, 130)]
        self.item._recompute()
        self.item.on_change(self.model, 'compact', [[180, 130]])
        old_start, old_end = self.item._points[0], self.item._points[-1]
        self.source.setPos(30, 50)
        self.target.setPos(340, 20)
        self.item.update_endpoints()
        self.assertNotEqual(self.item._points[0], old_start)
        self.assertNotEqual(self.item._points[-1], old_end)
        self.assertEqual(self.model.routes['compact'], [[180, 130]])
        self.item.reset_route()
        self.assertNotIn('compact', self.model.routes)
        self.assertEqual(self.model.routes['detailed'], [[150, 140]])

    def test_bounds_for_print_do_not_include_hidden_editing_handles(self):
        self.item.setSelected(True)
        selected = self.item.boundingRect()
        self.item.set_edit_handles_visible(False)
        printed = self.item.boundingRect()
        self.assertLess(printed.height(), selected.height())
        self.item.set_edit_handles_visible(True)
        self.assertEqual(self.item.boundingRect(), selected)

    def test_drag_control_point_through_qt_mouse_events(self):
        view = QGraphicsView(self.scene)
        view.resize(600, 300)
        view.setSceneRect(-30, -50, 470, 240)
        view.show()
        self.app.processEvents()
        self.item.setSelected(True)
        self.app.processEvents()
        start_scene = self.item._handles[0]
        start = view.mapFromScene(start_scene)
        end = start + QPoint(0, 70)
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        QTest.mouseMove(view.viewport(), end, 10)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
        self.app.processEvents()
        self.assertIn('compact', self.model.routes)
        self.assertGreater(self.model.routes['compact'][0][1], start_scene.y() + 20)
        self.assertTrue(math.isfinite(self.item._points[0].x()))
        self.assertTrue(math.isfinite(self.item._points[-1].x()))
        view.close()

    def test_double_click_on_line_adds_a_waypoint(self):
        view = QGraphicsView(self.scene)
        view.resize(600, 300)
        view.setSceneRect(-30, -50, 470, 240)
        view.show()
        self.app.processEvents()
        self.item.setSelected(True)
        self.app.processEvents()
        position = view.mapFromScene(QPointF(120, 40))
        QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, position)
        self.app.processEvents()
        self.assertIn('compact', self.model.routes)
        self.assertEqual(len(self.model.routes['compact']), 1)
        self.assertAlmostEqual(self.model.routes['compact'][0][0], 120, delta=3)
        view.close()

    def test_drag_line_segment_parallel_with_attached_endpoints(self):
        view = QGraphicsView(self.scene)
        view.resize(600, 300)
        view.setSceneRect(-30, -50, 470, 240)
        view.show()
        self.app.processEvents()
        # Away from the midpoint handle, drag the line on the first click.
        start = view.mapFromScene(QPointF(125, 40))
        end = start + QPoint(0, 60)
        QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(view.viewport(), end, 20)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, end)
        self.app.processEvents()
        route = self.model.routes['compact']
        self.assertEqual(len(route), 2)
        self.assertAlmostEqual(route[0][1], route[1][1], delta=.01)
        self.assertGreater(route[0][1], 75)
        self.assertTrue(self.source.sceneBoundingRect().adjusted(-1, -1, 1, 1).contains(self.item._points[0]))
        self.assertTrue(self.target.sceneBoundingRect().adjusted(-1, -1, 1, 1).contains(self.item._points[-1]))
        view.close()


if __name__ == '__main__':
    unittest.main()
