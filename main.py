"""Multiphase Winding Simulator - application entry point.

Run with: ``python main.py``
"""

import logging
import os
import sys
from pathlib import Path

# Select the Qt6 Matplotlib/pyqtgraph backend even if Qt5 is also installed.
os.environ['QT_API'] = 'pyqt6'
os.environ['PYQTGRAPH_QT_LIB'] = 'PyQt6'
if sys.argv[1:2] == ['--self-test']:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'

# Workers run before importing the GUI and never create another app window.
if __name__ == '__main__' and len(sys.argv) > 1:
    if sys.argv[1] == '--femm-worker':
        from tools.femm_check import main as worker_main
        raise SystemExit(worker_main(sys.argv[2:]))
    if sys.argv[1] == '--pyfemm-worker':
        from core.femm_runner import _pyfemm_worker
        _pyfemm_worker(sys.argv[2], keep_open='--keep-open' in sys.argv[3:])
        raise SystemExit(0)

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout,
                             QLabel, QMainWindow, QPushButton,
                             QTabWidget, QVBoxLayout, QWidget)

from ui.flux_viewer_tab import (go_to_flux_step, has_mesh_data,
                                setup_flux_viewer_tab)
from ui.mmf_tab import setup_connection_matrix_tab
from ui.theme import MAIN_WINDOW_STYLE, badge_style, dark_palette
from ui.winding_tab import WindingTabController

WINDOW_TITLE = "Multiphase Winding Simulator"
MIN_WINDOW_SIZE = (1200, 760)

# One visible navigation system for the complete calculation workflow.
STAGES = (
    ("Winding layout", "Define the coils and check the winding configuration."),
    ("MMF curves", "Inspect the phase contributions and the resultant MMF."),
    ("Machine geometry", "Set the dimensions and inspect the machine cross-section."),
    ("Mesh", "Choose a resolution and generate the polar mesh."),
    ("Field animation", "Play the prepared field, inspect results and compare with FEMM."),
)


class MainWindow(QMainWindow):
    """A five-stage workspace backed by the existing shared page controllers.

    Tab modules attach their interactive widgets to this window so the
    tabs can synchronise (slots/poles, slot arc angle, mesh data, ...).
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / 'ui' / 'assets' / 'app.ico')))
        self.setMinimumSize(*MIN_WINDOW_SIZE)
        self.setPalette(dark_palette())
        self.setStyleSheet(MAIN_WINDOW_STYLE)
        self._pages_ready = False

        shell = QWidget()
        shell.setObjectName('appShell')
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        self.setCentralWidget(shell)

        header = QFrame()
        header.setObjectName('appHeader')
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 10, 20, 10)
        self.page_title = QLabel()
        self.page_title.setObjectName('workspaceTitle')
        header_layout.addWidget(self.page_title)
        header_layout.addStretch()
        self.winding_context_label = QLabel()
        self.winding_context_label.setStyleSheet(badge_style('muted'))
        header_layout.addWidget(self.winding_context_label)
        self.settings_toggle = QPushButton('Hide settings')
        self.settings_toggle.setCheckable(True)
        self.settings_toggle.setChecked(True)
        self.settings_toggle.setToolTip('Expand the result view by hiding the parameter controls.')
        self.settings_toggle.clicked.connect(self._set_settings_visible)
        header_layout.addWidget(self.settings_toggle)
        shell_layout.addWidget(header)
        shell_layout.addWidget(self._build_stage_navigation())

        self.tabs = QTabWidget()
        self.tabs.setObjectName('mainTabs')
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().hide()
        shell_layout.addWidget(self.tabs, 1)
        self.tab_main = QWidget()
        self.tabs.addTab(self.tab_main, 'Winding')
        self.tab_connection = QWidget()
        self.tabs.addTab(self.tab_connection, 'MMF')
        self.tab3 = QWidget()
        self.tabs.addTab(self.tab3, 'Field workflow')

        # Order matters: the MMF tab and flux viewer read winding-tab widgets.
        self.winding_tab = WindingTabController(self)
        setup_connection_matrix_tab(self)
        setup_flux_viewer_tab(self)

        self.winding_tab.update_winding()
        self._pages_ready = True
        self.tabs.setCurrentIndex(0)
        self.tabs.currentChanged.connect(self.sync_navigation)
        self.sync_navigation()

    def _build_stage_navigation(self):
        bar = QFrame()
        bar.setObjectName('stageNavigation')
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 6, 20, 8)
        layout.setSpacing(8)
        self.navigation_group = QButtonGroup(self)
        self.navigation_group.setExclusive(True)
        self.navigation_buttons = []
        for index, short_title in enumerate(('Winding', 'MMF curves', 'Geometry', 'Mesh', 'Animation')):
            button = QPushButton(f'{index + 1}  {short_title}')
            button.setObjectName('workflowNavButton')
            button.setCheckable(True)
            button.setMinimumHeight(32)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(STAGES[index][0])
            button.setToolTip(f'{STAGES[index][1]} (Ctrl+{index+1})')
            button.clicked.connect(lambda checked=False, stage=index: self.navigate_to_stage(stage))
            self.navigation_group.addButton(button, index)
            self.navigation_buttons.append(button)
            layout.addWidget(button, 1)
            shortcut = QShortcut(QKeySequence(f'Ctrl+{index+1}'), self)
            shortcut.activated.connect(lambda stage=index: self.navigate_to_stage(stage))
        return bar

    def _set_settings_visible(self, visible):
        for panel in self.findChildren(QWidget, 'studySettings'):
            panel.setVisible(visible)
        self.settings_toggle.setText('Hide settings' if visible else 'Show settings')

    def current_stage(self):
        tab_index = self.tabs.currentIndex()
        return tab_index if tab_index < 2 else 2 + self.current_flux_step

    def closeEvent(self, event):
        controller = getattr(self, 'flux_density_page_ui', None)
        if controller is not None:
            controller._closing = True
            controller._auto_prepare_timer.stop()
            controller.pause_animation(sync_results=False)
        worker = getattr(controller, '_animation_worker', None)
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            worker.finished.connect(self.close)
            event.ignore()
            return
        # Release pyplot's hidden figure managers as well as the Qt window.
        from matplotlib import pyplot as plt
        for name in ('flux_figure', 'mesh_figure', 'flux_density_figure'):
            figure = getattr(self, name, None)
            if figure is not None:
                plt.close(figure)
        super().closeEvent(event)

    def navigate_to_stage(self, stage):
        """Open a stage directly, respecting the generated-mesh prerequisite."""
        if not self._pages_ready or not 0 <= stage < len(STAGES):
            return
        if stage == 4 and not has_mesh_data(self):
            return
        if stage != 4:
            self.flux_density_page_ui.pause_animation()
        if stage < 2:
            self.tabs.setCurrentIndex(stage)
        else:
            go_to_flux_step(self, stage - 2)
            self.tabs.setCurrentIndex(2)
        self.sync_navigation()
        self.tabs.currentWidget().setFocus(Qt.FocusReason.OtherFocusReason)

    def sync_navigation(self, *_):
        """Keep the compact stage navigation and current view in agreement."""
        if not self._pages_ready:
            return
        stage = self.current_stage()
        title, description = STAGES[stage]
        self.navigation_buttons[stage].setChecked(True)
        self.page_title.setText(f'Winding & Flux  /  {title}')
        mesh_ready = has_mesh_data(self)
        field_button = self.navigation_buttons[4]
        field_button.setEnabled(mesh_ready)
        field_button.setToolTip(
            'Inspect the solved field.\nShortcut: Ctrl+5' if mesh_ready else
            'Generate a mesh in stage 04 to unlock field analysis.')



def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = QApplication(sys.argv)
    # Fusion renders custom stylesheets consistently across platforms.
    app.setStyle('Fusion')
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    app.setPalette(dark_palette())
    app.setApplicationName('WindingFlux')
    app.setApplicationDisplayName('Winding & Flux')
    if sys.argv[1:2] == ['--self-test']:
        from tools.ui_smoke_test import load_preview_fonts, run_smoke_test
        load_preview_fonts()
    window = MainWindow()
    if sys.argv[1:2] == ['--self-test']:
        output = sys.argv[2] if len(sys.argv) > 2 else 'ui-check'
        raise SystemExit(run_smoke_test(window, output))
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
