"""Real GUI interactions for alignment guides and manual dragging."""
import unittest

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from flow_visualizer import gui, model


APP = QApplication.instance() or QApplication([])


class DragSnapTests(unittest.TestCase):
    def setUp(self):
        self.a = model.Stage(name='А', provider_type='Производство', x=60, y=90)
        self.b = model.Stage(name='Б', provider_type='Производство', x=420, y=150)
        self.project = model.Project(stages=[self.a, self.b])
        self.window = gui.MainWindow()
        self.window.set_project(self.project)
        self.window.show()
        APP.processEvents()
        self.window.view.resetTransform()
        self.window.view.centerOn(360, 130)
        APP.processEvents()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        APP.processEvents()

    def drag_b(self, desired_y, modifiers=Qt.NoModifier):
        view = self.window.view
        node = self.window.nodes[self.b.id]
        origin = view.mapFromScene(node.connection_rect().center())
        dest = origin + QPoint(0, round(desired_y - self.b.y))
        QTest.mousePress(view.viewport(), Qt.LeftButton, modifiers, origin)
        QTest.mouseMove(view.viewport(), dest, 25)
        APP.processEvents()
        guides = list(view.alignment_guides)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, modifiers, dest)
        APP.processEvents()
        return guides

    def test_real_drag_aligns_and_removes_temporary_guides(self):
        self.assertTrue(self.window.snap_action.isChecked())
        guides = self.drag_b(95)
        self.assertAlmostEqual(self.b.y, self.a.y, delta=0.6)
        self.assertTrue(guides)
        self.assertFalse(self.window.view.alignment_guides)

    def test_switch_off_preserves_free_movement(self):
        self.window.snap_action.setChecked(False)
        guides = self.drag_b(95)
        self.assertAlmostEqual(self.b.y, 95, delta=0.6)
        self.assertFalse(guides)

    def test_programmatic_moves_are_not_snapped(self):
        self.window.nodes[self.b.id].setPos(420, 95)
        APP.processEvents()
        self.assertEqual(self.b.y, 95)
        self.assertFalse(self.window.view.alignment_guides)

    def test_alt_bypasses_snapping(self):
        self.window.snap_action.setChecked(True)
        view, node = self.window.view, self.window.nodes[self.b.id]
        viewport = view.viewport()
        origin = view.mapFromScene(node.connection_rect().center())
        dest = origin + QPoint(0, -55)
        def send(kind, position, button, buttons):
            event = QMouseEvent(kind, QPointF(position), QPointF(viewport.mapToGlobal(position)),
                                button, buttons, Qt.AltModifier)
            QApplication.sendEvent(viewport, event)
            APP.processEvents()
        send(QEvent.MouseButtonPress, origin, Qt.LeftButton, Qt.LeftButton)
        send(QEvent.MouseMove, dest, Qt.NoButton, Qt.LeftButton)
        self.assertAlmostEqual(self.b.y, 95, delta=0.6)
        self.assertFalse(self.window.view.alignment_guides)
        send(QEvent.MouseButtonRelease, dest, Qt.LeftButton, Qt.NoButton)

    def drag_to(self, target, modifiers=Qt.NoModifier):
        view, node = self.window.view, self.window.nodes[self.b.id]
        viewport = view.viewport()
        origin = view.mapFromScene(node.connection_rect().center())
        destination = origin + QPoint(round(target[0] - self.b.x), round(target[1] - self.b.y))
        def send(kind, point, button, buttons):
            event = QMouseEvent(kind, QPointF(point), QPointF(viewport.mapToGlobal(point)),
                                button, buttons, modifiers)
            QApplication.sendEvent(viewport, event)
            APP.processEvents()
        send(QEvent.MouseButtonPress, origin, Qt.LeftButton, Qt.LeftButton)
        send(QEvent.MouseMove, destination, Qt.NoButton, Qt.LeftButton)
        send(QEvent.MouseButtonRelease, destination, Qt.LeftButton, Qt.NoButton)

    def test_overlap_blocked_during_drag_with_alt_and_disabled_snap(self):
        for enabled, modifier in ((True, Qt.NoModifier), (True, Qt.AltModifier), (False, Qt.NoModifier)):
            self.window.snap_action.setChecked(enabled)
            self.window.nodes[self.a.id].setPos(60, 90)
            self.window.nodes[self.b.id].setPos(420, 150)
            self.drag_to((60, 90), modifier)
            self.assertFalse(self.window._stage_bounds(self.a).intersects(self.window._stage_bounds(self.b)))
            self.assertEqual((self.a.x, self.a.y), (60, 90))

    def test_fast_drag_keeps_24_unit_gap_when_snap_enabled(self):
        # A single large event targets the centre of the obstacle; the pointer
        # never visits the usual narrow snapping tolerance on the way.
        self.window.nodes[self.b.id].setPos(420, 90)
        self.drag_to((60, 90))
        gap = self.window._stage_bounds(self.b).left() - self.window._stage_bounds(self.a).right()
        self.assertAlmostEqual(gap, 96.0, delta=0.01)
        self.assertEqual(self.a.x, 60)

    def test_fast_drag_aligns_orthogonal_axis_at_safe_gap(self):
        self.window.nodes[self.b.id].setPos(420, 95)
        self.drag_to((60, 95))
        gap = self.window._stage_bounds(self.b).left() - self.window._stage_bounds(self.a).right()
        self.assertAlmostEqual(gap, 96.0, delta=0.01)
        self.assertAlmostEqual(self.b.y, self.a.y, delta=0.01)

    def test_fast_drag_keeps_gap_for_hidden_stage(self):
        self.window.nodes[self.b.id].setPos(420, 90)
        self.window.search.setText('Б')
        APP.processEvents()
        self.drag_to((60, 90))
        gap = self.window._stage_bounds(self.b).left() - self.window._stage_bounds(self.a).right()
        self.assertAlmostEqual(gap, 96.0, delta=0.01)
        self.assertIn('скрытый', self.window.statusBar().currentMessage().casefold())

    def test_fast_drag_alt_and_disabled_snap_allow_touch_without_overlap(self):
        for enabled, modifier in ((True, Qt.AltModifier), (False, Qt.NoModifier)):
            self.window.snap_action.setChecked(enabled)
            self.window.nodes[self.a.id].setPos(60, 90)
            self.window.nodes[self.b.id].setPos(420, 90)
            self.drag_to((60, 90), modifier)
            gap = self.window._stage_bounds(self.b).left() - self.window._stage_bounds(self.a).right()
            self.assertAlmostEqual(gap, 0.0, delta=0.01)

    def test_fast_drag_can_reach_clear_space_on_the_other_side(self):
        self.window.snap_action.setChecked(False)
        self.drag_to((-250, 150))
        self.assertAlmostEqual(self.b.x, -250, delta=1)
        self.assertFalse(self.window._stage_bounds(self.a).intersects(self.window._stage_bounds(self.b)))
        self.assertEqual((self.a.x, self.a.y), (60, 90))

    def test_old_overlap_allows_escape_but_not_worse(self):
        self.window.snap_action.setChecked(False)
        self.window.nodes[self.b.id].setPos(250, 90)
        before = self.window._intersection_area(self.window._stage_bounds(self.a), self.window._stage_bounds(self.b))
        self.assertGreater(before, 0)
        self.drag_to((150, 90))
        self.assertLessEqual(self.window._intersection_area(self.window._stage_bounds(self.a), self.window._stage_bounds(self.b)), before + 1e-6)
        self.drag_to((420, 90))
        self.assertFalse(self.window._stage_bounds(self.a).intersects(self.window._stage_bounds(self.b)))

    def test_hidden_stage_blocks_drag(self):
        self.window.snap_action.setChecked(False)
        width = self.window.nodes[self.a.id].width
        self.drag_to((self.a.x + width, self.a.y))
        self.assertAlmostEqual(self.b.x, self.a.x + width, delta=0.6)
        self.window.search.setText('Б')
        APP.processEvents()
        self.assertNotIn(self.a.id, self.window.nodes)
        before = (self.b.x, self.b.y)
        self.drag_to((60, 90))
        self.assertEqual((self.b.x, self.b.y), before)
        self.assertFalse(self.window._stage_bounds(self.a).intersects(self.window._stage_bounds(self.b)))
        self.assertIn('скрытый', self.window.statusBar().currentMessage().casefold())

    def test_expanding_title_moves_only_edited_card(self):
        self.window.nodes[self.a.id].setPos(60, 90)
        self.window.nodes[self.b.id].setPos(60, 230)
        self.window.nodes[self.a.id].setSelected(True)
        APP.processEvents()
        original_b = (self.b.x, self.b.y)
        self.window.name_input.setText('Очень длинное название передела ' * 15)
        APP.processEvents()
        self.assertIn('Очень длинное', self.a.name)
        self.assertEqual((self.b.x, self.b.y), original_b)
        self.assertFalse(self.window._stage_bounds(self.a).intersects(self.window._stage_bounds(self.b)))
        self.assertIn('наложения', self.window.statusBar().currentMessage())

    def test_new_stage_avoids_existing_block_outside_selected_group(self):
        group = model.Group(name='Группа')
        self.project.groups.append(group)
        self.a.group_id = group.id
        self.b.x, self.b.y = 60, 280
        self.window.render_scene()
        self.window.selected_kind, self.window.selected_ref = 'group', group.id
        before = (self.a.x, self.a.y, self.b.x, self.b.y)
        self.window.add_stage()
        added = self.project.stages[-1]
        for other in (self.a, self.b):
            self.assertFalse(self.window._stage_bounds(added).intersects(self.window._stage_bounds(other)))
        self.assertEqual((self.a.x, self.a.y, self.b.x, self.b.y), before)

    def test_copy_avoids_existing_stage(self):
        self.b.x, self.b.y = 60, 310
        self.a.group_id = self.b.group_id = model.Group(name='Цех').id
        self.project.groups.append(model.Group(id=self.a.group_id, name='Цех'))
        self.window.render_scene()
        before = (self.a.x, self.a.y, self.b.x, self.b.y)
        copied = self.window.copy_stage(self.a.id)
        for other in (self.a, self.b):
            self.assertFalse(self.window._stage_bounds(copied).intersects(self.window._stage_bounds(other)))
        self.assertEqual((self.a.x, self.a.y, self.b.x, self.b.y), before)

    def test_edit_repairs_only_changed_stage_in_hidden_view(self):
        hidden = 'compact' if self.window._active_view == 'detailed' else 'detailed'
        self.project.view_positions[hidden] = {self.a.id: [60, 90], self.b.id: [60, 200]}
        self.window.nodes[self.a.id].setSelected(True)
        APP.processEvents()
        self.window.name_input.setText('Очень длинный текст названия для схемы ' * 20)
        APP.processEvents()
        self.assertEqual(self.project.view_positions[hidden][self.b.id], [60, 200])
        source_order = self.a.x < self.b.x
        self.window.show_warehouses_action.setChecked(hidden == 'detailed')
        APP.processEvents()
        self.assertFalse(self.window._stage_bounds(self.a).intersects(self.window._stage_bounds(self.b)))
        self.assertEqual(self.a.x < self.b.x, source_order)

    def test_compact_preserves_other_view_and_transforms_manual_route(self):
        self.b.x = 1000
        edge = model.Edge(source=self.a.id, target=self.b.id,
                          routes={'detailed': [[400.0, 300.0]], 'compact': [[350.0, 100.0]]})
        self.project.edges.append(edge)
        other_view = 'compact' if self.window._active_view == 'detailed' else 'detailed'
        self.project.view_positions[other_view] = {self.a.id: [20, 50], self.b.id: [500, 50]}
        before_other = dict(self.project.view_positions[other_view])
        other_route = [point[:] for point in edge.routes[other_view]]
        active = self.window._active_view
        expected = gui.compact_existing(self.project, *self.window._layout_measurements())
        expected_route = [list(expected.transform_point(*point)) for point in edge.routes[active]]
        self.assertTrue(self.window.auto_layout())
        self.assertEqual(edge.routes[active], expected_route)
        self.assertEqual(edge.routes[other_view], other_route)
        self.assertEqual(self.project.view_positions[other_view], before_other)
        self.assertEqual((self.b.x, self.b.y), expected[self.b.id])


if __name__ == '__main__':
    unittest.main()
