"""App-wide CSS for the Streamlit planner — Pulse / OP Lens light theme.

Built from the shared palette in ``ui/theme_tokens.py`` so the planner and the
customisation editor (``customisation/pulse.py``) share one visual language.
Extracted from app.py so the entry-point file stays small.
"""

from ui.theme_tokens import (
    YELLOW, YELLOW_HOVER, BLUE, BLUE_HOVER, GREEN, ORANGE, RED,
    PAGE_BG, CARD_BG, ALT_ROW, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    TEXT_DISABLED, BORDER, TINT_BLUE, TINT_ORANGE, TINT_YELLOW, PURPLE,
)

STYLES = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Figtree:wght@300;400;500;600;700;800&display=swap');

    /* ================================================================
       DESIGN TOKENS (Pulse light)
       ================================================================ */
    :root {{
        --bg-primary:    {PAGE_BG};
        --bg-secondary:  {CARD_BG};
        --bg-tertiary:   {ALT_ROW};
        --bg-elevated:   {CARD_BG};
        --bg-hover:      {TINT_BLUE};
        --border-subtle: {BORDER};
        --border-default:#D5D5D5;
        --text-primary:  {TEXT_PRIMARY};
        --text-secondary:{TEXT_SECONDARY};
        --text-tertiary: {TEXT_TERTIARY};
        --text-muted:    {TEXT_DISABLED};
        --accent:        {BLUE};
        --accent-dim:    {BLUE_HOVER};
        --yellow:        {YELLOW};
        --yellow-hover:  {YELLOW_HOVER};
        --success:       {GREEN};
        --warning:       {ORANGE};
        --danger:        {RED};
        --radius-sm:     6px;
        --radius-md:     10px;
        --radius-lg:     14px;
        --radius-xl:     20px;
        --shadow-sm:     0 1px 2px rgba(19,19,19,0.05);
        --shadow-md:     0 4px 12px rgba(19,19,19,0.08);
        --shadow-lg:     0 8px 30px rgba(19,19,19,0.12);
        --transition:    all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }}

    /* ================================================================
       GLOBAL
       ================================================================ */
    .stApp {{
        background: var(--bg-primary);
        font-family: 'Figtree', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        color: var(--text-primary);
    }}
    .block-container {{
        padding: 3.5rem 2rem 2rem;
        max-width: 1400px;
    }}

    /* ================================================================
       STREAMLIT HEADER — light
       ================================================================ */
    header[data-testid="stHeader"] {{
        background: var(--bg-secondary) !important;
        border-bottom: 1px solid var(--border-subtle) !important;
    }}
    [data-testid="stToolbar"] button,
    [data-testid="stToolbar"] a {{ color: var(--text-tertiary) !important; }}
    [data-testid="stToolbar"] button:hover,
    [data-testid="stToolbar"] a:hover {{ color: var(--text-primary) !important; }}
    [data-testid="collapsedControl"] button,
    [data-testid="stSidebarCollapsedControl"] button {{ color: var(--text-tertiary) !important; }}
    [data-testid="collapsedControl"] button:hover,
    [data-testid="stSidebarCollapsedControl"] button:hover {{ color: var(--text-primary) !important; }}
    footer, .stDeployButton,
    [data-testid="stDecoration"] {{ display: none !important; }}
    ._profileContainer_gzau3_53,
    [data-testid="manage-app-button"] {{ display: none !important; }}

    /* ================================================================
       SIDEBAR
       ================================================================ */
    [data-testid="stSidebar"] {{
        background: var(--bg-secondary) !important;
        border-right: 1px solid var(--border-subtle) !important;
    }}
    [data-testid="stSidebar"][aria-expanded="true"] {{
        min-width: 300px !important;
        max-width: 300px !important;
    }}
    [data-testid="stSidebar"] label {{
        color: var(--text-secondary) !important;
        font-size: 0.78rem !important;
        font-weight: 500 !important;
        letter-spacing: 0.02em;
    }}

    /* Brand block */
    .sidebar-brand {{
        padding: 0.5rem 0 1.5rem;
        border-bottom: 1px solid var(--border-subtle);
        margin-bottom: 1.5rem;
    }}
    .sidebar-brand-row {{ display: flex; align-items: center; gap: 0.65rem; }}
    .sidebar-brand-icon {{
        width: 36px; height: 36px; border-radius: var(--radius-md);
        background: var(--yellow);
        display: flex; align-items: center; justify-content: center;
        font-size: 1.1rem; flex-shrink: 0;
        box-shadow: 0 1px 4px rgba(254,191,52,0.5);
    }}
    .sidebar-brand h2 {{
        margin: 0; font-size: 1.15rem; color: var(--text-primary);
        font-weight: 700; letter-spacing: -0.4px; line-height: 1.2;
    }}
    .sidebar-brand p {{
        margin: 0; font-size: 0.7rem; color: var(--text-tertiary);
        font-weight: 400; letter-spacing: 0.02em;
    }}

    /* User chip */
    .user-chip {{
        display: flex; align-items: center; gap: 0.55rem;
        padding: 0.55rem 0.7rem; background: var(--bg-tertiary);
        border: 1px solid var(--border-subtle); border-radius: var(--radius-md);
        margin-bottom: 0.75rem;
    }}
    .user-avatar {{
        width: 30px; height: 30px; border-radius: 50%;
        background: var(--accent);
        display: flex; align-items: center; justify-content: center;
        font-size: 0.72rem; font-weight: 700; color: #fff; flex-shrink: 0;
    }}
    .user-chip-info {{ flex: 1; min-width: 0; }}
    .user-chip-name {{
        font-size: 0.8rem; font-weight: 600; color: var(--text-primary);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .user-chip-role {{
        font-size: 0.65rem; color: var(--text-tertiary);
        text-transform: uppercase; letter-spacing: 0.04em; font-weight: 500;
    }}

    /* ================================================================
       PAGE HEADER
       ================================================================ */
    .page-title {{
        font-size: 1.65rem; font-weight: 800; color: var(--text-primary);
        margin: 0; letter-spacing: -0.5px; line-height: 1.2;
    }}
    .page-subtitle {{
        font-size: 0.82rem; color: var(--text-tertiary); margin: 0.2rem 0 0;
        font-weight: 400;
    }}

    /* ================================================================
       METRIC CARDS
       ================================================================ */
    .metrics-grid {{
        display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 0.75rem; margin-bottom: 1.75rem;
    }}
    .metric-card {{
        background: var(--bg-secondary); border: 1px solid var(--border-subtle);
        border-radius: var(--radius-lg); padding: 1rem 1.15rem;
        position: relative; overflow: hidden; transition: var(--transition);
        box-shadow: var(--shadow-sm);
    }}
    .metric-card:hover {{
        border-color: var(--border-default);
        transform: translateY(-1px); box-shadow: var(--shadow-md);
    }}
    .metric-card::before {{
        content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
    }}
    .metric-card:nth-child(1)::before {{ background: {BLUE}; }}
    .metric-card:nth-child(2)::before {{ background: {YELLOW}; }}
    .metric-card:nth-child(3)::before {{ background: {GREEN}; }}
    .metric-card:nth-child(4)::before {{ background: {PURPLE}; }}
    .metric-card:nth-child(5)::before {{ background: {ORANGE}; }}
    .metric-label {{
        font-size: 0.65rem; color: var(--text-tertiary);
        text-transform: uppercase; letter-spacing: 0.06em;
        font-weight: 600; margin-bottom: 0.3rem;
    }}
    .metric-value {{
        font-size: 1.5rem; font-weight: 800; color: var(--text-primary);
        letter-spacing: -0.5px; line-height: 1;
    }}

    /* ================================================================
       MENU TABLE
       ================================================================ */
    .menu-table-wrap {{
        border: 1px solid var(--border-subtle); border-radius: var(--radius-lg);
        overflow: hidden; box-shadow: var(--shadow-sm); background: var(--bg-secondary);
    }}
    .menu-table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
    .menu-table thead th {{
        background: {TEXT_PRIMARY}; color: #fff;
        padding: 0.75rem 0.85rem; text-align: center; font-weight: 600;
        font-size: 0.76rem; border-right: 1px solid rgba(255,255,255,0.08);
    }}
    .menu-table thead th:first-child {{
        text-align: left; min-width: 120px; background: #000;
    }}
    .menu-table thead th:last-child {{ border-right: none; }}
    .day-label {{
        display: block; color: #fff; font-weight: 700;
        font-size: 0.82rem; margin-bottom: 4px;
    }}
    .theme-tag {{
        display: inline-flex; align-items: center; gap: 4px;
        padding: 2px 8px; border-radius: 99px;
        font-size: 0.6rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.04em; line-height: 1.6;
    }}
    .menu-table tbody td {{
        padding: 0.55rem 0.85rem;
        border-bottom: 1px solid var(--border-subtle);
        border-right: 1px solid var(--border-subtle);
        color: var(--text-secondary); background: var(--bg-secondary);
        vertical-align: middle; transition: background 0.15s ease;
    }}
    .menu-table tbody tr:nth-child(even) td {{ background: var(--bg-tertiary); }}
    .menu-table tbody td:first-child {{
        font-weight: 600; color: var(--text-secondary); background: var(--bg-tertiary);
        font-size: 0.76rem; white-space: nowrap; min-width: 120px;
        border-right: 1px solid var(--border-subtle);
    }}
    .menu-table tbody td:last-child {{ border-right: none; }}
    .menu-table tbody tr:last-child td {{ border-bottom: none; }}
    /* Full black grid borders on every cell (spreadsheet-style). */
    .menu-table {{ border: 1px solid #131313; }}
    .menu-table th, .menu-table td {{ border: 1px solid #131313 !important; }}
    .menu-table tbody tr:hover td {{ background: var(--bg-hover); }}
    .menu-table tbody tr:hover td:first-child {{ background: {TINT_BLUE}; }}
    .item-name {{ color: var(--text-primary); font-weight: 500; font-size: 0.8rem; }}
    .item-nonveg {{ color: #C40D1B !important; font-weight: 700 !important; }}
    .color-pill {{
        display: inline-block; margin-left: 5px; padding: 1px 6px;
        border-radius: 99px; font-size: 0.6rem; font-weight: 600;
    }}
    .cell-empty {{ color: var(--text-muted); font-size: 0.8rem; }}

    /* Pool warnings */
    .pool-warn-bar {{
        display: flex; align-items: center; gap: 0.5rem;
        padding: 0.6rem 1rem; margin-bottom: 1rem;
        background: {TINT_ORANGE};
        border: 1px solid rgba(247,141,0,0.25);
        border-radius: var(--radius-md); font-size: 0.78rem; color: #C56A00;
    }}

    /* Empty state */
    .empty-state {{
        text-align: center; padding: 5rem 2rem;
        border: 2px dashed var(--border-subtle);
        border-radius: var(--radius-xl); margin: 3rem auto; max-width: 500px;
        background: var(--bg-secondary);
    }}
    .empty-icon {{
        width: 64px; height: 64px; margin: 0 auto 1rem; border-radius: 50%;
        background: {TINT_YELLOW};
        display: flex; align-items: center; justify-content: center;
        font-size: 1.6rem;
    }}
    .empty-state h3 {{
        color: var(--text-primary); margin: 0 0 0.4rem; font-size: 1.15rem; font-weight: 700;
    }}
    .empty-state p {{ color: var(--text-tertiary); font-size: 0.85rem; margin: 0; line-height: 1.5; }}

    /* Changes log */
    .log-entry {{
        padding: 0.4rem 0.75rem; background: var(--bg-tertiary);
        border-left: 3px solid var(--accent);
        border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
        margin-bottom: 0.35rem; font-size: 0.78rem; color: var(--text-secondary);
        animation: fadeInUp 0.18s ease-out;
    }}
    .log-entry.log-diff {{
        display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap;
    }}
    .log-day {{
        color: var(--text-primary); font-weight: 600;
        font-size: 0.74rem; letter-spacing: 0.02em;
    }}
    .log-slot {{
        color: var(--text-tertiary); font-weight: 600;
        font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.04em;
    }}
    .log-sep {{ color: var(--text-muted); font-size: 0.72rem; }}
    .log-old {{
        color: var(--text-tertiary); text-decoration: line-through;
        text-decoration-color: rgba(250,16,36,0.4); font-size: 0.78rem;
    }}
    .log-arrow {{ color: var(--accent); font-weight: 700; padding: 0 2px; }}
    .log-new {{
        color: var(--success); font-weight: 600; font-size: 0.8rem;
    }}
    .regen-day-header {{
        font-weight: 700; font-size: 0.82rem; color: var(--text-primary);
        margin-bottom: 0.3rem; display: flex; align-items: center; gap: 0.4rem;
    }}

    @keyframes fadeInUp {{
        from {{ opacity: 0; transform: translateY(2px); }}
        to   {{ opacity: 1; transform: translateY(0); }}
    }}
    .menu-table-wrap, .metrics-grid {{
        animation: fadeInUp 0.22s ease-out;
    }}

    /* ================================================================
       STREAMLIT COMPONENT OVERRIDES
       ================================================================ */

    /* --- BUTTONS --- */
    .stButton > button,
    .stFormSubmitButton > button,
    .stDownloadButton > button,
    button[data-testid="baseButton-secondary"],
    button[data-testid="baseButton-primary"],
    button[data-testid="stBaseButton-secondary"],
    button[data-testid="stBaseButton-primary"] {{
        border-radius: var(--radius-sm) !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
        font-family: 'Figtree', sans-serif !important;
        transition: var(--transition) !important;
    }}
    /* Primary buttons — Brand Yellow with dark text */
    .stButton > button[kind="primary"],
    .stFormSubmitButton > button,
    button[data-testid="baseButton-primary"],
    button[data-testid="stBaseButton-primary"] {{
        background: var(--yellow) !important;
        border: 1px solid var(--yellow) !important;
        color: {TEXT_PRIMARY} !important;
        box-shadow: 0 1px 3px rgba(254,191,52,0.4) !important;
    }}
    .stButton > button[kind="primary"]:hover,
    .stFormSubmitButton > button:hover,
    button[data-testid="baseButton-primary"]:hover,
    button[data-testid="stBaseButton-primary"]:hover {{
        background: var(--yellow-hover) !important; border-color: var(--yellow-hover) !important;
        transform: translateY(-1px);
    }}
    /* Secondary buttons — white with border */
    .stButton > button:not([kind="primary"]),
    .stDownloadButton > button,
    button[data-testid="baseButton-secondary"],
    button[data-testid="stBaseButton-secondary"] {{
        background: var(--bg-secondary) !important;
        color: var(--text-primary) !important;
        border: 1px solid var(--border-subtle) !important;
    }}
    .stButton > button:not([kind="primary"]):hover,
    .stDownloadButton > button:hover,
    button[data-testid="baseButton-secondary"]:hover,
    button[data-testid="stBaseButton-secondary"]:hover {{
        background: var(--bg-tertiary) !important;
        color: var(--text-primary) !important;
        border-color: var(--border-default) !important;
    }}

    /* --- INPUTS --- dark text on white */
    input, textarea, select,
    .stTextInput input,
    .stNumberInput input,
    .stDateInput input,
    .stTextArea textarea,
    [data-baseweb="input"] input,
    [data-baseweb="base-input"] input,
    [data-baseweb="textarea"] textarea {{
        background-color: var(--bg-secondary) !important;
        border-color: var(--border-subtle) !important;
        color: {TEXT_PRIMARY} !important;
        -webkit-text-fill-color: {TEXT_PRIMARY} !important;
        border-radius: var(--radius-sm) !important;
        caret-color: {TEXT_PRIMARY} !important;
    }}
    .stSelectbox [data-baseweb="select"],
    .stSelectbox [data-baseweb="select"] > div,
    .stMultiSelect [data-baseweb="select"],
    .stMultiSelect [data-baseweb="select"] > div {{
        background-color: var(--bg-secondary) !important;
        border-color: var(--border-subtle) !important;
        border-radius: var(--radius-sm) !important;
    }}
    .stSelectbox [data-baseweb="select"] span,
    .stMultiSelect [data-baseweb="select"] span {{
        color: {TEXT_PRIMARY} !important;
        -webkit-text-fill-color: {TEXT_PRIMARY} !important;
    }}
    .stSelectbox svg, .stMultiSelect svg,
    [data-baseweb="select"] svg {{ fill: var(--text-tertiary) !important; }}
    input::placeholder, textarea::placeholder,
    [data-baseweb="input"] input::placeholder {{
        color: var(--text-muted) !important;
        -webkit-text-fill-color: var(--text-muted) !important;
        opacity: 1 !important;
    }}
    /* Multiselect tags — light blue chips */
    .stMultiSelect [data-baseweb="tag"] {{
        background-color: {TINT_BLUE} !important;
        color: {BLUE} !important; border-radius: 6px !important;
    }}
    .stMultiSelect [data-baseweb="tag"] svg {{ fill: {BLUE} !important; }}
    /* Dropdown menus */
    [data-baseweb="popover"], [data-baseweb="menu"],
    [data-baseweb="popover"] ul, [data-baseweb="menu"] ul,
    [data-baseweb="popover"] > div, [role="listbox"] {{
        background: var(--bg-secondary) !important;
        background-color: var(--bg-secondary) !important;
        border-color: var(--border-subtle) !important;
    }}
    [data-baseweb="menu"] li, [role="option"] {{
        color: {TEXT_PRIMARY} !important;
        background: transparent !important;
    }}
    [data-baseweb="menu"] li:hover, [role="option"]:hover,
    [role="option"][aria-selected="true"] {{
        background: {TINT_BLUE} !important;
    }}
    /* Focus ring — Brand Blue */
    input:focus, textarea:focus,
    [data-baseweb="input"]:focus-within,
    [data-baseweb="select"]:focus-within {{
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 1px var(--accent) !important;
    }}
    .stTextInput button, [data-baseweb="input"] button {{
        color: var(--text-tertiary) !important;
        background: transparent !important;
    }}
    .stTextInput button:hover, [data-baseweb="input"] button:hover {{
        color: var(--text-primary) !important;
    }}
    /* Labels */
    .stTextInput label, .stNumberInput label, .stDateInput label,
    .stTextArea label, .stSelectbox label, .stMultiSelect label,
    .stSlider label, .stCheckbox label, .stRadio label {{
        color: var(--text-secondary) !important;
    }}

    /* --- SLIDER --- */
    .stSlider [data-baseweb="slider"] [role="slider"] {{ background: var(--accent) !important; }}
    .stSlider > div > div > div {{ color: var(--text-primary) !important; }}

    /* --- EXPANDERS --- */
    .stExpander {{ border-color: var(--border-subtle) !important; }}
    div[data-testid="stExpander"] details {{
        background: var(--bg-secondary) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: var(--radius-md) !important;
    }}
    div[data-testid="stExpander"] summary span {{
        color: var(--text-secondary) !important; font-weight: 600 !important;
    }}
    div[data-testid="stExpander"] summary:hover span {{
        color: var(--text-primary) !important;
    }}

    /* --- MISC --- */
    hr {{ border-color: var(--border-subtle) !important; opacity: 0.6; }}
    .stAlert {{ border-radius: var(--radius-md) !important; }}
    [data-testid="stMarkdownContainer"] p {{ color: var(--text-secondary); }}
    .stSpinner > div {{ border-top-color: var(--accent) !important; }}

    /* --- RESPONSIVE --- */
    @media (max-width: 768px) {{
        .metrics-grid {{ grid-template-columns: repeat(2, 1fr); }}
        .block-container {{ padding: 3.5rem 1rem 1rem; }}
        .menu-table {{ font-size: 0.75rem; }}
    }}
</style>
"""
