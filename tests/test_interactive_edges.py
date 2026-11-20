"""Interaction tests for creating and editing the actual canvas connections."""
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from flow_visualizer import gui, model

APP = QApplication.instance() or QApplication([])


class InteractiveEdgeTests(unittest.TestCase):
    def setUp(self):
        self.a = model.Stage(name='Покупка', provider_type='Покупка', level=1)
        self.b = model.Stage(name='Резка', provider_type='Производство', level=2)
        self.project = model.Project(stages=[self.a, self.b])
        self.window = gui.MainWindow()
        self.window.set_project(self.project)
        self.window.show()
        APP.processEvents()
        self.addCleanup(self.close)

    def close(self):
        self.window.dirty = False
        self.window.close()
        APP.processEvents()

    def click_stage(self, stage):
        node = self.window.nodes[stage.id]
        pos = self.window.view.mapFromScene(node.sceneBoundingRect().center())
        QTest.mouseClick(self.window.view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        APP.processEvents()

    def test_click_create_cancel_filter_and_duplicate(self):
        w = self.window
        w.link_action.setChecked(True)
        self.click_stage(self.a)
        self.assertEqual(w.link_source, self.a.id)
        self.assertTrue(w.nodes[self.a.id].isSelected())
        self.click_stage(self.b)
        self.assertTrue(w.link_action.isChecked())
        self.assertEqual([(e.source, e.target) for e in self.project.edges], [(self.a.id, self.b.id)])
        self.assertLess(self.a.x, self.b.x)

        w.link_action.setChecked(True)
        self.click_stage(self.a)
        QTest.keyClick(w.view, Qt.Key_Escape)
        self.assertFalse(w.link_action.isChecked())
        self.assertIsNone(w.link_source)
        w.link_action.setChecked(True)
        self.click_stage(self.a)
        w.link_action.setChecked(False)
        self.assertIsNone(w.link_source)
        w.link_action.setChecked(True)
        self.click_stage(self.a)
        w.search.setText('нет совпадений')
        self.assertFalse(w.link_action.isChecked())
        w.search.clear()

        original = QMessageBox.information
        try:
            QMessageBox.information = staticmethod(lambda *args: QMessageBox.Ok)
            w.link_action.setChecked(True)
            self.click_stage(self.a)
            self.click_stage(self.b)
            self.assertEqual(len(self.project.edges), 1)
        finally:
            QMessageBox.information = original

    def test_select_drag_save_restore_reset_per_view(self):
        w = self.window
        self.assertTrue(w.create_edge(self.a.id, self.b.id))
        edge = self.project.edges[0]
        item = w.edge_items[0]
        item.setSelected(True)
        APP.processEvents()
        self.assertEqual(w.selected_kind, 'edge')
        point = item._handles[0]
        pos = w.view.mapFromScene(point)
        moved = pos + QPoint(0, 45)
        QTest.mousePress(w.view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        QTest.mouseMove(w.view.viewport(), moved, 30)
        QTest.mouseRelease(w.view.viewport(), Qt.LeftButton, Qt.NoModifier, moved)
        APP.processEvents()
        self.assertTrue(edge.routes.get('compact'))
        manual = [p[:] for p in edge.routes['compact']]
        end_before = item._points[-1]
        w.nodes[self.b.id].setPos(w.nodes[self.b.id].pos().x() + 80, w.nodes[self.b.id].pos().y())
        APP.processEvents()
        self.assertNotEqual(item._points[-1], end_before)
        self.assertEqual(edge.routes['compact'], manual)
        with tempfile.TemporaryDirectory() as temp:
            filename = Path(temp) / 'diagram.flow.json'
            model.save_project(self.project, filename)
            restored = model.load_project(filename)
            self.assertEqual(restored.edges[0].routes['compact'], manual)
        item.setSelected(True)
        w.reset_selected_edge()
        self.assertNotIn('compact', edge.routes)


if __name__ == '__main__':
    unittest.main()
