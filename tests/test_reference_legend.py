import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsTextItem
from flow_visualizer import gui, model
from flow_visualizer.colors import compact_color_for_stage, DEFAULT_COLORS, DEFICIT_COLOR
from flow_visualizer.symbols import ALGORITHMS, LAYOUTS, algorithm_kind, frame_pen, is_retired_algorithm
from flow_visualizer.selection_alignment import STANDARD_HORIZONTAL_GAP

APP = QApplication.instance() or QApplication([])


class ReferenceLegendTests(unittest.TestCase):
    def test_align_widens_unlinked_columns_in_both_views(self):
        for detailed in (False, True):
            stages = [model.Stage(name=name, provider_type='Производство',
                                  y=120 - index * 30)
                      for index, name in enumerate(('Закупка', 'Центральный склад', 'Заготовительный'))]
            x = 0
            for stage in stages:
                stage.x = x
                x += gui.StageItem(stage, {}, lambda: None, not detailed).width + 10
            window = gui.MainWindow()
            self.addCleanup(lambda w=window: self.close_window(w))
            window.set_project(model.Project(stages=stages, show_warehouses=detailed))
            self.assertTrue(window.auto_layout())
            bounds = [window.nodes[stage.id].connection_rect() for stage in stages]
            gaps = [bounds[i + 1].left() - bounds[i].right() for i in range(2)]
            self.assertAlmostEqual(gaps[0], gaps[1], delta=.01)
            self.assertAlmostEqual(gaps[0], STANDARD_HORIZONTAL_GAP, delta=.01)
            self.assertLess(stages[2].y, stages[1].y)
            self.assertLess(stages[1].y, stages[0].y)

    def test_align_measures_group_frames_as_boundaries(self):
        groups = [model.Group(id='g1', name='Цех 1'), model.Group(id='g2', name='Цех 2')]
        stages = [model.Stage(name='Первый', provider_type='Производство', group_id='g1', x=0, y=0),
                  model.Stage(name='Второй', provider_type='Производство', group_id='g2', x=280, y=0),
                  model.Stage(name='Третий', provider_type='Производство', x=560, y=0)]
        window = gui.MainWindow()
        self.addCleanup(lambda: self.close_window(window))
        window.set_project(model.Project(stages=stages, groups=groups))
        self.assertTrue(window.auto_layout())
        frames = {item.data(0)[1]: item.sceneBoundingRect() for item in window.group_items
                  if isinstance(item, gui.QGraphicsPathItem)}
        last = window.nodes[stages[-1].id].connection_rect()
        self.assertAlmostEqual(frames['g2'].left() - frames['g1'].right(), STANDARD_HORIZONTAL_GAP, delta=2)
        self.assertAlmostEqual(last.left() - frames['g2'].right(), STANDARD_HORIZONTAL_GAP, delta=2)

    def test_icons_leave_title_size_and_text_unchanged_in_both_modes(self):
        for title in ('РТИ', 'Заготовительный цех крупногабаритных деталей'):
            for detailed in (False, True):
                base = model.Stage(name=title, provider_type='Производство', has_buffer=True)
                marked = model.Stage(name=title, provider_type='Производство', has_buffer=True,
                                     rkt_algorithm=ALGORITHMS[0][0], deficit_launch=True)
                plain = gui.StageItem(base, {}, lambda: None, not detailed)
                card = gui.StageItem(marked, {}, lambda: None, not detailed)
                icon = card.algorithm_rect()
                if detailed:
                    self.assertEqual(card.header_height, plain.header_height)
                    self.assertLessEqual(icon.height(), plain.header_height - 16)
                    self.assertGreaterEqual(icon.left(), card.title_x + card.title.textWidth())
                else:
                    self.assertAlmostEqual(icon.height(), card.height * .70)
                self.assertGreaterEqual(icon.left(), 12 + card.title.textWidth())
                self.assertLessEqual(icon.bottom(), card.header_height)
                self.assertEqual(card.title.defaultFont().pointSize(), plain.title.defaultFont().pointSize())
                if not detailed:
                    self.assertLessEqual(card.boundingRect().top(), -41)

    def test_frames_are_three_times_thicker(self):
        for layout in ('', 'none', 'product', 'setup', 'assignments', 'demand'):
            self.assertAlmostEqual(frame_pen(layout).widthF(), 6)
        self.assertEqual(frame_pen('').style(), frame_pen('none').style())
        self.assertEqual(len({frame_pen(key).style() for key, _, _ in LAYOUTS}), 4)

    def test_reopening_wider_rkt_card_does_not_send_next_card_down(self):
        first = model.Stage(name='Резка', provider_type='Производство',
                            rkt_algorithm=ALGORITHMS[0][0], x=0, y=0)
        second = model.Stage(name='Сборка', provider_type='Производство', x=250, y=0)
        window = gui.MainWindow()
        self.addCleanup(lambda: self.close_window(window))
        window.set_project(model.Project(stages=[first, second]))
        self.assertEqual(first.y, 0)
        self.assertEqual(second.y, 0)
        self.assertGreater(second.x, 250)
        self.assertFalse(window._stage_bounds(first).intersects(window._stage_bounds(second)))
        self.assertAlmostEqual(window._stage_bounds(second).left() - window._stage_bounds(first).right(),
                               STANDARD_HORIZONTAL_GAP)

    def test_algorithm_identity_and_fallback(self):
        for label, ident, kind in ALGORITHMS:
            self.assertEqual(algorithm_kind(label), kind)
            self.assertEqual(algorithm_kind(ident), kind)
        self.assertEqual(algorithm_kind('График выпуска по расписанию APS'), 'aps')
        self.assertEqual(algorithm_kind('График выпуска по сборке/разборке'), 'assembly')
        self.assertEqual(algorithm_kind('Неизвестный алгоритм'), 'unknown')

    def test_colors_and_manual_annotations_roundtrip(self):
        stage = model.Stage(name='Резка', provider_type='Производство',
                            rkt_algorithm=ALGORITHMS[0][0], launch_layout='product', deficit_launch=True)
        self.assertEqual(compact_color_for_stage(stage).name(), '#c6a0de')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project.json'
            model.save_project(model.Project(stages=[stage]), path)
            loaded = model.load_project(path).stages[0]
        self.assertEqual((loaded.launch_layout, loaded.deficit_launch), ('product', True))
        loaded.rkt_algorithm = ''
        self.assertEqual(compact_color_for_stage(loaded).name(), '#00aeef')
        self.assertEqual(compact_color_for_stage(model.Stage(provider_type='Логистика')).name(), '#c4dfb4')
        self.assertEqual(compact_color_for_stage(model.Stage(provider_type='Промуслуги')).name(), '#d8d8d8')

    def test_type_colors_and_contrast_in_normal_rkt_and_deficit_states(self):
        names = ('Покупка', 'Производство', 'Логистика', 'Промуслуги', 'Сборка / Разборка')
        colors = [compact_color_for_stage(model.Stage(provider_type=name)).name() for name in names]
        self.assertEqual(len(set(colors)), len(names))
        self.assertEqual(colors[:2], ['#ffff00', '#00aeef'])
        for attrs in ({}, {'rkt_algorithm': ALGORITHMS[4][0]}, {'deficit_launch': True}):
            production = compact_color_for_stage(model.Stage(provider_type='Производство', **attrs))
            assembly = compact_color_for_stage(model.Stage(provider_type='Сборка / Разборка', **attrs))
            self.assertNotEqual(production, assembly)
        self.assertEqual(compact_color_for_stage(model.Stage(provider_type='Сборка / Разборка'),
                                                 {'assembly': '#123456'}).name(), '#123456')
        def luminance(color):
            def linear(v):
                v /= 255
                return v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
            return sum(w * linear(c) for w, c in zip((.2126, .7152, .0722), (color.red(), color.green(), color.blue())))
        from PySide6.QtGui import QColor
        for value in [*DEFAULT_COLORS.values(), '#000000', '#313131', '#fffffe', '#f01aff']:
            background = QColor(value)
            ink = gui.contrast_text_color(background)
            a, b = sorted((luminance(background), luminance(ink)))
            self.assertGreaterEqual((b + .05) / (a + .05), 4.5, value)

    def test_retired_options_are_hidden_without_erasing_existing_values(self):
        old = 'УДАЛИТЬ график отгрузок'
        stage = model.Stage(name='Передел', provider_type='Производство', rkt_algorithm=old)
        project = model.Project(stages=[stage], rkt_options=[old, 'Старый вариант', ALGORITHMS[5][0]],
                                rkt_option_ids={'УДАЛИТЬ_СтарыйВариант': 'Старый вариант'})
        self.assertTrue(is_retired_algorithm('Старый вариант', project.rkt_option_ids))
        window = gui.MainWindow()
        self.addCleanup(lambda: self.close_window(window))
        window.set_project(project)
        window.show()
        window.nodes[stage.id].setSelected(True)
        APP.processEvents()
        self.assertEqual(window.rkt_input.findData(old), -1)
        self.assertEqual(window.rkt_input.findData('Старый вариант'), -1)
        self.assertIn(old, window.rkt_legacy_label.text())
        window.name_input.setText('Переименованный передел')
        self.assertEqual(stage.rkt_algorithm, old)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project.json'
            model.save_project(project, path)
            self.assertEqual(model.load_project(path).stages[0].rkt_algorithm, old)
        window.rkt_input.setCurrentIndex(window.rkt_input.findData(ALGORITHMS[5][0]))
        self.assertEqual(stage.rkt_algorithm, ALGORITHMS[5][0])
        self.assertFalse(window.rkt_legacy_label.isVisible())

    def test_both_modes_and_warehouse_restrictions(self):
        warehouses = [model.Warehouse(name='Склад 1'), model.Warehouse(name='Склад 2')]
        stage = model.Stage(name='Резка', provider_type='Производство', rkt_algorithm=ALGORITHMS[2][0],
                            inlets=[model.WarehouseLink(warehouse_id=warehouses[0].id)])
        window = gui.MainWindow()
        window.set_project(model.Project(stages=[stage], warehouses=warehouses))
        window.show()
        window.nodes[stage.id].setSelected(True)
        APP.processEvents()
        self.addCleanup(lambda: self.close_window(window))
        def row(table, ident):
            return next(i for i in range(table.rowCount()) if table.item(i, 0).data(Qt.UserRole) == ident)
        blocked = window.stocks.item(row(window.stocks, warehouses[0].id), 0)
        self.assertFalse(blocked.flags() & Qt.ItemIsEnabled)
        self.assertIn('входных стеллажах', blocked.toolTip())
        self.assertIn('Недоступен:', blocked.text())
        self.assertEqual(blocked.background().color().name(), '#e1e5e8')
        window.stocks.scrollToItem(blocked)
        rect = window.stocks.visualItemRect(blocked)
        QTest.mouseClick(window.stocks.viewport(), Qt.LeftButton, Qt.NoModifier,
                         rect.topLeft() + gui.QPointF(8, rect.height() / 2).toPoint())
        self.assertEqual(blocked.checkState(), Qt.Unchecked)
        window.inlets.item(row(window.inlets, warehouses[0].id), 0).setCheckState(Qt.Unchecked)
        self.assertTrue(blocked.flags() & Qt.ItemIsEnabled)
        blocked.setCheckState(Qt.Checked)
        self.assertFalse(window.inlets.item(row(window.inlets, warehouses[0].id), 0).flags() & Qt.ItemIsEnabled)
        window.launch_layout_input.setCurrentIndex(window.launch_layout_input.findData('setup'))
        window.deficit_enabled.setChecked(True)
        self.assertEqual(stage.launch_layout, 'setup')
        self.assertTrue(stage.deficit_launch)
        for detailed in (False, True):
            window.show_warehouses_action.setChecked(detailed)
            APP.processEvents()
            node = window.nodes[stage.id]
            self.assertEqual(algorithm_kind(node.stage.rkt_algorithm), 'equipment')
            self.assertEqual(node.stage.launch_layout, 'setup')
            labels = [i.toPlainText() for i in window.legend_items if isinstance(i, QGraphicsTextItem)]
            for header in ('Алгоритмы расписания контрольной точки', 'Макеты плана запуска',
                           'Типы переделов'):
                self.assertIn(header, labels)
            for label, _, _ in ALGORITHMS:
                self.assertIn(label, labels)
            self.assertIn('Производство с группировкой по коду переналадки', labels)
            self.assertTrue(any('дефицит' in s for s in labels))

    def test_deficit_paints_the_left_quarter_in_both_views_without_recoloring_body(self):
        from PySide6.QtGui import QColor, QImage, QPainter
        for compact in (False, True):
            for provider in ('Производство', 'Сборка / Разборка'):
                stage = model.Stage(name='А', provider_type=provider, deficit_launch=True,
                                    rkt_algorithm=ALGORITHMS[0][0])
                card = gui.StageItem(stage, {}, lambda: None, compact=compact)
                image = QImage(round(card.width), round(card.height), QImage.Format_RGB32)
                painter = QPainter(image)
                card.paint(painter, None)
                painter.end()
                border = round(card.width / 4)
                self.assertEqual(image.pixelColor(border - 3, 8), QColor(DEFICIT_COLOR))
                self.assertEqual(image.pixelColor(border + 3, 8), compact_color_for_stage(stage))
                if not compact:
                    self.assertEqual(image.pixelColor(8, round(card.header_height) + 3), QColor('white'))

    def test_removing_primary_unblocks_other_list_and_updates_model(self):
        warehouse = model.Warehouse(name='Основной склад')
        stage = model.Stage(name='Передел', provider_type='Производство',
                            inlets=[model.WarehouseLink(warehouse_id=warehouse.id, primary=True)])
        window = gui.MainWindow()
        self.addCleanup(lambda: self.close_window(window))
        window.set_project(model.Project(stages=[stage], warehouses=[warehouse]))
        window.show()
        window.nodes[stage.id].setSelected(True)
        APP.processEvents()
        self.assertFalse(window.stocks.item(0, 0).flags() & Qt.ItemIsEnabled)
        window.inlets.item(0, 0).setCheckState(Qt.Unchecked)
        self.assertEqual(window.inlets.item(0, 1).checkState(), Qt.Unchecked)
        self.assertEqual(stage.inlets, [])
        self.assertTrue(window.stocks.item(0, 0).flags() & Qt.ItemIsEnabled)

    def test_real_checkbox_click_blocks_and_unblocks_the_other_list(self):
        warehouse = model.Warehouse(name='Склад')
        stage = model.Stage(name='Передел', provider_type='Производство')
        window = gui.MainWindow()
        self.addCleanup(lambda: self.close_window(window))
        window.set_project(model.Project(stages=[stage], warehouses=[warehouse]))
        window.show()
        window.nodes[stage.id].setSelected(True)
        APP.processEvents()
        def click(editor):
            cell = editor.item(0, 0)
            editor.scrollToItem(cell)
            bounds = editor.visualItemRect(cell)
            QTest.mouseClick(editor.viewport(), Qt.LeftButton, Qt.NoModifier,
                             bounds.topLeft() + gui.QPointF(8, bounds.height() / 2).toPoint())
            APP.processEvents()
        click(window.inlets)
        self.assertEqual(window.inlets.item(0, 0).checkState(), Qt.Checked)
        self.assertFalse(window.stocks.item(0, 0).flags() & Qt.ItemIsEnabled)
        self.assertTrue(window.stocks.item(0, 0).text().startswith('Недоступен:'))
        click(window.stocks)
        self.assertEqual(window.stocks.item(0, 0).checkState(), Qt.Unchecked)
        click(window.inlets)
        self.assertTrue(window.stocks.item(0, 0).flags() & Qt.ItemIsEnabled)
        click(window.stocks)
        self.assertEqual(window.stocks.item(0, 0).checkState(), Qt.Checked)
        self.assertFalse(window.inlets.item(0, 0).flags() & Qt.ItemIsEnabled)

    @staticmethod
    def close_window(window):
        window.dirty = False
        window.close()
        APP.processEvents()
