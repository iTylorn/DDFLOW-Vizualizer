"""Acceptance coverage of viewport dragging and both PDF page modes."""
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtPdf import QPdfDocument

from flow_visualizer import gui, model, print_export
from flow_visualizer.selection_alignment import STANDARD_HORIZONTAL_GAP

APP = QApplication.instance() or QApplication([])


class PlacementAcceptance(unittest.TestCase):
    def setUp(self):
        self.a = model.Stage(name='Первый', provider_type='Производство', x=60, y=90)
        self.b = model.Stage(name='Второй', provider_type='Покупка', x=420, y=150)
        self.project = model.Project(stages=[self.a, self.b])
        self.window = gui.MainWindow()
        self.window.set_project(self.project)
        self.window.show()
        APP.processEvents()
        self.window.view.resetTransform()
        self.window.view.centerOn(330, 150)
        APP.processEvents()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        APP.processEvents()

    def drag_to(self, x, y):
        view = self.window.view
        center = self.window.nodes[self.b.id].connection_rect().center()
        start = view.mapFromScene(center)
        end = view.mapFromScene(center + QPointF(x - self.b.x, y - self.b.y))
        QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(view.viewport(), end, 25)
        APP.processEvents()
        guides = list(view.alignment_guides)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, end)
        APP.processEvents()
        return guides

    def test_zoom_drag_aligns_side_and_keeps_temporary_guides(self):
        view = self.window.view
        view.scale(1.4, 1.4)
        view.centerOn(330, 150)
        APP.processEvents()
        a_bounds = self.window._stage_bounds(self.a)
        b_bounds = self.window._stage_bounds(self.b)
        desired_x = self.b.x + a_bounds.right() + STANDARD_HORIZONTAL_GAP - b_bounds.left() + 2
        guides = self.drag_to(desired_x, 92)
        a_bounds, b_bounds = self.window._stage_bounds(self.a), self.window._stage_bounds(self.b)
        self.assertAlmostEqual(b_bounds.left() - a_bounds.right(), STANDARD_HORIZONTAL_GAP, delta=1)
        self.assertAlmostEqual(self.a.y, self.b.y, delta=1)
        self.assertTrue(guides)
        self.assertFalse(view.alignment_guides)
        self.assertEqual((self.a.x, self.a.y), (60, 90))

    def test_drag_below_aligns_left_and_keeps_gap(self):
        self.window.nodes[self.b.id].setPos(90, 320)
        APP.processEvents()
        a_bounds, b_bounds = self.window._stage_bounds(self.a), self.window._stage_bounds(self.b)
        desired_y = self.b.y + a_bounds.bottom() + 24 - b_bounds.top() + 2
        self.drag_to(62, desired_y)
        a_bounds, b_bounds = self.window._stage_bounds(self.a), self.window._stage_bounds(self.b)
        self.assertAlmostEqual(b_bounds.top() - a_bounds.bottom(), 24, delta=1)
        self.assertAlmostEqual(self.a.x, self.b.x, delta=1)
        self.assertEqual((self.a.x, self.a.y), (60, 90))

    def test_fast_drag_into_card_keeps_gap_and_aligns_cross_axis(self):
        self.window.nodes[self.b.id].setPos(420, 95)
        APP.processEvents()
        self.drag_to(60, 95)
        a_bounds, b_bounds = self.window._stage_bounds(self.a), self.window._stage_bounds(self.b)
        self.assertAlmostEqual(b_bounds.left() - a_bounds.right(), STANDARD_HORIZONTAL_GAP, delta=1)
        self.assertAlmostEqual(self.b.y, self.a.y, delta=1)

    def test_pdf_contains_one_or_multiple_pages(self):
        self.window.nodes[self.b.id].setPos(2400, 150)
        APP.processEvents()
        self.assertTrue(print_export.prefer_multiple_pages(self.window.scene, print_export.make_printer()))
        with tempfile.TemporaryDirectory() as directory:
            for tiled in (False, True):
                path = Path(directory) / ('multi.pdf' if tiled else 'single.pdf')
                print_export.export_pdf(self.window.scene, path, tiled=tiled)
                data = QByteArray(path.read_bytes())
                buffer = QBuffer(data)
                self.assertTrue(buffer.open(QIODevice.ReadOnly))
                doc = QPdfDocument()
                doc.load(buffer)
                self.assertEqual(doc.status(), QPdfDocument.Status.Ready)
                self.assertGreater(doc.pageCount(), 1 if tiled else 0)
                if not tiled:
                    self.assertEqual(doc.pageCount(), 1)
                size = doc.pagePointSize(0)
                self.assertAlmostEqual(size.width(), 841.89, delta=1)
                self.assertAlmostEqual(size.height(), 595.28, delta=1)
                doc.close()
                buffer.close()


if __name__ == '__main__':
    unittest.main()
