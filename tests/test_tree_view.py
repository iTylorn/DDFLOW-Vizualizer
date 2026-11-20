"""The object tree can show only used groups or a flat stage list."""
import unittest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from flow_visualizer import gui, model


APP = QApplication.instance() or QApplication([])


def walk(item):
    yield item
    for i in range(item.childCount()):
        yield from walk(item.child(i))


def item_for(root, kind, ident):
    return next((item for item in walk(root) if item.data(0, Qt.UserRole) == (kind, ident)), None)


class TreeViewTests(unittest.TestCase):
    def setUp(self):
        self.used = model.Group(name='Используемая', code='001')
        self.empty = model.Group(name='Пустая', code='002')
        self.a = model.Stage(name='Фрезеровка', provider_type='Производство', group_id=self.used.id)
        self.b = model.Stage(name='Закупка', provider_type='Покупка')
        self.wh = model.Warehouse(name='Склад')
        self.project = model.Project(groups=[self.used, self.empty], stages=[self.a, self.b], warehouses=[self.wh])
        self.window = gui.MainWindow()
        self.window.set_project(self.project)
        self.window.show()
        APP.processEvents()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        APP.processEvents()

    def roots(self):
        tree = self.window.object_tree
        return tree.topLevelItem(0), tree.topLevelItem(1), tree.topLevelItem(2)

    def test_only_used_groups_under_stages_without_deleting_reference_groups(self):
        stages, warehouses, groups = self.roots()
        self.assertIsNotNone(item_for(stages, 'group', self.used.id))
        self.assertIsNone(item_for(stages, 'group', self.empty.id))
        self.assertIsNotNone(item_for(stages, 'stage', self.a.id))
        self.assertIsNotNone(item_for(stages, 'stage', self.b.id))
        self.assertIsNotNone(item_for(groups, 'group', self.empty.id))
        self.assertIsNotNone(item_for(groups, 'group', self.used.id))
        self.assertIsNotNone(item_for(warehouses, 'warehouse', self.wh.id))
        self.assertEqual(len(self.project.groups), 2)

    def test_flat_mode_selection_and_round_trip_to_grouped(self):
        stages, _, _ = self.roots()
        self.window.object_tree.setCurrentItem(item_for(stages, 'stage', self.a.id))
        APP.processEvents()
        self.window.stage_list_mode.setCurrentIndex(self.window.stage_list_mode.findData('flat'))
        APP.processEvents()
        stages, _, groups = self.roots()
        self.assertEqual([stages.child(i).data(0, Qt.UserRole)[0] for i in range(stages.childCount())], ['stage', 'stage'])
        self.assertEqual([stages.child(i).text(0) for i in range(stages.childCount())], ['Закупка', 'Фрезеровка'])
        self.assertEqual(self.window.selected_id, self.a.id)
        self.assertEqual(self.window.object_tree.currentItem().data(0, Qt.UserRole), ('stage', self.a.id))
        self.assertIsNotNone(item_for(groups, 'group', self.empty.id))
        self.assertFalse(self.window.dirty)
        self.window.stage_list_mode.setCurrentIndex(self.window.stage_list_mode.findData('grouped'))
        APP.processEvents()
        stages, _, _ = self.roots()
        self.assertEqual(self.window.selected_id, self.a.id)
        self.assertEqual(item_for(stages, 'stage', self.a.id).parent().data(0, Qt.UserRole), ('group', self.used.id))

    def test_move_stage_updates_used_groups_and_context_menu_in_flat_mode(self):
        self.assertTrue(self.window.assign_stage_group(self.a.id, self.empty.id))
        stages, _, _ = self.roots()
        self.assertIsNone(item_for(stages, 'group', self.used.id))
        self.assertIsNotNone(item_for(stages, 'group', self.empty.id))
        self.window.stage_list_mode.setCurrentIndex(self.window.stage_list_mode.findData('flat'))
        APP.processEvents()
        menu = self.window.build_stage_context_menu(self.a.id)
        self.assertIsNotNone(menu)
        action = next(a for a in menu.actions()[0].menu().actions() if a.data() == self.used.id)
        action.trigger()
        APP.processEvents()
        self.assertEqual(self.a.group_id, self.used.id)
        self.assertEqual(self.window.selected_id, self.a.id)
        self.assertEqual(self.window.object_tree.currentItem().data(0, Qt.UserRole), ('stage', self.a.id))
        self.window.stage_list_mode.setCurrentIndex(self.window.stage_list_mode.findData('grouped'))
        stages, _, _ = self.roots()
        self.assertIsNotNone(item_for(stages, 'group', self.used.id))
        self.assertIsNone(item_for(stages, 'group', self.empty.id))

    def test_empty_group_selected_from_reference_creates_stage(self):
        _, _, groups = self.roots()
        self.window.object_tree.setCurrentItem(item_for(groups, 'group', self.empty.id))
        APP.processEvents()
        button = next(button for button in self.window.objects_panel.findChildren(QPushButton)
                      if button.text() == '+ Передел')
        QTest.mouseClick(button, Qt.LeftButton)
        APP.processEvents()
        self.assertEqual(self.project.stages[-1].group_id, self.empty.id)
        stages, _, _ = self.roots()
        self.assertIsNotNone(item_for(stages, 'group', self.empty.id))
        self.assertEqual(self.window.selected_id, self.project.stages[-1].id)

    def test_hidden_search_result_selected_from_flat_tree(self):
        self.window.stage_list_mode.setCurrentIndex(self.window.stage_list_mode.findData('flat'))
        self.window.search.setText('несуществующий передел')
        APP.processEvents()
        self.assertFalse(self.window.nodes)
        stages, _, _ = self.roots()
        self.window.object_tree.setCurrentItem(item_for(stages, 'stage', self.a.id))
        APP.processEvents()
        self.assertEqual(self.window.selected_id, self.a.id)
        self.assertIn(self.a.id, self.window.nodes)
        self.assertEqual(self.window.search.text(), '')


if __name__ == '__main__':
    unittest.main()
