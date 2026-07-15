"""Counter editor — the full configuration for one cuisine counter.

Composes the three per-counter panels (food categories, frequency, day
themes) and returns a canonical counter dict:

    {'name', 'categories', 'slot_counts', 'theme_map'}

Used once for single-cuisine clients and once per tab for multi-cuisine
clients. Widget keys are namespaced by ``key_prefix`` (client + counter
index) so Streamlit keeps each counter's state independent across reruns.
"""

from typing import Dict

import streamlit as st

from customisation.slot_editor import render_slot_editor
from customisation.multi_slot_editor import render_multi_slot_editor
from customisation.theme_editor import render_theme_editor


def render_counter_editor(
    counter: Dict,
    idx: int,
    metadata: Dict,
    key_prefix: str,
    show_name: bool = True,
) -> Dict:
    """Render the panels for one counter and return its config dict."""

    all_base = metadata.get('base_slot_names', [])
    const = metadata.get('const_slots', [])
    themes = metadata.get('available_themes', [])
    default_theme = metadata.get('default_theme_map', {})

    fallback_name = f"Counter {idx + 1}"
    name = (counter.get('name') or fallback_name)

    if show_name:
        name = st.text_input(
            "Counter name",
            value=name,
            key=f"cname_{key_prefix}",
            placeholder=fallback_name,
            help="A label for this counter (e.g. \"North Indian\", \"Live Grill\").",
        )

    with st.container(border=True):
        cats = render_slot_editor(
            all_base, counter.get('categories', []), const, key_prefix,
        )

    with st.container(border=True):
        counts = render_multi_slot_editor(
            cats, counter.get('slot_counts', {}), const, key_prefix,
        )

    with st.container(border=True):
        theme_map = render_theme_editor(
            counter.get('theme_map', default_theme), default_theme, themes,
            key_prefix,
        )

    return {
        'name': (name or fallback_name).strip() or fallback_name,
        'categories': cats,
        'slot_counts': {c: int(counts.get(c, 1)) for c in cats},
        'theme_map': theme_map,
    }
