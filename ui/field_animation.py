"""Qt6 background preparation and lightweight live field rendering."""

import numpy as np
from matplotlib import colormaps
from PyQt6.QtCore import QRectF, QThread, pyqtSignal
import pyqtgraph as pg

from core.field_animation import build_field_animation


class AnimationPreparation(QThread):
    progress = pyqtSignal(int, str)
    prepared = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, parent, **inputs):
        super().__init__(parent)
        self.inputs = inputs

    def run(self):
        try:
            model = build_field_animation(
                **self.inputs, progress=self.progress.emit,
                cancelled=self.isInterruptionRequested)
            self.prepared.emit(model)
        except Exception as error:
            self.failed.emit(str(error))


class FieldAnimationView(pg.GraphicsLayoutWidget):
    """Update fixed raster/path items without rebuilding a Matplotlib figure."""

    def __init__(self):
        super().__init__()
        self.setBackground('w')
        self.plot = self.addPlot()
        self.plot.setAspectLocked(True)
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.hideButtons()
        for edge in ('left', 'bottom'):
            axis = self.plot.getAxis(edge)
            axis.setPen('#777777')
            axis.setTextPen('#555555')
            axis.setLabel('y' if edge == 'left' else 'x', units='mm', color='#555555')
        self.image = pg.ImageItem(axisOrder='row-major')
        self.plot.addItem(self.image)
        self.contours = pg.PlotCurveItem(pen=pg.mkPen('#202020', width=1),
                                         connect='finite', antialias=True)
        self.geometry = pg.PlotCurveItem(pen=pg.mkPen('#666666', width=0.6),
                                         connect='finite', antialias=True)
        self.plot.addItem(self.contours)
        self.plot.addItem(self.geometry)
        self.arrow_halo = pg.PlotCurveItem(pen=pg.mkPen('#ffffff', width=3.2),
                                          connect='finite', antialias=True)
        self.arrows = pg.PlotCurveItem(pen=pg.mkPen('#202020', width=1.3),
                                      connect='finite', antialias=True)
        self.plot.addItem(self.arrow_halo)
        self.plot.addItem(self.arrows)
        self.color_map = pg.ColorMap(np.linspace(0, 1, 256),
                                     colormaps['turbo'](np.linspace(0, 1, 256), bytes=True))
        self.colorbar = pg.ColorBarItem(values=(0, 1), colorMap=self.color_map,
                                        interactive=False,
                                        colorMapMenu=False)
        self.colorbar.setImageItem(self.image, insert_in=self.plot)
        self.colorbar.axis.setTextPen('#555555')
        self.colorbar.axis.setPen('#777777')
        self.colorbar.axis.setLabel('|B| (T)', color='#555555')
        self.model = None

    def set_model(self, model, mode, contour_count=12):
        self.model, self.mode = model, mode
        self.contour_count = contour_count
        radius = model.outer_radius
        # ImageItem requires assigned image dimensions before setRect.
        self.image.setImage(model.image_at(0), autoLevels=False, levels=(0, model.color_max))
        self.image.setRect(QRectF(-radius, -radius, 2*radius, 2*radius))
        self.plot.setRange(xRange=(-radius*1.08, radius*1.08),
                           yRange=(-radius*1.08, radius*1.08), padding=0)
        self.geometry.setData(model.geometry_paths[:, 0], model.geometry_paths[:, 1])
        heatmap = mode != 'Flux Lines'
        self.colorbar.setVisible(heatmap)
        self.colorbar.setLevels((0, model.color_max))
        if heatmap:
            self.image.setLookupTable(self.color_map.getLookupTable(nPts=256))
        else:
            self.image.setLookupTable(None)
            self.image.setImage(model.material_image, autoLevels=False, levels=(0, 255))
        self.contours.setVisible(mode != 'B Heatmap')
        self.arrow_halo.setVisible(mode != 'B Heatmap')
        self.arrows.setVisible(mode != 'B Heatmap')

    def show_angle(self, angle):
        if self.mode != 'Flux Lines':
            self.image.setImage(self.model.image_at(angle), autoLevels=False,
                                 levels=(0, self.model.color_max))
        if self.mode != 'B Heatmap':
            paths, arrows = self.model.contour_frame_at(angle, self.contour_count)
            self.contours.setData(paths[:, 0], paths[:, 1])
            self.arrow_halo.setData(arrows[:, 0], arrows[:, 1])
            self.arrows.setData(arrows[:, 0], arrows[:, 1])
        self.plot.setTitle(f'{self.mode} · Wt = {angle:.1f}°', color='#222222', size='11pt')
