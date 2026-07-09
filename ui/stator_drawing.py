"""Stator winding cross-section widget (formerly ``StatorDrawing.py``)."""

import math
from fractions import Fraction

from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QWidget

from utils.constants import DEFAULT_NUM_SLOTS, PHASE_COUNT

PHASE_COLORS = {
    'A': QColor(255, 0, 0),   # Red
    'B': QColor(0, 0, 255),   # Blue
    'C': QColor(0, 255, 0),   # Green
}

# Drawing geometry (pixels / degrees).
SLOT_ARC_WIDTH_DEG = 3
SYMBOL_SIZE_PX = 12
LEGEND_SYMBOL_SIZE_PX = 22
LEGEND_ROW_SPACING_PX = 25
DOUBLE_LAYER_ARC_OFFSET_PX = 33
SINGLE_LAYER_ARC_OFFSET_PX = 15


class StatorDrawing(QWidget):
    """Draws the stator slots and the per-slot winding phase symbols."""

    def __init__(self):
        super().__init__()
        self.slots = DEFAULT_NUM_SLOTS
        self.poles = 4  # actual poles (pole pairs × 2)
        self.coil_span = 6
        self.is_double_layer = True
        self.setMinimumSize(400, 400)
        self.winding_pattern = self.calculate_winding_pattern()

    def update_parameters(self, slots, poles, coil_span, is_double_layer):
        """Update configuration and recompute the winding pattern."""
        self.slots = slots
        self.poles = poles
        self.coil_span = coil_span
        self.is_double_layer = is_double_layer
        self.winding_pattern = self.calculate_winding_pattern()
        self.update()

    def save_drawing(self, filename):
        """Render the widget to an image file."""
        pixmap = QPixmap(self.size())
        self.render(pixmap)
        pixmap.save(filename)

    # ------------------------------------------------------ winding pattern

    def calculate_winding_pattern(self):
        """Per-slot (top_phase, bottom_phase) tuples.

        Fractional-slot single layer windings use unequal coil groups;
        otherwise phases follow the 120° electrical-angle zones.
        """
        q = Fraction(self.slots, PHASE_COUNT * self.poles)

        if not self.is_double_layer and q.denominator > 1:
            return self._fractional_single_layer_pattern(q)
        return self._zone_based_pattern()

    def _fractional_single_layer_pattern(self, q):
        q_float = float(q)
        floor_q = math.floor(q_float)
        ceil_q = math.ceil(q_float)
        group_sizes = [floor_q, floor_q, ceil_q, ceil_q]
        phase_sequence = ('A', 'C', 'B')

        pattern = []
        slot = 0
        phase_idx = 0
        while slot < self.slots:
            for _ in range(group_sizes[phase_idx % len(group_sizes)]):
                if slot >= self.slots:
                    break
                pattern.append((phase_sequence[phase_idx % 3], None))
                slot += 1
            phase_idx += 1
        return pattern

    def _zone_based_pattern(self):
        slots_per_pole = self.slots / self.poles
        pattern = []

        for slot in range(self.slots):
            top_phase = self._phase_for_slot(slot, slots_per_pole)
            if self.is_double_layer:
                span = self.slots - self.coil_span
                bottom_slot = (slot + span) % self.slots
                bottom_phase = self._phase_for_slot(bottom_slot, slots_per_pole)
                pattern.append((top_phase, bottom_phase))
            else:
                pattern.append((top_phase, None))
        return pattern

    @staticmethod
    def _phase_for_slot(slot, slots_per_pole):
        """Phase of a slot from its electrical angle (120° zones: A, C, B)."""
        angle_per_slot = 360 / slots_per_pole
        electrical_angle = (slot * angle_per_slot) % 360

        if electrical_angle < 120:
            return 'A'
        if electrical_angle < 240:
            return 'C'
        return 'B'

    # --------------------------------------------------------------- painting

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        center = QPoint(self.width() // 2, self.height() // 2)
        radius = min(self.width(), self.height()) // 2 - 20
        inner_radius = radius * 0.65

        painter.setPen(QPen(Qt.black, 2))
        painter.drawEllipse(center, radius, radius)

        for slot in range(self.slots):
            self._draw_slot(painter, slot, center, inner_radius)
            self._draw_slot_winding(painter, slot, center, inner_radius, radius)

        painter.setPen(Qt.black)
        painter.setFont(QFont("Arial", 12, QFont.Bold))
        title_rect = QRect(center.x() - 150, center.y() - 10, 300, 20)
        painter.drawText(title_rect, Qt.AlignCenter, "STATOR WINDING")

        self._draw_legend(painter)

    def _draw_slot(self, painter, slot, center, inner_radius):
        """Draw one slot opening, the tooth arc to the next slot, the slot
        side lines, and the slot number."""
        slot_angle = 360 / self.slots
        angle_deg = -slot * slot_angle  # negative = counterclockwise

        if self.is_double_layer:
            arc_radius = int(inner_radius) + DOUBLE_LAYER_ARC_OFFSET_PX
        else:
            arc_radius = int(inner_radius) + SINGLE_LAYER_ARC_OFFSET_PX

        painter.setPen(QPen(Qt.black, 2))

        # Slot opening arc (Qt arcs use 1/16th-degree units).
        arc_start = (angle_deg - SLOT_ARC_WIDTH_DEG / 2) * 16
        arc_span = SLOT_ARC_WIDTH_DEG * 16
        slot_rect = QRect(center.x() - arc_radius, center.y() - arc_radius,
                          arc_radius * 2, arc_radius * 2)
        painter.drawArc(slot_rect, int(arc_start), int(arc_span))

        # Tooth arc between this slot and the next.
        tooth_radius = int(inner_radius) - 4
        tooth_start = (angle_deg + SLOT_ARC_WIDTH_DEG / 2) * 16
        tooth_span = (slot_angle - SLOT_ARC_WIDTH_DEG) * 16
        tooth_rect = QRect(center.x() - tooth_radius, center.y() - tooth_radius,
                           tooth_radius * 2, tooth_radius * 2)
        painter.drawArc(tooth_rect, int(tooth_start), int(tooth_span))

        # Radial side lines connecting slot arc and tooth arc.
        for side in (-1, 1):
            side_angle = math.radians(angle_deg + side * SLOT_ARC_WIDTH_DEG / 2)
            x1 = center.x() + tooth_radius * math.cos(side_angle)
            y1 = center.y() + tooth_radius * math.sin(side_angle)
            x2 = center.x() + arc_radius * math.cos(side_angle)
            y2 = center.y() + arc_radius * math.sin(side_angle)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        # Slot number outside the slot arc.
        number_radius = arc_radius + 20
        number_angle = math.radians(angle_deg)
        nx = center.x() + number_radius * math.cos(number_angle)
        ny = center.y() + number_radius * math.sin(number_angle)
        painter.setPen(Qt.black)
        painter.setFont(QFont("Arial", 10))
        painter.drawText(int(nx) - 8, int(ny) + 4, str(slot + 1))

    def _draw_slot_winding(self, painter, slot, center, inner_radius, outer_radius):
        """Draw the phase symbol(s) inside one slot."""
        if slot >= len(self.winding_pattern):
            return

        angle_rad = math.radians(-360 / self.slots * slot)
        top_phase, bottom_phase = self.winding_pattern[slot]

        if self.is_double_layer:
            bottom_r = (inner_radius + outer_radius) * 0.43
            top_r = (inner_radius + outer_radius) * 0.4
            if bottom_phase:
                self._draw_symbol(painter, center, bottom_r, angle_rad, bottom_phase)
            if top_phase:
                self._draw_symbol(painter, center, top_r, angle_rad, top_phase)
        elif top_phase:
            r = (inner_radius + outer_radius) * 0.4
            self._draw_symbol(painter, center, r, angle_rad, top_phase)

    @staticmethod
    def _draw_symbol(painter, center, r, angle_rad, phase):
        x = center.x() + r * math.cos(angle_rad)
        y = center.y() + r * math.sin(angle_rad)

        painter.setPen(Qt.NoPen)
        painter.setBrush(PHASE_COLORS[phase])
        painter.drawEllipse(int(x - SYMBOL_SIZE_PX / 2),
                            int(y - SYMBOL_SIZE_PX / 2),
                            SYMBOL_SIZE_PX, SYMBOL_SIZE_PX)

    def _draw_legend(self, painter):
        legend_x = self.width() - 120
        legend_y = 20

        painter.setPen(QPen(Qt.black))
        for i, phase in enumerate(('A', 'B', 'C')):
            painter.setBrush(PHASE_COLORS[phase])
            painter.drawEllipse(legend_x, legend_y + i * LEGEND_ROW_SPACING_PX,
                                LEGEND_SYMBOL_SIZE_PX, LEGEND_SYMBOL_SIZE_PX)
            painter.setPen(QPen(Qt.black))
            painter.drawText(
                legend_x + LEGEND_SYMBOL_SIZE_PX + 5,
                legend_y + i * LEGEND_ROW_SPACING_PX + LEGEND_SYMBOL_SIZE_PX - 2,
                f"Phase {phase}")
