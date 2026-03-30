"""
Theme Editor — Customize day-wise menu theme per client.

Global defaults: Mon=Mix, Tue=Chinese, Wed=Biryani, Thu=South, Fri=North.
Each client can override any day to any of the 5 themes.
"""

import streamlit as st
from typing import Dict, List

from ui.formatters import THEME_TAG_COLORS

_WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']

_THEME_DISPLAY = {
    'mix': 'Mix (South + North)',
    'chinese': 'Chinese',
    'biryani': 'Biryani',
    'south': 'South Indian',
    'north': 'North Indian',
}


def render_theme_editor(
    current_theme_map: Dict[str, str],
    default_theme_map: Dict[str, str],
    available_themes: List[str],
) -> Dict[str, str]:
    """Render theme day editor. Returns updated theme_map dict."""

    st.markdown(
        '<p style="font-size:1.1rem;font-weight:700;color:#f5f5f5;margin:1.5rem 0 0.5rem;">'
        'Day-wise Menu Theme</p>'
        '<p style="font-size:0.78rem;color:#737373;margin:0 0 0.75rem;">'
        'Override the default theme for any weekday. '
        'Other clients keep the global defaults.</p>',
        unsafe_allow_html=True,
    )

    updated = {}

    for day in _WEEKDAYS:
        day_display = day.capitalize()
        current_val = current_theme_map.get(day, default_theme_map.get(day, 'mix'))
        default_val = default_theme_map.get(day, 'mix')

        col_day, col_select, col_tag = st.columns([1.2, 2, 1.5])
        with col_day:
            st.markdown(
                f'<p style="font-weight:600;color:#e5e5e5;margin:0.5rem 0;'
                f'font-size:0.88rem;">{day_display}</p>',
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
                key=f"editor_theme_{day}",
                label_visibility="collapsed",
            )
            updated[day] = chosen

        with col_tag:
            bg, fg = THEME_TAG_COLORS.get(chosen, ('#262626', '#a3a3a3'))
            is_override = (chosen != default_val)
            badge_extra = ' border:1px solid ' + fg + ';' if is_override else ''
            label = _THEME_DISPLAY.get(chosen, chosen.title())
            st.markdown(
                f'<span style="display:inline-block;margin-top:0.45rem;'
                f'padding:3px 10px;border-radius:5px;font-size:0.68rem;'
                f'font-weight:700;text-transform:uppercase;letter-spacing:0.4px;'
                f'background:{bg};color:{fg};{badge_extra}">'
                f'{label}{"  *" if is_override else ""}'
                f'</span>',
                unsafe_allow_html=True,
            )

    # Show override summary
    overrides = {d: t for d, t in updated.items()
                 if t != default_theme_map.get(d)}
    if overrides:
        parts = [f"{d.capitalize()}: {_THEME_DISPLAY.get(t, t)}"
                 for d, t in overrides.items()]
        st.markdown(
            f'<p style="font-size:0.75rem;color:#fdba74;margin:0.5rem 0 0;">'
            f'Overrides: {" | ".join(parts)}</p>',
            unsafe_allow_html=True,
        )

    return updated
