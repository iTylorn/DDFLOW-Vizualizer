import unittest

from PySide6.QtCore import QPointF, QRectF

from flow_visualizer.alignment_snap import constrain_movement, snap_to_alignment
from flow_visualizer.selection_alignment import STANDARD_HORIZONTAL_GAP


class AlignmentSnapTests(unittest.TestCase):
    def test_horizontal_clearance_leaves_room_for_arrows_without_widening_vertical_spacing(self):
        fixed = QRectF(0, 0, 100, 50)
        horizontal = QRectF(300, 0, 100, 50)
        delta = constrain_movement(horizontal, QRectF(50, 0, 100, 50), [fixed],
                                   gap=24, horizontal_gap=STANDARD_HORIZONTAL_GAP)
        self.assertAlmostEqual(horizontal.translated(delta).left() - fixed.right(), STANDARD_HORIZONTAL_GAP, places=5)
        vertical = QRectF(0, 200, 100, 50)
        delta = constrain_movement(vertical, QRectF(0, 10, 100, 50), [fixed],
                                   gap=24, horizontal_gap=STANDARD_HORIZONTAL_GAP)
        self.assertAlmostEqual(vertical.translated(delta).top() - fixed.bottom(), 24, places=5)

    def test_left_edges_align_without_moving_vertical_axis(self):
        moving = QRectF(4, 100, 50, 50)
        other = QRectF(0, 0, 50, 50)
        delta, guides = snap_to_alignment(moving, [other], 1.0)
        self.assertEqual(delta, QPointF(-4, 0))
        self.assertEqual(len(guides), 1)
        self.assertEqual(guides[0].x1(), guides[0].x2())
        self.assertEqual(moving, QRectF(4, 100, 50, 50), 'snap must not mutate its input')

    def test_top_edges_align_across_columns(self):
        moving = QRectF(0, 3, 100, 50)
        delta, guides = snap_to_alignment(moving, [QRectF(180, 0, 100, 50)], 1.0)
        self.assertEqual(delta, QPointF(0, -3))
        self.assertEqual(len(guides), 1)
        self.assertEqual(guides[0].y1(), guides[0].y2())

    def test_tolerance_is_in_viewport_pixels(self):
        moving = QRectF(0, 7, 100, 50)
        neighbors = [QRectF(180, 0, 100, 50)]
        self.assertEqual(snap_to_alignment(moving, neighbors, 1.0)[0], QPointF(0, -7))
        self.assertEqual(snap_to_alignment(moving, neighbors, 2.0)[0], QPointF(0, 0))
        self.assertEqual(snap_to_alignment(moving, neighbors, 0.5, 3)[0], QPointF(0, 0))

    def test_snap_never_introduces_a_new_collision(self):
        moving = QRectF(0, 70, 100, 20)
        neighbors = [QRectF(4, 0, 100, 20), QRectF(101, 70, 20, 20)]
        delta, _ = snap_to_alignment(moving, neighbors, 1.0)
        shifted = moving.translated(delta)
        self.assertFalse(shifted.intersects(neighbors[0]))
        self.assertFalse(shifted.intersects(neighbors[1]))
        self.assertEqual(delta.x(), 0)

    def test_snap_never_worsens_an_existing_overlap(self):
        moving, other = QRectF(99, 0, 10, 50), QRectF(0, 0, 100, 50)
        delta, _ = snap_to_alignment(moving, [other], 1.0)
        before = moving.intersected(other).width() * moving.intersected(other).height()
        after_rect = moving.translated(delta).intersected(other)
        self.assertLessEqual(after_rect.width() * after_rect.height(), before)

    def test_collision_bounds_include_icon_above_card(self):
        card = QRectF(0, 100, 100, 40)
        icon_and_card = QRectF(0, 70, 100, 70)
        neighbor = QRectF(3, 0, 100, 40)
        second = QRectF(101, 75, 30, 25)
        delta, _ = snap_to_alignment(card, [neighbor, second], 1.0,
                                     moving_bounds=icon_and_card,
                                     other_bounds=[neighbor, second])
        self.assertFalse(icon_and_card.translated(delta).intersects(second))
        self.assertEqual(delta.x(), 0)

    def test_adjacent_edges_snap_with_small_screen_gap(self):
        neighbor = QRectF(0, 0, 100, 50)
        moving = QRectF(100 + STANDARD_HORIZONTAL_GAP + 3, 0, 80, 50)
        delta, guides = snap_to_alignment(moving, [neighbor], 1)
        self.assertAlmostEqual(moving.translated(delta).left(), neighbor.right() + STANDARD_HORIZONTAL_GAP)
        self.assertTrue(any(abs(line.x1() - line.x2()) < 1e-8 for line in guides))
        below = QRectF(0, 77, 100, 50)
        delta, guides = snap_to_alignment(below, [neighbor], 1)
        self.assertAlmostEqual(below.translated(delta).top(), neighbor.bottom() + 24)
        self.assertTrue(any(abs(line.y1() - line.y2()) < 1e-8 for line in guides))
        zoomed = QRectF(100 + STANDARD_HORIZONTAL_GAP + 3, 0, 80, 50)
        delta, _ = snap_to_alignment(zoomed, [neighbor], 2)
        self.assertAlmostEqual(zoomed.translated(delta).left(), neighbor.right() + STANDARD_HORIZONTAL_GAP)

    def test_adjacent_gap_uses_full_bounds_including_buffer_and_cross_alignment(self):
        neighbor = QRectF(0, 0, 100, 50)
        neighbor_bounds = QRectF(-2, -2, 104, 54)
        # Card has a 31-unit-high buffer above it. The 24-unit gap is
        # measured to that full visual extent, not to the card's body.
        moving_card = QRectF(2, 110, 100, 50)
        moving_bounds = QRectF(0, 79, 104, 83)
        delta, guides = snap_to_alignment(moving_card, [neighbor], 1,
                                          moving_bounds=moving_bounds,
                                          other_bounds=[neighbor_bounds])
        moved = moving_bounds.translated(delta)
        self.assertAlmostEqual(moved.top() - neighbor_bounds.bottom(), 24)
        self.assertEqual(len(guides), 2, 'adjacency plus horizontal alignment')
        self.assertAlmostEqual(moving_card.translated(delta).left(), neighbor.left())

    def test_collision_safety_clamps_a_drag_even_without_snap(self):
        # Direct calls model either Alt or disabled snapping. Fast jumps must
        # not pass through another card simply because their final point is clear.
        source = QRectF(0, 0, 50, 50)
        other = QRectF(100, 0, 50, 50)
        for proposed in (QRectF(80, 0, 50, 50), QRectF(200, 0, 50, 50)):
            delta = constrain_movement(source, proposed, [other])
            self.assertAlmostEqual(delta.x(), 50, places=5)
            self.assertFalse(source.translated(delta).intersects(other))
        vertical = constrain_movement(source, QRectF(0, 200, 50, 50), [QRectF(0, 100, 50, 50)])
        self.assertAlmostEqual(vertical.y(), 50, places=5)
        around = constrain_movement(source, QRectF(0, 200, 50, 50), [other])
        self.assertEqual(around, QPointF(0, 200))

    def test_fast_drag_stops_at_magnetic_gap_independent_of_target(self):
        fixed = QRectF(60, 90, 230, 74)
        moving = QRectF(420, 90, 230, 74)
        for x in (280, 60, -400):
            delta = constrain_movement(moving, QRectF(x, 90, 230, 74), [fixed], gap=24)
            self.assertAlmostEqual(moving.translated(delta).left() - fixed.right(), 24, places=5)
        # Without magnetism the same fast move stops at contact, still safe.
        delta = constrain_movement(moving, QRectF(60, 90, 230, 74), [fixed], gap=0)
        self.assertAlmostEqual(moving.translated(delta).left() - fixed.right(), 0, places=5)

    def test_fast_contact_can_then_align_the_orthogonal_axis(self):
        fixed = QRectF(60, 90, 230, 74)
        moving = QRectF(420, 95, 230, 74)
        # First constrain the pointer's fast overshoot, then align the safe
        # preview; doing these in the opposite order would reject alignment
        # because the raw proposal itself intersects the fixed card.
        safe = constrain_movement(moving, QRectF(60, 95, 230, 74), [fixed], gap=24)
        preview = moving.translated(safe)
        snap, guides = snap_to_alignment(preview, [fixed], 1)
        final = moving.translated(constrain_movement(moving, preview.translated(snap), [fixed], gap=24))
        self.assertAlmostEqual(final.left() - fixed.right(), 24, places=5)
        self.assertAlmostEqual(final.top(), fixed.top(), places=5)
        self.assertGreaterEqual(len(guides), 1)

    def test_vertical_fast_drag_and_existing_close_gap(self):
        fixed = QRectF(0, 0, 100, 50)
        moving = QRectF(0, 150, 100, 50)
        delta = constrain_movement(moving, QRectF(0, -100, 100, 50), [fixed], gap=24)
        self.assertAlmostEqual(moving.translated(delta).top() - fixed.bottom(), 24, places=5)
        already_close = QRectF(0, 55, 100, 50)
        self.assertEqual(constrain_movement(already_close, QRectF(0, 51, 100, 50), [fixed], gap=24), QPointF())
        self.assertEqual(constrain_movement(already_close, QRectF(0, 80, 100, 50), [fixed], gap=24), QPointF(0, 25))
        # Legacy actual overlaps can still be resolved even in magnetic mode.
        overlap = QRectF(0, 45, 100, 50)
        self.assertEqual(constrain_movement(overlap, QRectF(0, 100, 100, 50), [fixed], gap=24), QPointF(0, 55))

    def test_existing_overlap_may_be_resolved_but_not_worsened_or_crossed(self):
        source, other = QRectF(85, 0, 50, 50), QRectF(100, 0, 50, 50)
        self.assertEqual(constrain_movement(source, QRectF(70, 0, 50, 50), [other]), QPointF(-15, 0))
        self.assertEqual(constrain_movement(source, QRectF(85, 60, 50, 50), [other]), QPointF(0, 60))
        self.assertEqual(constrain_movement(source, QRectF(100, 0, 50, 50), [other]), QPointF())
        self.assertEqual(constrain_movement(source, QRectF(170, 0, 50, 50), [other]), QPointF())

    def test_contact_allows_sliding_and_buffer_collision_is_respected(self):
        moving = QRectF(50, 0, 50, 50)
        other = QRectF(100, 0, 50, 50)
        self.assertEqual(constrain_movement(moving, QRectF(50, 100, 50, 50), [other]), QPointF(0, 100))
        # Full bounds include the icon protruding above the visible card.
        with_icon = QRectF(0, 20, 60, 80)
        other_card = QRectF(0, 0, 60, 10)
        self.assertAlmostEqual(constrain_movement(with_icon, QRectF(0, -10, 60, 80), [other_card]).y(), -10, places=5)

    def test_empty_invalid_and_large_diagram(self):
        self.assertEqual(snap_to_alignment(QRectF(0, 0, 10, 10), [], 1.0), (QPointF(), []))
        with self.assertRaises(ValueError):
            snap_to_alignment(QRectF(0, 0, 10, 10), [QRectF(20, 0, 10, 10)], 0)
        with self.assertRaises(ValueError):
            snap_to_alignment(QRectF(0, 0, 10, 10), [QRectF(20, 0, 10, 10)], 1,
                              other_bounds=[])
        neighbors = [QRectF(i * 200, (i % 5) * 120, 80, 60) for i in range(1, 1001)]
        delta, guides = snap_to_alignment(QRectF(0, 1, 80, 60), neighbors, 1)
        self.assertEqual(delta.y(), -1)
        self.assertTrue(guides)


if __name__ == '__main__':
    unittest.main()
