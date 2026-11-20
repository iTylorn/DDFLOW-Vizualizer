import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLineEdit
from PySide6.QtTest import QTest
from PySide6.QtCore import QTimer
from flow_visualizer import gui, model
from flow_visualizer.group_alignment import align_group_columns
from flow_visualizer.shift_push import push_in_direction

APP = QApplication.instance() or QApplication([])


class DiagramGroups(unittest.TestCase):
    def setUp(self):
        self.group = model.Group(name='Цех')
        self.stages = [model.Stage(name='А', provider_type='Производство', x=60, y=100, group_id=self.group.id),
                       model.Stage(name='Б', provider_type='Производство', x=60, y=220, group_id=self.group.id),
                       model.Stage(name='В', provider_type='Покупка', x=650, y=100)]
        self.window = gui.MainWindow()
        self.window.set_project(model.Project(stages=self.stages, groups=[self.group]))
        self.window.show()
        APP.processEvents()
        self.window.view.resetTransform()
        self.window.view.scale(.55, .55)
        self.window.view.centerOn(380, 200)
        APP.processEvents()

    def tearDown(self):
        self.window.dirty = False
        self.window.close()
        APP.processEvents()

    def drag(self, stage, delta, modifiers=Qt.NoModifier):
        view = self.window.view
        viewport = view.viewport()
        node = self.window.nodes[stage.id]
        center = node.connection_rect().center()
        start = view.mapFromScene(center)
        def send(kind, p, button, buttons):
            event = QMouseEvent(kind, QPointF(p), QPointF(viewport.mapToGlobal(p)), button, buttons, modifiers)
            QApplication.sendEvent(viewport, event)
            APP.processEvents()
        send(QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
        for i in range(1, 7):
            p = view.mapFromScene(center + delta * (i / 6))
            send(QEvent.MouseMove, p, Qt.NoButton, Qt.LeftButton)
        send(QEvent.MouseButtonRelease, p, Qt.LeftButton, Qt.NoButton)

    def test_drag_member_moves_whole_group_and_preserves_offsets(self):
        a, b, c = self.stages
        before = [(s.x, s.y) for s in self.stages]
        self.drag(a, QPointF(90, 0))
        self.assertAlmostEqual(a.x - before[0][0], 90, delta=3)
        self.assertAlmostEqual(b.x - before[1][0], a.x - before[0][0], delta=.01)
        self.assertEqual((c.x, c.y), before[2])

    def test_shift_moves_one_member_independently(self):
        a, b, c = self.stages
        before = [(s.x, s.y) for s in self.stages]
        self.drag(b, QPointF(300, 0), Qt.ShiftModifier)
        self.assertAlmostEqual(b.x - before[1][0], 300, delta=3)
        self.assertEqual((a.x, a.y), before[0])
        self.assertEqual((c.x, c.y), before[2])

    def test_group_from_canvas_dialog_stacks_selected_stages(self):
        a, b, c = self.stages
        self.window.scene.clearSelection()
        for stage in (b, c):
            position = self.window.view.mapFromScene(self.window.nodes[stage.id].connection_rect().center())
            QTest.mouseClick(self.window.view.viewport(), Qt.LeftButton, Qt.ControlModifier, position)
            APP.processEvents()
        self.assertTrue(self.window.nodes[b.id].isSelected())
        self.assertTrue(self.window.nodes[c.id].isSelected())
        def accept_dialog():
            dialog = QApplication.activeModalWidget()
            self.assertIsInstance(dialog, QDialog)
            dialog.findChild(QLineEdit).setText('Новая группа')
            dialog.findChild(QDialogButtonBox).accepted.emit()
        QTimer.singleShot(0, accept_dialog)
        self.window.group_diagram_selection()
        self.assertTrue(b.group_id)
        self.assertEqual(b.group_id, c.group_id)
        self.assertNotEqual(a.group_id, b.group_id)
        self.assertAlmostEqual(b.x + self.window.nodes[b.id].width / 2,
                               c.x + self.window.nodes[c.id].width / 2, delta=.01)

    def test_yellow_background_uses_dark_text(self):
        color = gui.contrast_text_color('#fff200')
        self.assertEqual(color.name(), '#000000')

    def test_group_move_preserves_group_and_moves_internal_manual_route(self):
        a, b, _ = self.stages
        edge = model.Edge(source=a.id, target=b.id, routes={'compact': [[390, 180], [400, 210]]})
        self.window.project.edges.append(edge)
        self.window.render_scene()
        before = [point[:] for point in edge.routes['compact']]
        x = a.x
        self.drag(a, QPointF(80, 0))
        delta = a.x - x
        self.assertGreater(delta, 70)
        self.assertAlmostEqual(edge.routes['compact'][0][0], before[0][0] + delta, delta=.01)
        self.assertEqual(edge.routes['compact'][0][1], before[0][1])
        with tempfile.TemporaryDirectory() as directory:
            self.window.path = str(Path(directory) / 'project.flow.json')
            self.assertTrue(self.window.save())
            restored = model.load_project(self.window.path)
        self.assertEqual(restored.stages[0].group_id, restored.stages[1].group_id)
        self.assertEqual(restored.edges[0].routes['compact'], edge.routes['compact'])

    def test_align_preserves_two_stacks_and_matches_centers(self):
        group = model.Group(name='Два столбца')
        members = [model.Stage(name=str(i), provider_type='Покупка', group_id=group.id, x=x, y=y)
                   for i, (x, y) in enumerate([(60, 100), (70, 220), (400, 103), (408, 223)])]
        outside = model.Stage(name='Вне группы', provider_type='Логистика', x=850, y=400)
        self.window.set_project(model.Project(stages=members + [outside], groups=[group]))
        self.assertTrue(self.window.auto_layout())
        centers = [self.window.nodes[s.id].connection_rect().center() for s in members]
        self.assertAlmostEqual(centers[0].x(), centers[1].x(), delta=.01)
        self.assertAlmostEqual(centers[2].x(), centers[3].x(), delta=.01)
        self.assertGreater(centers[2].x() - centers[0].x(), 230)
        self.assertAlmostEqual(centers[0].y(), centers[2].y(), delta=.01)
        self.assertAlmostEqual(centers[1].y(), centers[3].y(), delta=.01)
        once = [(s.x, s.y) for s in members + [outside]]
        self.assertTrue(self.window.auto_layout())
        for stage, (x, y) in zip(members + [outside], once):
            self.assertAlmostEqual(stage.x, x, delta=.001)
            self.assertAlmostEqual(stage.y, y, delta=.001)


class GroupGeometry(unittest.TestCase):
    def test_all_rows_to_right_move_together(self):
        moving = gui.QRectF(0, 100, 100, 70)
        rects = [('front', gui.QRectF(124, 100, 100, 70)),
                 ('above', gui.QRectF(124, 0, 100, 70)),
                 ('below', gui.QRectF(124, 200, 100, 70)),
                 ('left', gui.QRectF(-124, 0, 100, 70))]
        shifts = push_in_direction(moving, 40, rects)
        self.assertEqual({key: delta.x() for key, delta in shifts.items()},
                         {'front': 40, 'above': 40, 'below': 40})

    def test_two_columns_keep_columns_and_align_centers(self):
        g = model.Group(name='Группа')
        stages = [model.Stage(id=str(i), group_id=g.id, x=x, y=y) for i, (x, y) in
                  enumerate([(0, 0), (12, 100), (270, 3), (280, 104)])]
        project = model.Project(stages=stages, groups=[g])
        positions = {s.id: (s.x, s.y) for s in stages}
        aligned = align_group_columns(project, positions, lambda _: (100, 60, 0, 0, 30))
        self.assertEqual(aligned['0'][0], aligned['1'][0])
        self.assertEqual(aligned['2'][0], aligned['3'][0])
        self.assertGreater(aligned['2'][0] - aligned['0'][0], 200)
        self.assertEqual(aligned['0'][1], aligned['2'][1])
        self.assertEqual(aligned['1'][1], aligned['3'][1])


class ShiftAllRows(unittest.TestCase):
    def test_shift_drag_moves_all_rows_at_the_same_time(self):
        stages = [model.Stage(name=str(i), provider_type='Покупка', x=x, y=y)
                  for i, (x, y) in enumerate([(60, 220), (314, 220), (314, 100),
                                              (314, 340), (568, 100)])]
        window = gui.MainWindow()
        window.set_project(model.Project(stages=stages))
        window.show()
        APP.processEvents()
        view = window.view
        view.resetTransform()
        view.scale(.5, .5)
        view.centerOn(400, 230)
        APP.processEvents()
        original = [(s.x, s.y) for s in stages]
        viewport = view.viewport()
        center = window.nodes[stages[0].id].connection_rect().center()
        def send(kind, p, button, buttons):
            event = QMouseEvent(kind, QPointF(p), QPointF(viewport.mapToGlobal(p)), button, buttons, Qt.ShiftModifier)
            QApplication.sendEvent(viewport, event)
            APP.processEvents()
        start = view.mapFromScene(center)
        send(QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
        for i in range(1, 9):
            end = view.mapFromScene(center + QPointF(i * 10, 0))
            send(QEvent.MouseMove, end, Qt.NoButton, Qt.LeftButton)
        send(QEvent.MouseButtonRelease, end, Qt.LeftButton, Qt.NoButton)
        for stage, (x, y) in zip(stages, original):
            self.assertAlmostEqual(stage.x - x, 80, delta=3)
            self.assertEqual(stage.y, y)
        window.dirty = False
        window.close()
