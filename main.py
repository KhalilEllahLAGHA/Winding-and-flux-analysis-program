"""Three Phase Winding Simulator - application entry point.

Run with: ``python main.py``
"""

import logging
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                             QMainWindow, QTabWidget, QVBoxLayout, QWidget)

from ui.flux_viewer_tab import setup_flux_viewer_tab
from ui.mmf_tab import setup_connection_matrix_tab
from ui.theme import MAIN_WINDOW_STYLE, badge_style
from ui.winding_tab import WindingTabController

WINDOW_TITLE = "Three Phase Winding Simulator"
MIN_WINDOW_SIZE = (1200, 800)


class MainWindow(QMainWindow):
    """Hosts the three tabs and the state they share.

    Tab modules attach their interactive widgets to this window so the
    tabs can synchronise (slots/poles, slot arc angle, mesh data, ...).
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumSize(*MIN_WINDOW_SIZE)
        self.setStyleSheet(MAIN_WINDOW_STYLE)

        shell = QWidget()
        shell.setObjectName('appShell')
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        self.setCentralWidget(shell)

        header = QFrame()
        header.setObjectName('appHeader')
        header.setFixedHeight(54)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 8, 20, 8)
        identity = QLabel('Winding & Flux')
        identity.setStyleSheet('font-size: 18px; font-weight: 700; background: transparent;')
        header_layout.addWidget(identity)
        header_layout.addStretch()
        self.winding_context_label = QLabel()
        self.winding_context_label.setStyleSheet(badge_style('info'))
        header_layout.addWidget(self.winding_context_label)
        shell_layout.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setObjectName('mainTabs')
        self.tabs.setDocumentMode(True)
        self.tabs.setElideMode(Qt.ElideRight)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setDrawBase(False)
        shell_layout.addWidget(self.tabs, 1)

        self.tab_main = QWidget()
        self.tabs.addTab(self.tab_main, "Winding Simulator")

        self.tab_connection = QWidget()
        self.tabs.addTab(self.tab_connection, "MMF Curves")

        self.tab3 = QWidget()
        self.tabs.addTab(self.tab3, "Flux Viewer")

        # Order matters: the MMF tab and flux viewer read winding-tab widgets.
        self.winding_tab = WindingTabController(self)
        setup_connection_matrix_tab(self)
        setup_flux_viewer_tab(self)

        self.winding_tab.update_winding()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = QApplication(sys.argv)
    # Fusion renders custom stylesheets consistently across platforms.
    app.setStyle('Fusion')
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
