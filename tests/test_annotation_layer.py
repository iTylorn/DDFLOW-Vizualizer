import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from flow_visualizer import exchange, gui, model
from flow_visualizer.annotation_layer import AnnotationItem, read_picture
from flow_visualizer.print_export import export_pdf


APP = QApplication.instance() or QApplication([])


class AnnotationLayerTest(unittest.TestCase):
    def setUp(self):
        self.stage = model.Stage(name='Закупка', provider_type='Покупка', x=50, y=80)
        self.project = model.Project(stages=[self.stage])
        self.window = gui.MainWindow()
        self.window.set_project(self.project)
        self.window.show()
        self.window.view.resetTransform()
        self.window.view.centerOn(320, 230)
        APP.processEvents()

    def tearDown(self):
        self.window.dirty = False
        self.window.close()
        APP.processEvents()

    def drag(self, start, finish):
        view = self.window.view
        source = view.mapFromScene(start)
        target = view.mapFromScene(finish)
        self.assertTrue(view.viewport().rect().contains(source))
        self.assertTrue(view.viewport().rect().contains(target))
        QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, source)
        QTest.mouseMove(view.viewport(), target)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, target)
        APP.processEvents()

    def test_drag_and_resize_are_independent_of_stages(self):
        stage_pose = (self.stage.x, self.stage.y)
        self.window.add_annotation('rectangle')
        item = self.project.annotations[0]
        old_pos = QPointF(item.x, item.y)
        handle = old_pos + QPointF(item.width, item.height)
        self.drag(handle, handle + QPointF(42, 50))
        self.assertAlmostEqual(item.width, 302, delta=2)
        self.assertAlmostEqual(item.height, 150, delta=2)
        mid = old_pos + QPointF(80, 40)
        self.drag(mid, mid + QPointF(34, 20))
        self.assertAlmostEqual(item.x, old_pos.x() + 34, delta=2)
        self.assertAlmostEqual(item.y, old_pos.y() + 20, delta=2)
        self.assertEqual((self.stage.x, self.stage.y), stage_pose)

    def test_arrow_start_moves_while_end_stays_put(self):
        self.window.add_annotation('arrow')
        arrow = self.project.annotations[0]
        start = QPointF(arrow.x, arrow.y)
        endpoint = start + QPointF(arrow.width, arrow.height)
        self.drag(start, start + QPointF(24, -40))
        self.assertAlmostEqual(arrow.x, start.x() + 24, delta=2)
        self.assertAlmostEqual(arrow.y, start.y() - 40, delta=2)
        self.assertAlmostEqual(arrow.x + arrow.width, endpoint.x(), delta=2)
        self.assertAlmostEqual(arrow.y + arrow.height, endpoint.y(), delta=2)

    def test_thick_arrow_shaft_ends_inside_triangular_head(self):
        arrow = model.Annotation(kind='arrow', width=150, height=0, stroke_width=20, stroke='#000000')
        item = AnnotationItem(arrow, lambda: None, lambda _: None)
        image = QImage(360, 200, QImage.Format_RGB32)
        image.fill(QColor('white'))
        painter = QPainter(image)
        painter.translate(50, 100)
        painter.setRenderHint(QPainter.Antialiasing)
        item.paint(painter, None)
        painter.end()
        self.assertEqual(image.pixelColor(195, 100), QColor('black'))
        self.assertEqual(image.pixelColor(195, 108), QColor('white'))
        self.assertEqual(image.pixelColor(201, 100), QColor('white'))

    def test_project_and_pdf_include_embedded_image_and_exchange_excludes_layer(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'picture.png'
            image = QImage(120, 80, QImage.Format_RGB32)
            image.fill(QColor('green'))
            self.assertTrue(image.save(str(source)))
            _, picture = read_picture(source)
            self.project.annotations = [
                model.Annotation(kind='text', x=100, y=190, text='Цеховой комментарий', bold=True),
                model.Annotation(kind='arrow', x=100, y=330, width=-80, height=20, stroke_width=6),
                model.Annotation(kind='image', x=400, y=270, width=120, height=80, image_data=picture),
            ]
            self.project.auto_align = True
            project_file = root / 'схема.flow.json'
            model.save_project(self.project, project_file)
            source.unlink()
            loaded = model.load_project(project_file)
            self.assertEqual(loaded.annotations, self.project.annotations)
            self.assertTrue(loaded.auto_align)
            self.window.set_project(loaded)
            items = self.window.annotation_items.copy()
            self.window.show_warehouses_action.setChecked(True)
            self.assertEqual(self.window.annotation_items, items)
            for tiled in (False, True):
                pdf = root / f'map-{tiled}.pdf'
                export_pdf(self.window.scene, pdf, tiled)
                self.assertTrue(pdf.read_bytes().startswith(b'%PDF'))
                self.assertIn(b'/Subtype /Image', pdf.read_bytes())
            outgoing = root / 'map.json'
            exchange.export_map(loaded, outgoing)
            raw = outgoing.read_text(encoding='utf-8')
            self.assertNotIn('annotations', raw)
            self.assertNotIn('auto_align', raw)
            self.assertNotIn(picture, raw)
            self.assertIn(self.stage.id, json.loads(raw)['order'])

    def test_auto_align_is_queued_after_stage_edit_and_drag_only(self):
        with patch.object(self.window, 'auto_layout', wraps=self.window.auto_layout) as layout:
            self.window._auto_align_timer.timeout.disconnect()
            self.window._auto_align_timer.timeout.connect(layout)
            self.window.auto_align_check.setChecked(True)
            self.window.add_annotation('ellipse')
            QTest.qWait(300)
            layout.assert_not_called()
            node = self.window.nodes[self.stage.id]
            node.setSelected(True)
            self.window.name_input.setText('Новый текст')
            self.window.name_input.setText('Закупка металла')
            QTest.qWait(320)
            self.assertEqual(layout.call_count, 1)
            self.window.view.resetTransform()
            self.window.view.centerOn(320, 200)
            node = self.window.nodes[self.stage.id]
            start = node.connection_rect().center()
            self.drag(start, start + QPointF(0, 100))
            QTest.qWait(320)
            self.assertEqual(layout.call_count, 2)
