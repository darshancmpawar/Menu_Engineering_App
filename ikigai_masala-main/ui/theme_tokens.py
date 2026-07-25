"""Pulse / OP Lens design tokens — the single source of truth for the app's
colour palette.

Both the planner stylesheet (``ui/styles.py``) and the customisation editor
(``customisation/pulse.py``) build their CSS from these constants so the whole
app shares one light theme. See UI_THEMING.md for the brand reference.
"""

# --- Brand ---
YELLOW = "#FEBF34"          # primary actions
YELLOW_HOVER = "#F0B020"
BLUE = "#0D6EFD"            # links / accents / selection
BLUE_HOVER = "#0A58CA"
PURPLE = "#6F42C1"          # tertiary highlight

# --- Status ---
GREEN = "#1AA45B"
ORANGE = "#F78D00"
RED = "#FA1024"

# --- Surfaces ---
PAGE_BG = "#F5F5F5"         # page canvas
CARD_BG = "#FFFFFF"         # cards / panels
ALT_ROW = "#F9F9F9"         # alternating table rows

# --- Text ---
TEXT_PRIMARY = "#131313"
TEXT_SECONDARY = "#414141"
TEXT_TERTIARY = "#777777"
TEXT_DISABLED = "#AEAEAE"

# --- Lines ---
BORDER = "#E5E5E5"

# Soft status/theme tints (low-emphasis badge style: tinted bg + darker text).
TINT_GREEN = "#E5FFF1"
TINT_ORANGE = "#FFF5E8"
TINT_RED = "#FFE7E9"
TINT_BLUE = "#EBF3FF"
TINT_PURPLE = "#F3ECFF"
TINT_YELLOW = "#FFF6E3"
TINT_TEAL = "#E4F7F4"

# Cuisine-theme badges, keyed by theme name → (background tint, foreground).
PULSE_THEME_COLORS = {
    "mix":     (TINT_GREEN, GREEN),
    "chinese": (TINT_ORANGE, "#C56A00"),
    "biryani": (TINT_RED, "#C40D1B"),
    "south":   (TINT_BLUE, BLUE),
    "north":   (TINT_PURPLE, PURPLE),
    "continental": (TINT_TEAL, "#0F8E80"),
    # Weekly-alternating meta-theme (shown in the editor; resolves to
    # chinese/continental at plan time).
    "chinese_continental": (TINT_TEAL, "#0F8E80"),
}

# Item colour pills (menu table), keyed by the colour initial → (name, bg, fg).
# Light tints so they read cleanly on white cells.
ITEM_COLOR_MAP = {
    "R": ("Red",    TINT_RED,    "#C40D1B"),
    "G": ("Green",  TINT_GREEN,  GREEN),
    "B": ("Brown",  "#F3E9DD",   "#8A5A2B"),
    "Y": ("Yellow", TINT_YELLOW, "#9A7A10"),
    "W": ("White",  "#F0F0F0",   "#555555"),
    "O": ("Orange", TINT_ORANGE, "#C56A00"),
    "K": ("Black",  "#E8E8E8",   "#333333"),
}
