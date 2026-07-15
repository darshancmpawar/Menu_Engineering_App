"""Food-category editor — pick which categories a counter serves.

Rendered inside a counter panel (one per counter for multi-cuisine clients).
The caller wraps this in a bordered container; this function only draws the
heading + multiselect and returns the selected base categories.
"""

import streamlit as st
from typing import List

from ui.formatters import prettify_slot_name


def render_slot_editor(
    all_base_slots: List[str],
    current_active: List[str],
    const_slots: List[str],
    key_prefix: str = "",
) -> List[str]:
    """Render the food-category multiselect. Returns selected base categories."""

    st.markdown(
        '<p class="pulse-sub-title">Food Categories</p>'
        '<p class="pulse-sub-desc">'
        'Choose which dishes this counter serves. Constant items '
        '(White Rice, Papad, Pickle, Chutney) are always included.</p>',
        unsafe_allow_html=True,
    )

    toggleable = [s for s in all_base_slots if s not in const_slots]
    active_set = set(current_active)

    selected = st.multiselect(
        "Food Categories",
        options=toggleable,
        default=[s for s in toggleable if s in active_set],
        format_func=prettify_slot_name,
        key=f"slot_ms_{key_prefix}",
        label_visibility="collapsed",
    )

    if selected:
        st.markdown(
            f'<p class="pulse-hint">{len(selected)} of {len(toggleable)} '
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
