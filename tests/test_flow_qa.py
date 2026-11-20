"""User-facing flow arrows and legend, including redraw and printing."""
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QGraphicsTextItem

from flow_visualizer import gui, model
from flow_visualizer.print_export import export_pdf


APP = QApplication.instance() or QApplication([])


class FlowQATests(unittest.TestCase):
    def setUp(self):
        self.window = gui.MainWindow()
        self.window.show()
        APP.processEvents()
        self.addCleanup(self._close)

    def _close(self):
        self.window.dirty = False
        self.window.close()
        APP.processEvents()

    def assert_flows(self):
        window = self.window
        self.assertEqual(len(window.flow_items), 4)
        information, information_label, material, material_label = window.flow_items
        self.assertEqual(information_label.text(), 'Информационный поток')
        self.assertEqual(material_label.text(), 'Материальный поток')
        info_points = list(information.polygon())
        material_points = list(material.polygon())
        self.assertEqual(info_points[0].x(), min(p.x() for p in info_points))
        self.assertGreater(info_points[1].x(), info_points[0].x())
        self.assertEqual(material_points[2].x(), max(p.x() for p in material_points))
        self.assertGreater(material_points[2].x(), material_points[1].x())
        self.assertGreaterEqual(information.boundingRect().height(), 30)
        self.assertGreaterEqual(material.boundingRect().height(), 30)
        self.assertEqual(information_label.brush().color(), QColor('white'))
        self.assertEqual(material_label.brush().color(), QColor('white'))
        content = window._diagram_bounds()
        self.assertLess(information.sceneBoundingRect().bottom(), content.top())
        self.assertGreater(material.sceneBoundingRect().top(), content.bottom())
        legend = window.legend_items[0].sceneBoundingRect()
        self.assertGreater(legend.top(), material.sceneBoundingRect().bottom())
        self.assertLessEqual(information.sceneBoundingRect().left(), content.left())
        self.assertGreaterEqual(information.sceneBoundingRect().right(), content.right())
        self.assertLessEqual(material.sceneBoundingRect().left(), content.left())
        self.assertGreaterEqual(material.sceneBoundingRect().right(), content.right())
        self.assertTrue(window.legend_items)
        texts = [item.toPlainText() for item in window.legend_items if isinstance(item, QGraphicsTextItem)]
        self.assertIn('Легенда', texts)
        for name in ('Производство', 'Покупка', 'Логистика', 'Промуслуги', 'Сборка / Разборка'):
            self.assertIn(name, texts)
        self.assertTrue(any('РКТ' in text for text in texts))
        if window.show_warehouses_action.isChecked():
            self.assertTrue(any('основной склад' in text for text in texts))
        else:
            self.assertFalse(any('основной склад' in text for text in texts))

    def test_empty_group_move_filter_redraw_and_pdf(self):
        self.assert_flows()  # even an empty project has both flows
        group = model.Group(name='Цех резки')
        stages = [model.Stage(name='Резка', provider_type='Производство', level=1, group_id=group.id),
                  model.Stage(name='Покупка листа', provider_type='Покупка', level=2)]
        project = model.Project(groups=[group], stages=stages,
                                edges=[model.Edge(source=stages[1].id, target=stages[0].id)])
        self.window.set_project(project)
        APP.processEvents()
        self.assert_flows()
        self.assertTrue(self.window.group_items)
        node = self.window.nodes[stages[0].id]
        initial = QPointF(node.pos())
        node.setPos(initial + QPointF(200, 120))
        self.assert_flows()
        node.setPos(initial)
        self.assert_flows()
        baseline = self.window.scene.itemsBoundingRect()
        count = len(self.window.scene.items())
        for _ in range(4):
            self.window.render_scene()
        self.assertEqual(self.window.scene.itemsBoundingRect(), baseline)
        self.assertEqual(len(self.window.scene.items()), count)
        self.window.search.setText('ничего не найдено')
        self.assertFalse(self.window.nodes)
        self.assert_flows()
        self.window.search.clear()
        self.assertEqual(len(self.window.nodes), 2)
        self.assert_flows()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'one-page.pdf'
            export_pdf(self.window.scene, output)
            self.assertTrue(output.read_bytes().startswith(b'%PDF'))


if __name__ == '__main__':
    unittest.main()
