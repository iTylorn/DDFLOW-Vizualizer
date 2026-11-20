"""Regression tests for the stage type picker."""
import unittest

from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication

from flow_visualizer import gui, model


APP = QApplication.instance() or QApplication([])
STANDARD_TYPES = ('Производство', 'Покупка', 'Промуслуги', 'Логистика', 'Сборка / Разборка')


class ProviderTypeChoicesTests(unittest.TestCase):
    def setUp(self):
        self.window = gui.MainWindow()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        APP.processEvents()

    def test_new_stage_keeps_all_standard_types_after_purchase(self):
        self.window.set_project(model.Project(provider_options=['Покупка']))
        self.window.show()
        self.window.add_stage()
        self.window.type_input.setCurrentIndex(self.window.type_input.findData('Покупка'))
        self.window.add_stage()
        choices = tuple(self.window.type_input.itemData(index)
                        for index in range(1, self.window.type_input.count()))
        self.assertEqual(choices[:len(STANDARD_TYPES)], STANDARD_TYPES)
        self.assertEqual(set(STANDARD_TYPES) - set(choices), set())

    def test_toolbar_type_filter_shows_full_selected_label_and_popup(self):
        self.window.set_project(model.Project(provider_options=list(STANDARD_TYPES)))
        self.window.show()
        APP.processEvents()
        combo = self.window.type_filter
        name = max(STANDARD_TYPES, key=QFontMetrics(combo.font()).horizontalAdvance)
        combo.setCurrentIndex(combo.findData(name))
        required = QFontMetrics(combo.font()).horizontalAdvance(name)
        self.assertGreaterEqual(combo.width(), required + 18)
        combo.showPopup()
        try:
            APP.processEvents()
            self.assertGreaterEqual(combo.view().viewport().width(), required)
        finally:
            combo.hidePopup()


if __name__ == '__main__':
    unittest.main()
