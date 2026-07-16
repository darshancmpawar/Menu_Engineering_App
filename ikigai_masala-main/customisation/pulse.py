"""Pulse / OP Lens light-theme styling for the customisation editor.

The whole app now uses the Pulse light theme (see ``ui/styles.py`` for the
planner). This module holds the editor-specific components (step cards,
counter panels, etc.) layered on the shared palette from
``ui.theme_tokens``.
"""

# ---------------------------------------------------------------------------
# Brand tokens — single source of truth in ui.theme_tokens.
# PULSE_THEME_COLORS is re-exported here for callers that import it from this
# module (e.g. customisation.theme_editor).
# ---------------------------------------------------------------------------
from ui.theme_tokens import (  # noqa: F401 — re-exported / used in the f-string
    YELLOW, YELLOW_HOVER, BLUE, BLUE_HOVER, PURPLE, GREEN, ORANGE, RED,
    PAGE_BG, CARD_BG, ALT_ROW, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    TEXT_DISABLED, BORDER, PULSE_THEME_COLORS,
)


PULSE_EDITOR_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Figtree:wght@300;400;500;600;700;800&display=swap');

/* ================================================================
   GLOBAL — Pulse light canvas
   ================================================================ */
.stApp {{
    background: {PAGE_BG} !important;
    font-family: 'Figtree', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    color: {TEXT_PRIMARY} !important;
}}
.block-container {{
    padding: 2.5rem 2rem 3rem !important;
    max-width: 1180px !important;
}}
[data-testid="stMarkdownContainer"] p {{ color: {TEXT_SECONDARY}; }}

/* App chrome — light header, hide footer/deploy badge */
header[data-testid="stHeader"] {{
    background: {CARD_BG} !important;
    border-bottom: 1px solid {BORDER} !important;
}}
[data-testid="stToolbar"] button, [data-testid="stToolbar"] a {{ color: {TEXT_TERTIARY} !important; }}
[data-testid="collapsedControl"] button,
[data-testid="stSidebarCollapsedControl"] button {{ color: {TEXT_TERTIARY} !important; }}
footer, .stDeployButton, [data-testid="stDecoration"],
[data-testid="manage-app-button"] {{ display: none !important; }}

/* ================================================================
   EDITOR HEADER
   ================================================================ */
.pulse-title {{
    font-size: 1.6rem; font-weight: 700; color: {TEXT_PRIMARY};
    letter-spacing: -0.4px; margin: 0; line-height: 1.2;
}}
.pulse-subtitle {{
    font-size: 0.9rem; color: {TEXT_TERTIARY}; margin: 0.2rem 0 0; font-weight: 400;
}}

/* ================================================================
   STEP HEADERS
   ================================================================ */
.pulse-step {{
    display: flex; align-items: center; gap: 0.6rem; margin: 0.25rem 0 0.6rem;
}}
.pulse-step-badge {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 26px; height: 26px; border-radius: 8px; flex-shrink: 0;
    background: {YELLOW}; color: {TEXT_PRIMARY};
    font-weight: 700; font-size: 0.8rem; box-shadow: 0 1px 3px rgba(254,191,52,0.4);
}}
.pulse-step-title {{
    font-size: 1.05rem; font-weight: 700; color: {TEXT_PRIMARY};
    letter-spacing: -0.2px; margin: 0;
}}
.pulse-step-desc {{
    font-size: 0.8rem; color: {TEXT_TERTIARY}; margin: -0.35rem 0 0.75rem 2.2rem;
}}

/* ================================================================
   CARDS — style Streamlit bordered containers as white Pulse cards
   ================================================================ */
[data-testid="stVerticalBlockBorderWrapper"] {{
    background: {CARD_BG} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 14px !important;
    padding: 1.1rem 1.35rem !important;
    box-shadow: 0 1px 3px rgba(19,19,19,0.04) !important;
    margin-bottom: 0.35rem;
}}

/* Sub-section headings inside a counter panel */
.pulse-sub-title {{
    font-size: 0.92rem; font-weight: 700; color: {TEXT_PRIMARY}; margin: 0 0 0.15rem;
}}
.pulse-sub-desc {{
    font-size: 0.76rem; color: {TEXT_TERTIARY}; margin: 0 0 0.85rem;
}}
.pulse-hint {{ font-size: 0.74rem; color: {TEXT_TERTIARY}; margin: 0.45rem 0 0; }}
.pulse-hint.ok {{ color: {GREEN}; }}
.pulse-hint.warn {{ color: {RED}; font-weight: 600; }}
.pulse-hint.accent {{ color: {BLUE}; }}

/* Unsaved-changes indicator */
.pulse-changes {{
    display: inline-flex; align-items: center; gap: 0.4rem;
    padding: 0.3rem 0.8rem; background: {PULSE_THEME_COLORS['chinese'][0]};
    border: 1px solid rgba(247,141,0,0.3); border-radius: 99px;
    font-size: 0.76rem; color: {ORANGE}; font-weight: 600; margin-bottom: 0.5rem;
}}

/* ================================================================
   BUTTONS
   ================================================================ */
.stButton > button, .stDownloadButton > button,
button[data-testid="stBaseButton-primary"],
button[data-testid="stBaseButton-secondary"] {{
    border-radius: 8px !important; font-weight: 600 !important;
    font-size: 0.9rem !important; font-family: 'Figtree', sans-serif !important;
    transition: all 0.15s ease !important;
}}
/* Primary — Brand Yellow with dark text */
.stButton > button[kind="primary"],
button[data-testid="stBaseButton-primary"] {{
    background: {YELLOW} !important; color: {TEXT_PRIMARY} !important;
    border: 1px solid {YELLOW} !important; box-shadow: 0 1px 3px rgba(254,191,52,0.4) !important;
}}
.stButton > button[kind="primary"]:hover,
button[data-testid="stBaseButton-primary"]:hover {{
    background: {YELLOW_HOVER} !important; border-color: {YELLOW_HOVER} !important;
}}
/* Secondary — white with border */
.stButton > button[kind="secondary"], .stDownloadButton > button,
button[data-testid="stBaseButton-secondary"] {{
    background: {CARD_BG} !important; color: {TEXT_PRIMARY} !important;
    border: 1px solid {BORDER} !important;
}}
.stButton > button[kind="secondary"]:hover,
button[data-testid="stBaseButton-secondary"]:hover {{
    background: {ALT_ROW} !important; border-color: {TEXT_DISABLED} !important;
    color: {TEXT_PRIMARY} !important;
}}

/* ================================================================
   INPUTS / SELECTS / NUMBER
   ================================================================ */
input, textarea,
.stTextInput input, .stNumberInput input,
[data-baseweb="input"] input, [data-baseweb="base-input"] input {{
    background-color: {CARD_BG} !important;
    color: {TEXT_PRIMARY} !important;
    -webkit-text-fill-color: {TEXT_PRIMARY} !important;
    border-radius: 8px !important;
}}
[data-baseweb="input"], [data-baseweb="base-input"] {{
    background-color: {CARD_BG} !important;
    border-color: {BORDER} !important; border-radius: 8px !important;
}}
.stSelectbox [data-baseweb="select"], .stSelectbox [data-baseweb="select"] > div,
.stMultiSelect [data-baseweb="select"], .stMultiSelect [data-baseweb="select"] > div {{
    background-color: {CARD_BG} !important;
    border-color: {BORDER} !important; border-radius: 8px !important;
}}
.stSelectbox [data-baseweb="select"] span,
.stMultiSelect [data-baseweb="select"] span {{
    color: {TEXT_PRIMARY} !important; -webkit-text-fill-color: {TEXT_PRIMARY} !important;
}}
.stSelectbox svg, .stMultiSelect svg, [data-baseweb="select"] svg {{ fill: {TEXT_TERTIARY} !important; }}
input::placeholder {{ color: {TEXT_DISABLED} !important; -webkit-text-fill-color: {TEXT_DISABLED} !important; opacity: 1 !important; }}

/* Multiselect chosen tags — light blue chips */
.stMultiSelect [data-baseweb="tag"] {{
    background-color: {PULSE_THEME_COLORS['south'][0]} !important;
    color: {BLUE} !important; border-radius: 6px !important;
}}
.stMultiSelect [data-baseweb="tag"] svg {{ fill: {BLUE} !important; }}

/* Dropdown popovers */
[data-baseweb="popover"], [data-baseweb="menu"], [role="listbox"],
[data-baseweb="popover"] > div, [data-baseweb="menu"] ul {{
    background: {CARD_BG} !important; border-color: {BORDER} !important;
}}
[data-baseweb="menu"] li, [role="option"] {{ color: {TEXT_PRIMARY} !important; background: transparent !important; }}
[data-baseweb="menu"] li:hover, [role="option"]:hover,
[role="option"][aria-selected="true"] {{ background: {PULSE_THEME_COLORS['south'][0]} !important; }}

/* Focus ring — Brand Blue */
input:focus, textarea:focus,
[data-baseweb="input"]:focus-within, [data-baseweb="select"]:focus-within {{
    border-color: {BLUE} !important; box-shadow: 0 0 0 1px {BLUE} !important;
}}

/* Number input +/- steppers */
.stNumberInput button {{
    background: {ALT_ROW} !important; color: {TEXT_SECONDARY} !important;
    border-color: {BORDER} !important;
}}
.stNumberInput button:hover {{ background: {BORDER} !important; color: {TEXT_PRIMARY} !important; }}

/* Labels */
.stTextInput label, .stNumberInput label, .stSelectbox label,
.stMultiSelect label, .stRadio label, .stSlider label {{
    color: {TEXT_SECONDARY} !important; font-weight: 500 !important;
}}

/* ================================================================
   RADIO — used for mode toggles
   ================================================================ */
.stRadio [role="radiogroup"] {{ gap: 0.6rem; }}
.stRadio [role="radiogroup"] label p {{ color: {TEXT_PRIMARY} !important; font-weight: 500; }}
.stRadio [data-baseweb="radio"] div[aria-checked="true"] {{ border-color: {BLUE} !important; }}
.stRadio [data-baseweb="radio"] div[aria-checked="true"] > div {{ background: {BLUE} !important; }}

/* ================================================================
   TABS — per-counter panels
   ================================================================ */
.stTabs [data-baseweb="tab-list"] {{
    gap: 0.35rem; border-bottom: 1px solid {BORDER};
}}
.stTabs [data-baseweb="tab"] {{
    color: {TEXT_TERTIARY} !important; font-weight: 600 !important;
    font-family: 'Figtree', sans-serif !important;
    padding: 0.4rem 0.9rem;
}}
.stTabs [data-baseweb="tab"][aria-selected="true"] {{ color: {BLUE} !important; }}
.stTabs [data-baseweb="tab-highlight"] {{ background: {BLUE} !important; }}

/* ================================================================
   MISC
   ================================================================ */
hr {{ border-color: {BORDER} !important; }}
.stAlert {{ border-radius: 10px !important; }}
.stSpinner > div {{ border-top-color: {BLUE} !important; }}
</style>
"""
