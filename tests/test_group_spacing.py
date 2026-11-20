import tempfile
import unittest
from pathlib import Path
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication
from flow_visualizer import gui, model
from flow_visualizer.group_graph import GroupTitleItem
from flow_visualizer.print_export import export_pdf
from flow_visualizer.selection_alignment import STANDARD_HORIZONTAL_GAP

APP = QApplication.instance() or QApplication([])


class GroupAndArrowSpacingTests(unittest.TestCase):
    def test_short_gap_does_not_reverse_automatic_arrow_route(self):
        class Node:
            def __init__(self, rect):
                self.rect = rect
            def connection_rect(self):
                return QRectF(self.rect)
        for gap in (8, 24, 72):
            for reverse in (False, True):
                a = Node(QRectF(0, 80, 100, 60))
                b = Node(QRectF(100 + gap, 180, 100, 60))
                source, target = (b, a) if reverse else (a, b)
                points = gui.route_points(source, target, [])
                xs = [p.x() for p in points]
                signed = [-x for x in xs] if reverse else xs
                self.assertEqual(signed, sorted(signed), (gap, reverse, xs))

    def test_standard_spacing_keeps_room_for_arrow_and_project(self):
        a = model.Stage(name='Закупка', provider_type='Покупка', x=0, y=150)
        b = model.Stage(name='Центральный склад', provider_type='Логистика', x=700, y=70)
        edge = model.Edge(source=a.id, target=b.id)
        project = model.Project(stages=[a, b], edges=[edge])
        window = gui.MainWindow()
        window.set_project(project)
        self.addCleanup(lambda: (setattr(window, 'dirty', False), window.close()))
        self.assertTrue(window.align_objects([a.id, b.id], 'space_x'))
        source, target = window.nodes[a.id], window.nodes[b.id]
        gap = target.connection_rect().left() - source.connection_rect().right()
        self.assertAlmostEqual(gap, STANDARD_HORIZONTAL_GAP, delta=.01)
        points = window.edge_items[0]._points
        self.assertEqual([p.x() for p in points], sorted(p.x() for p in points))
        self.assertEqual(window.edge_items[0]._head[0], points[-1])
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / 'flow.json'
            window.path = str(filename)
            self.assertTrue(window.save())
            saved = model.load_project(filename)
            self.assertEqual((saved.stages[0].x, saved.stages[1].x), (a.x, b.x))

    def test_wrapped_group_heading_is_inside_frame_in_pdf_scene(self):
        group = model.Group(name='Цех №3 Заготовительный участок производственного комплекса')
        stage = model.Stage(name='Заготовительный Цех №1', provider_type='Производство',
                            group_id=group.id, x=50, y=100)
        window = gui.MainWindow()
        window.set_project(model.Project(groups=[group], stages=[stage]))
        self.addCleanup(lambda: (setattr(window, 'dirty', False), window.close()))
        frame = window.group_items[0]
        title = next(item for item in window.group_items if isinstance(item, GroupTitleItem))
        self.assertGreater(title.document().begin().layout().lineCount(), 1)
        self.assertTrue(frame.sceneBoundingRect().contains(title.sceneBoundingRect()))
        self.assertFalse(title.sceneBoundingRect().intersects(window.nodes[stage.id].sceneBoundingRect()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'page.pdf'
            export_pdf(window.scene, path, tiled=False)
            self.assertTrue(path.read_bytes().startswith(b'%PDF'))
