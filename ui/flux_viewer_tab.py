"""Magnetic-field pages, reached through the shared workflow navigation."""

from PyQt6.QtWidgets import QStackedWidget, QVBoxLayout

from ui.flux_density_page import FluxDensityHeatmapUI
from ui.meshing_page import MeshingPageUI
from ui.motor_drawing_page import MotorDrawingPageUI
from ui.theme import FLUX_VIEWER_TAB_STYLE


class FluxViewerSteps:
    MOTOR_DRAWING = 0
    MESHING_CONFIG = 1
    FLUX_DENSITY_HEATMAP = 2
    LAST = FLUX_DENSITY_HEATMAP


def setup_flux_viewer_tab(main_window):
    """Build geometry, mesh and field pages without nested navigation."""
    main_window.tab3.setStyleSheet(FLUX_VIEWER_TAB_STYLE)
    layout = QVBoxLayout(main_window.tab3)
    layout.setContentsMargins(20, 18, 20, 18)
    main_window.flux_stacked_widget = QStackedWidget()
    layout.addWidget(main_window.flux_stacked_widget)
    main_window.current_flux_step = FluxViewerSteps.MOTOR_DRAWING
    main_window.update_flux_navigation = lambda: update_step_display(main_window)

    # Keep controllers alive: PyQt uses weak references to bound slots.
    geometry = MotorDrawingPageUI(main_window)
    mesh = MeshingPageUI(main_window)
    field = FluxDensityHeatmapUI(main_window)
    main_window.flux_page_controllers = (geometry, mesh, field)
    main_window.flux_stacked_widget.addWidget(geometry.create_motor_input_widget())
    main_window.flux_stacked_widget.addWidget(mesh.create_meshing_widget())
    main_window.flux_stacked_widget.addWidget(field.create_flux_density_heatmap_widget())
    update_step_display(main_window)


def has_mesh_data(main_window):
    controller = getattr(main_window, 'meshing_page_ui', None)
    return controller is not None and controller.mesh_data is not None


def go_to_flux_step(main_window, step):
    """Open a page; a generated mesh is required for field analysis."""
    if not 0 <= step <= FluxViewerSteps.LAST:
        return
    if step == FluxViewerSteps.FLUX_DENSITY_HEATMAP and not has_mesh_data(main_window):
        return
    main_window.current_flux_step = step
    update_step_display(main_window)


def navigate_step(main_window, direction):
    go_to_flux_step(main_window, main_window.current_flux_step + direction)


def update_step_display(main_window):
    """Refresh navigation after mesh generation or input invalidation."""
    if (main_window.current_flux_step == FluxViewerSteps.FLUX_DENSITY_HEATMAP
            and not has_mesh_data(main_window)):
        main_window.current_flux_step = FluxViewerSteps.MESHING_CONFIG
    main_window.flux_stacked_widget.setCurrentIndex(main_window.current_flux_step)
    main_window.sync_navigation()
