import unittest
from types import SimpleNamespace

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsTextItem

from flow_visualizer.colors import DEFICIT_COLOR, compact_color_for_type
from flow_visualizer.legend import (BufferLegendIcon, ColorLegendSwatch, draw_legend,
                                    LEGEND_GAP, legend_types)


class LegendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_empty_and_extra_types(self):
        self.assertIn('Производство', legend_types([]))
        types = legend_types([SimpleNamespace(provider_type='Производство'),
                              SimpleNamespace(provider_type='Особый тип'),
                              SimpleNamespace(provider_type='')])
        self.assertEqual(types.count('Производство'), 1)
        self.assertIn('Особый тип', types)
        self.assertIn('Тип не указан', types)

    def test_draw_stays_clear_of_content_and_explains_markers(self):
        scene = QGraphicsScene()
        content = QRectF(-300, -50, 700, 400)
        items, bounds = draw_legend(scene, [], lambda _: QColor('#123456'), content)
        self.assertEqual(bounds.top(), content.bottom() + LEGEND_GAP)
        self.assertEqual(bounds.left(), content.left())
        self.assertFalse(bounds.intersects(content))
        texts = [item.toPlainText() for item in items if isinstance(item, QGraphicsTextItem)]
        self.assertIn('Легенда', texts)
        self.assertTrue(any('РКТ' in value for value in texts))
        self.assertTrue(any('основной склад' in value for value in texts))
        for description in ('материальный склад', 'Цеховая кладовая', 'Тип склада не задан', 'Буфер запаса'):
            self.assertTrue(any(description in value for value in texts), description)
        self.assertTrue(any(isinstance(item, BufferLegendIcon) for item in items))
        for item in items:
            scene.removeItem(item)
        again, after = draw_legend(scene, [], lambda _: QColor('#123456'), content)
        self.assertEqual(bounds, after)
        for item in again:
            scene.removeItem(item)

    def test_compact_legend_explains_rkt_without_warehouse_symbols(self):
        scene = QGraphicsScene()
        items, _ = draw_legend(scene, [], lambda _: QColor('#123456'), QRectF(0, 0, 400, 200), compact=True)
        texts = [item.toPlainText() for item in items if isinstance(item, QGraphicsTextItem)]
        self.assertTrue(any('Производство с РКТ' in value for value in texts))
        self.assertTrue(any('Сборка / разборка с РКТ' in value for value in texts))
        self.assertTrue(any('Буфер запаса' in value for value in texts))
        self.assertFalse(any('Цеховая кладовая' in value for value in texts))

    def test_legend_text_grows_with_composition_width(self):
        scene = QGraphicsScene()
        sizes = []
        for width in (560, 2000):
            items, bounds = draw_legend(scene, [], lambda _: QColor('#123456'), QRectF(0, 0, width, 200), compact=True)
            text = next(item for item in items if isinstance(item, QGraphicsTextItem) and item.toPlainText() == 'Производство')
            sizes.append(text.font().pointSize())
            self.assertGreaterEqual(sizes[-1], 13)
            self.assertTrue(bounds.contains(text.sceneBoundingRect()))
            for item in items:
                scene.removeItem(item)
        self.assertGreater(sizes[1], sizes[0])

    def test_deficit_swatches_share_rows_and_buffer_is_below_layouts(self):
        for compact in (True, False):
            scene = QGraphicsScene()
            items, bounds = draw_legend(scene, [], compact_color_for_type, QRectF(0, 0, 1600, 200), compact=compact)
            labels = {item.toPlainText(): item for item in items if isinstance(item, QGraphicsTextItem)}
            swatches = [item for item in items if isinstance(item, ColorLegendSwatch)]
            striped = [item for item in swatches if item.deficit]
            self.assertEqual(len(striped), 4)
            for item in striped:
                match = next(plain for plain in swatches if not plain.deficit and plain.pos().y() == item.pos().y())
                self.assertEqual(match.color, item.color)
                self.assertLess(match.pos().x(), item.pos().x())
                self.assertTrue(bounds.contains(item.sceneBoundingRect()))
                image = QImage(60, 40, QImage.Format_RGB32)
                image.fill(QColor('white'))
                painter = QPainter(image)
                item.paint(painter, None)
                painter.end()
                self.assertEqual(image.pixelColor(9, 12), QColor(DEFICIT_COLOR))
                self.assertEqual(image.pixelColor(13, 12), item.color)
            buffer = labels['Буфер запаса']
            self.assertGreater(buffer.pos().y(), labels['Группировка по источнику потребности (производство)'].sceneBoundingRect().bottom())
            self.assertLess(buffer.pos().x(), labels['Типы переделов'].pos().x())

    def test_deficit_section_stays_close_to_types_when_scheme_grows(self):
        distances = []
        custom = SimpleNamespace(provider_type='Производство длинного перечня крупногабаритных деталей')
        for width in (4200, 7000):
            scene = QGraphicsScene()
            items, _ = draw_legend(scene, [custom], compact_color_for_type, QRectF(0, 0, width, 200))
            labels = {item.toPlainText(): item for item in items if isinstance(item, QGraphicsTextItem)}
            types = labels['Типы переделов']
            deficit = labels['С дефицитом']
            standard = labels['Сборка / разборка с РКТ']
            self.assertAlmostEqual(deficit.pos().x() - standard.sceneBoundingRect().right(), 12, delta=.05)
            self.assertGreater(labels[custom.provider_type].boundingRect().height(), standard.boundingRect().height())
            distances.append(deficit.pos().x() - types.pos().x())
        self.assertAlmostEqual(*distances)


if __name__ == '__main__':
    unittest.main()
