import unittest
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from flow_visualizer import gui, model
from flow_visualizer.shift_push import push_in_direction

APP = QApplication.instance() or QApplication([])


class ShiftPushTest(unittest.TestCase):
    def test_geometry_pushes_only_contacted_chain(self):
        rect = QRectF(0, 0, 100, 70)
        obstacles = [('a', QRectF(124, 0, 100, 70)), ('b', QRectF(248, 0, 100, 70)),
                     ('far', QRectF(700, 0, 100, 70)), ('other', QRectF(124, 150, 100, 70))]
        shifts = push_in_direction(rect, 40, obstacles)
        self.assertEqual(shifts['a'].x(), 40)
        self.assertEqual(shifts['b'].x(), 40)
        self.assertEqual(shifts['far'].x(), 40)
        self.assertEqual(shifts['other'].x(), 40)
        self.assertEqual(push_in_direction(rect, 20, [('x', QRectF(-124, 0, 100, 70))]), {})

    def run_drag(self, vertical=False, reverse=False):
        stages = [model.Stage(name=str(i), provider_type='Покупка',
                              x=60 if vertical else 60 + 254 * i,
                              y=80 + 98 * i if vertical else 80) for i in range(5)]
        window = gui.MainWindow()
        window.set_project(model.Project(stages=stages))
        window.show()
        APP.processEvents()
        view = window.view
        view.resetTransform()
        view.scale(.4, .4)
        view.centerOn(500 if not vertical else 170, 260 if vertical else 100)
        APP.processEvents()
        self.addCleanup(lambda: (setattr(window, 'dirty', False), window.close(), APP.processEvents()))
        start_positions = [(s.x, s.y) for s in stages]
        node = window.nodes[stages[2].id]
        start = view.mapFromScene(node.connection_rect().center())
        viewport = view.viewport()
        def send(kind, position, button, buttons):
            ev = QMouseEvent(kind, QPointF(position), QPointF(viewport.mapToGlobal(position)),
                             button, buttons, Qt.ShiftModifier)
            QApplication.sendEvent(viewport, ev)
            APP.processEvents()
        send(QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
        distance = -100 if reverse else 100
        for step in range(1, 11):
            delta = QPointF(0, distance * step / 10) if vertical else QPointF(distance * step / 10, 0)
            point = start + (view.mapFromScene(delta) - view.mapFromScene(QPointF(0, 0)))
            send(QEvent.MouseMove, point, Qt.NoButton, Qt.LeftButton)
        send(QEvent.MouseButtonRelease, point, Qt.LeftButton, Qt.NoButton)
        unaffected = (3, 4) if reverse else (0, 1)
        shifted = (0, 1, 2) if reverse else (2, 3, 4)
        for i in unaffected:
            self.assertEqual((stages[i].x, stages[i].y), start_positions[i])
        for i in shifted:
            axis = stages[i].y - start_positions[i][1] if vertical else stages[i].x - start_positions[i][0]
            self.assertAlmostEqual(axis, distance, delta=3)
        bounds = [window._stage_bounds(s) for s in stages]
        self.assertTrue(all(not a.intersects(b) for i, a in enumerate(bounds) for b in bounds[i+1:]))

    def test_shift_drag_right_pushes_next_two_equally(self):
        self.run_drag()

    def test_shift_drag_down_pushes_next_two_equally(self):
        self.run_drag(vertical=True)

    def test_shift_drag_left_pushes_preceding_two_equally(self):
        self.run_drag(reverse=True)

    def test_shift_drag_up_pushes_preceding_two_equally(self):
        self.run_drag(vertical=True, reverse=True)
