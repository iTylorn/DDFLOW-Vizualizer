"""Interaction tests for level controls and assignment from the object tree."""
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QColorDialog, QDialog, QInputDialog, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox)

from flow_visualizer import gui, model
from flow_visualizer.print_export import export_pdf


APP = QApplication.instance() or QApplication([])


class ContextAndLevelTests(unittest.TestCase):
    def setUp(self):
        self.window = gui.MainWindow()
        self.stage = model.Stage(name='Резка', provider_type='Производство', has_buffer=True)
        self.other = model.Stage(name='Готовая деталь', provider_type='Покупка')
        self.group = model.Group(name='Механический цех')
        self.project = model.Project(stages=[self.stage, self.other], groups=[self.group])
        self.window.set_project(self.project)
        self.window.show()
        APP.processEvents()
        self.window.nodes[self.stage.id].setSelected(True)
        APP.processEvents()
        self.addCleanup(self._close)

    def _close(self):
        self.window.dirty = False
        self.window.close()
        APP.processEvents()

    def test_legacy_level_is_not_shown_or_modified_by_edit(self):
        self.stage.level = 7
        self.window.populate_stage(self.stage)
        self.assertFalse(hasattr(self.window, 'level_input'))
        self.window.name_input.setText('Новая резка')
        self.assertEqual(self.stage.level, 7)

    def test_context_menu_assign_create_cancel_and_save(self):
        menu = self.window.build_stage_context_menu(self.stage.id)
        sub = menu.actions()[0].menu()
        group_action = next(action for action in sub.actions() if action.data() == self.group.id)
        group_action.trigger()
        self.assertEqual(self.stage.group_id, self.group.id)
        self.assertTrue(self.stage.has_buffer)
        self.assertEqual(self.stage.name, 'Резка')
        self.assertEqual(self.window.selected_id, self.stage.id)
        self.assertTrue(self.window.nodes[self.stage.id].isSelected())
        before = len(self.project.groups)
        original = QInputDialog.getText
        try:
            QInputDialog.getText = staticmethod(lambda *args, **kwargs: ('', False))
            self.window.create_group_for_stage(self.stage.id)
            self.assertEqual(len(self.project.groups), before)
            self.assertEqual(self.stage.group_id, self.group.id)
            QInputDialog.getText = staticmethod(lambda *args, **kwargs: ('Новая группа', True))
            self.window.create_group_for_stage(self.stage.id)
        finally:
            QInputDialog.getText = original
        created = self.project.groups[-1]
        self.assertEqual(created.name, 'Новая группа')
        self.assertEqual(self.stage.group_id, created.id)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'project.flow.json'
            model.save_project(self.project, path)
            loaded = model.load_project(path)
            self.assertEqual(loaded.stages[0].group_id, created.id)
            self.assertTrue(loaded.stages[0].has_buffer)
        menu = self.window.build_stage_context_menu(self.stage.id)
        sub = menu.actions()[0].menu()
        next(action for action in sub.actions() if action.text() == 'Без группы').trigger()
        self.assertEqual(self.stage.group_id, '')

    def test_right_clicked_tree_item_is_target(self):
        # Right-clicking a different stage must operate on it, not the old selection.
        tree = self.window.object_tree
        root = tree.topLevelItem(0)
        ungrouped = root.child(0)
        item = next(ungrouped.child(i) for i in range(ungrouped.childCount())
                    if ungrouped.child(i).data(0, Qt.UserRole) == ('stage', self.other.id))
        rect = tree.visualItemRect(item)
        self.assertFalse(rect.isEmpty())
        def choose():
            menu = QApplication.activePopupWidget()
            if isinstance(menu, QMenu):
                sub = menu.actions()[0].menu()
                next(action for action in sub.actions() if action.data() == self.group.id).trigger()
                menu.close()
        QTimer.singleShot(10, choose)
        self.window.show_tree_context_menu(rect.center())
        self.assertEqual(self.other.group_id, self.group.id)
        self.assertEqual(self.stage.group_id, '')
        self.assertEqual(self.window.selected_id, self.other.id)

    def test_initial_positions_and_preserve_manual_positions(self):
        self.assertAlmostEqual(self.window.nodes[self.stage.id].connection_rect().center().y(),
                               self.window.nodes[self.other.id].connection_rect().center().y())
        self.assertLess(self.stage.x, self.other.x)
        self.stage.x, self.stage.y = 1234.0, 987.0
        self.other.x, self.other.y = 2200.0, 333.0
        self.window.set_project(self.project)
        self.assertEqual((self.stage.x, self.stage.y), (1234.0, 987.0))
        self.assertEqual((self.other.x, self.other.y), (2200.0, 333.0))

    def test_compact_toggle_preserves_data_and_positions(self):
        wh = model.Warehouse(name='Материалы', warehouse_type='ordinary')
        self.project.warehouses.append(wh)
        self.stage.inlets.append(model.WarehouseLink(warehouse_id=wh.id))
        self.stage.rkt_algorithm = 'Расписание'
        before = (self.stage.x, self.stage.y, list(self.stage.inlets), self.stage.has_buffer)
        self.window.render_scene()
        node = self.window.nodes[self.stage.id]
        self.assertTrue(node.compact)
        self.assertIsNone(node.body)
        self.assertLess(node.boundingRect().top(), -2)
        self.assertEqual(gui.compact_color_for_stage(self.stage), QColor('#c6a0de'))
        self.window.show_warehouses_action.setChecked(True)
        node = self.window.nodes[self.stage.id]
        self.assertFalse(node.compact)
        self.assertIn('Материалы', node.body.toPlainText())
        self.window.show_warehouses_action.setChecked(False)
        self.assertEqual((self.stage.x, self.stage.y, self.stage.inlets, self.stage.has_buffer), before)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'compact.pdf'
            export_pdf(self.window.scene, output)
            self.assertTrue(output.read_bytes().startswith(b'%PDF'))

    def test_two_views_restore_manual_positions_after_reopening(self):
        self.stage.group_id = self.group.id
        self.other.group_id = self.group.id
        self.stage.level = self.other.level = 1
        self.window.auto_layout()
        self.window.nodes[self.stage.id].setPos(130, 170)
        self.window.nodes[self.other.id].setPos(130, 500)
        compact_positions = [(stage.x, stage.y) for stage in self.project.stages]
        self.window.show_warehouses_action.setChecked(True)
        self.assertFalse(self.window.nodes[self.stage.id].sceneBoundingRect().intersects(
            self.window.nodes[self.other.id].sceneBoundingRect()))
        self.window.nodes[self.stage.id].setPos(310, 250)
        self.window.nodes[self.other.id].setPos(310, 1050)
        detailed_positions = [(stage.x, stage.y) for stage in self.project.stages]
        self.window.show_warehouses_action.setChecked(False)
        synced_compact = [(stage.x, stage.y) for stage in self.project.stages]
        self.assertNotEqual(synced_compact, compact_positions)
        self.assertAlmostEqual(synced_compact[0][0], synced_compact[1][0], delta=.01)
        self.assertLess(synced_compact[0][1], synced_compact[1][1])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'views.flow.json'
            self.window.path = str(path)
            self.assertTrue(self.window.save())
            loaded = model.load_project(path)
            self.window.set_project(loaded, str(path))
            self.assertFalse(self.window.show_warehouses_action.isChecked())
            self.assertEqual([(stage.x, stage.y) for stage in loaded.stages], synced_compact)
            self.window.show_warehouses_action.setChecked(True)
            self.assertEqual(loaded.stages[0].group_id, loaded.stages[1].group_id)
            self.assertLess(loaded.stages[0].y, loaded.stages[1].y)
            self.assertEqual(len(loaded.stages), len(detailed_positions))

    def test_legacy_positions_belong_to_detailed_view(self):
        self.stage.x, self.stage.y = 121.0, 211.0
        self.other.x, self.other.y = 903.0, 311.0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.flow.json'
            model.save_project(self.project, path)
            import json
            data = json.loads(path.read_text(encoding='utf-8'))
            data['version'] = 4
            data['project'].pop('show_warehouses', None)
            data['project'].pop('view_positions', None)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            loaded = model.load_project(path)
            self.assertEqual(loaded.view_positions['detailed'][self.stage.id], [121.0, 211.0])
            self.window.set_project(loaded, str(path))
            self.assertFalse(self.window.show_warehouses_action.isChecked())
            self.window.show_warehouses_action.setChecked(True)
            self.assertEqual([(s.x, s.y) for s in loaded.stages], [(121.0, 211.0), (903.0, 311.0)])

    def test_new_connection_preserves_other_view_positions(self):
        self.window.nodes[self.stage.id].setPos(900, 90)
        self.window.nodes[self.other.id].setPos(20, 90)
        self.window.show_warehouses_action.setChecked(True)
        self.window.show_warehouses_action.setChecked(False)
        self.assertIn('detailed', self.project.view_positions)
        before = dict(self.project.view_positions['detailed'])
        compact = (self.stage.x, self.stage.y, self.other.x, self.other.y)
        self.window.create_edge(self.stage.id, self.other.id)
        self.assertEqual(self.project.view_positions['detailed'], before)
        self.assertEqual((self.stage.x, self.stage.y, self.other.x, self.other.y), compact)
        self.window.show_warehouses_action.setChecked(True)
        self.assertEqual([self.stage.x, self.stage.y], before[self.stage.id])
        self.assertEqual([self.other.x, self.other.y], before[self.other.id])

    def test_title_edit_save_and_redraw_without_growth(self):
        failures = []
        original_color = QColorDialog.getColor
        def enter_title():
            dialog = APP.activeModalWidget()
            try:
                self.assertIsInstance(dialog, QDialog)
                dialog.findChild(QPlainTextEdit).setPlainText('Схема производственного потока')
                field = dialog.findChild(QSpinBox, 'font_size')
                default = field.value()
                QTest.mouseClick(dialog.findChild(QPushButton, 'font_size_up'), Qt.LeftButton)
                QTest.mouseClick(dialog.findChild(QPushButton, 'font_size_up'), Qt.LeftButton)
                self.assertEqual(field.value(), default + 2)
                QTest.mouseClick(dialog.findChild(QPushButton, 'font_size_down'), Qt.LeftButton)
                self.assertEqual(field.value(), default + 1)
                QColorDialog.getColor = staticmethod(lambda *args, **kwargs: QColor('#990000'))
                QTest.mouseClick(dialog.findChild(QPushButton, 'text_color'), Qt.LeftButton)
            except Exception as exc:
                failures.append(exc)
            finally:
                if dialog:
                    dialog.accept()

        self.window.fit_all()
        view = self.window.view
        position = view.mapFromScene(self.window.title_items[0].sceneBoundingRect().center())
        QTimer.singleShot(25, enter_title)
        try:
            QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, position)
            QTest.qWait(35)
        finally:
            QColorDialog.getColor = original_color
        if failures:
            raise failures[0]
        self.assertEqual(self.project.title, 'Схема производственного потока')
        self.assertEqual(self.window.title_items[0].toPlainText(), self.project.title)
        self.assertEqual(self.window.title_items[0].font().pointSize(), 31)
        self.assertEqual(self.window.title_items[0].defaultTextColor(), QColor('#990000'))
        self.assertLess(self.window.title_items[0].sceneBoundingRect().bottom(),
                        self.window.flow_items[0].sceneBoundingRect().top())
        bounds = self.window.scene.itemsBoundingRect()
        for _ in range(3):
            self.window.render_scene()
        self.assertEqual(bounds, self.window.scene.itemsBoundingRect())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'project.flow.json'
            model.save_project(self.project, path)
            loaded = model.load_project(path)
            self.assertEqual(loaded.title, self.project.title)
            self.assertEqual(loaded.title_style, self.project.title_style)
            output = Path(directory) / 'titled.pdf'
            export_pdf(self.window.scene, output)
            self.assertTrue(output.read_bytes().startswith(b'%PDF'))

    def test_copy_stage_is_independent_and_keeps_settings(self):
        wh = model.Warehouse(name='Материал', warehouse_type='ordinary')
        self.project.warehouses.append(wh)
        self.stage.group_id = self.group.id
        self.stage.level = 3
        self.stage.code = '000003'
        self.stage.extra = {'source_id': 'source-guid', 'provider_type_id': 'Производство',
                            'deletion_mark': True, 'nested': {'hint': 'исходный'}}
        self.stage.inlets = [model.WarehouseLink(warehouse_id=wh.id, extra={'x': ['old']})]
        self.stage.stocks = [model.WarehouseLink(warehouse_id=wh.id, primary=True)]
        self.project.edges.append(model.Edge(source=self.stage.id, target=self.other.id))
        self.window.render_scene()
        old_positions = [(s.x, s.y) for s in self.project.stages]
        menu = self.window.build_stage_context_menu(self.stage.id)
        next(action for action in menu.actions() if action.text() == 'Копировать передел').trigger()
        copy = self.project.stages[-1]
        self.assertNotEqual(copy.id, self.stage.id)
        self.assertEqual(copy.name, 'Резка (копия)')
        self.assertEqual(copy.code, '')
        self.assertEqual(copy.group_id, self.group.id)
        self.assertEqual(copy.provider_type, self.stage.provider_type)
        self.assertEqual(copy.level, 3)
        self.assertTrue(copy.has_buffer)
        self.assertNotIn('source_id', copy.extra)
        self.assertFalse(copy.extra['deletion_mark'])
        self.assertEqual(copy.extra['provider_type_id'], 'Производство')
        self.assertEqual(copy.inlets[0].warehouse_id, wh.id)
        self.assertEqual(copy.stocks[0].warehouse_id, wh.id)
        self.assertEqual(len(self.project.edges), 1)
        self.assertEqual([(s.x, s.y) for s in self.project.stages[:-1]], old_positions)
        self.assertEqual(self.window.selected_id, copy.id)
        self.assertTrue(self.window.name_input.hasFocus())
        copy.inlets[0].extra['x'].append('new')
        copy.extra['nested']['hint'] = 'копия'
        self.assertEqual(self.stage.inlets[0].extra['x'], ['old'])
        self.assertEqual(self.stage.extra['nested']['hint'], 'исходный')
        self.window.name_input.setText('Изменённая копия')
        self.assertEqual(self.stage.name, 'Резка')
        self.assertEqual(copy.name, 'Изменённая копия')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'copy.flow.json'
            model.save_project(self.project, path)
            loaded = model.load_project(path)
            self.assertEqual(loaded.stages[-1].name, 'Изменённая копия')

    def test_new_edge_preserves_positions_and_allows_reverse_cycle(self):
        self.stage.x, self.stage.y = 900.0, 100.0
        self.other.x, self.other.y = 20.0, 100.0
        self.window.set_project(self.project)
        self.assertTrue(self.window.create_edge(self.stage.id, self.other.id))
        self.assertEqual((self.stage.x, self.stage.y, self.other.x, self.other.y), (900, 100, 20, 100))
        self.assertEqual(len(self.project.edges), 1)
        messages = []
        old_warning = QMessageBox.warning
        try:
            QMessageBox.warning = staticmethod(lambda *args: messages.append(args[-1]))
            self.assertTrue(self.window.create_edge(self.other.id, self.stage.id))
        finally:
            QMessageBox.warning = old_warning
        self.assertEqual(len(self.project.edges), 2)
        self.assertEqual({(e.source, e.target) for e in self.project.edges},
                         {(self.stage.id, self.other.id), (self.other.id, self.stage.id)})
        self.assertFalse(messages)

    def test_new_edge_preserves_positions_even_when_filtered(self):
        self.stage.x, self.stage.y = 900.0, 100.0
        self.other.x, self.other.y = 20.0, 100.0
        self.window.set_project(self.project)
        self.window.search.setText('Резка')
        self.assertEqual(list(self.window.nodes), [self.stage.id])
        self.assertTrue(self.window.create_edge(self.stage.id, self.other.id))
        self.assertEqual((self.stage.x, self.stage.y, self.other.x, self.other.y), (900, 100, 20, 100))
        self.assertEqual(list(self.window.nodes), [self.stage.id])

    def test_copy_name_collision_and_bounds(self):
        first = self.window.copy_stage(self.stage.id)
        second = self.window.copy_stage(self.stage.id)
        self.assertEqual(first.name, 'Резка (копия)')
        self.assertEqual(second.name, 'Резка (копия 2)')
        nodes = [self.window.nodes[s.id].sceneBoundingRect() for s in self.project.stages]
        for i, left in enumerate(nodes):
            for right in nodes[i + 1:]:
                self.assertFalse(left.intersects(right))


if __name__ == '__main__':
    unittest.main()
