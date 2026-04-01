"""
Category Editor — Toggle categories on/off for a client.
"""

import streamlit as st
from typing import List

from ui.formatters import prettify_slot_name


def render_slot_editor(
    all_base_slots: List[str],
    current_active: List[str],
    const_slots: List[str],
    client_name: str = "",
) -> List[str]:
    """Render category toggle UI. Returns the list of selected base categories."""

    st.markdown(
        '<p style="font-size:1.1rem;font-weight:700;color:#f5f5f5;margin:1.5rem 0 0.5rem;">'
        'Customize Categories</p>'
        '<p style="font-size:0.78rem;color:#737373;margin:0 0 0.75rem;">'
        'Toggle which categories this client uses. Constant items '
        '(White Rice, Papad, Pickle, Chutney) are always included.</p>',
        unsafe_allow_html=True,
    )

    # Show toggleable categories (base slots only, no constants)
    toggleable = [s for s in all_base_slots if s not in const_slots]
    active_set = set(current_active)

    # Use multiselect for clean UI
    selected = st.multiselect(
        "Active Categories",
        options=toggleable,
        default=[s for s in toggleable if s in active_set],
        format_func=prettify_slot_name,
        key=f"editor_slot_multiselect_{client_name}",
        label_visibility="collapsed",
    )

    # Show summary
    if selected:
        st.markdown(
            f'<p style="font-size:0.75rem;color:#a3a3a3;margin:0.25rem 0 0;">'
            f'{len(selected)} categories selected</p>',
            unsafe_allow_html=True,
        )

    return selected
