"""Day-theme editor — the per-weekday cuisine theme for one counter.

Global defaults: Mon=Mix, Tue=Chinese, Wed=Biryani, Thu=South, Fri=North.
Each counter can override any day to any of the 5 themes. Rendered inside a
counter panel.
"""

import streamlit as st
from typing import Dict, List

from ui.formatters import THEME_ICONS
from customisation.pulse import PULSE_THEME_COLORS

_WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']

_THEME_DISPLAY = {
    'mix': 'Mix (South + North)',
    'chinese': 'Chinese',
    'biryani': 'Biryani',
    'south': 'South Indian',
    'north': 'North Indian',
    'continental': 'Continental',
    'chinese_continental': 'Chinese / Continental (alt. weekly)',
}


def render_theme_editor(
    current_theme_map: Dict[str, str],
    default_theme_map: Dict[str, str],
    available_themes: List[str],
    key_prefix: str = "",
) -> Dict[str, str]:
    """Render the per-weekday theme selectors. Returns the theme_map."""

    st.markdown(
        '<p class="pulse-sub-title">Day Themes</p>'
        '<p class="pulse-sub-desc">'
        'Set the cuisine theme this counter follows on each weekday. '
        'Weekends (Sat/Sun) are skipped.</p>',
        unsafe_allow_html=True,
    )

    updated: Dict[str, str] = {}

    for day in _WEEKDAYS:
        day_display = day.capitalize()
        current_val = current_theme_map.get(day, default_theme_map.get(day, 'mix'))
        default_val = default_theme_map.get(day, 'mix')

        col_day, col_select, col_tag = st.columns([1.1, 2.2, 1.7])
        with col_day:
            st.markdown(
                f'<p style="font-weight:700;color:#131313;margin:0.55rem 0;'
                f'font-size:0.85rem;">{day_display}</p>',
                unsafe_allow_html=True,
            )
        with col_select:
            try:
                default_idx = available_themes.index(current_val)
            except ValueError:
                default_idx = 0
            chosen = st.selectbox(
                f"Theme for {day_display}",
                available_themes,
                index=default_idx,
                format_func=lambda t: _THEME_DISPLAY.get(t, t.title()),
                key=f"theme_{key_prefix}_{day}",
                label_visibility="collapsed",
            )
            updated[day] = chosen

        with col_tag:
            bg, fg = PULSE_THEME_COLORS.get(chosen, ('#F5F5F5', '#777777'))
            icon = THEME_ICONS.get(chosen, '')
            is_override = (chosen != default_val)
            border = f' border:1px solid {fg};' if is_override else ''
            label = _THEME_DISPLAY.get(chosen, chosen.title())
            st.markdown(
                f'<span style="display:inline-flex;align-items:center;gap:4px;'
                f'margin-top:0.5rem;padding:3px 10px;border-radius:99px;'
                f'font-size:0.64rem;font-weight:700;text-transform:uppercase;'
                f'letter-spacing:0.04em;background:{bg};color:{fg};{border}">'
                f'{icon} {label}{" *" if is_override else ""}'
                f'</span>',
                unsafe_allow_html=True,
            )

    overrides = {d: t for d, t in updated.items()
                 if t != default_theme_map.get(d)}
    if overrides:
        parts = [f"{d.capitalize()}: {_THEME_DISPLAY.get(t, t)}"
                 for d, t in overrides.items()]
        st.markdown(
            f'<p class="pulse-hint accent">Overrides: {" | ".join(parts)}</p>',
            unsafe_allow_html=True,
        )

    return updated
