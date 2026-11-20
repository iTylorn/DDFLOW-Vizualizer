import unittest

from flow_visualizer.auto_layout import LayoutError, arrange_stages, COLUMN_GAP, ROW_GAP
from flow_visualizer.model import Edge, Group, Project, Stage


class AutoLayoutTests(unittest.TestCase):
    def test_ungrouped_are_horizontal_by_level_and_manual_positions_unchanged(self):
        project = Project(stages=[Stage(id='later', level=3, x=777, y=-30),
                                  Stage(id='first', level=1), Stage(id='unset'),
                                  Stage(id='middle', level=2)])
        result = arrange_stages(project, lambda _: (260, 100))
        ordered = ['first', 'middle', 'later', 'unset']
        self.assertEqual([result[s][0] for s in ordered], sorted(result[s][0] for s in ordered))
        self.assertEqual(len({result[s][1] for s in ordered}), 1)
        self.assertEqual((project.stages[0].x, project.stages[0].y), (777, -30))

    def test_grouped_levels_grid_and_foreign_boxes_do_not_overlap(self):
        group = Group(id='workshop', name='Цех')
        stages = [Stage(id='l2', group_id=group.id, level=2),
                  Stage(id='l1a', group_id=group.id, level=1),
                  Stage(id='l1b', group_id=group.id, level=1),
                  Stage(id='u1', group_id=group.id), Stage(id='u2', group_id=group.id),
                  Stage(id='u3', group_id=group.id), Stage(id='u4', group_id=group.id),
                  Stage(id='solo', level=3)]
        project = Project(groups=[group], stages=stages)
        sizes = {'l1a': (260, 150), 'l1b': (260, 350), 'l2': (260, 210),
                 'u1': (260, 170), 'u2': (260, 110), 'u3': (260, 130),
                 'u4': (260, 190), 'solo': (260, 130)}
        pos = arrange_stages(project, lambda stage: sizes[stage.id])
        self.assertEqual(pos['l1a'][0], pos['l1b'][0])
        self.assertGreaterEqual(pos['l1b'][1] - pos['l1a'][1], sizes['l1a'][1] + ROW_GAP)
        self.assertGreaterEqual(pos['l2'][0], pos['l1a'][0] + sizes['l1a'][0] + COLUMN_GAP)
        self.assertGreater(pos['u1'][0], pos['l2'][0])
        self.assertEqual(len({pos[name][0] for name in ('u1', 'u2', 'u3', 'u4')}), 2)
        self.assertEqual(len({pos[name][1] + sizes[name][1] / 2
                              for name in ('u1', 'u2', 'u3', 'u4')}), 2)
        group_right = max(pos[stage.id][0] + sizes[stage.id][0] for stage in stages if stage.group_id)
        self.assertGreater(pos['solo'][0], group_right + 36)
        for i, a in enumerate(stages):
            for b in stages[i + 1:]:
                ax, ay = pos[a.id]; bx, by = pos[b.id]
                aw, ah = sizes[a.id]; bw, bh = sizes[b.id]
                self.assertFalse(ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah,
                                 f'{a.id} overlaps {b.id}')

    def test_group_order_and_long_name_reserves_horizontal_space(self):
        group = Group(id='g', name='Длинное наименование подразделения')
        project = Project(groups=[group], stages=[Stage(id='a', level=2, group_id='g'),
                                                  Stage(id='b', level=1), Stage(id='c', level=3)])
        positions = arrange_stages(project, lambda _: (100, 50), lambda _: 600)
        self.assertLess(positions['b'][0], positions['a'][0])
        self.assertGreater(positions['c'][0], positions['a'][0] + 600)
        self.assertEqual(arrange_stages(project, lambda _: (100, 50), lambda _: 600), positions)

    def test_empty_and_invalid_sizes(self):
        self.assertEqual(arrange_stages(Project(groups=[Group(id='empty')]), lambda _: (1, 1)), {})
        with self.assertRaisesRegex(ValueError, 'Размер передела'):
            arrange_stages(Project(stages=[Stage()]), lambda _: (0, 12))

    def test_real_cards_with_long_names_and_buffer_do_not_overlap(self):
        from PySide6.QtWidgets import QApplication
        from flow_visualizer.gui import StageItem
        app = QApplication.instance() or QApplication([])
        group = Group(id='g', name='Длинное название участка производства')
        stages = [Stage(id='a', group_id='g', level=1, has_buffer=True,
                        name='Особенно длинное название производственного участка с дополнительным пояснением'),
                  Stage(id='b', group_id='g', level=1, name='Короткое название'),
                  Stage(id='c', level=2, name='Другой передел')]
        cards = {stage.id: StageItem(stage, {}, lambda: None) for stage in stages}
        positions = arrange_stages(Project(groups=[group], stages=stages),
                                   lambda stage: (cards[stage.id].WIDTH, cards[stage.id].height),
                                   lambda _: 280)
        self.assertGreaterEqual(positions['b'][1], positions['a'][1] + cards['a'].height + ROW_GAP)
        self.assertGreater(positions['c'][0], positions['a'][0] + cards['a'].WIDTH)
        self.assertGreater(cards['a'].header_height, cards['b'].header_height)
        self.assertIsNotNone(app)

    def test_horizontal_axis_centers_different_sizes(self):
        stages = [Stage(id='short', level=1), Stage(id='tall', level=2), Stage(id='medium', level=3)]
        dimensions = {'short': (100, 60), 'tall': (100, 200), 'medium': (100, 100)}
        pos = arrange_stages(Project(stages=stages), lambda stage: dimensions[stage.id])
        centers = [pos[stage.id][1] + dimensions[stage.id][1] / 2 for stage in stages]
        self.assertEqual(len(set(centers)), 1)
        self.assertLess(pos['short'][0] + 100, pos['tall'][0])

    def test_card_center_ignores_buffer_and_rows_do_not_overlap(self):
        group = Group(id='g', name='Цех')
        stages = [Stage(id='a', group_id='g', level=1), Stage(id='b', group_id='g', level=1),
                  Stage(id='c', group_id='g', level=2)]
        # a has an icon extending 30 above its visible 80-high card. The
        # vertical alignment anchor remains the visible card's center (40).
        dimensions = {'a': (104, 112, -2, -30, 40),
                      'b': (104, 84, -2, -2, 40),
                      'c': (104, 144, -2, -2, 70)}
        pos = arrange_stages(Project(groups=[group], stages=stages), lambda stage: dimensions[stage.id])
        self.assertEqual(pos['a'][1] + 40, pos['c'][1] + 70)
        a_bottom = pos['a'][1] + dimensions['a'][3] + dimensions['a'][1]
        b_top = pos['b'][1] + dimensions['b'][3]
        self.assertGreaterEqual(b_top - a_bottom, ROW_GAP)

    def test_buffer_does_not_shift_flow_axis_between_containers(self):
        stages = [Stage(id='a', level=1, has_buffer=True), Stage(id='b', level=2)]
        dimensions = {'a': (104, 112, -2, -30, 40), 'b': (104, 84, -2, -2, 40)}
        pos = arrange_stages(Project(stages=stages), lambda stage: dimensions[stage.id])
        self.assertEqual(pos['a'][1] + 40, pos['b'][1] + 40)

    def test_chain_respects_edges_over_insertion_and_levels(self):
        stages = [Stage(id='c', level=1), Stage(id='b', level=2), Stage(id='a', level=9)]
        edges = [Edge('a', 'b'), Edge('b', 'c')]
        project = Project(stages=stages, edges=edges)
        before_levels = [s.level for s in stages]
        pos = arrange_stages(project, lambda _: (260, 100))
        self.assertLess(pos['a'][0] + 260, pos['b'][0])
        self.assertLess(pos['b'][0] + 260, pos['c'][0])
        self.assertEqual([s.level for s in stages], before_levels)
        self.assertEqual(edges, project.edges)

    def test_branch_merge_in_group_with_mixed_sizes(self):
        group = Group(id='g', name='Группа')
        stages = [Stage(id='finish', group_id='g', level=1),
                  Stage(id='left', group_id='g', level=7),
                  Stage(id='right', group_id='g', level=None),
                  Stage(id='start', group_id='g', level=9)]
        edges = [Edge('start', 'left'), Edge('start', 'right'),
                 Edge('left', 'finish'), Edge('right', 'finish')]
        project = Project(groups=[group], stages=stages, edges=edges)
        sizes = {'start': (320, 220), 'left': (200, 90), 'right': (270, 310), 'finish': (180, 170)}
        pos = arrange_stages(project, lambda s: sizes[s.id])
        for edge in edges:
            self.assertLess(pos[edge.source][0] + sizes[edge.source][0], pos[edge.target][0])
        for i, a in enumerate(stages):
            for b in stages[i + 1:]:
                ax, ay = pos[a.id]; bx, by = pos[b.id]
                aw, ah = sizes[a.id]; bw, bh = sizes[b.id]
                self.assertFalse(ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah)

    def test_intergroup_and_single_member_group_order(self):
        groups = [Group(id='g1', name='Один'), Group(id='g2', name='Два')]
        stages = [Stage(id='end', level=1), Stage(id='b', group_id='g2', level=2),
                  Stage(id='a', group_id='g1', level=8), Stage(id='other', group_id='g2', level=2)]
        edges = [Edge('a', 'b'), Edge('b', 'end')]
        project = Project(groups=groups, stages=stages, edges=edges)
        pos = arrange_stages(project, lambda _: (100, 50))
        self.assertLess(pos['a'][0] + 100, pos['b'][0])
        self.assertLess(max(pos['b'][0], pos['other'][0]) + 100, pos['end'][0])
        self.assertEqual([stage.level for stage in stages], [1, 2, 8, 2])

    def test_cycles_preserve_edges_and_original_coordinates(self):
        stages = [Stage(id='a', x=10, y=20), Stage(id='b', x=30, y=40)]
        cyclic = Project(stages=stages, edges=[Edge('a', 'b'), Edge('b', 'a')])
        result = arrange_stages(cyclic, lambda _: (100, 50))
        self.assertNotEqual(result['a'][0], result['b'][0])
        self.assertEqual(len(cyclic.edges), 2)
        self.assertEqual([(s.x, s.y) for s in stages], [(10, 20), (30, 40)])
        self.assertIn('self', arrange_stages(Project(stages=[Stage(id='self')],
                                                     edges=[Edge('self', 'self')]), lambda _: (100, 50)))
        g1, g2 = Group(id='g1'), Group(id='g2')
        mixed = [Stage(id='a1', group_id='g1'), Stage(id='a2', group_id='g1'),
                 Stage(id='b1', group_id='g2'), Stage(id='b2', group_id='g2')]
        # The stage graph has no cycle, but a single contiguous box per group
        # cannot satisfy both directions: one original edge is necessarily backward.
        conflict = Project(groups=[g1, g2], stages=mixed, edges=[Edge('a1', 'b1'), Edge('b2', 'a2')])
        pos = arrange_stages(conflict, lambda _: (100, 50))
        g1_right = max(pos['a1'][0], pos['a2'][0]) + 100
        g2_right = max(pos['b1'][0], pos['b2'][0]) + 100
        self.assertTrue(g1_right < min(pos['b1'][0], pos['b2'][0])
                        or g2_right < min(pos['a1'][0], pos['a2'][0]))
        forward = [pos[e.source][0] + 100 < pos[e.target][0] for e in conflict.edges]
        self.assertEqual(sum(forward), 1)
        self.assertTrue(all(s.x is None and s.y is None for s in mixed))
        self.assertEqual(len(conflict.edges), 2)

    def test_three_node_cycle_keeps_causal_order_and_dag_neighbors(self):
        stages = [Stage(id='down', level=5), Stage(id='c', level=3),
                  Stage(id='b', level=2), Stage(id='a', level=1), Stage(id='up', level=9)]
        edges = [Edge('up', 'a'), Edge('a', 'b'), Edge('b', 'c'), Edge('c', 'a'), Edge('c', 'down')]
        project = Project(stages=stages, edges=edges)
        pos = arrange_stages(project, lambda _: (100, 50))
        for src, dst in [('up', 'a'), ('a', 'b'), ('b', 'c'), ('c', 'down')]:
            self.assertLess(pos[src][0] + 100, pos[dst][0])
        self.assertGreater(pos['c'][0], pos['a'][0])  # C -> A remains an actual backward edge.
        self.assertEqual(edges, project.edges)
        self.assertEqual(pos, arrange_stages(project, lambda _: (100, 50)))

    def test_cycle_inside_group_with_external_dag(self):
        group = Group(id='g', name='Цех')
        stages = [Stage(id='c', group_id='g', level=3), Stage(id='up', level=9),
                  Stage(id='b', group_id='g', level=2), Stage(id='a', group_id='g', level=1),
                  Stage(id='down', level=1)]
        edges = [Edge('up', 'a'), Edge('a', 'b'), Edge('b', 'c'), Edge('c', 'a'), Edge('c', 'down')]
        pos = arrange_stages(Project(groups=[group], stages=stages, edges=edges), lambda _: (150, 50))
        for src, dst in [('up', 'a'), ('a', 'b'), ('b', 'c'), ('c', 'down')]:
            self.assertLess(pos[src][0] + 150, pos[dst][0])
        self.assertGreater(pos['c'][0], pos['a'][0])

    def test_invalid_and_duplicate_edges_are_handled(self):
        project = Project(stages=[Stage(id='a'), Stage(id='b')],
                          edges=[Edge('a', 'b'), Edge('a', 'b')])
        pos = arrange_stages(project, lambda _: (100, 50))
        self.assertLess(pos['a'][0] + 100, pos['b'][0])
        project.edges.append(Edge('b', 'absent'))
        with self.assertRaisesRegex(LayoutError, 'отсутствующий передел'):
            arrange_stages(project, lambda _: (100, 50))


if __name__ == '__main__':
    unittest.main()
