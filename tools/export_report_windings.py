"""Export the application's actual stator widget with French report legends.

Only annotation methods are overridden. Slot geometry, conductor phase/sign,
layer placement and the matrix remain those of ui.stator_drawing.StatorDrawing.
"""

import hashlib
import json
import os
from pathlib import Path
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPixmap
from PyQt6.QtWidgets import QApplication

from core.connection_matrix import build_winding_connection_matrix
from ui.stator_drawing import StatorDrawing
from tools.ui_smoke_test import load_preview_fonts
from utils.phases import phase_color, phase_names


class FrenchReportStator(StatorDrawing):
    """Use the native drawing with French annotations, without changing coils."""

    def _draw_center_label(self, painter, center, bore):
        width = bore*1.75
        painter.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
        painter.setPen(QColor('#292929'))
        painter.drawText(QRectF(center.x()-width/2, center.y()-46, width, 29),
                         Qt.AlignmentFlag.AlignCenter, 'Double couche')
        font = QFont('Segoe UI')
        font.setPixelSize(14)
        painter.setFont(font)
        painter.setPen(QColor('#565e66'))
        text = (f'{self.phase_count} phases · {self.slots} encoches\n'
                f'{self.poles} pôles · pas de {self.coil_span} encoches')
        painter.drawText(QRectF(center.x()-width/2, center.y()-9, width, 65),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, text)

    def _draw_legend(self, painter):
        font = QFont('Segoe UI')
        font.setPixelSize(18)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor('#292929'))
        painter.drawText(QRectF(18, 9, self.width()-36, 27),
                         Qt.AlignmentFlag.AlignVCenter, 'Répartition du bobinage statorique')
        font.setPixelSize(14)
        font.setBold(False)
        painter.setFont(font)
        for index, phase in enumerate(self.phases):
            x, y = 25+index*70, 50
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(phase_color(phase)))
            painter.drawEllipse(QPointF(x, y), 5.5, 5.5)
            painter.setPen(QColor('#4c4c4c'))
            painter.drawText(QRectF(x+12, y-12, 36, 24), Qt.AlignmentFlag.AlignVCenter, phase)
        y = self.height()-43
        left = (self.width()-525)/2
        painter.setPen(QColor('#565e66'))
        painter.drawText(QRectF(left, y-12, 151, 25), Qt.AlignmentFlag.AlignVCenter, 'Polarité de référence :')
        for offset, sign, label in ((170, 1, 'sortant (+z)'), (350, -1, 'entrant (-z)')):
            self._draw_conductor(painter, QPointF(left+offset, y), 6,
                                 QColor('#666666'), sign)
            painter.setPen(QColor('#565e66'))
            painter.drawText(QRectF(left+offset+13, y-12, 157, 25),
                             Qt.AlignmentFlag.AlignVCenter, label)
        font.setPixelSize(12)
        painter.setFont(font)
        painter.drawText(QRectF(8, self.height()-23, self.width()-16, 20),
                         Qt.AlignmentFlag.AlignCenter,
                         'Conducteur intérieur : couche haute · Conducteur extérieur : couche basse')


def export_all_windings():
    app = QApplication.instance() or QApplication([])
    load_preview_fonts()
    assets = ROOT/'docs/multiphase-report/assets'
    data = ROOT/'docs/multiphase-report/data'
    assets.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    cases = (('three-phase-default', 3, 36, 4, 9),
             ('two-phase', 2, 24, 4, 6),
             ('five-phase-45s-8p-span5', 5, 45, 8, 5))
    exported = []
    for slug, m, slots, poles, span in cases:
        widget = FrenchReportStator()
        widget.resize(800, 800)
        widget.update_parameters(slots, poles, span, True, m)
        assert widget.winding_error is None, widget.winding_error
        expected = build_winding_connection_matrix(slots, poles, True, span, phase_names(m))
        np.testing.assert_array_equal(widget.winding_matrix, expected)
        np.testing.assert_array_equal(abs(expected).sum(axis=0), np.full(slots, 2))
        widget.show()
        app.processEvents()
        pixmap = QPixmap(1600, 1600)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.GlobalColor.white)
        widget.render(pixmap)
        path = assets/f'{slug}-winding.png'
        assert pixmap.save(str(path))
        exported.append({'case':slug, 'phases':m, 'slots':slots, 'poles':poles,
                         'span':span, 'layers':'double', 'matrix_shape':list(expected.shape),
                         'source_widget':'ui.stator_drawing.StatorDrawing',
                         'annotations_language':'fr', 'native_matrix_verified':True,
                         'image':path.name, 'width':1600, 'height':1600,
                         'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        widget.close()
        widget.deleteLater()
    (data/'stator-windings.json').write_text(json.dumps(exported,indent=2),encoding='utf-8')
    print(json.dumps(exported,indent=2))
    return exported


if __name__ == '__main__':
    export_all_windings()
