"""Stator winding cross-section widget (formerly ``StatorDrawing.py``)."""

import math

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QToolTip, QWidget

from core.connection_matrix import (build_winding_connection_matrix,
                                     phase_pattern_from_matrix)
from utils.constants import DEFAULT_NUM_SLOTS

PHASE_COLORS = {
    'A': QColor('#df4856'),
    'B': QColor('#3277cf'),
    'C': QColor('#159b75'),
}


class StatorDrawing(QWidget):
    """Draws the stator slots and the per-slot winding phase symbols."""

    def __init__(self):
        super().__init__()
        self.slots = DEFAULT_NUM_SLOTS
        self.poles = 4  # actual poles (pole pairs × 2)
        self.coil_span = 6
        self.is_double_layer = True
        self.setMinimumSize(400, 400)
        self.setMouseTracking(True)
        self._hovered_slot = None
        self.winding_pattern = self.calculate_winding_pattern()

    def update_parameters(self, slots, poles, coil_span, is_double_layer):
        """Update configuration and recompute the winding pattern."""
        self.slots = slots
        self.poles = poles
        self.coil_span = coil_span
        self.is_double_layer = is_double_layer
        self._hovered_slot = None
        QToolTip.hideText()
        self.winding_pattern = self.calculate_winding_pattern()
        self.update()

    def save_drawing(self, filename):
        """Render the widget to an image file."""
        pixmap = QPixmap(self.size())
        self.render(pixmap)
        pixmap.save(filename)

    # ------------------------------------------------------ winding pattern

    def calculate_winding_pattern(self):
        """Use the same signed coil topology as the calculation engine."""
        try:
            self.winding_matrix = build_winding_connection_matrix(
                self.slots, self.poles, self.is_double_layer, self.coil_span)
            self.winding_error = None
            return phase_pattern_from_matrix(self.winding_matrix)
        except ValueError as error:
            self.winding_matrix = None
            self.winding_error = str(error)
            # Retain the machine/slot drawing while showing no invented
            # coil phases. The MMF engine reports the same physical error.
            return [(None, None)] * self.slots

    # --------------------------------------------------------------- painting

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.fillRect(self.rect(), Qt.white)
        center, radius = self._drawing_geometry()
        bore = radius * 0.59
        steel = QPainterPath()
        steel.addEllipse(center, radius, radius)
        steel.addEllipse(center, bore, bore)
        steel.setFillRule(Qt.OddEvenFill)
        painter.setPen(QPen(QColor('#7d8c9e'), 1.2))
        painter.setBrush(QColor('#e8edf3'))
        painter.drawPath(steel)

        slot_shape = self._slot_shape(radius)
        body_width = self._slot_width(radius)
        marker_radius = min(9.0, body_width * 0.36, radius * 0.042)
        for slot in range(self.slots):
            painter.save()
            painter.translate(center)
            painter.rotate(-360 * slot / self.slots)
            hovered = slot == self._hovered_slot
            painter.fillPath(slot_shape, QColor('#edf4ff') if hovered else Qt.white)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor('#4f8cff') if hovered else QColor('#7d8c9e'),
                                1.7 if hovered else 0.9))
            # The slot mouth opens into the bore. Its outline has no end cap.
            painter.drawPath(slot_shape)
            if self.winding_matrix is not None:
                fractions = (0.38, 0.75) if self.is_double_layer else (0.56,)
                for layer, fraction in enumerate(fractions):
                    phase, sign = self._coil_side(slot, layer)
                    position = QPointF(bore + radius * 0.25 * fraction, 0)
                    self._draw_conductor(painter, position, marker_radius,
                                         PHASE_COLORS[phase], sign,
                                         orientation=360 * slot / self.slots)
            painter.restore()
            self._draw_slot_number(painter, center, radius, slot)

        self._draw_center_label(painter, center, bore)
        self._draw_legend(painter)

    def _drawing_geometry(self):
        center = QPointF(self.width() / 2, (self.height() - 4) / 2)
        radius = max(20.0, min((self.width() - 84) / 2,
                               (self.height() - 134) / 2))
        return center, radius

    def _slot_width(self, radius):
        return 2 * radius * 0.72 * math.sin(math.radians(360 / self.slots * 0.28))

    def _slot_shape(self, radius):
        """An open slot with a narrow mouth, shoulders and rounded back."""
        bore, back = radius * 0.59, radius * 0.84
        width = self._slot_width(radius)
        mouth = width * 0.40
        tip, shoulder = bore + radius * 0.026, bore + radius * 0.055
        corner = min(width * 0.24, radius * 0.018)
        path = QPainterPath(QPointF(bore - 1.0, -mouth / 2))
        path.lineTo(tip, -mouth / 2)
        path.lineTo(shoulder, -width / 2)
        path.lineTo(back - corner, -width / 2)
        path.quadTo(back, -width / 2, back, -width / 2 + corner)
        path.lineTo(back, width / 2 - corner)
        path.quadTo(back, width / 2, back - corner, width / 2)
        path.lineTo(shoulder, width / 2)
        path.lineTo(tip, mouth / 2)
        path.lineTo(bore - 1.0, mouth / 2)
        return path

    def _coil_side(self, slot, layer):
        rows = self.winding_matrix[layer * 3:layer * 3 + 3, slot]
        phase_index = next(index for index, value in enumerate(rows) if value)
        return 'ABC'[phase_index], int(rows[phase_index])

    @staticmethod
    def _draw_conductor(painter, position, radius, color, sign, orientation=0):
        painter.save()
        painter.translate(position)
        painter.rotate(orientation)
        origin = QPointF()
        painter.setPen(QPen(color.darker(115), 0.7))
        painter.setBrush(color)
        painter.drawEllipse(origin, radius, radius)
        if sign > 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(Qt.white)
            painter.drawEllipse(origin, max(1.0, radius * 0.23), max(1.0, radius * 0.23))
        else:
            painter.setPen(QPen(Qt.white, max(1.0, radius * 0.18), Qt.SolidLine, Qt.RoundCap))
            delta = radius * 0.38
            painter.drawLine(QPointF(-delta, -delta), QPointF(delta, delta))
            painter.drawLine(QPointF(-delta, delta), QPointF(delta, -delta))
        painter.restore()

    def _draw_slot_number(self, painter, center, radius, slot):
        angle = math.radians(360 * slot / self.slots)
        direction = QPointF(math.cos(angle), -math.sin(angle))
        painter.setPen(QPen(QColor('#c2ccd8'), 0.8))
        painter.drawLine(center + direction * (radius + 3),
                         center + direction * (radius + 8))
        font = QFont('Segoe UI')
        font.setPixelSize(int(max(8, min(12, 2 * math.pi * (radius + 18) / self.slots * 0.55))))
        painter.setFont(font)
        painter.setPen(QColor('#4e6075'))
        point = center + direction * (radius + 20)
        painter.drawText(QRectF(point.x() - 14, point.y() - 9, 28, 18),
                         Qt.AlignCenter, str(slot + 1))

    def _draw_center_label(self, painter, center, bore):
        width = bore * 1.74
        area = QRectF(center.x() - width / 2, center.y() - 42, width, 84)
        font = QFont('Segoe UI')
        font.setPixelSize(14)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor('#b34452') if self.winding_error else QColor('#263a51'))
        title = 'Invalid winding' if self.winding_error else (
            'Double layer' if self.is_double_layer else 'Single layer')
        painter.drawText(QRectF(area.x(), area.y(), width, 24), Qt.AlignCenter, title)
        font.setPixelSize(11)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor('#6a7c91'))
        text = self.winding_error or (
            f'{self.slots} slots · {self.poles} poles\nCoil span {self.coil_span} slots')
        painter.drawText(QRectF(area.x(), area.y() + 29, width, max(64, bore * 0.85)),
                         Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, text)

    def _draw_legend(self, painter):
        font = QFont('Segoe UI')
        font.setPixelSize(15)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor('#263a51'))
        painter.drawText(QRectF(16, 10, 165, 27), Qt.AlignVCenter, 'Stator winding')
        font.setPixelSize(11)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor('#6a7c91'))
        x = self.width() - 178
        painter.drawText(QRectF(x, 12, 43, 24), Qt.AlignVCenter, 'Phases')
        for index, phase in enumerate('ABC'):
            dot = QPointF(x + 54 + index * 41, 24)
            painter.setPen(Qt.NoPen)
            painter.setBrush(PHASE_COLORS[phase])
            painter.drawEllipse(dot, 4.5, 4.5)
            painter.setPen(QColor('#43566e'))
            painter.drawText(QRectF(dot.x() + 10, 12, 20, 24), Qt.AlignVCenter, phase)

        y = self.height() - 36
        start = (self.width() - 324) / 2
        painter.setPen(QColor('#6a7c91'))
        painter.drawText(QRectF(start, y - 9, 104, 20), Qt.AlignVCenter, 'Reference polarity')
        for offset, sign, label in ((114, 1, 'Out of plane'), (228, -1, 'Into plane')):
            self._draw_conductor(painter, QPointF(start + offset, y), 5.0,
                                 QColor('#5d7087'), sign)
            painter.setPen(QColor('#6a7c91'))
            painter.drawText(QRectF(start + offset + 11, y - 9, 95, 20), Qt.AlignVCenter, label)
        if self.is_double_layer:
            font.setPixelSize(10)
            painter.setFont(font)
            painter.drawText(QRectF(10, self.height() - 21, self.width() - 20, 18),
                             Qt.AlignCenter, 'Inner conductor = top layer · Outer conductor = bottom layer')

    def mouseMoveEvent(self, event):
        center, radius = self._drawing_geometry()
        dx, dy = event.pos().x() - center.x(), center.y() - event.pos().y()
        angle = math.degrees(math.atan2(dy, dx)) % 360
        slot = int(round(angle * self.slots / 360)) % self.slots
        slot_angle = math.radians(360 * slot / self.slots)
        local = QPointF(dx * math.cos(slot_angle) + dy * math.sin(slot_angle),
                        dx * math.sin(slot_angle) - dy * math.cos(slot_angle))
        if not self._slot_shape(radius).contains(local):
            slot = None
        if slot != self._hovered_slot:
            self._hovered_slot = slot
            self.update()
            if slot is not None and self.winding_matrix is not None:
                lines = [f'Slot {slot + 1}']
                for layer in range(2 if self.is_double_layer else 1):
                    phase, sign = self._coil_side(slot, layer)
                    name = ('Top' if layer == 0 else 'Bottom') if self.is_double_layer else 'Coil side'
                    direction = '+z, out of plane' if sign > 0 else '−z, into plane'
                    lines.append(f'{name} · Phase {phase} · {direction}')
                QToolTip.showText(event.globalPos(), '\n'.join(lines), self)
            else:
                QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hovered_slot = None
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)
