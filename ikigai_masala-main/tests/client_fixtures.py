"""Real production client configurations, for the all-clients sweep.

Mirrors the live ``clients`` table (counters JSONB, city, source_pools,
item_cooldown_days, working_days) so the sweep in
``test_all_clients_generate.py`` exercises the shapes that actually ship:
multi-counter clients, ``nonveg_main`` counts of 2 and 3, combo slots,
single-theme counters, restricted ``source_pools`` and ``working_days``.

Kept as a Python literal rather than a SQL dump so it is reviewable in diffs
and does not need a parser. Update it when the live table gains a shape that
isn't represented here.
"""

from typing import Any, Dict, List

# A counter shorthand: (name, categories, slot_counts, theme_map)
_MIX = {
    'monday': 'mix', 'tuesday': 'chinese', 'wednesday': 'biryani',
    'thursday': 'south', 'friday': 'north',
}


def _c(name, cats, counts=None, themes=None) -> Dict[str, Any]:
    return {
        'name': name,
        'categories': list(cats),
        'slot_counts': dict(counts or {}),
        'theme_map': dict(themes if themes is not None else _MIX),
    }


_STD = ['welcome_drink', 'bread', 'rice', 'dal', 'sambar', 'rasam',
        'veg_gravy', 'veg_dry', 'curd_side', 'dessert', 'white_rice',
        'papad', 'pickle']

CLIENTS: List[Dict[str, Any]] = [
    # --- multi-counter, restricted pools, single-theme counters -------------
    {
        'name': 'Amadeus', 'version': 5, 'city': 'Bangalore',
        'serve_weekends': False, 'item_cooldown_days': 20,
        'source_pools': ['amadeus', 'continental', 'healthineers'],
        'counters': [
            _c('South', ['bread', 'rice', 'veg_dry', 'veg_gravy', 'sambar',
                         'rasam', 'dessert', 'salad', 'curd', 'papad', 'pickle'],
               {'curd': 1, 'rice': 1, 'bread': 1, 'rasam': 1, 'salad': 1,
                'sambar': 1, 'dessert': 1, 'veg_dry': 1, 'veg_gravy': 1},
               {d: 'south' for d in _MIX}),
            _c('Chinese', ['rice', 'veg_gravy'], {'rice': 1, 'veg_gravy': 1},
               {d: 'chinese_continental' for d in _MIX}),
        ],
    },
    # --- 3 nonveg slots + curd_rice (the starved-slot case) ----------------
    {
        'name': 'Computa Centre', 'version': 2, 'city': 'Bangalore',
        'serve_weekends': False, 'item_cooldown_days': 20,
        'source_pools': ['computacenter'],
        'counters': [
            _c('Counter 1',
               ['salad', 'bread', 'rice', 'white_rice', 'veg_dry', 'veg_gravy',
                'dal', 'rasam', 'dessert', 'curd_side', 'nonveg_main',
                'curd_rice'],
               {'dal': 1, 'rice': 1, 'bread': 1, 'rasam': 1, 'salad': 1,
                'dessert': 1, 'veg_dry': 1, 'curd_rice': 1, 'curd_side': 1,
                'veg_gravy': 1, 'nonveg_main': 3},
               {'monday': 'mix', 'tuesday': 'biryani', 'wednesday': 'north',
                'thursday': 'south', 'friday': 'north'}),
        ],
    },
    # --- all-south counter (theme filter starves curd_side) + all-biryani
    #     nonveg counter (collides with the weekly nonveg-biryani cap) -------
    {
        'name': 'L&T', 'version': 2, 'city': 'Bangalore',
        'serve_weekends': False, 'item_cooldown_days': 20, 'source_pools': [],
        'counters': [
            _c('South Lunch',
               ['bread', 'salad', 'rice', 'white_rice', 'veg_dry', 'veg_gravy',
                'sambar', 'rasam', 'dessert', 'papad', 'curd_side'],
               {'rice': 1, 'bread': 1, 'rasam': 1, 'salad': 1, 'sambar': 1,
                'dessert': 1, 'veg_dry': 1, 'curd_side': 1, 'veg_gravy': 1},
               {d: 'south' for d in _MIX}),
            _c('Non Veg Lunch', ['bread', 'curd_side', 'nonveg_main'],
               {'bread': 1, 'curd_side': 1, 'nonveg_main': 1},
               {d: 'biryani' for d in _MIX}),
        ],
    },
    # --- curd_rice + 2 soups, common-only pool ------------------------------
    {
        'name': 'ToastTab', 'version': 2, 'city': 'Bangalore',
        'serve_weekends': False, 'item_cooldown_days': 20, 'source_pools': [],
        'counters': [
            _c('Counter 1',
               ['salad', 'bread', 'rice', 'white_rice', 'veg_dry', 'veg_gravy',
                'dal', 'rasam', 'dessert', 'curd_side', 'curd_rice', 'pickle',
                'nonveg_main', 'soup', 'welcome_drink'],
               {'dal': 1, 'rice': 1, 'soup': 2, 'bread': 1, 'rasam': 1,
                'salad': 1, 'dessert': 1, 'veg_dry': 1, 'curd_rice': 1,
                'curd_side': 1, 'veg_gravy': 1, 'nonveg_main': 1,
                'welcome_drink': 1},
               {'monday': 'north', 'tuesday': 'biryani', 'wednesday': 'mix',
                'thursday': 'north', 'friday': 'mix'}),
        ],
    },
    # --- working_days client (3-day week) + pinned yogurt pair -------------
    {
        'name': 'Quince', 'version': 1, 'city': 'Bangalore',
        'serve_weekends': False, 'item_cooldown_days': 20, 'source_pools': [],
        'working_days': ['wednesday', 'thursday', 'friday'],
        'counters': [
            _c('Counter 1',
               ['welcome_drink', 'bread', 'rice', 'healthy_rice', 'dal',
                'veg_gravy', 'veg_dry', 'nonveg_main', 'dessert', 'starter',
                'white_rice', 'sambar_rasam', 'curd'],
               {'dal': 1, 'curd': 1, 'rice': 1, 'bread': 1, 'dessert': 1,
                'starter': 1, 'veg_dry': 1, 'veg_gravy': 1, 'nonveg_main': 2,
                'healthy_rice': 1, 'sambar_rasam': 1, 'welcome_drink': 1},
               {'monday': 'mix', 'tuesday': 'chinese', 'wednesday': 'north',
                'thursday': 'mix', 'friday': 'biryani'}),
        ],
    },
    # --- pinned expansion (nonveg_main__2) that must not disable the pair --
    {
        'name': 'Plan View', 'version': 2, 'city': 'Bangalore',
        'serve_weekends': False, 'item_cooldown_days': 20,
        'source_pools': ['infineon'],
        'counters': [
            _c('Counter 1',
               ['welcome_drink', 'salad', 'bread', 'rice', 'white_rice',
                'veg_dry', 'veg_gravy', 'rasam', 'dessert', 'curd',
                'dal_sambar', 'nonveg_main'],
               {'curd': 1, 'rice': 1, 'bread': 1, 'rasam': 1, 'salad': 1,
                'dessert': 1, 'veg_dry': 1, 'veg_gravy': 1, 'dal_sambar': 1,
                'nonveg_main': 2, 'welcome_drink': 1},
               {'monday': 'mix', 'tuesday': 'mix', 'wednesday': 'biryani',
                'thursday': 'south', 'friday': 'north'}),
        ],
    },
    # --- day-restricted nonveg + egg/chicken pair override ----------------
    {
        'name': 'F5', 'version': 2, 'city': 'Bangalore',
        'serve_weekends': False, 'item_cooldown_days': 20, 'source_pools': [],
        'counters': [
            _c('Counter 1',
               ['welcome_drink', 'salad', 'bread', 'rice', 'white_rice',
                'veg_dry', 'veg_gravy', 'dal', 'sambar', 'rasam', 'dessert',
                'curd', 'papad', 'nonveg_main'],
               {'dal': 1, 'curd': 1, 'rice': 1, 'bread': 1, 'rasam': 1,
                'salad': 1, 'sambar': 1, 'dessert': 1, 'veg_dry': 1,
                'veg_gravy': 1, 'nonveg_main': 2, 'welcome_drink': 1},
               {'monday': 'mix', 'tuesday': 'north', 'wednesday': 'biryani',
                'thursday': 'south', 'friday': 'north'}),
        ],
    },
    # --- white_rice day restriction (const-slot skip) ---------------------
    {
        'name': 'Ikea', 'version': 2, 'city': 'Bangalore',
        'serve_weekends': False, 'item_cooldown_days': 20, 'source_pools': [],
        'counters': [
            _c('Counter 1',
               ['salad', 'bread', 'rice', 'white_rice', 'veg_dry', 'veg_gravy',
                'dal', 'sambar', 'rasam', 'dessert', 'curd_side', 'papad',
                'pickle', 'nonveg_main'],
               {'dal': 1, 'rice': 1, 'bread': 1, 'rasam': 1, 'salad': 1,
                'sambar': 1, 'dessert': 1, 'veg_dry': 1, 'curd_side': 1,
                'veg_gravy': 1, 'nonveg_main': 1}),
        ],
    },
    # --- plain city-baseline client (no per-client block) ------------------
    {
        'name': 'Cargil', 'version': 2, 'city': 'Bangalore',
        'serve_weekends': False, 'item_cooldown_days': None,
        'source_pools': None,
        'counters': [_c('Counter 1', _STD, {
            'dal': 1, 'rice': 1, 'bread': 1, 'rasam': 1, 'sambar': 1,
            'dessert': 1, 'veg_dry': 1, 'curd_side': 1, 'veg_gravy': 1,
            'welcome_drink': 1})],
    },
]


APP_SETTINGS = [
    {'key': 'constant_slots',
     'value': ['white_rice', 'papad', 'pickle', 'chutney']},
    {'key': 'core_min_one_slots',
     'value': ['bread', 'rice', 'starter', 'veg_dry', 'welcome_drink',
               'curd_side', 'nonveg_main', 'veg_gravy']},
    {'key': 'fallback_menu_category', 'value': 'menu_cat_3'},
]
