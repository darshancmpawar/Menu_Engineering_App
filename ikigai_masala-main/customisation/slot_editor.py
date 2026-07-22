"""Food-category editor — pick which categories a counter serves.

Rendered inside a counter panel (one per counter for multi-cuisine clients).
The caller wraps this in a bordered container; this function only draws the
heading + multiselect and returns the selected categories. Constant items
(White Rice, Papad, Pickle, Chutney) are now selectable per counter — not
forced on every client.
"""

import streamlit as st
from typing import List

from ui.formatters import display_label_for_slot_id
from src.constants import DISPLAY_SLOT_ORDER


def render_slot_editor(
    all_base_slots: List[str],
    current_active: List[str],
    const_slots: List[str],
    key_prefix: str = "",
) -> List[str]:
    """Render the food-category multiselect. Returns selected categories."""

    st.markdown(
        '<p class="pulse-sub-title">Food Categories</p>'
        '<p class="pulse-sub-desc">'
        'Choose which dishes this counter serves. Constants '
        '(White Rice, Papad, Pickle, Chutney) are optional — select them '
        'only for the counters that need them.</p>',
        unsafe_allow_html=True,
    )

    # Order every category (base + selectable constants) by the canonical
    # DISPLAY_SLOT_ORDER so the config list matches the rendered menu order.
    options = sorted(
        set(list(all_base_slots) + list(const_slots)),
        key=lambda s: (
            DISPLAY_SLOT_ORDER.index(s) if s in DISPLAY_SLOT_ORDER else 999
        ),
    )
    active_set = set(current_active)

    selected = st.multiselect(
        "Food Categories",
        options=options,
        default=[s for s in options if s in active_set],
        format_func=display_label_for_slot_id,
        key=f"slot_ms_{key_prefix}",
        label_visibility="collapsed",
    )

    if selected:
        st.markdown(
            f'<p class="pulse-hint">{len(selected)} of {len(options)} '
            f'categories active</p>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<p class="pulse-hint warn">Select at least one category '
            'for this counter.</p>',
            unsafe_allow_html=True,
        )

    return selected
