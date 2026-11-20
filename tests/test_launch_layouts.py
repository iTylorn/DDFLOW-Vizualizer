import json
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QGraphicsTextItem
from flow_visualizer import gui, model
from flow_visualizer.symbols import LAYOUTS, layout_label

APP = QApplication.instance() or QApplication([])


class LaunchLayoutsTests(unittest.TestCase):
    def setUp(self):
        self.window = gui.MainWindow()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        APP.processEvents()

    def test_four_exact_1c_layouts_in_editor_and_legend(self):
        stage = model.Stage(name='Резка', provider_type='Производство', x=0, y=0)
        self.window.set_project(model.Project(stages=[stage]))
        self.window.show()
        self.window.nodes[stage.id].setSelected(True)
        APP.processEvents()
        combo = self.window.launch_layout_input
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], [
            'Без группировки', 'С группировкой по коду переналадки',
            'С группировкой по назначениям', 'Группировка по источнику потребности'])
        self.assertEqual(combo.currentData(), 'none')
        for key, short, full in LAYOUTS:
            combo.setCurrentIndex(combo.findData(key))
            self.assertEqual(stage.launch_layout, key)
            self.assertEqual(layout_label(key), full)
            for detailed in (False, True):
                self.window.show_warehouses_action.setChecked(detailed)
                APP.processEvents()
                texts = [item.toPlainText() for item in self.window.legend_items
                         if isinstance(item, QGraphicsTextItem)]
                self.assertIn(full, texts)
                self.assertFalse(any('Макет запуска: Не указан' in t for t in texts))
                if detailed:
                    self.assertIn(full, self.window.nodes[stage.id].body.toPlainText())

    def test_legacy_empty_defaults_to_no_grouping(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.flow.json'
            original = model.Project(stages=[model.Stage(name='Тест', provider_type='Производство')])
            model.save_project(original, path)
            data = json.loads(path.read_text(encoding='utf-8'))
            data['version'] = 9
            data['project']['stages'][0]['launch_layout'] = ''
            path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            loaded = model.load_project(path)
            self.assertEqual(loaded.stages[0].launch_layout, 'none')
            self.assertEqual(layout_label(''), 'Производство без группировки')
            model.save_project(loaded, path)
            self.assertEqual(model.load_project(path).stages[0].launch_layout, 'none')

    def test_legacy_head_product_stays_until_user_selects_an_actual_layout(self):
        stage = model.Stage(name='Резка', provider_type='Производство', launch_layout='product')
        self.window.set_project(model.Project(stages=[stage]))
        self.window.show()
        self.window.nodes[stage.id].setSelected(True)
        APP.processEvents()
        self.assertEqual(self.window.launch_layout_input.currentData(), 'product')
        self.assertTrue(self.window.launch_layout_input.view().isRowHidden(
            self.window.launch_layout_input.findData('product')))
        self.assertIn('Укажите соответствующий макет', self.window.layout_legacy_label.text())
        self.window.name_input.setText('Резка новая')
        self.assertEqual(stage.launch_layout, 'product')
        self.window.launch_layout_input.setCurrentIndex(self.window.launch_layout_input.findData('assignments'))
        self.assertEqual(stage.launch_layout, 'assignments')
        self.assertFalse(self.window.layout_legacy_label.isVisible())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'project.flow.json'
            model.save_project(self.window.project, path)
            self.assertEqual(model.load_project(path).stages[0].launch_layout, 'assignments')

    def test_unknown_imported_layout_is_not_silently_replaced(self):
        stage = model.Stage(name='Отгрузка', provider_type='Логистика', launch_layout='unknown',
                            extra={'launch_layout_id': 'Логистика_ГруппировкаПоСкладу',
                                   'launch_layout_name': 'Группировка по складу куда нести'})
        self.window.set_project(model.Project(stages=[stage]))
        self.window.show()
        self.window.nodes[stage.id].setSelected(True)
        APP.processEvents()
        self.assertEqual(self.window.launch_layout_input.currentData(), 'unknown')
        self.assertIn('Группировка по складу', self.window.launch_layout_input.currentText())
        self.window.name_input.setText('Отгрузка ГП')
        self.assertEqual(stage.launch_layout, 'unknown')
        for detailed in (False, True):
            self.window.show_warehouses_action.setChecked(detailed)
            APP.processEvents()
            texts = [item.toPlainText() for item in self.window.legend_items if isinstance(item, QGraphicsTextItem)]
            self.assertTrue(any('Макет из 1С не распознан' in t for t in texts))
        self.window.launch_layout_input.setCurrentIndex(self.window.launch_layout_input.findData('setup'))
        self.assertEqual(stage.launch_layout, 'setup')
