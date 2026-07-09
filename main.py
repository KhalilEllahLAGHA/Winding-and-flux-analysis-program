"""Three Phase Winding Simulator - application entry point.

Run with: ``python main.py``
"""

import logging
import sys

from PyQt5.QtWidgets import QApplication, QMainWindow, QTabWidget, QWidget

from ui.flux_viewer_tab import setup_flux_viewer_tab
from ui.mmf_tab import setup_connection_matrix_tab
from ui.theme import MAIN_WINDOW_STYLE
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

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

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
