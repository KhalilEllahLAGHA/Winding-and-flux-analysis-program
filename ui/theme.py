"""Shared design system: color tokens, typography, and Qt stylesheets.

Every page composes its stylesheet from the fragments below so spacing,
colors, radii, and interactive states (hover / focus / pressed / disabled)
stay consistent across the whole application.

Conventions used by the pages:
  - ``btn.setObjectName("primaryButton")`` promotes a button to the primary
    (primary action) style.
  - ``set_status(label, text, kind)`` renders neutral feedback lines
    (kind: muted / info / success / warning / error).
  - ``badge_style(kind)`` returns a tinted "chip" style for QLabels.
"""

from PyQt6.QtGui import QColor, QPalette
from pathlib import Path

_ASSETS = Path(__file__).resolve().with_name('assets')

# --- Design tokens -----------------------------------------------------------

# Dark neutral surfaces. White backgrounds are reserved for image/plot canvases.
BG_WINDOW = "#141414"
BG_SURFACE = "#1e1e1e"
BG_INPUT = "#282828"
BG_HOVER = "#353535"
BG_PRESSED = "#101010"

BORDER = "#505050"
BORDER_SOFT = "#353535"

TEXT = "#eeeeee"
TEXT_DIM = "#b8b8b8"
TEXT_FAINT = "#999999"

ACCENT = "#5389db"
ACCENT_HOVER = "#6b9be2"
ACCENT_PRESSED = "#3b6db5"

SUCCESS = "#81c6a7"
WARNING = "#e0bb71"
DANGER = "#ea9898"

FONT_FAMILY = '"Segoe UI", "Helvetica Neue", Arial, sans-serif'


def dark_palette():
    """Keep native popups, spin arrows and plot toolbar icons in the same theme."""
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: BG_WINDOW, QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: BG_INPUT, QPalette.ColorRole.AlternateBase: BG_SURFACE,
        QPalette.ColorRole.Text: TEXT, QPalette.ColorRole.Button: BG_INPUT,
        QPalette.ColorRole.ButtonText: TEXT, QPalette.ColorRole.BrightText: TEXT,
        QPalette.ColorRole.ToolTipBase: BG_INPUT, QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.Highlight: ACCENT, QPalette.ColorRole.HighlightedText: '#ffffff',
        QPalette.ColorRole.Light: '#616161', QPalette.ColorRole.Midlight: '#3a3a3a',
        QPalette.ColorRole.Mid: '#383838', QPalette.ColorRole.Dark: '#101010',
        QPalette.ColorRole.Shadow: '#000000', QPalette.ColorRole.Link: TEXT,
        QPalette.ColorRole.LinkVisited: TEXT_DIM,
    }.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(TEXT_FAINT))
    return palette

# --- Fragments ---------------------------------------------------------------

_BASE = f"""
    QWidget {{
        color: {TEXT};
        font-family: {FONT_FAMILY};
        font-size: 13px;
    }}

    QMainWindow, QWidget#appShell, QDialog {{
        background-color: {BG_WINDOW};
    }}

    QFrame#appHeader {{
        background-color: {BG_SURFACE};
        border-bottom: 1px solid {BORDER_SOFT};
    }}

    QScrollArea {{
        border: none;
        background-color: transparent;
    }}

    QScrollArea > QWidget > QWidget {{
        background-color: transparent;
    }}

    QLabel {{
        background-color: transparent;
        color: {TEXT};
        font-size: 13px;
    }}

    QToolTip {{
        background-color: {BG_INPUT};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 4px;
        padding: 6px 8px;
        font-size: 12px;
    }}

    QSplitter::handle {{
        background-color: {BORDER_SOFT};
    }}
"""

_BUTTONS = f"""
    QPushButton {{
        background-color: {BG_INPUT};
        color: {TEXT};
        border: 1px solid {BORDER};
        padding: 7px 12px;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 600;
        min-width: 64px;
    }}

    QPushButton:hover {{
        background-color: {BG_HOVER};
        border: 1px solid {ACCENT};
    }}

    QPushButton:pressed {{
        background-color: {BG_PRESSED};
    }}

    QPushButton:focus {{
        border: 1px solid {ACCENT};
    }}

    QPushButton:disabled {{
        background-color: {BG_SURFACE};
        color: {TEXT_FAINT};
        border: 1px solid {BORDER_SOFT};
    }}

    QPushButton#primaryButton {{
        background-color: {ACCENT};
        color: #ffffff;
        border: 1px solid {ACCENT};
    }}

    QPushButton#primaryButton:hover {{
        background-color: {ACCENT_HOVER};
        border: 1px solid {ACCENT_HOVER};
    }}

    QPushButton#primaryButton:pressed {{
        background-color: {ACCENT_PRESSED};
        border: 1px solid {ACCENT_PRESSED};
    }}

    QPushButton#primaryButton:disabled {{
        background-color: {BG_SURFACE};
        color: {TEXT_FAINT};
        border: 1px solid {BORDER_SOFT};
    }}
"""

_GROUP_BOX = f"""
    QGroupBox {{
        background-color: {BG_SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER_SOFT};
        border-radius: 9px;
        margin-top: 10px;
        padding: 6px 6px 6px 6px;
        font-weight: 600;
        font-size: 12px;
    }}

    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 10px;
        padding: 0 6px;
        color: {TEXT_DIM};
        background-color: {BG_SURFACE};
    }}
"""

_LINE_EDIT = f"""
    QLineEdit {{
        background-color: {BG_INPUT};
        color: {TEXT};
        border: 1px solid {BORDER};
        padding: 6px 8px;
        border-radius: 6px;
        font-size: 13px;
        min-width: 54px;
        selection-background-color: {ACCENT};
        selection-color: #ffffff;
    }}

    QLineEdit:hover {{
        border: 1px solid {TEXT_FAINT};
    }}

    QLineEdit:focus {{
        border: 1px solid {ACCENT};
        background-color: {BG_HOVER};
    }}

    QLineEdit:disabled {{
        background-color: {BG_SURFACE};
        color: {TEXT_FAINT};
        border: 1px solid {BORDER_SOFT};
    }}
"""


def _spin_box_rules(selector):
    """Neutral style block for QSpinBox-like widgets."""
    return f"""
    {selector} {{
        background-color: {BG_INPUT};
        color: {TEXT};
        border: 1px solid {BORDER};
        padding: 6px 22px 6px 8px;
        border-radius: 6px;
        font-size: 13px;
        min-width: 54px;
        selection-background-color: {ACCENT};
        selection-color: #ffffff;
    }}

    {selector}:hover {{
        border: 1px solid {TEXT_FAINT};
    }}

    {selector}:focus {{
        border: 1px solid {ACCENT};
        background-color: {BG_INPUT};
    }}

    {selector}:disabled {{
        background-color: {BG_SURFACE};
        color: {TEXT_FAINT};
        border: 1px solid {BORDER_SOFT};
    }}

    {selector}::up-button, {selector}::down-button {{
        subcontrol-origin: border;
        width: 18px;
        border-left: 1px solid {BORDER};
        background: {BG_INPUT};
    }}
    {selector}::up-button {{ subcontrol-position: top right; }}
    {selector}::down-button {{ subcontrol-position: bottom right; }}
    {selector}::up-arrow {{
        image: url("{(_ASSETS / 'chevron-up.svg').as_posix()}");
        width: 10px; height: 7px;
    }}
    {selector}::down-arrow {{
        image: url("{(_ASSETS / 'chevron-down.svg').as_posix()}");
        width: 10px; height: 7px;
    }}

"""


_SPIN_BOXES = _spin_box_rules("QSpinBox") + _spin_box_rules("QDoubleSpinBox")

_COMBO_BOX = f"""
    QComboBox {{
        background-color: {BG_INPUT};
        color: {TEXT};
        border: 1px solid {BORDER};
        padding: 6px 10px;
        border-radius: 6px;
        font-size: 13px;
        min-width: 100px;
    }}

    QComboBox:hover {{
        border: 1px solid {TEXT_FAINT};
        background-color: {BG_HOVER};
    }}

    QComboBox:focus {{
        border: 1px solid {ACCENT};
    }}

    QComboBox:disabled {{
        background-color: {BG_SURFACE};
        color: {TEXT_FAINT};
        border: 1px solid {BORDER_SOFT};
    }}

    QComboBox QAbstractItemView {{
        background-color: {BG_INPUT};
        color: {TEXT};
        selection-background-color: {ACCENT};
        selection-color: #ffffff;
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 4px;
        outline: none;
    }}
"""

_PROGRESS_BAR = f"""
    QProgressBar {{
        background-color: {BG_INPUT};
        border: none;
        border-radius: 8px;
        text-align: center;
        color: {TEXT};
        font-size: 11px;
        font-weight: 600;
        min-height: 16px;
        max-height: 16px;
    }}

    QProgressBar::chunk {{
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {ACCENT_PRESSED}, stop:1 {ACCENT});
        border-radius: 8px;
    }}
"""

_CHECK_BOX = f"""
    QCheckBox {{
        background-color: transparent;
        color: {TEXT};
        spacing: 8px;
        font-size: 13px;
    }}

    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        background-color: {BG_INPUT};
        border: 1px solid {BORDER};
        border-radius: 4px;
    }}

    QCheckBox::indicator:hover {{
        border: 1px solid {ACCENT};
        background-color: {BG_HOVER};
    }}

    QCheckBox::indicator:checked {{
        background-color: {ACCENT};
        border: 1px solid {ACCENT};
        image: url("{(_ASSETS / 'check.svg').as_posix()}");
    }}

    QCheckBox:focus, QRadioButton:focus {{
        color: {ACCENT};
    }}

    QCheckBox:disabled {{
        color: {TEXT_FAINT};
    }}
"""

_RADIO_BUTTON = f"""
    QRadioButton {{
        background-color: transparent;
        color: {TEXT};
        spacing: 8px;
        font-size: 13px;
        border: none;
        padding: 2px;
    }}

    QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 9px;
        border: 1px solid {BORDER};
        background-color: {BG_INPUT};
    }}

    QRadioButton::indicator:hover {{
        border: 1px solid {ACCENT};
    }}

    QRadioButton::indicator:checked {{
        border: 5px solid {ACCENT};
        background-color: {BG_SURFACE};
    }}

    QRadioButton:disabled {{
        color: {TEXT_FAINT};
    }}
"""

_SCROLL_BARS = f"""
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}

    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}

    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: {BORDER};
        border-radius: 4px;
        min-height: 30px;
        min-width: 30px;
    }}

    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
        background: {TEXT_FAINT};
    }}

    QScrollBar::add-line, QScrollBar::sub-line {{
        background: none;
        border: none;
        width: 0px;
        height: 0px;
    }}

    QScrollBar::add-page, QScrollBar::sub-page {{
        background: none;
    }}
"""

_TEXT_EDIT = f"""
    QTextEdit {{
        background-color: {BG_INPUT};
        color: {TEXT_DIM};
        border: 1px solid {BORDER_SOFT};
        border-radius: 6px;
        font-family: Consolas, "Courier New", monospace;
        font-size: 11px;
        padding: 4px;
        selection-background-color: {ACCENT};
        selection-color: #ffffff;
    }}
"""


def _tab_bar_rules(tab_extras=""):
    """Nested tab widgets rendered as underlined segmented controls."""
    return f"""
    QTabWidget::pane {{
        border: 1px solid {BORDER_SOFT};
        border-radius: 6px;
        background-color: {BG_WINDOW};
        top: -1px;
    }}

    QTabWidget::tab-bar {{
        alignment: left;
        left: 6px;
    }}

    QTabBar::tab {{
        background-color: transparent;
        color: {TEXT_DIM};
        border: 1px solid transparent;
        border-bottom: 2px solid transparent;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        padding: 7px 10px;
        margin-right: 2px;
        font-size: 12px;
        min-width: 0px;
        {tab_extras}
    }}

    QTabBar::tab:selected {{
        background-color: {BG_SURFACE};
        color: {TEXT};
        font-weight: 600;
        border: 1px solid {BORDER_SOFT};
        border-bottom: 2px solid {ACCENT};
    }}

    QTabBar::tab:hover:!selected {{
        background-color: {BG_HOVER};
        color: {TEXT};
    }}
"""


# Plot controls use dark surfaces; the canvas itself keeps a white background.
_MATPLOTLIB_TOOLBAR = """
    QToolBar {
        background-color: #242424;
        border: 1px solid #454545;
        border-radius: 6px;
        spacing: 2px;
        padding: 1px;
    }

    QToolBar QToolButton {
        background-color: transparent;
        color: #eeeeee;
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 3px;
        margin: 1px;
        font-size: 11px;
    }

    QToolBar QToolButton:hover {
        background-color: #383838;
        border: 1px solid #888888;
    }

    QToolBar QToolButton:pressed {
        background-color: #181818;
    }

    QToolBar QToolButton:checked {
        background-color: #505050;
        color: #ffffff;
        border: 1px solid #222222;
    }

    QToolBar QLabel {
        color: #eeeeee;
        background-color: transparent;
        font-size: 11px;
        padding: 2px;
    }
"""

# --- Page-level styles --------------------------------------------------------

# Whole-window style. The sidebar replaces top-level tabs; small page-level
# tabs still group related settings. Scientific plots retain their data colours.
MAIN_WINDOW_STYLE = (
    _BASE + _BUTTONS + _GROUP_BOX + _CHECK_BOX + _RADIO_BUTTON + _SPIN_BOXES
    + _LINE_EDIT + _COMBO_BOX + _SCROLL_BARS + _MATPLOTLIB_TOOLBAR + f"""
    QTabWidget::pane {{
        border: none;
        background-color: {BG_WINDOW};
    }}

    QFrame#stageNavigation {{
        background-color: {BG_SURFACE};
        border-bottom: 1px solid {BORDER_SOFT};
    }}
    QPushButton#workflowNavButton {{
        background-color: {BG_INPUT};
        color: {TEXT_DIM};
        border: 1px solid {BORDER_SOFT};
        border-radius: 5px;
        font-size: 12px;
        padding: 0 10px;
        min-width: 0;
    }}
    QPushButton#workflowNavButton:hover {{
        background-color: {BG_HOVER};
        color: {TEXT};
    }}
    QPushButton#workflowNavButton:checked {{
        background-color: #263a54;
        color: #a8c9ff;
        border: 1px solid {ACCENT};
        font-weight: 700;
    }}
    QPushButton#workflowNavButton:disabled {{
        color: #888888;
        background-color: {BG_WINDOW};
    }}
    QLabel#workspaceTitle {{
        color: {TEXT};
        font-size: 18px;
        font-weight: 600;
    }}

    QTabBar::tab {{
        background-color: transparent;
        color: {TEXT_DIM};
        border: none;
        border-bottom: 3px solid transparent;
        min-width: 150px;
        padding: 11px 22px;
        font-size: 13px;
    }}

    QTabBar::tab:selected {{
        color: {TEXT};
        font-weight: 700;
        border-bottom: 3px solid {ACCENT};
    }}

    QTabBar::tab:hover:!selected {{
        color: {TEXT};
        background-color: {BG_SURFACE};
    }}
"""
)

# Single-widget styles used wherever a spinbox needs explicit styling.
SPIN_BOX_STYLE = _spin_box_rules("QSpinBox")
DOUBLE_SPIN_BOX_STYLE = _spin_box_rules("QDoubleSpinBox")

# Flux Viewer tab (container of the 3-step flow).
FLUX_VIEWER_TAB_STYLE = (
    _BASE + _BUTTONS + _GROUP_BOX + _SPIN_BOXES + _COMBO_BOX + _PROGRESS_BAR
    + _CHECK_BOX + _SCROLL_BARS + f"""
    QStackedWidget {{
        background-color: {BG_WINDOW};
    }}

"""
)

# Step 1: machine parameters page.
MOTOR_INPUT_PAGE_STYLE = (
    _BASE + _LINE_EDIT + _BUTTONS + _GROUP_BOX + _SCROLL_BARS
)

# Step 2: meshing configuration page.
MESHING_PAGE_STYLE = (
    _BASE + _BUTTONS + _tab_bar_rules() + _GROUP_BOX + _COMBO_BOX
    + _SPIN_BOXES + _PROGRESS_BAR + _TEXT_EDIT + _SCROLL_BARS
    + _MATPLOTLIB_TOOLBAR
)

# Step 3: flux density page.
FLUX_DENSITY_PAGE_STYLE = (
    _BASE + _BUTTONS + _GROUP_BOX + _LINE_EDIT + _COMBO_BOX + _SPIN_BOXES
    + _tab_bar_rules() + _PROGRESS_BAR + _CHECK_BOX + _SCROLL_BARS
    + _MATPLOTLIB_TOOLBAR
)

# Connection-matrix dialog.
MATRIX_DIALOG_STYLE = _SCROLL_BARS + f"""
    QDialog {{
        background-color: {BG_WINDOW};
    }}
    QTableWidget {{
        background-color: {BG_WINDOW};
        color: {TEXT};
        gridline-color: {BORDER_SOFT};
        border: none;
        font-size: 12px;
    }}
    QHeaderView::section {{
        background-color: {BG_SURFACE};
        color: {TEXT_DIM};
        padding: 6px;
        border: none;
        font-weight: 600;
    }}
    QTableWidget::item {{
        border: none;
    }}
    QTableWidget::item:selected {{
        background-color: {ACCENT};
        color: #ffffff;
    }}
    QTableCornerButton::section {{
        background-color: {BG_SURFACE};
        border: none;
    }}
"""

# --- Reusable inline styles ----------------------------------------------------

PAGE_TITLE_STYLE = (
    f"color: {TEXT}; font-size: 20px; font-weight: 700;"
    "background: transparent;"
)

PAGE_SUBTITLE_STYLE = (
    f"color: {TEXT_DIM}; font-size: 12px; background: transparent;"
)

SECTION_LABEL_STYLE = (
    f"color: {TEXT_DIM}; font-size: 11px; font-weight: 700;"
    "background: transparent; letter-spacing: 1px;"
)

# --- Status + badge helpers -----------------------------------------------------

_STATUS_COLORS = {
    'muted': TEXT_FAINT,
    'info': ACCENT_HOVER,
    'success': SUCCESS,
    'warning': WARNING,
    'error': DANGER,
}

# (text color, tinted background) per badge kind.
_BADGE_TINTS = {
    'muted': (TEXT_DIM, '#282828'),
    'info': (TEXT_DIM, '#282828'),
    'success': (SUCCESS, '#303030'),
    'warning': (WARNING, '#303030'),
    'error': (DANGER, '#383838'),
}


def set_status(label, text, kind='muted'):
    """Show neutral status feedback; the message carries the state."""
    label.setText(text)
    label.setStyleSheet(
        f"color: {_STATUS_COLORS.get(kind, TEXT_FAINT)};"
        "font-size: 12px; font-weight: 600; background: transparent;"
        "border: none;")


def badge_style(kind='muted'):
    """Tinted rounded 'chip' style for QLabel badges."""
    color, tint = _BADGE_TINTS.get(kind, _BADGE_TINTS['muted'])
    return (
        f"color: {color}; background-color: {tint};"
        f"border: 1px solid {color}; border-radius: 5px;"
        "padding: 6px 10px; font-weight: 600; font-size: 12px;")
