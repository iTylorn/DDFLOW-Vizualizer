import unittest
from copy import deepcopy

from flow_visualizer.gentle_layout import MIN_GAP, compact_existing
from flow_visualizer.selection_alignment import STANDARD_HORIZONTAL_GAP
from flow_visualizer.model import Edge, Group, Project, Stage


class GentleLayoutTests(unittest.TestCase):
    def setUp(self):
        self.measure = lambda stage: (100, 80)

    def test_only_empty_horizontal_strips_shrink(self):
        stages = [Stage(id='a', x=0, y=10), Stage(id='b', x=400, y=10),
                  Stage(id='c', x=800, y=10)]
        project = Project(stages=stages, edges=[Edge('a', 'b'), Edge('b', 'c'), Edge('c', 'a')])
        before = deepcopy(project)
        pos = compact_existing(project, self.measure)
        self.assertEqual(pos['a'], (0, 10))
        self.assertEqual(pos['b'], (100 + STANDARD_HORIZONTAL_GAP, 10))
        self.assertEqual(pos['c'], (2 * (100 + STANDARD_HORIZONTAL_GAP), 10))
        self.assertEqual(project, before)

    def test_narrow_link_gap_expands_without_rearranging_other_rows(self):
        stages = [Stage(id='a', x=0, y=0), Stage(id='b', x=124, y=0),
                  Stage(id='c', x=124, y=120)]
        edge = Edge('a', 'b', routes={'compact': [[112, 30]]})
        pos = compact_existing(Project(stages=stages, edges=[edge]), self.measure)
        self.assertEqual(pos['a'], (0, 0))
        self.assertEqual(pos['b'], (100 + STANDARD_HORIZONTAL_GAP, 0))
        self.assertEqual(pos['c'], (100 + STANDARD_HORIZONTAL_GAP, 120))
        self.assertGreater(pos.transform_point(112, 30)[0], 100)
        self.assertLess(pos.transform_point(112, 30)[0], pos['b'][0])
        plain = compact_existing(Project(stages=stages), self.measure)
        self.assertEqual(plain['b'], (100 + STANDARD_HORIZONTAL_GAP, 0))

    def test_mixed_short_and_long_gaps_equal_without_connections(self):
        stages = [Stage(id='a', x=0, y=0), Stage(id='b', x=120, y=60),
                  Stage(id='c', x=380, y=0), Stage(id='d', x=480, y=90)]
        pos = compact_existing(Project(stages=stages), self.measure)
        self.assertEqual([pos[s.id][0] for s in stages],
                         [0, 100 + STANDARD_HORIZONTAL_GAP, 2 * (100 + STANDARD_HORIZONTAL_GAP),
                          3 * (100 + STANDARD_HORIZONTAL_GAP)])
        self.assertEqual([pos[s.id][1] for s in stages], [0, 60, 0, 90])
        for stage in stages:
            stage.x, stage.y = pos[stage.id]
        self.assertEqual(compact_existing(Project(stages=stages), self.measure), pos)

    def test_group_frame_to_group_frame_uses_the_same_gap(self):
        groups = [Group(id='a', name='Цех 1'), Group(id='b', name='Цех 2')]
        stages = [Stage(id='a1', group_id='a', x=0, y=0),
                  Stage(id='a2', group_id='a', x=0, y=90),
                  Stage(id='b1', group_id='b', x=150, y=30)]
        pos = compact_existing(Project(stages=stages, groups=groups), self.measure)
        self.assertEqual(pos['a1'][0], pos['a2'][0])
        self.assertAlmostEqual((pos['b1'][0] - 20) - (pos['a1'][0] + 100 + 20), STANDARD_HORIZONTAL_GAP)

    def test_vertical_whitespace_shrinks_without_reordering(self):
        stages = [Stage(id='a', x=0, y=10), Stage(id='b', x=0, y=400)]
        pos = compact_existing(Project(stages=stages), self.measure)
        self.assertEqual(pos['a'], (0, 10))
        self.assertEqual(pos['b'], (0, 10 + 80 + MIN_GAP))

    def test_already_compact_and_crossing_grid_do_not_move(self):
        stages = [Stage(id='a', x=0, y=0), Stage(id='b', x=100 + STANDARD_HORIZONTAL_GAP, y=0),
                  Stage(id='c', x=0, y=120), Stage(id='d', x=100 + STANDARD_HORIZONTAL_GAP, y=120)]
        pos = compact_existing(Project(stages=stages), self.measure)
        self.assertEqual(pos, {s.id: (s.x, s.y) for s in stages})

    def test_staggered_composition_is_not_rebuilt(self):
        # Overlapping projections leave no fully empty strip on either axis.
        stages = [Stage(id='a', x=0, y=0), Stage(id='b', x=90, y=70),
                  Stage(id='c', x=180, y=140)]
        pos = compact_existing(Project(stages=stages), self.measure)
        self.assertEqual(pos, {s.id: (s.x, s.y) for s in stages})

    def test_group_interior_is_not_a_solid_obstacle(self):
        group = Group(id='g', name='Цех')
        stages = [Stage(id='a', group_id='g', x=0, y=0), Stage(id='b', group_id='g', x=500, y=0)]
        project = Project(stages=stages, groups=[group], edges=[Edge('a', 'b'), Edge('b', 'a')])
        pos = compact_existing(project, self.measure, lambda _: 32)
        self.assertLess(pos['b'][0] - pos['a'][0], 500)
        self.assertGreater(pos['b'][0], pos['a'][0] + 100)
        self.assertEqual(len(project.edges), 2)

    def test_long_group_title_buffer_and_cross_group_order(self):
        groups = [Group(id='g1', name='Длинное название производственного подразделения'),
                  Group(id='g2', name='Цех 2')]
        stages = [Stage(id='a', group_id='g1', x=100, y=100, has_buffer=True),
                  Stage(id='b', group_id='g1', x=100, y=400),
                  Stage(id='c', group_id='g2', x=1000, y=100)]
        project = Project(stages=stages, groups=groups, edges=[Edge('a', 'c'), Edge('c', 'a')])
        measure = lambda stage: (104, 112, -2, -30, 40) if stage.has_buffer else (104, 84, -2, -2, 40)
        pos = compact_existing(project, measure, lambda group: 350 if group.id == 'g1' else 60)
        self.assertEqual(pos['a'][0], pos['b'][0])
        self.assertLess(pos['a'][1], pos['b'][1])
        self.assertLess(pos['a'][0], pos['c'][0])
        self.assertLess(pos['b'][1] - pos['a'][1], 300)

    def test_transform_preserves_manual_route_and_is_idempotent(self):
        stages = [Stage(id='a', x=0, y=0), Stage(id='b', x=400, y=0)]
        edge = Edge('a', 'b', routes={'compact': [[250, 25]], 'detailed': [[200, 30]]})
        project = Project(stages=stages, edges=[edge])
        before = deepcopy(project)
        pos = compact_existing(project, self.measure)
        point = pos.transform_point(*edge.routes['compact'][0])
        self.assertGreater(point[0], pos['a'][0] + 100)
        self.assertLess(point[0], pos['b'][0])
        self.assertEqual(point[1], 25)
        self.assertEqual(project, before)
        for stage in stages:
            stage.x, stage.y = pos[stage.id]
        second = compact_existing(project, self.measure)
        self.assertEqual(second, pos)
        self.assertEqual(second.transform_point(*point), point)

    def test_invalid_geometry_does_not_mutate(self):
        project = Project(stages=[Stage(id='a', x=None, y=0)])
        before = deepcopy(project)
        with self.assertRaisesRegex(ValueError, 'положение'):
            compact_existing(project, self.measure)
        self.assertEqual(project, before)



if __name__ == '__main__':
    unittest.main()
