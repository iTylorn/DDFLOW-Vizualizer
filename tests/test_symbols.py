import unittest

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter

from flow_visualizer.symbols import draw_buffer


class BufferSymbolTests(unittest.TestCase):
    def test_top_is_wider_than_bottom_and_colors_follow_original(self):
        image = QImage(100, 120, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        draw_buffer(painter, QRectF(20, 10, 60, 90))
        painter.end()
        def opaque_width(y):
            return sum(image.pixelColor(x, y).alpha() > 0 for x in range(image.width()))
        self.assertGreater(opaque_width(16), opaque_width(94))
        self.assertEqual(image.pixelColor(50, 20).name().lower(), '#2ecc71')
        self.assertEqual(image.pixelColor(50, 55).name().lower(), '#f1c40f')
        self.assertEqual(image.pixelColor(50, 90).name().lower(), '#e74c3c')


if __name__ == '__main__':
    unittest.main()
