"""Shared design system: color tokens, typography, and Qt stylesheets.

Every page composes its stylesheet from the fragments below so spacing,
colors, radii, and interactive states (hover / focus / pressed / disabled)
stay consistent across the whole application.

Conventions used by the pages:
  - ``btn.setObjectName("primaryButton")`` promotes a button to the accent
    (primary action) style.
  - ``set_status(label, text, kind)`` renders color-coded feedback lines
    (kind: muted / info / success / warning / error).
  - ``badge_style(kind)`` returns a tinted "chip" style for QLabels.
"""

# --- Design tokens -----------------------------------------------------------

# Background layers (darkest -> lightest).
BG_WINDOW = "#14171c"     # page background
BG_SURFACE = "#1d222a"    # cards, group boxes, bars
BG_INPUT = "#262d37"      # editable fields and buttons
BG_HOVER = "#303947"      # hover fill
BG_PRESSED = "#10141a"    # pressed fill

BORDER = "#39424f"
BORDER_SOFT = "#2a313c"

TEXT = "#e8ebef"
TEXT_DIM = "#9aa4b2"
TEXT_FAINT = "#6d7785"

ACCENT = "#4c8dff"
ACCENT_HOVER = "#6ba1ff"
ACCENT_PRESSED = "#3a72d8"

SUCCESS = "#3ddc84"
WARNING = "#f0b429"
DANGER = "#ff6b6b"

FONT_FAMILY = '"Segoe UI", "Helvetica Neue", Arial, sans-serif'

# --- Fragments ---------------------------------------------------------------

_BASE = f"""
    QWidget {{
        background-color: {BG_WINDOW};
        color: {TEXT};
        font-family: {FONT_FAMILY};
        font-size: 13px;
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
        padding: 7px 14px;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 600;
        min-width: 80px;
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
        border-radius: 8px;
        margin-top: 14px;
        padding: 10px 6px 6px 6px;
        font-weight: 600;
        font-size: 13px;
    }}

    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 10px;
        padding: 0 6px;
        color: {ACCENT_HOVER};
        background-color: {BG_WINDOW};
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
        min-width: 70px;
        selection-background-color: {ACCENT};
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
    """Dark style block for QSpinBox-like widgets."""
    return f"""
    {selector} {{
        background-color: {BG_INPUT};
        color: {TEXT};
        border: 1px solid {BORDER};
        padding: 5px 8px;
        border-radius: 6px;
        font-size: 13px;
        min-width: 70px;
        selection-background-color: {ACCENT};
    }}

    {selector}:hover {{
        border: 1px solid {TEXT_FAINT};
    }}

    {selector}:focus {{
        border: 1px solid {ACCENT};
        background-color: {BG_HOVER};
    }}

    {selector}:disabled {{
        background-color: {BG_SURFACE};
        color: {TEXT_FAINT};
        border: 1px solid {BORDER_SOFT};
    }}

    {selector}::up-button, {selector}::down-button {{
        background-color: {BG_HOVER};
        border: none;
        width: 18px;
    }}

    {selector}::up-button {{
        border-top-right-radius: 5px;
    }}

    {selector}::down-button {{
        border-bottom-right-radius: 5px;
    }}

    {selector}::up-button:hover, {selector}::down-button:hover {{
        background-color: {ACCENT};
    }}

    {selector}::up-arrow, {selector}::down-arrow {{
        width: 7px;
        height: 7px;
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

    QComboBox::drop-down {{
        background-color: transparent;
        border: none;
        width: 24px;
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
        background-color: #ffffff;
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
        background-color: {BG_PRESSED};
        color: {TEXT_DIM};
        border: 1px solid {BORDER_SOFT};
        border-radius: 6px;
        font-family: Consolas, "Courier New", monospace;
        font-size: 11px;
        padding: 4px;
        selection-background-color: {ACCENT};
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


# Light styling for the matplotlib navigation toolbar (sits on white canvases).
_MATPLOTLIB_TOOLBAR = """
    QToolBar {
        background-color: #f4f6f8;
        border: 1px solid #d7dce1;
        border-radius: 6px;
        spacing: 2px;
        padding: 2px;
    }

    QToolBar QToolButton {
        background-color: transparent;
        color: #333333;
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 4px;
        margin: 1px;
        font-size: 11px;
    }

    QToolBar QToolButton:hover {
        background-color: #e2ecfb;
        border: 1px solid #4c8dff;
    }

    QToolBar QToolButton:pressed {
        background-color: #cbdffa;
    }

    QToolBar QToolButton:checked {
        background-color: #4c8dff;
        color: #ffffff;
        border: 1px solid #3a72d8;
    }

    QToolBar QLabel {
        color: #333333;
        background-color: transparent;
        font-size: 11px;
        padding: 2px;
    }
"""

# --- Page-level styles --------------------------------------------------------

# Whole-window style (set once on the main window). Top-level tabs are wide
# underlined headers; shared widget rules cover the MMF tab which has no
# page-level stylesheet of its own.
MAIN_WINDOW_STYLE = (
    _BASE + _BUTTONS + _GROUP_BOX + _CHECK_BOX + _RADIO_BUTTON + _SPIN_BOXES
    + _SCROLL_BARS + f"""
    QTabWidget::pane {{
        border: none;
        background-color: {BG_WINDOW};
    }}

    QTabBar::tab {{
        background-color: transparent;
        color: {TEXT_DIM};
        border: none;
        border-bottom: 3px solid transparent;
        min-width: 220px;
        padding: 12px 24px;
        font-size: 14px;
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

    QFrame#fluxStepHeader, QFrame#fluxNavBar {{
        background-color: {BG_SURFACE};
        border: 1px solid {BORDER_SOFT};
        border-radius: 8px;
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

# Connection-matrix dialog (dark table + slim scrollbars).
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
    f"color: {TEXT}; font-size: 18px; font-weight: 700;"
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
    'muted': (TEXT_DIM, "rgba(154, 164, 178, 26)"),
    'info': (ACCENT_HOVER, "rgba(76, 141, 255, 30)"),
    'success': (SUCCESS, "rgba(61, 220, 132, 30)"),
    'warning': (WARNING, "rgba(240, 180, 41, 30)"),
    'error': (DANGER, "rgba(255, 107, 107, 30)"),
}


def set_status(label, text, kind='muted'):
    """Show color-coded status feedback on a QLabel."""
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


# --- Step indicator (Flux Viewer wizard header) ----------------------------------

_STEP_BADGE_BASE = (
    "border-radius: 14px; font-weight: 700; font-size: 13px;"
)


def step_badge_style(state):
    """Circular number badge for one wizard step.

    state: 'active' (current step), 'done' (completed), or 'todo'.
    """
    if state == 'active':
        return (_STEP_BADGE_BASE
                + f"background-color: {ACCENT}; color: #ffffff;"
                  f"border: 1px solid {ACCENT};")
    if state == 'done':
        return (_STEP_BADGE_BASE
                + "background-color: rgba(61, 220, 132, 30);"
                  f"color: {SUCCESS}; border: 1px solid {SUCCESS};")
    return (_STEP_BADGE_BASE
            + f"background-color: transparent; color: {TEXT_FAINT};"
              f"border: 1px solid {BORDER};")


def step_title_style(state):
    """Step name next to its badge."""
    if state == 'active':
        return (f"color: {TEXT}; font-size: 13px; font-weight: 700;"
                "background: transparent;")
    if state == 'done':
        return (f"color: {SUCCESS}; font-size: 13px; font-weight: 600;"
                "background: transparent;")
    return (f"color: {TEXT_FAINT}; font-size: 13px;"
            "background: transparent;")


def step_connector_style(done):
    """Thin line between steps; lights up once the step before it is done."""
    color = SUCCESS if done else BORDER_SOFT
    return f"background-color: {color}; border: none; border-radius: 1px;"
