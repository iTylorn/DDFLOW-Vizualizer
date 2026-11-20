import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGraphicsRectItem, QGraphicsScene
from flow_visualizer.group_graph import draw_group_frames


class GroupGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.scene = QGraphicsScene()
        self.nodes = {}
        self.group = SimpleNamespace(id='a', name='Цех резки')

    def add_node(self, ident, group, x):
        node = QGraphicsRectItem(0, 0, 100, 100)
        node.stage = SimpleNamespace(group_id=group)
        node.setPos(x, 0)
        self.scene.addItem(node)
        self.nodes[ident] = node
        return node

    def test_bounding_frame_and_drag_redraw(self):
        self.add_node('one', 'a', 0)
        second = self.add_node('two', 'a', 250)
        items = draw_group_frames(self.scene, [self.group], self.nodes)
        self.assertEqual(3, len(items))
        self.assertEqual('Цех резки', items[-1].text())
        self.assertEqual(Qt.MouseButton.NoButton, items[0].acceptedMouseButtons())
        self.assertLess(items[0].zValue(), 0)
        old_width = items[0].boundingRect().width()
        for item in items:
            self.scene.removeItem(item)
        second.setPos(500, 0)
        items = draw_group_frames(self.scene, [self.group], self.nodes)
        self.assertGreater(items[0].boundingRect().width(), old_width)

    def test_foreign_stage_splits_frame(self):
        self.add_node('one', 'a', 0)
        self.add_node('other', '', 200)
        self.add_node('two', 'a', 400)
        items = draw_group_frames(self.scene, [self.group], self.nodes)
        self.assertEqual(6, len(items))
        self.assertEqual(['Цех резки', 'Цех резки'], [items[2].text(), items[5].text()])
        self.assertFalse(items[0].sceneBoundingRect().intersects(self.nodes['other'].sceneBoundingRect()))
        self.assertFalse(items[3].sceneBoundingRect().intersects(self.nodes['other'].sceneBoundingRect()))

    def test_empty_and_hidden_group(self):
        node = self.add_node('one', 'a', 0)
        node.hide()
        self.assertEqual([], draw_group_frames(self.scene, [self.group], self.nodes))

    def test_long_title_wraps_inside_frame_without_overlapping_cards(self):
        self.group.name = 'Цех №3 Заготовительный участок с длинным названием'
        node = self.add_node('one', 'a', 0)
        for font_size in (18, 36):
            items = draw_group_frames(self.scene, [self.group], self.nodes, font_size=font_size)
            frame, _, title = items
            self.assertGreater(title.document().begin().layout().lineCount(), 1)
            self.assertTrue(frame.sceneBoundingRect().contains(title.sceneBoundingRect()))
            self.assertFalse(title.sceneBoundingRect().intersects(node.sceneBoundingRect()))
            self.assertLessEqual(title.sceneBoundingRect().right(), frame.sceneBoundingRect().right())
            for item in items:
                self.scene.removeItem(item)

    def test_unbroken_word_also_remains_inside_group(self):
        self.group.name = 'Сверхдлинноенеразрывноенаименованиеподразделения' * 2
        self.add_node('one', 'a', 0)
        frame, _, title = draw_group_frames(self.scene, [self.group], self.nodes)
        self.assertGreater(title.document().begin().layout().lineCount(), 1)
        self.assertTrue(frame.sceneBoundingRect().contains(title.sceneBoundingRect()))


if __name__ == '__main__':
    unittest.main()
