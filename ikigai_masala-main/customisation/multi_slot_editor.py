"""Frequency editor — how many distinct items each category contributes.

Example: a counter with Veg Dry x2 will serve two different dry-veg dishes
per day (Veg Dry 1 & Veg Dry 2). Rendered inside a counter panel.
"""

import streamlit as st
from typing import Dict, List

from ui.formatters import display_label_for_slot_id as prettify_slot_name

# Single source of truth for the bounds, so the editor can never offer a value
# the loader would clamp (or reject) behind its back.
from src.client.client_config import _MAX_SLOT_COUNT, _MIN_SLOT_COUNT


def render_multi_slot_editor(
    active_base_slots: List[str],
    current_slot_counts: Dict[str, int],
    const_slots: List[str],
    key_prefix: str = "",
) -> Dict[str, int]:
    """Render per-category frequency inputs. Returns {category: count} for the
    currently-active categories only."""

    st.markdown(
        '<p class="pulse-sub-title">Frequency</p>'
        '<p class="pulse-sub-desc">'
        'Set a count of 2+ for categories that need duplicates per day '
        f'(e.g. Veg Dry 1 &amp; Veg Dry 2). Up to {_MAX_SLOT_COUNT}.</p>',
        unsafe_allow_html=True,
    )

    editable = [s for s in active_base_slots if s not in const_slots]

    if not editable:
        st.markdown(
            '<p class="pulse-hint">Pick categories above to set their '
            'frequency.</p>',
            unsafe_allow_html=True,
        )
        return {}

    updated: Dict[str, int] = {}
    cols = st.columns(3)
    for idx, slot in enumerate(editable):
        with cols[idx % 3]:
            current = int(current_slot_counts.get(slot, 1) or 1)
            current = max(_MIN_SLOT_COUNT, min(_MAX_SLOT_COUNT, current))
            val = st.number_input(
                prettify_slot_name(slot),
                min_value=_MIN_SLOT_COUNT, max_value=_MAX_SLOT_COUNT,
                value=current, step=1,
                key=f"cnt_{key_prefix}_{slot}",
            )
            updated[slot] = int(val)

    multi_slots = [s for s in editable if updated.get(s, 1) > 1]
    if multi_slots:
        tags = ', '.join(
            f"{prettify_slot_name(s)} x{updated[s]}" for s in multi_slots
        )
        st.markdown(
            f'<p class="pulse-hint accent">Duplicated: {tags}</p>',
            unsafe_allow_html=True,
        )

    return updated
