#!/usr/bin/env python3
"""
menu_eng_latest_v27.py (CP-SAT OR-Tools) — required-comments edition

Purpose:
- Generate Mon–Fri weekly menus with hard constraints using OR-Tools CP-SAT.
- Support slot multiplicity (e.g., veg_dry__1, veg_dry__2).
- Respect client-wise history cooldown and week-signature cooldown.
- Provide targeted regeneration while keeping untouched cells locked.

Public API used by app.py:
- load_df(path, sheet) -> (df, pools, cfg, meta)
- plan_week(...)
- regenerate_selected_from_plan(...)
- write_plan_xlsx(week_plan, dates, out_path)
- compute_week_signature(week_plan, dates)
- _strip_color_suffix(s)
- capacity_report(path, sheet="Sheet1", cooldown_days=20)
"""

from __future__ import annotations
import datetime as dt
import random
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
import pandas as pd
from constraints_cooldown import (
    banned_items_by_date as cooldown_banned_items_by_date,
    ensure_history_long as cooldown_ensure_history_long,
    ensure_history_weeks as cooldown_ensure_history_weeks,
    filter_history_by_client as cooldown_filter_history_by_client,
    parse_signature_to_expected_map as cooldown_parse_signature_to_expected_map,
    recent_week_signatures as cooldown_recent_week_signatures,
    ricebread_ban_by_date as cooldown_ricebread_ban_by_date,
)
from constraints_theme import (
    apply_cuisine_theme_filters as theme_apply_cuisine_theme_filters,
    apply_non_theme_exclusions as theme_apply_non_theme_exclusions,
    apply_theme_slot_locks as theme_apply_theme_slot_locks,
    chinese_side_mask as theme_chinese_side_mask,
    enforce_day_slot_filters_static as theme_enforce_day_slot_filters_static,
    starter_theme_mask as theme_starter_theme_mask,
    starter_theme_match_row as theme_starter_theme_match_row,
    theme_preference_mask as theme_theme_preference_mask,
)
from constraints_hard import (
    add_color_constraints as hard_add_color_constraints,
    add_coupling_constraints as hard_add_coupling_constraints,
    add_curd_side_constraints as hard_add_curd_side_constraints,
    add_item_uniqueness_constraints as hard_add_item_uniqueness_constraints,
    add_premium_constraints as hard_add_premium_constraints,
    add_theme_day_constraints as hard_add_theme_day_constraints,
    add_week_signature_cooldown_constraints as hard_add_week_signature_cooldown_constraints,
    add_welcome_drink_color_constraints as hard_add_welcome_drink_color_constraints,
)
from constraints_soft import (
    build_objective as soft_build_objective,
    build_starter_theme_ok_vars as soft_build_starter_theme_ok_vars,
)
try:
    from ortools.sat.python import cp_model
except Exception as e:
    raise RuntimeError('OR-Tools is required. Install with: pip install ortools') from e
# Item bases that can repeat across the planning horizon.
REPEATABLE_ITEM_BASES: Set[str] = {'curd'}
PULAO_SUBCATS: Set[str] = {'south_veg_pulao', 'north_simple_veg_pulao', 'north_rich_pulao', 'millet_pulao', 'mixed_grain_pulao'}
DEEPFRIED_STARTER_HINT_WORDS = ('fried', 'fry', 'pakoda', 'pakora', 'vada', 'bonda', 'bhaji', 'bajji', 'cutlet')
SLOT_SUFFIX_SEP = '__'
BASE_SLOT_NAMES: List[str] = ['welcome_drink', 'soup', 'salad', 'starter', 'bread', 'rice', 'healthy_rice', 'dal', 'sambar', 'rasam', 'veg_gravy', 'veg_dry', 'nonveg_main', 'curd_side', 'dessert']
CONST_SLOTS: List[str] = ['white_rice', 'papad', 'pickle', 'chutney']
OUTPUT_SLOTS: List[str] = BASE_SLOT_NAMES + CONST_SLOTS
CONSTANT_ITEMS: Dict[str, str] = {'white_rice': 'steamed rice', 'papad': 'Papad', 'pickle': 'Pickle', 'chutney': 'chutney'}
EXEMPT_FROM_CUISINE: Set[str] = {'welcome_drink', 'dal', 'sambar', 'rasam', 'starter', 'soup', 'salad', 'healthy_rice'}
DISPLAY_SLOT_NAME: Dict[str, str] = {'rice': 'Flavor Rice', 'healthy_rice': 'Healthy Rice', 'white_rice': 'White Rice', 'welcome_drink': 'Welcome Drink', 'soup': 'Soup', 'salad': 'Salad', 'veg_gravy': 'Veg Gravy', 'veg_dry': 'Veg Dry', 'nonveg_main': 'Nonveg Main', 'curd_side': 'Curd Side'}
THEME_FALLBACK_SLOTS: Set[str] = {'starter', 'veg_dry'}


# -----------------------------
# Normalization helpers
# -----------------------------
def _norm_str(x) -> str:
    if pd.isna(x):
        return ''
    return str(x).strip().lower()

def _norm_color(x) -> str:
    s = _norm_str(x).replace(' ', '_')
    return 'unknown' if s in ('', 'na', 'nan', 'null', 'none', 'unknown', 'unk') else s

def _to_bool01(x) -> int:
    if pd.isna(x):
        return 0
    if isinstance(x, (int, float)):
        return int(x != 0)
    return 1 if str(x).strip().lower() in ('1', 'y', 'yes', 'true', 't') else 0

def pick_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in cols:
            return cols[cand.lower()]
    return None

def _is_chinese_cuisine_value(x: str) -> bool:
    s = _norm_str(x)
    return s == 'chinese' or 'chinese' in s

def _color_initial(x) -> str:
    c = _norm_color(x)
    if c == 'unknown':
        return ''
    base = c.split('_')[-1]
    return base[:1].upper() if base else ''

def _fmt_item_with_color(row: pd.Series, color_col: str) -> str:
    item = str(row['item'])
    ini = _color_initial(row.get(color_col, 'unknown'))
    return f'{item}({ini})' if ini else item

def _strip_color_suffix(s: str) -> str:
    return re.sub('\\([A-Z]\\)\\s*$', '', (s or '').strip()).strip()

def _is_deepfried_starter_row(row: pd.Series) -> bool:
    if 'is_deep_fried_starter' in row.index and int(row.get('is_deep_fried_starter', 0)) == 1:
        return True
    text = f"{_norm_str(row.get('item', ''))} {_norm_str(row.get('sub_category', ''))}"
    return any((w in text for w in DEEPFRIED_STARTER_HINT_WORDS))


def _is_nonveg_dry_row(row: pd.Series) -> bool:
    if int(_to_bool01(row.get('is_nonveg_dry', 0))) == 1:
        return True
    if _norm_str(row.get('category', '')) == 'chicken_dry':
        return True
    text = ' '.join((
        _norm_str(row.get('sub_category', '')),
        _norm_str(row.get('key_ingredient', '')),
        _norm_str(row.get('item', '')),
    ))
    return ('chicken_dry' in text) or ('chicken dry' in text)

def _base_slot(slot_id: str) -> str:
    s = _norm_str(slot_id)
    if SLOT_SUFFIX_SEP in s:
        left, right = s.rsplit(SLOT_SUFFIX_SEP, 1)
        if right.isdigit():
            return left
    return s

def _slot_num(slot_id: str) -> Optional[int]:
    s = _norm_str(slot_id)
    if SLOT_SUFFIX_SEP in s:
        _, right = s.rsplit(SLOT_SUFFIX_SEP, 1)
        if right.isdigit():
            return int(right)
    return None

def _expand_slots_in_order(base_slots: List[str], slot_counts: Dict[str, int]) -> List[str]:
    out: List[str] = []
    for s in base_slots:
        n = int(slot_counts.get(s, 1))
        if n <= 0:
            continue
        out += [s] if n == 1 else [f'{s}{SLOT_SUFFIX_SEP}{i}' for i in range(1, n + 1)]
    return out

def _display_slot(slot_id: str) -> str:
    base, num = (_base_slot(slot_id), _slot_num(slot_id))
    base_disp = DISPLAY_SLOT_NAME.get(base, base)
    return base_disp if num is None else f'{base_disp} {num}'

def _weekday_type(d: dt.date) -> str:
    wd = d.strftime('%A').lower()
    if wd == 'tuesday':
        return 'chinese'
    if wd == 'wednesday':
        return 'biryani'
    if wd == 'thursday':
        return 'south'
    if wd == 'friday':
        return 'north'
    if wd == 'monday':
        return 'mix'
    if wd in ('saturday', 'sunday'):
        return 'holiday'
    return 'normal'

def _theme_label(day_type: str) -> str:
    return {'mix': 'Mix of South + North', 'chinese': 'Chinese', 'biryani': 'Biryani', 'south': 'South Indian', 'north': 'North Indian', 'holiday': 'Holiday', 'normal': 'Normal'}.get(day_type, day_type.capitalize())

def _starter_theme_match_row(row: pd.Series, cfg: 'Config', day_type: str) -> bool:
    return theme_starter_theme_match_row(row, cfg, day_type)

def _starter_theme_mask(pool: pd.DataFrame, cfg: 'Config', day_type: str) -> pd.Series:
    return theme_starter_theme_mask(pool, cfg, day_type)

def _chinese_side_mask(pool: pd.DataFrame, cfg: 'Config') -> pd.Series:
    return theme_chinese_side_mask(pool, cfg)

def _theme_preference_mask(base_slot: str, pool: pd.DataFrame, cfg: 'Config', day_type: str) -> pd.Series:
    return theme_theme_preference_mask(base_slot, pool, cfg, day_type)

def _apply_non_theme_exclusions(base_slot: str, pool: pd.DataFrame, cfg: 'Config', day_type: str) -> pd.DataFrame:
    return theme_apply_non_theme_exclusions(base_slot, pool, cfg, day_type)

def _apply_theme_slot_locks(base_slot: str, pool: pd.DataFrame, cfg: 'Config', day_type: str) -> pd.DataFrame:
    return theme_apply_theme_slot_locks(base_slot, pool, cfg, day_type)

def _apply_cuisine_theme_filters(base_slot: str, pool: pd.DataFrame, cfg: 'Config', day_type: str) -> pd.DataFrame:
    return theme_apply_cuisine_theme_filters(base_slot, pool, cfg, day_type, EXEMPT_FROM_CUISINE)

def _sample_with_priority(pool: pd.DataFrame, cap: int, priority_mask: pd.Series, rng: random.Random) -> pd.DataFrame:
    if len(pool) <= cap:
        return pool
    pm = priority_mask.reindex(pool.index).fillna(False).astype(bool)
    pri, oth = (pool[pm], pool[~pm])
    if len(pri) >= cap:
        return pri.sample(cap, random_state=rng.randint(1, 10 ** 9))
    if len(pri) == 0:
        return pool.sample(cap, random_state=rng.randint(1, 10 ** 9))
    need = cap - len(pri)
    if len(oth) > need:
        oth = oth.sample(need, random_state=rng.randint(1, 10 ** 9))
    return pd.concat([pri, oth], axis=0)

def _link_any(model: cp_model.CpModel, lits: List[cp_model.IntVar], y: cp_model.IntVar) -> None:
    if not lits:
        model.Add(y == 0)
        return
    model.Add(sum(lits) >= y)  # Link y<->selection so distinct-color count is valid
    for lit in lits:
        model.Add(lit <= y)


# -----------------------------
# Runtime config object (set by app.py)
# -----------------------------
@dataclass
class Config:
    days: int
    start_date: dt.date
    seed: int
    time_limit_sec: int
    max_attempts: int
    slot_counts: Optional[Dict[str, int]] = None
    color_col: str = 'item_color'
    color_slots: List[str] = None
    min_distinct_colors_per_day: int = 4
    min_distinct_colors_per_day_chinese: int = 4
    min_distinct_colors_per_day_biryani: int = 4
    max_same_color_per_day: int = 2
    ignore_rice_gravy_color_diff_on_chinese_day: bool = True
    premium_flag_col: Optional[str] = None
    premium_min_per_horizon: int = 1
    premium_max_per_horizon: int = 2
    premium_max_per_day: int = 1
    rice_exclude_items: Set[str] = None
    cuisine_col: str = 'cuisine_family'
    cuisine_south_value: str = 'south_indian'
    cuisine_north_value: str = 'north_indian'
    f_chinese_rice: Optional[str] = None
    f_chinese_nonveg: Optional[str] = None
    f_chinese_veg_gravy: Optional[str] = None
    f_chinese_starter: Optional[str] = None
    f_nonveg_biryani: Optional[str] = None
    f_veg_biryani: Optional[str] = None
    f_raita: Optional[str] = None
    prefer_theme_starter: bool = True
    theme_fallback_penalty: int = 2000000
    deterministic: bool = True

def _ensure_history_long(history_long_df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    return cooldown_ensure_history_long(history_long_df)

def _ensure_history_weeks(history_weeks_df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    return cooldown_ensure_history_weeks(history_weeks_df)

def _filter_history_by_client(history_long_df, history_weeks_df, client_name):
    return cooldown_filter_history_by_client(history_long_df, history_weeks_df, client_name)

def banned_items_by_date(history_long_df, dates, item_cooldown_days=20):
    return cooldown_banned_items_by_date(
        history_long_df,
        dates,
        item_cooldown_days=item_cooldown_days,
        const_slots=CONST_SLOTS,
        repeatable_item_bases=REPEATABLE_ITEM_BASES,
    )

def recent_week_signatures(history_weeks_df, week_start, menu_cooldown_days=30):
    return cooldown_recent_week_signatures(history_weeks_df, week_start, menu_cooldown_days=menu_cooldown_days)

def _infer_picked_slot_order_from_plan(week_plan, dates):
    const_set = set(CONST_SLOTS)
    for d in dates:
        day_map = week_plan.get(d, {})
        if day_map:
            return [k for k in day_map.keys() if _base_slot(k) not in const_set and k not in const_set]
    return []

def compute_week_signature(week_plan, dates):
    slot_order = _infer_picked_slot_order_from_plan(week_plan, dates)
    parts = []
    for d in dates:
        parts.append(d.isoformat())
        day_map = week_plan.get(d, {})
        for slot_id in slot_order:
            parts.append(f"{slot_id}={_strip_color_suffix(day_map.get(slot_id, ''))}")
    return '|'.join(parts)

def ricebread_ban_by_date(history_long_df, dates, ricebread_items, rice_bread_gap_days=10):
    return cooldown_ricebread_ban_by_date(
        history_long_df,
        dates,
        ricebread_items,
        rice_bread_gap_days=rice_bread_gap_days,
        base_slot_fn=_base_slot,
    )


# -----------------------------
# Ontology loading + standardization
# -----------------------------
def load_df(path: str, sheet: str):
    df = pd.read_excel(path, sheet_name=sheet)
    item_col = pick_col(df, ['item', 'menu_items', 'menu_item'])
    course_col = pick_col(df, ['course_type', 'course', 'slot'])
    if item_col is None or course_col is None:
        raise ValueError('Dataset must include item and course_type.')
    cuisine_col = pick_col(df, ['cuisine_family', 'cuisine_family_', 'cuisine_family_region', 'cuisine'])
    color_col = pick_col(df, ['item_color', 'colour', 'color', 'color_group', 'dominant_color'])
    key_col = pick_col(df, ['key_ingredient', 'keyingredient', 'ingredient_key'])
    subcat_col = pick_col(df, ['sub_category', 'subcategory'])
    if cuisine_col is None:
        cuisine_col = '__cuisine_family_tmp__'
        df[cuisine_col] = ''
    if color_col is None:
        color_col = '__item_color_tmp__'
        df[color_col] = 'unknown'
    if key_col is None:
        key_col = '__key_ingredient_tmp__'
        df[key_col] = pd.NA
    if subcat_col is None:
        subcat_col = '__sub_category_tmp__'
        df[subcat_col] = ''
    df = df.rename(columns={item_col: 'item', course_col: 'course_type', cuisine_col: 'cuisine_family', color_col: 'item_color', key_col: 'key_ingredient', subcat_col: 'sub_category'})

    optional_flag_aliases = {
        'is_liquid_rice': ['is_liquid_rice'],
        'is_rice_bread': ['is_rice_bread'],
        'is_deep_fried_veg_dry': ['is_deep_fried_veg_dry'],
        'is_chinese_fried_rice': ['is_chinese_fried_rice'],
        'is_chinese_chicken_gravy': ['is_chinese_chicken_gravy'],
        'is_chinese_veg_gravy': ['is_chinese_veg_gravy'],
        'is_chinese_starter': ['is_chinese_starter'],
        'is_nonveg_biryani': ['is_nonveg_biryani'],
        'is_mixedveg_biryani': ['is_mixedveg_biryani'],
        'is_raita': ['is_raita'],
        'is_premium_veg': ['is_premium_veg'],
        'is_deep_fried_starter': ['is_deep_fried_starter'],
        'is_nonveg_dry': ['is_nonveg_dry', 'is_non_veg_dry', 'nonveg_dry', 'non_veg_dry'],
        'is_nonveg_gravy': ['is_nonveg_gravy', 'is_non_veg_gravy', 'nonveg_gravy', 'non_veg_gravy'],
    }
    for canon_col, aliases in optional_flag_aliases.items():
        found = pick_col(df, aliases)
        if found is not None and found != canon_col and canon_col not in df.columns:
            df[canon_col] = df[found]

    for col, fn in (('item', _norm_str), ('course_type', _norm_str), ('cuisine_family', _norm_str), ('item_color', _norm_color), ('key_ingredient', _norm_str), ('sub_category', _norm_str)):
        df[col] = df[col].map(fn)
    for col in ('is_liquid_rice', 'is_rice_bread', 'is_deep_fried_veg_dry'):
        df[col] = df[col].map(_to_bool01) if col in df.columns else 0
    for col in ('is_chinese_fried_rice', 'is_chinese_chicken_gravy', 'is_chinese_veg_gravy', 'is_chinese_starter', 'is_nonveg_biryani', 'is_mixedveg_biryani', 'is_raita', 'is_premium_veg', 'is_deep_fried_starter', 'is_nonveg_dry', 'is_nonveg_gravy'):
        df[col] = df[col].map(_to_bool01) if col in df.columns else 0
    cat_series = df['category'].map(_norm_str) if 'category' in df.columns else pd.Series([''] * len(df), index=df.index)

    def _compute_key_eff_row(r):
        k = r['key_ingredient'] if r['key_ingredient'] else r['item']
        cf, sc, ct, cat = (r['cuisine_family'], r['sub_category'], r['course_type'], cat_series.loc[r.name])
        if k in ('chicken', 'egg') or ct in ('rice', 'healthy_rice') or cat.startswith('flavoured_rice') or ('biryani' in cat):
            return '_'.join([p for p in (k, cf, sc) if p])
        return k
    df['key_eff'] = df.apply(_compute_key_eff_row, axis=1).map(_norm_str)
    pools = {}
    mapping = {'welcome_drink': {'welcome_drink', 'infused_water'}, 'soup': {'soup'}, 'salad': {'salad'}, 'starter': {'starter'}, 'bread': {'bread'}, 'rice': {'rice'}, 'healthy_rice': {'healthy_rice', 'healthy rice', 'healthy-rice'}, 'dal': {'dal'}, 'veg_gravy': {'veg_gravy'}, 'veg_dry': {'veg_dry'}, 'nonveg_main': {'nonveg_main'}, 'curd_side': {'curd_side'}, 'dessert': {'dessert'}}
    for slot, cts in mapping.items():
        pools[slot] = df[df['course_type'].isin(cts)].copy()
    pools['rasam'] = df[(df['course_type'] == 'rasam') | (df['course_type'] == 'sambar/rasam') & df['item'].str.contains('rasam', na=False)].copy()
    pools['sambar'] = df[(df['course_type'] == 'sambar') | (df['course_type'] == 'sambar/rasam') & ~df['item'].str.contains('rasam', na=False)].copy()
    for s in BASE_SLOT_NAMES:
        if s not in pools or len(pools[s]) == 0:
            raise ValueError(f"Slot '{s}' has 0 items after mapping.")
    premium_enabled = int(df['is_premium_veg'].sum()) > 0
    cfg = Config(days=5, start_date=dt.date.today(), seed=7, time_limit_sec=240, max_attempts=500000)
    cfg.color_col = 'item_color'
    cfg.color_slots = ['starter', 'rice', 'veg_gravy', 'veg_dry', 'nonveg_main', 'dal', 'dessert']
    cfg.premium_flag_col = 'is_premium_veg' if premium_enabled else None
    cfg.rice_exclude_items = {'steamed_rice', 'steamed rice', 'white_rice', 'white rice', 'steam rice', 'plain rice', 'plain_rice'}
    cfg.cuisine_col = 'cuisine_family'
    cfg.f_chinese_rice, cfg.f_chinese_nonveg, cfg.f_chinese_veg_gravy, cfg.f_chinese_starter = ('is_chinese_fried_rice', 'is_chinese_chicken_gravy', 'is_chinese_veg_gravy', 'is_chinese_starter')
    cfg.f_nonveg_biryani, cfg.f_veg_biryani, cfg.f_raita = ('is_nonveg_biryani', 'is_mixedveg_biryani', 'is_raita')
    meta = {'columns': list(df.columns), 'standardized': True, 'solver': 'cp-sat', 'premium_enabled': premium_enabled, 'repeatable_items': sorted(list(REPEATABLE_ITEM_BASES))}
    return (df, pools, cfg, meta)

def _enforce_day_slot_filters_static(base_slot, pool, cfg, day_type):
    return theme_enforce_day_slot_filters_static(base_slot, pool, cfg, day_type, EXEMPT_FROM_CUISINE)

def _min_distinct_for_day(cfg, day_type):
    return cfg.min_distinct_colors_per_day_chinese if day_type == 'chinese' else cfg.min_distinct_colors_per_day_biryani if day_type == 'biryani' else cfg.min_distinct_colors_per_day

def _effective_slot_counts(cfg):
    counts = {s: 1 for s in BASE_SLOT_NAMES}
    if cfg.slot_counts:
        for k, v in cfg.slot_counts.items():
            try:
                counts[_base_slot(k)] = int(v)
            except Exception:
                pass
    for must in ('bread', 'rice', 'starter', 'veg_dry', 'welcome_drink', 'curd_side', 'nonveg_main', 'veg_gravy'):
        counts[must] = max(1, int(counts.get(must, 1)))
    return counts

def _expanded_slot_ids(cfg):
    return _expand_slots_in_order(BASE_SLOT_NAMES, _effective_slot_counts(cfg))


# CP cell = (date, slot_id) with candidate rows + solver vars.
class _Cell:
    __slots__ = ('d_idx', 'date', 'slot_id', 'base_slot', 'cand_df', 'theme_pref_flags', 'x_vars', 'cand_rows')

    def __init__(self, d_idx, date, slot_id, base_slot, cand_df, theme_pref_flags):
        self.d_idx, self.date, self.slot_id, self.base_slot, self.cand_df = (d_idx, date, slot_id, base_slot, cand_df)
        self.theme_pref_flags = list(theme_pref_flags)
        self.x_vars, self.cand_rows = ([], [])

def _parse_signature_to_expected_map(sig):
    return cooldown_parse_signature_to_expected_map(sig)

def _sample_cell_candidates(pool: pd.DataFrame, pref_mask: pd.Series, cap: int, rng: random.Random) -> Tuple[pd.DataFrame, List[bool]]:
    pool2 = pool
    pref2 = pref_mask.reindex(pool2.index).fillna(False).astype(bool)
    if len(pool2) > cap:
        if bool(pref2.any()):
            pool2 = _sample_with_priority(pool2, cap, pref2, rng)
        else:
            pool2 = pool2.sample(cap, random_state=rng.randint(1, 10 ** 9))
    pref2 = pref2.reindex(pool2.index).fillna(False).astype(bool)
    return pool2.reset_index(drop=True), pref2.tolist()

def _build_day_base_pool_cache(pools, cfg, dates, base_slots, banned_by_date, ricebread_ban_day):
    cache = {}
    for di, d in enumerate(dates):
        day_type = _weekday_type(d)
        banned = banned_by_date.get(d, set())
        for base in base_slots:
            pool2 = _enforce_day_slot_filters_static(base, pools[base], cfg, day_type)
            if base == 'bread' and ricebread_ban_day.get(d, False):
                pool2 = pool2[pool2.get('is_rice_bread', 0) == 0]
            if banned:
                pool2 = pool2[~pool2['item'].isin(banned)]
            pref_mask = _theme_preference_mask(base, pool2, cfg, day_type)
            cache[di, base] = (pool2, pref_mask, day_type)
    return cache

def _build_cells(pools, cfg, dates, expanded_slots, banned_by_date, ricebread_ban_day, cap_default, cap_by_slot, rng):
    cells = []
    base_slots = list(dict.fromkeys((_base_slot(slot_id) for slot_id in expanded_slots)))
    day_base_pool_cache = _build_day_base_pool_cache(pools, cfg, dates, base_slots, banned_by_date, ricebread_ban_day)
    for di, d in enumerate(dates):
        for slot_id in expanded_slots:
            base = _base_slot(slot_id)
            pool2, pref_mask, day_type = day_base_pool_cache[di, base]
            if base == 'nonveg_main' and (_slot_num(slot_id) or 1) >= 2:
                if day_type in {'biryani', 'chinese'}:
                    biryani_flag = cfg.f_nonveg_biryani
                    alt_pool = pools[base].copy()
                    if cfg.f_chinese_nonveg and cfg.f_chinese_nonveg in alt_pool.columns:
                        alt_pool = alt_pool[alt_pool[cfg.f_chinese_nonveg].map(_to_bool01) == 0]
                    if biryani_flag and biryani_flag in alt_pool.columns:
                        alt_pool = alt_pool[alt_pool[biryani_flag].map(_to_bool01) == 0]
                    banned = banned_by_date.get(d, set())
                    if banned:
                        alt_pool = alt_pool[~alt_pool['item'].isin(banned)]
                    if len(alt_pool) > 0:
                        pool2 = alt_pool
                dry_pool = pool2[pool2.apply(_is_nonveg_dry_row, axis=1)]
                if len(dry_pool) > 0:
                    pool2 = dry_pool
                else:
                    gravy_pool = pool2[pool2.get('is_nonveg_gravy', 0).map(_to_bool01) == 1] if 'is_nonveg_gravy' in pool2.columns else pool2.iloc[0:0]
                    if len(gravy_pool) > 0:
                        pool2 = gravy_pool
            if len(pool2) == 0:
                extra = ' (rice-bread banned by gap rule)' if base == 'bread' and ricebread_ban_day.get(d, False) else ''
                raise RuntimeError(f'Empty pool after filters: {d.isoformat()} slot={slot_id} day_type={day_type}{extra}')
            cap = cap_by_slot.get(base, cap_default)
            sampled_pool, theme_pref_flags = _sample_cell_candidates(pool2, pref_mask, cap, rng)
            cells.append(_Cell(di, d, slot_id, base, sampled_pool, theme_pref_flags))
    return cells

def _find_cells(cells, di, base_slot):
    return [c for c in cells if c.d_idx == di and c.base_slot == base_slot]


# -----------------------------
# CP-SAT model
# -----------------------------
def _collect_known_colors(cells, cfg):
    known_colors, known_welcome_colors = (set(), set())
    for cell in cells:
        if cell.base_slot in cfg.color_slots:
            for c in cell.cand_df[cfg.color_col].tolist():
                col = _norm_color(c)
                if col != 'unknown':
                    known_colors.add(col)
        if cell.base_slot == 'welcome_drink':
            for c in cell.cand_df[cfg.color_col].tolist():
                col = _norm_color(c)
                if col != 'unknown':
                    known_welcome_colors.add(col)
    return sorted(known_colors), sorted(known_welcome_colors)

def _build_decision_variables(model, cfg, cells, day_types, locked=None, forbidden=None):
    item_to_vars, day_color_vars, day_rice_color_vars, day_gravy_color_vars = ({}, {}, {}, {})
    day_premium_vars, day_welcome_color_vars = ({}, {})
    monday_has_south_lits, monday_has_north_lits = ([], [])
    theme_fallback_bools = []
    for cell in cells:
        di, slot_id, base = (cell.d_idx, cell.slot_id, cell.base_slot)
        x_vars, cand_rows = ([], [])
        for j in range(len(cell.cand_df)):
            row, item_base = (cell.cand_df.iloc[j], _norm_str(cell.cand_df.iloc[j]['item']))
            var = model.NewBoolVar(f'x_d{di}_{slot_id}_{j}')
            x_vars.append(var)
            cand_rows.append(row)
            item_to_vars.setdefault(item_base, []).append(var)
            if cfg.premium_flag_col and int(row.get(cfg.premium_flag_col, 0)) == 1:
                day_premium_vars.setdefault(di, []).append(var)
            if base in cfg.color_slots:
                col = _norm_color(row.get(cfg.color_col, 'unknown'))
                if col != 'unknown':
                    day_color_vars.setdefault((di, col), []).append(var)
                    if base == 'rice':
                        day_rice_color_vars.setdefault((di, col), []).append(var)
                    elif base == 'veg_gravy':
                        day_gravy_color_vars.setdefault((di, col), []).append(var)
            if base == 'welcome_drink':
                col = _norm_color(row.get(cfg.color_col, 'unknown'))
                if col != 'unknown':
                    day_welcome_color_vars.setdefault((di, col), []).append(var)
            if day_types[di] == 'mix' and base not in EXEMPT_FROM_CUISINE:
                cf = _norm_str(row.get(cfg.cuisine_col, ''))
                if cf == cfg.cuisine_south_value:
                    monday_has_south_lits.append(var)
                elif cf == cfg.cuisine_north_value:
                    monday_has_north_lits.append(var)
            if locked and (cell.date, slot_id) in locked and (item_base != _norm_str(locked[cell.date, slot_id])):
                model.Add(var == 0)
            if forbidden and (cell.date, slot_id) in forbidden and (item_base in forbidden[cell.date, slot_id]):
                model.Add(var == 0)
        model.Add(sum(x_vars) == 1)
        cell.x_vars, cell.cand_rows = (x_vars, cand_rows)
        if cell.base_slot in THEME_FALLBACK_SLOTS:
            pref_flags = [bool(v) for v in cell.theme_pref_flags]
            if pref_flags and any(pref_flags) and (not all(pref_flags)):
                fallback_lits = [v for v, pref in zip(x_vars, pref_flags) if not pref]
                if fallback_lits:
                    fb = model.NewBoolVar(f'theme_fallback_{di}_{slot_id}')
                    _link_any(model, fallback_lits, fb)
                    theme_fallback_bools.append(fb)
    return (item_to_vars, day_color_vars, day_rice_color_vars, day_gravy_color_vars, day_premium_vars, day_welcome_color_vars, monday_has_south_lits, monday_has_north_lits, theme_fallback_bools)

def _add_item_uniqueness_constraints(model, item_to_vars):
    hard_add_item_uniqueness_constraints(model, item_to_vars, REPEATABLE_ITEM_BASES)

def _add_color_premium_constraints(model, cfg, dates, day_types, known_colors, day_color_vars, day_rice_color_vars, day_gravy_color_vars):
    hard_add_color_constraints(
        model,
        cfg,
        dates,
        day_types,
        known_colors,
        day_color_vars,
        day_rice_color_vars,
        day_gravy_color_vars,
        link_any_fn=_link_any,
        min_distinct_for_day_fn=_min_distinct_for_day,
    )

def _add_theme_day_constraints(model, day_types, monday_has_south_lits, monday_has_north_lits):
    hard_add_theme_day_constraints(model, day_types, monday_has_south_lits, monday_has_north_lits)

def _add_coupling_constraints(model, cells, dates):
    hard_add_coupling_constraints(
        model,
        cells,
        dates,
        find_cells_fn=_find_cells,
        link_any_fn=_link_any,
        is_deepfried_starter_row_fn=_is_deepfried_starter_row,
    )

def _add_premium_constraints(model, cfg, dates, day_premium_vars):
    hard_add_premium_constraints(model, cfg, dates, day_premium_vars)

def _add_welcome_drink_color_constraints(model, dates, known_welcome_colors, day_welcome_color_vars):
    hard_add_welcome_drink_color_constraints(model, dates, known_welcome_colors, day_welcome_color_vars)

def _add_curd_side_constraints(model, cells, dates, day_types):
    hard_add_curd_side_constraints(
        model,
        cells,
        dates,
        day_types,
        find_cells_fn=_find_cells,
        link_any_fn=_link_any,
        pulao_subcats=PULAO_SUBCATS,
    )

def _add_week_signature_cooldown_constraints(model, cells, recent_sigs):
    hard_add_week_signature_cooldown_constraints(model, cells, recent_sigs)

def _build_starter_theme_ok_vars(model, cfg, cells, dates):
    return soft_build_starter_theme_ok_vars(model, cfg, cells, dates, find_cells_fn=_find_cells, link_any_fn=_link_any)

def _build_objective(model, cfg, cells, rng, similarity, starter_theme_ok_vars, theme_fallback_bools):
    soft_build_objective(
        model,
        cfg,
        cells,
        rng,
        similarity,
        starter_theme_ok_vars,
        theme_fallback_bools,
        norm_str_fn=_norm_str,
    )

def _build_solver(cfg):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(cfg.time_limit_sec)
    solver.parameters.random_seed = int(cfg.seed)
    solver.parameters.num_search_workers = 1 if cfg.deterministic else 8
    solver.parameters.cp_model_presolve = True
    return solver

def _extract_solution_rows(solver, cells, dates):
    chosen = {d: {} for d in dates}
    for cell in cells:
        pick_idx = next((j for j, var in enumerate(cell.x_vars) if solver.Value(var) == 1), None)
        if pick_idx is None:
            raise RuntimeError('Solver solution missing selection in a cell.')
        chosen[cell.date][cell.slot_id] = cell.cand_rows[pick_idx]
    return chosen

def _solve_cpsat(cfg, dates, cells, expanded_slots, recent_sigs, locked=None, similarity=None, forbidden=None):
    del expanded_slots  # kept for API compatibility with call sites
    rng, model = (random.Random(cfg.seed), cp_model.CpModel())
    day_types = [_weekday_type(d) for d in dates]
    known_colors, known_welcome_colors = _collect_known_colors(cells, cfg)
    (item_to_vars, day_color_vars, day_rice_color_vars, day_gravy_color_vars, day_premium_vars, day_welcome_color_vars, monday_has_south_lits, monday_has_north_lits, theme_fallback_bools) = _build_decision_variables(model, cfg, cells, day_types, locked=locked, forbidden=forbidden)
    _add_item_uniqueness_constraints(model, item_to_vars)
    _add_color_premium_constraints(model, cfg, dates, day_types, known_colors, day_color_vars, day_rice_color_vars, day_gravy_color_vars)
    _add_theme_day_constraints(model, day_types, monday_has_south_lits, monday_has_north_lits)
    _add_coupling_constraints(model, cells, dates)
    _add_premium_constraints(model, cfg, dates, day_premium_vars)
    _add_welcome_drink_color_constraints(model, dates, known_welcome_colors, day_welcome_color_vars)
    _add_curd_side_constraints(model, cells, dates, day_types)
    _add_week_signature_cooldown_constraints(model, cells, recent_sigs)
    starter_theme_ok_vars = _build_starter_theme_ok_vars(model, cfg, cells, dates)
    _build_objective(model, cfg, cells, rng, similarity, starter_theme_ok_vars, theme_fallback_bools)
    solver = _build_solver(cfg)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if status == cp_model.INFEASIBLE:
            raise RuntimeError('No feasible plan found (INFEASIBLE).')
        if status == cp_model.UNKNOWN:
            raise RuntimeError('No feasible plan found (TIME LIMIT).')
        if status == cp_model.MODEL_INVALID:
            raise RuntimeError('CP-SAT model invalid.')
        raise RuntimeError(f'CP-SAT failed with status={status}.')
    return _extract_solution_rows(solver, cells, dates)

def similarity_score(cand, orig):
    score = 0
    if _norm_str(cand.get('sub_category', '')) == _norm_str(orig.get('sub_category', '')):
        score += 30
    if _norm_str(cand.get('key_ingredient', '')) == _norm_str(orig.get('key_ingredient', '')):
        score += 20
    if _norm_str(cand.get('cuisine_family', '')) == _norm_str(orig.get('cuisine_family', '')):
        score += 20
    if _norm_color(cand.get('item_color', 'unknown')) == _norm_color(orig.get('item_color', 'unknown')):
        score += 10
    score += 2 * len(set(_norm_str(cand.get('item', '')).split('_')) & set(_norm_str(orig.get('item', '')).split('_')))
    return int(score)

def _ricebread_items_from_df(df: pd.DataFrame) -> Set[str]:
    rb_series = df['is_rice_bread'] if 'is_rice_bread' in df.columns else pd.Series(0, index=df.index)
    return set(df.loc[rb_series.map(_to_bool01) == 1, 'item'].tolist())

def _prepare_generation_context(df, cfg, history_long_df, history_weeks_df, item_cooldown_days, menu_cooldown_days, rice_bread_gap_days):
    dates = [cfg.start_date + dt.timedelta(days=i) for i in range(cfg.days)]
    expanded_slots = _expanded_slot_ids(cfg)
    banned_by_date = banned_items_by_date(history_long_df, dates, item_cooldown_days=item_cooldown_days)
    recent_sigs = recent_week_signatures(history_weeks_df, cfg.start_date, menu_cooldown_days=menu_cooldown_days)
    ricebread_items = _ricebread_items_from_df(df)
    ricebread_ban_day = ricebread_ban_by_date(history_long_df, dates, ricebread_items, rice_bread_gap_days=rice_bread_gap_days)
    return (dates, expanded_slots, banned_by_date, recent_sigs, ricebread_ban_day)

def _rows_to_week_plan(chosen_rows, dates, expanded_slots, color_col):
    week_plan = {}
    for d in dates:
        day_out = {slot_id: _fmt_item_with_color(chosen_rows[d][slot_id], color_col) for slot_id in expanded_slots}
        day_out.update(CONSTANT_ITEMS)
        week_plan[d] = day_out
    return week_plan

def plan_week(df, pools, cfg, meta, history_long_df=None, history_weeks_df=None, client_name=None, item_cooldown_days=20, menu_cooldown_days=30, rice_bread_gap_days=10):
    history_long_df, history_weeks_df = _filter_history_by_client(history_long_df, history_weeks_df, client_name)
    (dates, expanded_slots, banned_by_date, recent_sigs, ricebread_ban_day) = _prepare_generation_context(df, cfg, history_long_df, history_weeks_df, item_cooldown_days, menu_cooldown_days, rice_bread_gap_days)
    cap_by_slot_base = {'rice': 1600, 'healthy_rice': 1200, 'veg_gravy': 1400, 'nonveg_main': 1400, 'curd_side': 1400, 'veg_dry': 1100, 'bread': 1100, 'starter': 1200, 'soup': 900, 'salad': 900, 'dal': 1000, 'dessert': 1000, 'welcome_drink': 1000, 'sambar': 900, 'rasam': 900}
    cap_default_base = 900
    cap_multipliers, restarts_per_multiplier = ([1, 2], 4)
    base_seed, total_time = (int(cfg.seed), float(cfg.time_limit_sec))
    per_attempt_time = max(20.0, total_time / (len(cap_multipliers) * restarts_per_multiplier))
    last_err, orig_seed, orig_time = (None, cfg.seed, cfg.time_limit_sec)
    try:
        for mult in cap_multipliers:
            cap_default, cap_by_slot = (cap_default_base * mult, {k: v * mult for k, v in cap_by_slot_base.items()})
            for r in range(restarts_per_multiplier):
                attempt_seed, rng = (base_seed + mult * 1000 + r * 17, random.Random(base_seed + mult * 1000 + r * 17))
                cfg.seed, cfg.time_limit_sec = (attempt_seed, int(per_attempt_time))
                cells = _build_cells(pools=pools, cfg=cfg, dates=dates, expanded_slots=expanded_slots, banned_by_date=banned_by_date, ricebread_ban_day=ricebread_ban_day, cap_default=cap_default, cap_by_slot=cap_by_slot, rng=rng)
                try:
                    chosen_rows = _solve_cpsat(cfg, dates, cells, expanded_slots, recent_sigs)
                    week_plan = _rows_to_week_plan(chosen_rows, dates, expanded_slots, cfg.color_col)
                    return (week_plan, dates)
                except Exception as e:
                    last_err = e
                    continue
        raise RuntimeError('No feasible plan found after CP-SAT restarts. Likely causes: tight history cooldown, rice-bread gap, insufficient deep-fried starters, tight Chinese/Biryani pools, or color/premium constraints.') from last_err
    finally:
        cfg.seed, cfg.time_limit_sec = (orig_seed, orig_time)

def regenerate_selected_from_plan(df, pools, cfg, base_plan, replace_mask, history_long_df=None, history_weeks_df=None, client_name=None, item_cooldown_days=20, menu_cooldown_days=30, rice_bread_gap_days=10):
    history_long_df, history_weeks_df = _filter_history_by_client(history_long_df, history_weeks_df, client_name)
    dates = [cfg.start_date + dt.timedelta(days=i) for i in range(cfg.days)]
    if sum((len(v) for v in replace_mask.values())) == 0:
        return (base_plan, dates)
    expanded_slots = _expanded_slot_ids(cfg)
    locked = {}
    for d in dates:
        for slot_id in expanded_slots:
            if slot_id not in replace_mask.get(d, set()):
                locked[d, slot_id] = _norm_str(_strip_color_suffix(base_plan.get(d, {}).get(slot_id, '')))
    forbidden = {}
    for d, slots in replace_mask.items():
        for slot_id in slots:
            old_item = _norm_str(_strip_color_suffix(base_plan.get(d, {}).get(slot_id, '')))
            if old_item:
                forbidden[d, slot_id] = {old_item}
    by_item = {}
    for _, row in df.iterrows():
        it = _norm_str(row.get('item', ''))
        if it and it not in by_item:
            by_item[it] = row
    (_, _, banned_by_date, recent_sigs, ricebread_ban_day) = _prepare_generation_context(df, cfg, history_long_df, history_weeks_df, item_cooldown_days, menu_cooldown_days, rice_bread_gap_days)
    cells = _build_cells(pools=pools, cfg=cfg, dates=dates, expanded_slots=expanded_slots, banned_by_date=banned_by_date, ricebread_ban_day=ricebread_ban_day, cap_default=1200, cap_by_slot={'rice': 2000, 'healthy_rice': 1600, 'veg_gravy': 1800, 'nonveg_main': 1800, 'curd_side': 1800, 'veg_dry': 1500, 'bread': 1500, 'starter': 1800, 'soup': 1400, 'salad': 1400, 'dal': 1400, 'dessert': 1400, 'welcome_drink': 1400, 'sambar': 1200, 'rasam': 1200}, rng=random.Random(cfg.seed))
    similarity = {}
    for cell in cells:
        if cell.slot_id not in replace_mask.get(cell.date, set()):
            continue
        old_item = _norm_str(_strip_color_suffix(base_plan.get(cell.date, {}).get(cell.slot_id, '')))
        orig_row = by_item.get(old_item)
        for row in cell.cand_rows:
            it = _norm_str(row.get('item', ''))
            similarity[cell.date, cell.slot_id, it] = 0 if orig_row is None else similarity_score(row, orig_row)
    try:
        chosen_rows = _solve_cpsat(cfg, dates, cells, expanded_slots, recent_sigs, locked=locked, similarity=similarity, forbidden=forbidden)
    except Exception:
        similarity2 = dict(similarity)
        for (d, slot_id), olds in forbidden.items():
            for old_item in olds:
                similarity2[d, slot_id, old_item] = -10000
        chosen_rows = _solve_cpsat(cfg, dates, cells, expanded_slots, recent_sigs, locked=locked, similarity=similarity2, forbidden=None)
    new_plan = _rows_to_week_plan(chosen_rows, dates, expanded_slots, cfg.color_col)
    return (new_plan, dates)

def write_plan_xlsx(week_plan, dates, out_path):
    row_slots = []
    for d in dates:
        if week_plan.get(d):
            row_slots = list(week_plan[d].keys())
            break
    if not row_slots:
        row_slots = OUTPUT_SLOTS
    cols = [f"{_theme_label(_weekday_type(d))}-{d.strftime('%A')}({d.isoformat()})" for d in dates]
    data = {c: [] for c in cols}
    rows = []
    for slot_id in row_slots:
        rows.append(_display_slot(slot_id))
        for c, d in zip(cols, dates):
            data[c].append(week_plan.get(d, {}).get(slot_id, ''))
    pd.DataFrame(data, index=rows).to_excel(out_path, sheet_name='menu', index=True)

def capacity_report(path, sheet='Sheet1', cooldown_days=20):
    df, pools, cfg, _ = load_df(path, sheet)
    week = [('Monday', 'mix'), ('Tuesday', 'chinese'), ('Wednesday', 'biryani'), ('Thursday', 'south'), ('Friday', 'north')]
    needed_daily, needed_weekly = (cooldown_days + 1, (cooldown_days + 7) // 7)
    rows = []
    for day_name, day_type in week:
        for slot in BASE_SLOT_NAMES:
            pool2 = _enforce_day_slot_filters_static(slot, pools[slot], cfg, day_type)
            rows.append({'weekday': day_name, 'day_type': day_type, 'slot': slot, 'unique_items': int(pool2['item'].nunique())})
    rep = pd.DataFrame(rows)
    rep['needed_unique_for_cooldown'] = rep['slot'].apply(lambda s: needed_daily if s in EXEMPT_FROM_CUISINE else needed_weekly)
    rep['bottleneck'] = rep['unique_items'] < rep['needed_unique_for_cooldown']
    cs = pools['curd_side'].copy()
    cs['sub_category'], cs['is_raita'] = (cs['sub_category'].map(_norm_str), cs.get('is_raita', 0).map(_to_bool01))
    curd_count = int((cs['sub_category'] == 'curd').sum())
    raita_count = int(((cs['is_raita'] == 1) | cs['sub_category'].str.contains('raita', na=False)).sum())
    rp = pools['rice'].copy()
    rp['sub_category'] = rp['sub_category'].map(_norm_str)
    pulao_rice_count = int(rp[rp['sub_category'].isin(PULAO_SUBCATS)]['item'].nunique())
    prem_series = df['is_premium_veg'] if 'is_premium_veg' in df.columns else pd.Series(0, index=df.index)
    prem_count = int(df[prem_series.map(_to_bool01) == 1]['item'].nunique())
    stp = pools['starter'].copy()
    df_starters = int(sum((1 for _, r in stp.iterrows() if _is_deepfried_starter_row(r))))
    rb_series = df['is_rice_bread'] if 'is_rice_bread' in df.columns else pd.Series(0, index=df.index)
    rb_count = int(df[rb_series.map(_to_bool01) == 1]['item'].nunique())
    rep['est_max_days_from_pool_only'] = rep.apply(lambda row: int(row['unique_items']) if row['slot'] in EXEMPT_FROM_CUISINE and row['unique_items'] < needed_daily else int(row['unique_items']) * 7 if row['slot'] not in EXEMPT_FROM_CUISINE and row['unique_items'] < needed_weekly else 10 ** 9, axis=1)
    overall_est = int(rep['est_max_days_from_pool_only'].min())
    print('\n=== CAPACITY REPORT (POOL-ONLY, ignores color/coupling/premium/history interactions) ===')
    print(f'Cooldown days: {cooldown_days}')
    print(f'Needed unique for DAILY pools (theme-exempt slots): {needed_daily}')
    print(f'Needed unique for WEEKLY subsets (weekday-specific): {needed_weekly}')
    print('\nKey counts:')
    print(f'- curd_side curd items: {curd_count}')
    print(f'- curd_side raita items: {raita_count}')
    print(f'- rice pulao items: {pulao_rice_count}')
    print(f'- premium veg unique items: {prem_count}')
    print(f'- deep-fried starter candidates: {df_starters}')
    print(f'- rice-bread unique items: {rb_count}')
    print('\nTop bottlenecks (unique < needed):')
    bott = rep[rep['bottleneck']].sort_values(['slot', 'weekday'])
    if len(bott) == 0:
        print('None (pool sizes meet basic cooldown needs).')
    else:
        print(bott[['weekday', 'slot', 'unique_items', 'needed_unique_for_cooldown']].to_string(index=False))
    if overall_est >= 10 ** 9:
        print('\nEstimated max days from POOL-ONLY perspective: unlimited (as long as other constraints allow).')
    else:
        print(f'\nEstimated max days from POOL-ONLY perspective (rough): ~{overall_est} days')
    print('\n(Real feasibility can still fail due to color/coupling/premium/history.)\n')
if __name__ == '__main__':
    import argparse
    import sys
    parser = argparse.ArgumentParser(description='Generate weekly menu plan with CP-SAT.')
    parser.add_argument('path', help='Path to Ontology.xlsx')
    parser.add_argument('--sheet', default='Sheet1', help='Excel sheet name')
    parser.add_argument('--start', default=None, help='Start date YYYY-MM-DD (default: today)')
    parser.add_argument('--days', type=int, default=5, help='Days to generate (default: 5)')
    parser.add_argument('--seed', type=int, default=7, help='Random seed')
    parser.add_argument('--time', type=int, default=240, help='Solver time limit sec')
    parser.add_argument('--out', default='menu_plan.xlsx', help='Output xlsx path')
    parser.add_argument('--capacity', action='store_true', help='Print capacity report and exit')
    parser.add_argument('--item-cooldown', type=int, default=20, help='Item cooldown days')
    parser.add_argument('--menu-cooldown', type=int, default=30, help='Week signature cooldown days')
    parser.add_argument('--rice-bread-gap', type=int, default=10, help='Rice-bread gap days')
    args = parser.parse_args()
    try:
        if args.capacity:
            capacity_report(args.path, sheet=args.sheet, cooldown_days=args.item_cooldown)
            sys.exit(0)
        df, pools, cfg, meta = load_df(args.path, args.sheet)
        cfg.days, cfg.seed, cfg.time_limit_sec = (int(args.days), int(args.seed), int(args.time))
        if args.start:
            cfg.start_date = dt.date.fromisoformat(args.start)
        plan, dates = plan_week(df=df, pools=pools, cfg=cfg, meta=meta, history_long_df=None, history_weeks_df=None, client_name=None, item_cooldown_days=int(args.item_cooldown), menu_cooldown_days=int(args.menu_cooldown), rice_bread_gap_days=int(args.rice_bread_gap))
        write_plan_xlsx(plan, dates, args.out)
        print(f'✅ Generated: {args.out}')
    except Exception as e:
        print(f'❌ {e}')
        raise
