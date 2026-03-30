# client_logic.py
from __future__ import annotations

from typing import Dict, List

# Supported clients (dropdown options)
CLIENT_NAMES: List[str] = [
    "Rippling",
    "Tekion",
    "Odessia",
    "Vector",
    "Scalar",
    "Clario",
    "Tessolve",
    "Stryker",
    "Cargil",
    "Ikea",
    "H&M",
    "Konsberg",
    "Moengage",
    "Stripe",
    "Semiens Technologies North",
    "Semiens Technologies South",
    "Semiens Technologies Non veg",
    "Citrix",
]

SLOT_SUFFIX_SEP = "__"

# Canonical slot names used by generator
BASE_SLOTS: List[str] = [
    "welcome_drink",
    "soup",
    "salad",
    "starter",
    "bread",
    "rice",
    "healthy_rice",
    "dal",
    "sambar",
    "rasam",
    "veg_gravy",
    "veg_dry",
    "nonveg_main",
    "curd_side",
    "dessert",
]

# Constant slots (always present in output, not selected by solver)
CONST_SLOTS: List[str] = ["white_rice", "papad", "pickle", "chutney"]

ALL_SLOTS: List[str] = BASE_SLOTS + CONST_SLOTS
FALLBACK_MENU_CATEGORY = "menu_cat_3"

# Menu category presets (base slot names only)
MENU_CATEGORIES: Dict[str, List[str]] = {
    "menu_cat_1": [
        "bread", "veg_dry", "rice", "veg_gravy", "nonveg_main", "dal", "sambar",
        "rasam", "white_rice", "papad", "pickle", "curd_side", "dessert", "salad",
    ],
    "menu_cat_2": [
        "bread", "veg_dry", "rice", "veg_gravy", "nonveg_main", "dal",
        "rasam", "white_rice", "papad", "pickle", "curd_side", "dessert", "welcome_drink", "salad",
    ],
    "menu_cat_3": [
        "bread", "veg_dry", "rice", "veg_gravy", "dal", "sambar",
        "rasam", "white_rice", "papad", "pickle", "curd_side", "dessert", "welcome_drink",
    ],
    "menu_cat_4": [
        "bread", "veg_dry", "welcome_drink", "rice", "veg_gravy", "nonveg_main", "soup", "dal", "sambar",
        "rasam", "white_rice", "papad", "pickle", "curd_side", "dessert",
    ],
    "menu_cat_5": [
        "bread", "veg_dry", "rice", "veg_gravy", "nonveg_main", "dal", "sambar", "starter",
        "rasam", "white_rice", "papad", "pickle", "curd_side", "dessert", "welcome_drink",
    ],
    "menu_cat_6": [
        "bread", "veg_dry", "rice", "veg_gravy", "nonveg_main", "dal", "sambar",
        "rasam", "white_rice", "papad", "pickle", "curd_side", "dessert", "welcome_drink", "healthy_rice",
    ],
    "menu_cat_7": [
        "bread", "veg_dry", "rice", "veg_gravy", "dal", "sambar",
        "rasam", "white_rice", "papad", "pickle", "curd_side", "dessert", "welcome_drink", "healthy_rice",
    ],
    "menu_cat_8": [
        "bread", "veg_dry", "rice", "veg_gravy", "dal", "sambar", "nonveg_main",
        "rasam", "white_rice", "papad", "pickle", "curd_side", "dessert", "salad",
    ],
    "menu_cat_9": [
        "bread", "veg_dry", "rice", "veg_gravy", "dal", "sambar", "nonveg_main",
        "rasam", "white_rice", "papad", "pickle", "curd_side", "dessert", "welcome_drink",
    ],
    "menu_cat_10": [
        "bread", "veg_dry", "rice", "veg_gravy", "sambar",
        "rasam", "white_rice", "papad", "pickle", "dessert",
    ],
    "menu_cat_11": [
        "bread", "veg_dry", "rice", "veg_gravy", "dal", "papad", "pickle", "curd_side", "dessert", "welcome_drink",
    ],
    "menu_cat_12": [
        "bread", "veg_dry", "rice", "veg_gravy", "dal", "sambar", "nonveg_main",
        "rasam", "white_rice", "papad", "pickle", "curd_side", "dessert", "salad",
    ],
}

# Client -> menu category
CLIENT_TO_MENU_CATEGORY: Dict[str, str] = {
    "Rippling": "menu_cat_4",
    "Tekion": "menu_cat_1",
    "Konsberg": "menu_cat_1",
    "Odessia": "menu_cat_2",
    "Vector": "menu_cat_3",
    "Scalar": "menu_cat_5",
    "Clario": "menu_cat_6",
    "Tessolve": "menu_cat_7",
    "Stryker": "menu_cat_1",
    "Cargil": "menu_cat_3",
    "Citrix": "menu_cat_2",
    "Ikea": "menu_cat_8",
    "H&M": "menu_cat_1",
    "Stripe": "menu_cat_9",
    "Moengage": "menu_cat_9",
    "Semiens Technologies North": "menu_cat_10",
    "Semiens Technologies South": "menu_cat_11",
    "Semiens Technologies Non veg": "menu_cat_12",
}

# Default: one of each base slot
DEFAULT_SLOT_COUNTS: Dict[str, int] = {s: 1 for s in BASE_SLOTS}

# Per-client multiplicity overrides
CLIENT_SLOT_COUNT_OVERRIDES: Dict[str, Dict[str, int]] = {
    "Rippling": {"veg_dry": 2},
    "Stripe": {"nonveg_main": 2},
    "Moengage": {"nonveg_main": 2},
}

# Core slots must always exist in plan
CORE_MIN_ONE_SLOTS = (
    "bread", "rice", "starter", "veg_dry",
    "welcome_drink", "curd_side", "nonveg_main", "veg_gravy",
)


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for v in values:
        if v not in seen:
            out.append(v)
            seen.add(v)
    return out


def _expand_slot_ids(base_slot: str, count: int) -> List[str]:
    n = int(count)
    if n <= 0:
        return []
    if n == 1:
        return [base_slot]
    return [f"{base_slot}{SLOT_SUFFIX_SEP}{i}" for i in range(1, n + 1)]


def get_client_names() -> List[str]:
    return list(CLIENT_NAMES)


def get_menu_category_names() -> List[str]:
    return list(MENU_CATEGORIES.keys())


def get_client_menu_category(client_name: str) -> str:
    return CLIENT_TO_MENU_CATEGORY.get(client_name, FALLBACK_MENU_CATEGORY)


def get_slots_for_menu_category(menu_category: str) -> List[str]:
    slots = MENU_CATEGORIES.get(menu_category, MENU_CATEGORIES[FALLBACK_MENU_CATEGORY])
    return _dedupe_preserve_order(list(slots))


def get_slot_counts_for_client(client_name: str) -> Dict[str, int]:
    counts = dict(DEFAULT_SLOT_COUNTS)
    overrides = CLIENT_SLOT_COUNT_OVERRIDES.get(client_name, {})

    for k, v in overrides.items():
        if k in counts:
            try:
                counts[k] = max(0, int(v))
            except Exception:
                pass

    for must in CORE_MIN_ONE_SLOTS:
        counts[must] = max(1, int(counts.get(must, 1)))

    return counts


def get_slots_for_client(client_name: str) -> List[str]:
    category = get_client_menu_category(client_name)
    base_to_show = get_slots_for_menu_category(category)
    counts = get_slot_counts_for_client(client_name)

    out: List[str] = []
    for slot in base_to_show:
        if slot in CONST_SLOTS:
            out.append(slot)
        else:
            out.extend(_expand_slot_ids(slot, counts.get(slot, 1)))

    return _dedupe_preserve_order(out)


def validate() -> None:
    # Duplicate client names (UI confusion + mapping drift risk)
    if len(set(CLIENT_NAMES)) != len(CLIENT_NAMES):
        seen = set()
        dups = []
        for c in CLIENT_NAMES:
            if c in seen and c not in dups:
                dups.append(c)
            seen.add(c)
        raise ValueError(f"CLIENT_NAMES has duplicate(s): {dups}")

    unknown_clients_in_mapping = [c for c in CLIENT_TO_MENU_CATEGORY if c not in CLIENT_NAMES]
    if unknown_clients_in_mapping:
        raise ValueError(f"CLIENT_TO_MENU_CATEGORY has unknown client(s): {unknown_clients_in_mapping}")

    unknown_categories_in_mapping = [cat for cat in CLIENT_TO_MENU_CATEGORY.values() if cat not in MENU_CATEGORIES]
    if unknown_categories_in_mapping:
        raise ValueError(f"CLIENT_TO_MENU_CATEGORY has unknown category(s): {unknown_categories_in_mapping}")

    for cat, slots in MENU_CATEGORIES.items():
        bad = [s for s in slots if s not in ALL_SLOTS]
        if bad:
            raise ValueError(f"MENU_CATEGORIES[{cat}] has unknown slot(s): {bad}")

    for client, overrides in CLIENT_SLOT_COUNT_OVERRIDES.items():
        if client not in CLIENT_NAMES:
            raise ValueError(f"CLIENT_SLOT_COUNT_OVERRIDES has unknown client: {client}")
        bad_keys = [k for k in overrides if k not in BASE_SLOTS]
        if bad_keys:
            raise ValueError(f"CLIENT_SLOT_COUNT_OVERRIDES[{client}] has unknown base slot(s): {bad_keys}")


if __name__ == "__main__":
    validate()
    print("client_logic.py OK ✅")
