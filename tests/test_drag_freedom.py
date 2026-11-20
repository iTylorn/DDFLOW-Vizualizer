"""Exercise everyday mouse placement, including movement around other cards."""
import unittest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from flow_visualizer import gui, model

APP = QApplication.instance() or QApplication([])


class FreeDragTest(unittest.TestCase):
    def setUp(self):
        self.stages = [model.Stage(name=str(i), provider_type='Покупка', x=60 + 320 * i, y=100)
                       for i in range(3)]
        self.window = gui.MainWindow()
        self.window.set_project(model.Project(stages=self.stages))
        self.window.show()
        self.window.view.resetTransform()
        self.window.view.scale(.5, .5)
        self.window.view.centerOn(400, 180)
        APP.processEvents()

    def tearDown(self):
        self.window.dirty = False
        self.window.close()
        APP.processEvents()

    def drag(self, index, target, steps=20):
        stage = self.stages[index]
        original = QPointF(stage.x, stage.y)
        view = self.window.view
        center = self.window.nodes[stage.id].connection_rect().center()
        start = view.mapFromScene(center)
        QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, start)
        for i in range(1, steps + 1):
            destination = view.mapFromScene(center + (QPointF(*target) - original) * (i / steps))
            QTest.mouseMove(view.viewport(), destination, 5)
            APP.processEvents()
            bounds = [self.window._stage_bounds(s) for s in self.stages]
            self.assertTrue(all(not a.intersects(b) for n, a in enumerate(bounds) for b in bounds[n + 1:]))
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, destination)
        APP.processEvents()

    def test_move_third_below_first_without_moving_other_cards(self):
        first, second, moving = self.stages
        original = [(s.x, s.y) for s in (first, second)]
        desired_y = first.y + self.window.nodes[first.id].height + 24
        self.drag(2, (first.x, desired_y))
        self.assertEqual([(s.x, s.y) for s in (first, second)], original)
        self.assertAlmostEqual(moving.x, first.x, delta=2.1)
        self.assertAlmostEqual(moving.y, desired_y, delta=2.1)

    def test_move_block_to_free_space_on_the_other_side(self):
        first, second, moving = self.stages
        original = [(s.x, s.y) for s in (first, second)]
        self.drag(2, (first.x - 280, first.y))
        self.assertEqual([(s.x, s.y) for s in (first, second)], original)
        self.assertAlmostEqual(moving.x, first.x - 280, delta=2.1)
        self.assertAlmostEqual(moving.y, first.y, delta=2.1)

    def test_selecting_multiple_does_not_move_neighbors(self):
        first, second, moving = self.stages
        self.window.nodes[first.id].setSelected(True)
        self.window.nodes[moving.id].setSelected(True)
        APP.processEvents()
        original = [(s.x, s.y) for s in (first, second)]
        self.drag(2, (moving.x, moving.y + 150))
        self.assertEqual([(s.x, s.y) for s in (first, second)], original)
        self.assertAlmostEqual(moving.y, 250, delta=2.1)
