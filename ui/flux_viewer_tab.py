"""Flux Viewer tab (formerly ``Flux_viewer_tab.py``): hosts the three-step
flow Motor Drawing -> Meshing Config -> Flux Density Heatmap with a wizard
style step indicator and contextual navigation hints."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                             QStackedWidget, QVBoxLayout)

from ui.flux_density_page import FluxDensityHeatmapUI
from ui.meshing_page import MeshingPageUI
from ui.motor_drawing_page import MotorDrawingPageUI
from ui.theme import (FLUX_VIEWER_TAB_STYLE, set_status, step_badge_style,
                      step_connector_style, step_title_style)


class FluxViewerSteps:
    MOTOR_DRAWING = 0
    MESHING_CONFIG = 1
    FLUX_DENSITY_HEATMAP = 2
    LAST = FLUX_DENSITY_HEATMAP


STEP_TITLES = ("Machine Parameters", "Meshing Configuration",
               "Flux Density Analysis")

STEP_BADGE_SIZE_PX = 28


def setup_flux_viewer_tab(main_window):
    """Build the flux viewer tab with its step navigation."""
    main_window.tab3.setStyleSheet(FLUX_VIEWER_TAB_STYLE)

    layout = QVBoxLayout(main_window.tab3)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)

    layout.addWidget(_create_step_header(main_window))

    main_window.flux_stacked_widget = QStackedWidget()
    layout.addWidget(main_window.flux_stacked_widget)

    layout.addWidget(_create_navigation_frame(main_window))

    # Pages call this to refresh the Next/Previous buttons when the mesh
    # state changes (avoids a circular import with the meshing page).
    main_window.update_flux_navigation = lambda: update_step_display(main_window)

    _create_step_widgets(main_window)

    main_window.current_flux_step = FluxViewerSteps.MOTOR_DRAWING
    update_step_display(main_window)


def _create_step_header(main_window):
    """Wizard progress header: numbered badges joined by connector lines."""
    frame = QFrame()
    frame.setObjectName("fluxStepHeader")
    frame.setFixedHeight(56)

    layout = QHBoxLayout(frame)
    layout.setContentsMargins(16, 8, 16, 8)
    layout.setSpacing(10)

    main_window.flux_step_badges = []
    main_window.flux_step_titles = []
    main_window.flux_step_connectors = []

    for index, title in enumerate(STEP_TITLES):
        if index > 0:
            connector = QFrame()
            connector.setFixedHeight(2)
            connector.setMinimumWidth(24)
            layout.addWidget(connector, 1)
            main_window.flux_step_connectors.append(connector)

        badge = QLabel(str(index + 1))
        badge.setFixedSize(STEP_BADGE_SIZE_PX, STEP_BADGE_SIZE_PX)
        badge.setAlignment(Qt.AlignCenter)
        layout.addWidget(badge)
        main_window.flux_step_badges.append(badge)

        title_label = QLabel(title)
        layout.addWidget(title_label)
        main_window.flux_step_titles.append(title_label)

    return frame


def _create_navigation_frame(main_window):
    frame = QFrame()
    frame.setObjectName("fluxNavBar")
    frame.setFixedHeight(58)

    layout = QHBoxLayout(frame)
    layout.setContentsMargins(16, 8, 16, 8)
    layout.setSpacing(10)

    # Contextual hint ("Generate a mesh to continue", ...).
    main_window.flux_nav_hint = QLabel("")
    layout.addWidget(main_window.flux_nav_hint)
    layout.addStretch()

    main_window.flux_prev_btn = QPushButton("← Previous")
    main_window.flux_prev_btn.setFixedSize(120, 38)
    main_window.flux_prev_btn.clicked.connect(
        lambda: navigate_step(main_window, -1))
    layout.addWidget(main_window.flux_prev_btn)

    main_window.flux_next_btn = QPushButton("Next →")
    main_window.flux_next_btn.setObjectName("primaryButton")
    main_window.flux_next_btn.setFixedSize(120, 38)
    main_window.flux_next_btn.clicked.connect(
        lambda: navigate_step(main_window, 1))
    layout.addWidget(main_window.flux_next_btn)

    return frame


def _create_step_widgets(main_window):
    # The page controllers must stay referenced: PyQt5 only holds weak
    # references to bound-method slots, so a garbage-collected controller
    # silently loses every signal connection it made (this is what froze
    # the Step 1 motor preview before).
    motor_drawing_ui = MotorDrawingPageUI(main_window)
    meshing_ui = MeshingPageUI(main_window)
    flux_density_ui = FluxDensityHeatmapUI(main_window)
    main_window.flux_page_controllers = (motor_drawing_ui, meshing_ui,
                                         flux_density_ui)

    main_window.flux_stacked_widget.addWidget(
        motor_drawing_ui.create_motor_input_widget())
    main_window.flux_stacked_widget.addWidget(meshing_ui.create_meshing_widget())
    main_window.flux_stacked_widget.addWidget(
        flux_density_ui.create_flux_density_heatmap_widget())


def navigate_step(main_window, direction):
    """Move between steps and refresh the page being entered."""
    new_step = main_window.current_flux_step + direction
    if not 0 <= new_step <= FluxViewerSteps.LAST:
        return

    main_window.current_flux_step = new_step
    update_step_display(main_window)

    if (new_step == FluxViewerSteps.MESHING_CONFIG
            and hasattr(main_window, 'meshing_page_ui')):
        main_window.meshing_page_ui.refresh_visualization()


def _has_mesh_data(main_window):
    return (hasattr(main_window, 'meshing_page_ui')
            and main_window.meshing_page_ui is not None
            and main_window.meshing_page_ui.mesh_data is not None)


def _update_step_header(main_window, current_step):
    if not hasattr(main_window, 'flux_step_badges'):
        return

    for index, (badge, title) in enumerate(
            zip(main_window.flux_step_badges, main_window.flux_step_titles)):
        if index < current_step:
            state = 'done'
            badge.setText("✓")
        else:
            state = 'active' if index == current_step else 'todo'
            badge.setText(str(index + 1))
        badge.setStyleSheet(step_badge_style(state))
        title.setStyleSheet(step_title_style(state))

    for index, connector in enumerate(main_window.flux_step_connectors):
        connector.setStyleSheet(step_connector_style(index < current_step))


def _update_navigation_hint(main_window, current_step, has_mesh_data):
    hint_label = getattr(main_window, 'flux_nav_hint', None)
    if hint_label is None:
        return

    if current_step == FluxViewerSteps.MOTOR_DRAWING:
        set_status(hint_label,
                   "The preview updates live as you edit parameters.",
                   'muted')
    elif current_step == FluxViewerSteps.MESHING_CONFIG:
        if has_mesh_data:
            set_status(hint_label,
                       "Mesh ready — continue to the flux analysis.",
                       'success')
        else:
            set_status(hint_label,
                       "Generate a mesh to unlock the next step.",
                       'warning')
    else:
        set_status(hint_label,
                   "Run Calculate, then generate a visualisation or animation.",
                   'muted')


def update_step_display(main_window):
    """Sync the stacked widget, header, and navigation to the current step."""
    current_step = main_window.current_flux_step
    main_window.flux_stacked_widget.setCurrentIndex(current_step)
    main_window.flux_prev_btn.setEnabled(current_step > 0)

    has_mesh_data = _has_mesh_data(main_window)
    if current_step == FluxViewerSteps.MESHING_CONFIG:
        # Only allow continuing once a mesh has been generated.
        main_window.flux_next_btn.setEnabled(has_mesh_data)
    else:
        main_window.flux_next_btn.setEnabled(current_step < FluxViewerSteps.LAST)

    is_last = current_step == FluxViewerSteps.LAST
    main_window.flux_next_btn.setText("Finish" if is_last else "Next →")

    _update_step_header(main_window, current_step)
    _update_navigation_hint(main_window, current_step, has_mesh_data)
