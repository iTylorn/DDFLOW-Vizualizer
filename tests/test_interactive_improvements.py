import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFontMetricsF
from PySide6.QtWidgets import QApplication, QMessageBox, QStyle, QStyleOptionSpinBox
from PySide6.QtTest import QTest

from flow_visualizer import gui, model

APP = QApplication.instance() or QApplication([])


class InteractiveImprovements(unittest.TestCase):
    def setUp(self):
        self.stage = model.Stage(name='Первый передел', provider_type='Производство', x=60, y=90)
        self.warehouse = model.Warehouse(name='Общий склад')
        self.project = model.Project(stages=[self.stage], warehouses=[self.warehouse])
        self.window = gui.MainWindow()
        self.window.set_project(self.project)
        self.window.show()
        self.window.nodes[self.stage.id].setSelected(True)
        APP.processEvents()

    def tearDown(self):
        self.window.dirty = False
        self.window.close()
        APP.processEvents()

    def test_same_warehouse_cannot_be_added_to_both_lists(self):
        self.window.inlets.item(0, 0).setCheckState(Qt.Checked)
        self.window.stocks.item(0, 0).setCheckState(Qt.Checked)
        self.assertEqual(self.window.stocks.item(0, 0).checkState(), Qt.Unchecked)
        self.assertEqual([x.warehouse_id for x in self.stage.inlets], [self.warehouse.id])
        self.assertFalse(self.stage.stocks)
        self.window.inlets.item(0, 0).setCheckState(Qt.Unchecked)
        self.window.stocks.item(0, 0).setCheckState(Qt.Checked)
        self.window.inlets.item(0, 0).setCheckState(Qt.Checked)
        self.assertEqual(self.window.inlets.item(0, 0).checkState(), Qt.Unchecked)
        self.assertEqual([x.warehouse_id for x in self.stage.stocks], [self.warehouse.id])

    def test_imported_conflict_is_preserved_and_cannot_be_saved(self):
        self.stage.inlets = [model.WarehouseLink(warehouse_id=self.warehouse.id)]
        self.stage.stocks = [model.WarehouseLink(warehouse_id=self.warehouse.id)]
        self.window.populate_stage(self.stage)
        self.assertIn('обоих списках', self.window.error_label.text())
        with patch.object(QMessageBox, 'warning'):
            self.assertFalse(self.window.save())
        self.assertTrue(self.stage.inlets and self.stage.stocks)

    def test_legacy_level_does_not_reduce_card_font(self):
        old = model.Stage(name='Закупка', level=None)
        with_level = model.Stage(name='Закупка', level=1)
        a = gui.StageItem(old, {}, lambda: None, True)
        b = gui.StageItem(with_level, {}, lambda: None, True)
        self.assertEqual(a.title.defaultFont().pointSize(), b.title.defaultFont().pointSize())
        self.assertEqual(a.height, b.height)

    def test_context_menu_deletes_stage_and_related_arrows(self):
        second = model.Stage(name='Второй', provider_type='Покупка', x=400, y=90)
        self.project.stages.append(second)
        self.project.edges.append(model.Edge(source=self.stage.id, target=second.id))
        menu = self.window.build_stage_context_menu(self.stage.id)
        action = next(action for action in menu.actions() if action.text() == 'Удалить передел')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            action.trigger()
        self.assertEqual(self.project.stages, [second])
        self.assertFalse(self.project.edges)

    def test_appearance_and_long_words_survive_save(self):
        self.stage.name = 'Сверхдлинноенеразрывноеслово' * 3
        self.window.apply_appearance(180, 90, 36, 42, {'production': '#123456', 'rkt': '#abcdef'})
        node = self.window.nodes[self.stage.id]
        font = node.title.defaultFont()
        self.assertLessEqual(QFontMetricsF(font).horizontalAdvance(self.stage.name), node.width - 24 + 0.01)
        self.assertGreaterEqual(node.width, 180)
        self.assertEqual(gui.compact_color_for_stage(self.stage, self.project.colors).name(), '#123456')
        self.assertEqual(self.window.flow_items[1].font().pointSize(), 36)
        self.assertEqual(self.window.title_items[0].font().pointSize(), 42)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'project.json'
            model.save_project(self.project, path)
            saved = model.load_project(path)
        self.assertEqual((saved.card_width, saved.card_height, saved.flow_font_size, saved.title_font_size), (180, 90, 36, 42))
        self.assertEqual(saved.colors, self.project.colors)

    def test_long_title_wraps_words_at_readable_size(self):
        self.stage.name = 'Заготовительный Литьё'
        self.stage.level = 1
        self.window.render_scene()
        card = self.window.nodes[self.stage.id]
        self.assertGreaterEqual(card.title.defaultFont().pointSize(), 13)
        self.assertGreaterEqual(card.title.begin().layout().lineCount(), 2)
        self.assertLessEqual(card.title.size().height() + 24, card.height + .01)

    def test_open_existing_project_resolves_overlaps_caused_by_larger_titles(self):
        first = model.Stage(name='Производственный подготовительный участок обработки деталей',
                            provider_type='Производство', level=1, x=20, y=30)
        second = model.Stage(name='Далее', provider_type='Покупка', x=20, y=130)
        self.window.set_project(model.Project(stages=[first, second]))
        self.assertEqual((first.x, first.y), (20, 30))
        self.assertGreater(second.y, 130)
        self.assertFalse(self.window._stage_bounds(first).intersects(self.window._stage_bounds(second)))
        self.assertTrue(self.window.dirty)
