from __future__ import annotations

from collections.abc import Callable

from constraints_cooldown import add_week_signature_cooldown_constraints as cooldown_add_week_signature_cooldown_constraints
from constraints_coupling import (
    add_coupling_constraints as coupling_add_coupling_constraints,
    add_curd_side_constraints as coupling_add_curd_side_constraints,
)
from constraints_theme import add_theme_day_constraints as theme_add_theme_day_constraints


def add_item_uniqueness_constraints(model, item_to_vars, repeatable_item_bases) -> None:
    repeatable = set(repeatable_item_bases)
    for item_base, vars_ in item_to_vars.items():
        if item_base not in repeatable:
            model.Add(sum(vars_) <= 1)


def add_color_constraints(
    model,
    cfg,
    dates,
    day_types,
    known_colors,
    day_color_vars,
    day_rice_color_vars,
    day_gravy_color_vars,
    link_any_fn: Callable,
    min_distinct_for_day_fn: Callable,
) -> None:
    for di, _ in enumerate(dates):
        day_type = day_types[di]
        min_dist = min_distinct_for_day_fn(cfg, day_type)
        for col in known_colors:
            lits = day_color_vars.get((di, col), [])
            if lits:
                model.Add(sum(lits) <= cfg.max_same_color_per_day)
        y_vars = []
        for col in known_colors:
            lits = day_color_vars.get((di, col), [])
            if not lits:
                continue
            y = model.NewBoolVar(f'y_color_{di}_{col}')
            link_any_fn(model, lits, y)
            y_vars.append(y)
        model.Add(sum(y_vars) >= min_dist) if y_vars else model.Add(0 >= min_dist)
        if not (cfg.ignore_rice_gravy_color_diff_on_chinese_day and day_type == 'chinese'):
            for col in known_colors:
                r_lits, g_lits = (day_rice_color_vars.get((di, col), []), day_gravy_color_vars.get((di, col), []))
                if r_lits and g_lits:
                    model.Add(sum(r_lits) + sum(g_lits) <= 1)


def add_theme_day_constraints(model, day_types, monday_has_south_lits, monday_has_north_lits) -> None:
    theme_add_theme_day_constraints(model, day_types, monday_has_south_lits, monday_has_north_lits)


def add_coupling_constraints(model, cells, dates, find_cells_fn, link_any_fn, is_deepfried_starter_row_fn) -> None:
    coupling_add_coupling_constraints(
        model,
        cells,
        dates,
        find_cells_fn=find_cells_fn,
        link_any_fn=link_any_fn,
        is_deepfried_starter_row_fn=is_deepfried_starter_row_fn,
    )


def add_premium_constraints(model, cfg, dates, day_premium_vars) -> None:
    if not cfg.premium_flag_col:
        return
    premium_day_bools = []
    for di in range(len(dates)):
        lits, prem_day = (day_premium_vars.get(di, []), model.NewBoolVar(f'premium_day_{di}'))
        if lits:
            model.Add(sum(lits) <= cfg.premium_max_per_day)
            model.Add(sum(lits) == prem_day)
        else:
            model.Add(prem_day == 0)
        premium_day_bools.append(prem_day)
    total_premium = sum(premium_day_bools)
    has_any_candidate = any((len(day_premium_vars.get(di, [])) > 0 for di in range(len(dates))))
    if has_any_candidate:
        model.Add(total_premium >= cfg.premium_min_per_horizon)
        model.Add(total_premium <= cfg.premium_max_per_horizon)
    else:
        model.Add(total_premium == 0)


def add_welcome_drink_color_constraints(model, dates, known_welcome_colors, day_welcome_color_vars) -> None:
    for di in range(len(dates) - 1):
        for col in known_welcome_colors:
            a, b = (day_welcome_color_vars.get((di, col), []), day_welcome_color_vars.get((di + 1, col), []))
            if a and b:
                model.Add(sum(a) + sum(b) <= 1)


def add_curd_side_constraints(model, cells, dates, day_types, find_cells_fn, link_any_fn, pulao_subcats) -> None:
    coupling_add_curd_side_constraints(
        model,
        cells,
        dates,
        day_types,
        find_cells_fn=find_cells_fn,
        link_any_fn=link_any_fn,
        pulao_subcats=pulao_subcats,
    )


def add_week_signature_cooldown_constraints(model, cells, recent_sigs) -> None:
    cooldown_add_week_signature_cooldown_constraints(model, cells, recent_sigs)
