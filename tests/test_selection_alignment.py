import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QGraphicsSimpleTextItem, QMenu, QPushButton, QSpinBox
from flow_visualizer import gui, model
from flow_visualizer.selection_alignment import align_selection, STANDARD_HORIZONTAL_GAP
from flow_visualizer.group_graph import GroupTitleItem

APP = QApplication.instance() or QApplication([])


class AlignmentGeometry(unittest.TestCase):
    def setUp(self):
        self.rects = {'a': QRectF(0, 0, 100, 50), 'b': QRectF(200, 90, 120, 60),
                      'c': QRectF(480, 230, 80, 70)}

    def aligned(self, mode):
        changes = align_selection(self.rects, self.rects, ['a', 'b', 'c'], mode)
        return {key: r.translated(changes[key]) for key, r in self.rects.items()}

    def test_six_alignment_directions(self):
        for mode, property_name in [('left', 'left'), ('hcenter', None), ('right', 'right'),
                                    ('top', 'top'), ('vcenter', None), ('bottom', 'bottom')]:
            with self.subTest(mode=mode):
                result = self.aligned(mode)
                if mode == 'hcenter':
                    values = [r.center().x() for r in result.values()]
                elif mode == 'vcenter':
                    values = [r.center().y() for r in result.values()]
                else:
                    values = [getattr(r, property_name)() for r in result.values()]
                self.assertAlmostEqual(max(values), min(values), delta=.001)

    def test_distribute_centers_and_equal_or_standard_gaps(self):
        for axis in ('x', 'y'):
            centers = self.aligned('distribute_' + axis)
            coord = (lambda r: r.center().x()) if axis == 'x' else (lambda r: r.center().y())
            c = sorted(coord(r) for r in centers.values())
            self.assertAlmostEqual(c[1] - c[0], c[2] - c[1], delta=.001)
            for mode in ('equal_gaps_', 'space_'):
                result = self.aligned(mode + axis)
                rs = sorted(result.values(), key=coord)
                gaps = ([rs[i+1].left() - rs[i].right() for i in range(2)] if axis == 'x' else
                        [rs[i+1].top() - rs[i].bottom() for i in range(2)])
                self.assertAlmostEqual(gaps[0], gaps[1], delta=.001)
                if mode == 'space_':
                    self.assertAlmostEqual(gaps[0], STANDARD_HORIZONTAL_GAP if axis == 'x' else 24, delta=.001)

    def test_refuses_to_overlap_and_keeps_input_unchanged(self):
        row = {'a': QRectF(0, 0, 100, 50), 'b': QRectF(200, 0, 100, 50)}
        with self.assertRaisesRegex(ValueError, 'наложени'):
            align_selection(row, row, ['a', 'b'], 'left')
        self.assertEqual(row['b'].x(), 200)


class AlignmentUI(unittest.TestCase):
    def setUp(self):
        self.group = model.Group(name='Большая группа')
        self.stages = [model.Stage(name=str(i), provider_type='Покупка', x=x, y=y, group_id=self.group.id)
                       for i, (x, y) in enumerate([(40, 50), (380, 130), (720, 210)])]
        self.window = gui.MainWindow()
        self.window.set_project(model.Project(stages=self.stages, groups=[self.group]))
        self.window.show()
        APP.processEvents()
        self.addCleanup(self.close)

    def close(self):
        self.window.dirty = False
        self.window.close()
        APP.processEvents()

    def test_group_context_menu_aligns_members_and_preserves_selection(self):
        a, b, c = self.stages
        self.window.nodes[a.id].setSelected(True)
        self.window.nodes[b.id].setSelected(True)
        pos = self.window.view.mapFromScene(self.window.nodes[b.id].connection_rect().center())
        called = []
        def activate():
            menu = QApplication.activePopupWidget()
            try:
                group = next(action.menu() for action in menu.actions() if action.text() == 'Выровнять всю группу')
                action = next(action for action in group.actions() if action.text() == 'По центру по вертикали')
                called.append(action.text())
                action.trigger()
            except Exception as exc:
                called.append(exc)
            finally:
                menu.close()
        QTimer.singleShot(0, activate)
        self.window.diagram_context_menu(pos)
        self.assertTrue(called)
        if isinstance(called[0], Exception):
            raise called[0]
        ys = [self.window.nodes[s.id].connection_rect().center().y() for s in self.stages]
        self.assertAlmostEqual(max(ys), min(ys), delta=.01)
        self.assertTrue(self.window.nodes[a.id].isSelected())
        self.assertTrue(self.window.nodes[b.id].isSelected())

    def test_group_label_context_menu_works_without_selection(self):
        self.window.scene.clearSelection()
        label = next(i for i in self.window.group_items if isinstance(i, GroupTitleItem))
        self.window.view.ensureVisible(label)
        APP.processEvents()
        pos = self.window.view.mapFromScene(label.sceneBoundingRect().center())
        seen = []
        def inspect():
            menu = QApplication.activePopupWidget()
            try:
                seen.extend(action.text() for action in menu.actions())
            finally:
                menu.close()
        QTimer.singleShot(0, inspect)
        self.window.diagram_context_menu(pos)
        self.assertIn('Выровнять всю группу', seen)

    def test_settings_actual_plus_minus_clicks_and_save_group_font(self):
        captured = []
        def fill():
            dialog = QApplication.activeModalWidget()
            try:
                self.assertIsInstance(dialog, QDialog)
                for key in ('card_width', 'card_height', 'flow_font', 'title_font', 'group_font'):
                    value = dialog.findChild(QSpinBox, key)
                    before = value.value()
                    QTest.mouseClick(dialog.findChild(QPushButton, key + '_up'), Qt.LeftButton)
                    self.assertEqual(value.value(), before + 1)
                    QTest.mouseClick(dialog.findChild(QPushButton, key + '_down'), Qt.LeftButton)
                    self.assertEqual(value.value(), before)
                group = dialog.findChild(QSpinBox, 'group_font')
                group.setValue(24)
            except Exception as exc:
                captured.append(exc)
            finally:
                dialog.accept()
        QTimer.singleShot(0, fill)
        self.window.edit_card_size()
        if captured:
            raise captured[0]
        self.assertEqual(self.window.project.group_font_size, 24)
        labels = [i for i in self.window.group_items if isinstance(i, GroupTitleItem)]
        self.assertTrue(labels)
        self.assertTrue(all(i.font().pointSize() == 24 for i in labels))
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'project.json'
            model.save_project(self.window.project, file)
            self.assertEqual(model.load_project(file).group_font_size, 24)

    def test_old_project_levels_round_trip_but_do_not_control_layout(self):
        a, b, _ = self.stages
        a.level, b.level = 1, 20
        first = self.window._layout_positions()
        a.level, b.level = 20, 1
        second = self.window._layout_positions()
        self.assertEqual(first, second)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'old.json'
            model.save_project(self.window.project, path)
            raw = json.loads(path.read_text(encoding='utf-8'))
            raw['version'] = 7
            raw['project'].pop('group_font_size')
            path.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
            old = model.load_project(path)
            self.assertEqual(old.group_font_size, 18)
            self.assertEqual([old.stages[0].level, old.stages[1].level], [20, 1])
            model.save_project(old, path)
            self.assertEqual(model.load_project(path).stages[0].level, 20)
