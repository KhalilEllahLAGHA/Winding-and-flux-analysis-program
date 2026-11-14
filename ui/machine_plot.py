"""Shared, toolbar-free machine preview for geometry and mesh pages."""

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.collections import LineCollection
import numpy as np
from PyQt6.QtWidgets import QFrame, QVBoxLayout

from ui.machine_drawer import MachineDrawer


class MachinePlot(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName('machinePlotSurface')
        self.setStyleSheet(
            'QFrame#machinePlotSurface { background: white; border: 1px solid #dedede; border-radius: 9px; }')
        self.figure, self.ax = plt.subplots(figsize=(8, 8), layout='constrained')
        self.figure.patch.set_facecolor('white')
        self.ax.set_facecolor('white')
        self.canvas = FigureCanvas(self.figure)
        self.drawer = MachineDrawer(self.figure, self.ax)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.canvas)
        self._drawn_params = None
        self._drawn_mesh = None

    def clear_cache(self):
        self._drawn_params = None
        self._drawn_mesh = None

    def draw_machine(self, params, mesh=None):
        """Draw once per changed geometry/mesh, retaining an unchanged view."""
        key = tuple(sorted(params.items()))
        if key == self._drawn_params and mesh is self._drawn_mesh:
            return False
        self.drawer.draw_machine(params, render=False)
        if mesh is not None:
            self._draw_mesh(mesh)
        self.canvas.draw()
        self._drawn_params, self._drawn_mesh = key, mesh
        return True

    def _draw_mesh(self, mesh):
        params = mesh['params']
        theta = np.radians(np.asarray(mesh['theta_divisions'])[:-1])
        unit = np.column_stack((np.cos(theta), np.sin(theta)))
        radial = np.stack((unit * params['shaft_radius'],
                           unit * params['stator_outer_radius']), axis=1)
        self.ax.add_collection(LineCollection(
            radial, colors='#555555', linewidths=0.3, alpha=0.7))
        angles = np.linspace(0, 2*np.pi, 181)
        circles = np.asarray(mesh['r_divisions'])[:, None, None] * np.column_stack(
            (np.cos(angles), np.sin(angles)))[None, :, :]
        self.ax.add_collection(LineCollection(
            circles, colors='#333333', linewidths=0.3, alpha=0.7))
