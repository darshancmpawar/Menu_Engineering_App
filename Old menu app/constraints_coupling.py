from __future__ import annotations

from typing import Set

import pandas as pd


def _norm_str(x) -> str:
    if pd.isna(x):
        return ''
    return str(x).strip().lower()


def add_coupling_constraints(model, cells, dates, find_cells_fn, link_any_fn, is_deepfried_starter_row_fn) -> None:
    bread_ricebread_day, vegdry_deepfried_day = ([], [])
    for di in range(len(dates)):
        bread_cells, rice_cells = (find_cells_fn(cells, di, 'bread'), find_cells_fn(cells, di, 'rice'))
        starter_cells, vegdry_cells = (find_cells_fn(cells, di, 'starter'), find_cells_fn(cells, di, 'veg_dry'))
        if not bread_cells or not rice_cells or (not starter_cells) or (not vegdry_cells):
            raise RuntimeError('Missing required core slots (bread/rice/starter/veg_dry). Check cfg.slot_counts.')
        bread_rb_lits = [v for c in bread_cells for v, r in zip(c.x_vars, c.cand_rows) if int(r.get('is_rice_bread', 0)) == 1]
        bread_rb = model.NewBoolVar(f'bread_ricebread_{di}')
        link_any_fn(model, bread_rb_lits, bread_rb)
        bread_ricebread_day.append(bread_rb)

        rice_liq_lits = [v for c in rice_cells for v, r in zip(c.x_vars, c.cand_rows) if int(r.get('is_liquid_rice', 0)) == 1]
        rice_liq = model.NewBoolVar(f'rice_liquid_{di}')
        link_any_fn(model, rice_liq_lits, rice_liq)

        starter_df_lits = [v for c in starter_cells for v, r in zip(c.x_vars, c.cand_rows) if is_deepfried_starter_row_fn(r)]
        starter_df = model.NewBoolVar(f'starter_deepfried_{di}')
        link_any_fn(model, starter_df_lits, starter_df)

        vegdry_df_vars = []
        for idx, vc in enumerate(vegdry_cells, start=1):
            df_lits = [v for v, r in zip(vc.x_vars, vc.cand_rows) if int(r.get('is_deep_fried_veg_dry', 0)) == 1]
            vdf = model.NewBoolVar(f'vegdry_deepfried_{di}_{idx}')
            link_any_fn(model, df_lits, vdf)
            vegdry_df_vars.append(vdf)
        vegdry_any = model.NewBoolVar(f'vegdry_any_deepfried_{di}')
        model.AddMaxEquality(vegdry_any, vegdry_df_vars) if vegdry_df_vars else model.Add(vegdry_any == 0)
        vegdry_deepfried_day.append(vegdry_any)

        model.Add(bread_rb <= rice_liq)
        model.Add(bread_rb <= starter_df)
        model.Add(starter_df <= bread_rb)
        model.Add(vegdry_any <= rice_liq)
        model.Add(vegdry_any <= bread_rb)
    model.Add(sum(bread_ricebread_day) <= 1)
    model.Add(sum(vegdry_deepfried_day) <= 1)


def add_curd_side_constraints(model, cells, dates, day_types, find_cells_fn, link_any_fn, pulao_subcats: Set[str]) -> None:
    for di, _ in enumerate(dates):
        day_type = day_types[di]
        rice_cells, curd_cells = (find_cells_fn(cells, di, 'rice'), find_cells_fn(cells, di, 'curd_side'))
        if not rice_cells or not curd_cells:
            raise RuntimeError('Missing rice/curd_side slots.')
        rice_pulao_lits = [v for rc in rice_cells for v, row in zip(rc.x_vars, rc.cand_rows) if _norm_str(row.get('sub_category', '')) in pulao_subcats]
        rice_is_pulao = model.NewBoolVar(f'rice_is_pulao_{di}')
        link_any_fn(model, rice_pulao_lits, rice_is_pulao)

        curd_lits, raita_lits = ([], [])
        for cc in curd_cells:
            for v, row in zip(cc.x_vars, cc.cand_rows):
                sc = _norm_str(row.get('sub_category', ''))
                if sc == 'curd':
                    curd_lits.append(v)
                if int(row.get('is_raita', 0)) == 1 or 'raita' in sc:
                    raita_lits.append(v)
        curd_is_curd = model.NewBoolVar(f'curd_is_curd_{di}')
        link_any_fn(model, curd_lits, curd_is_curd)
        curd_is_raita = model.NewBoolVar(f'curd_is_raita_{di}')
        link_any_fn(model, raita_lits, curd_is_raita)
        if day_type == 'biryani':
            model.Add(curd_is_raita == 1)
        else:
            model.Add(curd_is_raita == 1).OnlyEnforceIf(rice_is_pulao)
            model.Add(curd_is_curd == 1).OnlyEnforceIf(rice_is_pulao.Not())
