"""
Slot Editor — Toggle base slots on/off for a client.
"""

import streamlit as st
from typing import List

from ui.formatters import prettify_slot_name


def render_slot_editor(
    all_base_slots: List[str],
    current_active: List[str],
    const_slots: List[str],
) -> List[str]:
    """Render slot toggle UI. Returns the list of selected base slots."""

    st.markdown(
        '<p style="font-size:1.1rem;font-weight:700;color:#f5f5f5;margin:1.5rem 0 0.5rem;">'
        'Customize Slots</p>'
        '<p style="font-size:0.78rem;color:#737373;margin:0 0 0.75rem;">'
        'Toggle which slots this client uses. Constant items '
        '(White Rice, Papad, Pickle, Chutney) are always included.</p>',
        unsafe_allow_html=True,
    )

    # Show toggleable slots (base slots only, no constants)
    toggleable = [s for s in all_base_slots if s not in const_slots]
    active_set = set(current_active)

    # Use multiselect for clean UI
    selected = st.multiselect(
        "Active Slots",
        options=toggleable,
        default=[s for s in toggleable if s in active_set],
        format_func=prettify_slot_name,
        key="editor_slot_multiselect",
        label_visibility="collapsed",
    )

    # Show summary
    if selected:
        st.markdown(
            f'<p style="font-size:0.75rem;color:#a3a3a3;margin:0.25rem 0 0;">'
            f'{len(selected)} slots selected</p>',
            unsafe_allow_html=True,
        )

    return selected
