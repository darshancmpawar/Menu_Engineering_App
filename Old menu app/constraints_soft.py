from __future__ import annotations

from collections.abc import Callable


def build_starter_theme_ok_vars(model, cfg, cells, dates, find_cells_fn: Callable, link_any_fn: Callable):
    if not cfg.prefer_theme_starter:
        return []
    starter_theme_ok_vars = []
    for di in range(len(dates)):
        for idx, scell in enumerate(find_cells_fn(cells, di, 'starter'), start=1):
            lits = [v for v, pref in zip(scell.x_vars, scell.theme_pref_flags) if pref]
            if lits:
                ok = model.NewBoolVar(f'starter_theme_ok_{di}_{idx}')
                link_any_fn(model, lits, ok)
                starter_theme_ok_vars.append(ok)
    return starter_theme_ok_vars


def build_objective(model, cfg, cells, rng, similarity, starter_theme_ok_vars, theme_fallback_bools, norm_str_fn: Callable):
    obj_terms = []
    if similarity:
        for cell in cells:
            for var, row in zip(cell.x_vars, cell.cand_rows):
                sc = int(similarity.get((cell.date, cell.slot_id, norm_str_fn(row.get('item', ''))), 0))
                if sc:
                    obj_terms.append(var * sc)
        if starter_theme_ok_vars:
            obj_terms.append(sum(starter_theme_ok_vars) * 25000)
        for cell in cells:
            for var in cell.x_vars:
                obj_terms.append(var * rng.randint(0, 3))
    else:
        for cell in cells:
            for var in cell.x_vars:
                obj_terms.append(var * rng.randint(0, 1000))
        if starter_theme_ok_vars:
            obj_terms.append(sum(starter_theme_ok_vars) * 1000000)
    if theme_fallback_bools:
        obj_terms.append(sum(theme_fallback_bools) * (-abs(int(cfg.theme_fallback_penalty))))
    if obj_terms:
        model.Maximize(sum(obj_terms))
