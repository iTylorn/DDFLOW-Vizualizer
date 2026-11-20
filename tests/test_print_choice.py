import unittest

from PySide6.QtWidgets import QApplication, QGraphicsScene

from flow_visualizer.print_export import make_printer, prefer_multiple_pages


class PrintChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_suggests_multiple_pages_for_a_large_diagram(self):
        scene = QGraphicsScene()
        card = scene.addRect(0, 0, 2200, 1300)
        self.assertTrue(prefer_multiple_pages(scene, make_printer()))
        scene.removeItem(card)
        card = scene.addRect(0, 0, 300, 200)
        self.assertFalse(prefer_multiple_pages(scene, make_printer()))


if __name__ == '__main__':
    unittest.main()
