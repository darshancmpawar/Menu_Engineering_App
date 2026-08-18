#!/usr/bin/env python3
"""Import Booking.com's 3-month menu into the Bangalore ontology.

Source: `data/raw/source_workbooks/booking_menu_3_months.xlsx` — a printed
Lunch / Dinner / Breakfast grid, week blocks laid side by side. **Only Lunch and
Dinner are imported**: the tool plans lunch, and the breakfast sheet is cereals,
cut fruit, milk and juice as much as it is dishes. The one thing breakfast has
that lunch does not is the infused-water list, and Lunch carries the same 50
under "Detox water", so nothing is lost.

Three passes, the order every earlier city import used:

1. **Language.** The source spells the same dish several ways — `Chciken` /
   `Chcken` / `Chiceken`, `Chilli Parataha` / `Chilli Paratha`, `Brown Rice
   Kanjee` / `Brown rice kanjee`, `Apple&Celery Infused Wate`. Names are
   lowercased to the ontology's snake_case and the known misspellings corrected.
2. **Similar items.** What survives is folded at 0.90 similarity, so
   `beet_and_celery_detox_water` and `beetroot_and_celery_detox_water` become
   one dish rather than two.
3. **Unique.** Anything Bangalore already carries is dropped — the import only
   ever adds dishes that are new.

`client` tagging follows the rule the client stated: an item made by **6 or more
clients is `common`**, otherwise it lists the clients that make it. A dish new to
the ontology is made by Booking alone, so it is tagged `Booking.com`; a dish
Bangalore already has gains `Booking.com` in its list, and if that takes the
count to 6 the row is promoted to `common`.

Two new categories come out of this menu and are created here:
`infused_water` (Detox water) and `nonveg_soup` (Non Veg Soup).

Attributes are set only where the dish NAME supports them — course_type,
cuisine_family, primary_protein, the veg/non-veg flags — and left at the
schema default otherwise. Guessing `is_premium_gravy` or a colour for 628 dishes
would be inventing data the rules then act on; the cloned-template approach in
`expand_side_pools.py` sets the same honest minimum.

Idempotent: re-running adds nothing and re-tags nothing.
"""
from __future__ import annotations

import argparse
import sys
import difflib
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling scripts
ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "raw" / "source_workbooks" / "booking_menu_3_months.xlsx"
BLR = ROOT / "data" / "raw" / "city_items" / "bangalore.xlsx"

CLIENT_TOKEN = "Booking.com"
COMMON_AT = 6          # >= this many clients make it -> `common`

#: Booking's menu-pattern label -> the app's course_type. Breakfast omitted.
CATEGORY_MAP = {
    "Lunch||Welcome Drink": "welcome_drink",
    "Lunch||Detox water": "infused_water",
    "Lunch||Veg Soup": "soup",
    "Lunch||Non Veg Soup": "nonveg_soup",
    "Lunch||Main Entrée - Dry": "veg_dry",
    "Lunch||Main Entrée - 2": "veg_gravy",
    "Lunch||Live": "starter",
    "Lunch||Indian Bread": "bread",
    "Lunch||Flavoured Bread": "bread",
    "Lunch||Flavoured Rice": "rice",
    "Lunch||Dal  (Buffet 1)": "dal",
    "Lunch||Dal (Buffet 1)": "dal",
    "Lunch||Pulses - 1": "sambar",
    "Lunch||Pulses - 2": "rasam",
    "Lunch||Non-Veg": "nonveg_main",
    "Lunch||Dessert": "dessert",
    "Lunch||Healthy Option": "healthy_rice",
    "Dinner||Welcome Drink": "welcome_drink",
    "Dinner||Salad": "salad",
    "Dinner||Veg Dry": "veg_dry",
    "Dinner||Veg Gravy": "veg_gravy",
    "Dinner||Indian Bread": "bread",
    "Dinner||Flavoured Rice": "rice",
    "Dinner||Dal/Sambar": "dal",
    "Dinner||Rasam": "rasam",
    "Dinner||Dessert": "dessert",
    "Dinner||Non Veg": "nonveg_main",
}

#: Steamed rice / curd are fixed condiments the app pins as CONST_SLOTS, and
#: `Accompaniments` is a single "Fryums" row. Nothing to import.
SKIP_LABELS = {"Steamed Rice", "Curd", "Accompaniments", "Live Salad Counter"}

#: When the same dish name comes out of two menu rows it must be filed ONCE.
#: The printed menu lists e.g. `mix_veg_sambar` under both Dal and Pulses-1, and
#: importing it twice put one dish in two categories with a duplicate name.
#: More specific category wins; ties resolve by this order.
COURSE_PRIORITY = [
    "nonveg_soup", "infused_water", "sambar", "rasam", "dal", "soup",
    "nonveg_main", "salad", "starter", "healthy_rice", "bread", "rice",
    "veg_gravy", "veg_dry", "dessert", "welcome_drink", "curd_side",
]

#: Spellings the source uses for a dish the ontology (or the source itself)
#: writes another way.
def _tok(*variants):
    """A pattern matching any of *variants* as a whole snake_case token."""
    return r"(?<![a-z0-9])(?:" + "|".join(variants) + r")(?![a-z0-9])"


SPELLING = [
    (_tok("chciken", "chcken", "chiceken", "chikcen", "chickem"), "chicken"),
    (_tok("parataha", "paratah", "paranthaa"), "paratha"),
    (_tok("pomogranate", "pomogranete"), "pomegranate"),
    (_tok("biriyani", "briyani"), "biryani"),
    (_tok("kanjee", "kanjii"), "kanji"),
    (_tok("corriander", "coriender"), "coriander"),
    (_tok("rassam"), "rasam"),
    (_tok("mediteranean", "mediterranian"), "mediterranean"),
    (_tok("cajune", "cajuce"), "cajun"),
    (_tok("idly"), "idli"),
    (_tok("samber", "sambhar"), "sambar"),
    (_tok("chhutney", "chutny"), "chutney"),
    (_tok("wate"), "water"),
    (_tok("beet"), "beetroot"),
    (r"cous_cous", "couscous"),
    (_tok("vegetabe", "vegitable"), "vegetable"),
    (_tok("thalasserry"), "thalassery"),
    (_tok("kerla"), "kerala"),
    (_tok("asorted"), "assorted"),
    (_tok("manglore"), "mangalore"),
    (_tok("chetinad", "chettinadu", "chittinadu", "chettibnadu"), "chettinad"),
    (_tok("capcicum", "capsicium"), "capsicum"),
    (_tok("enchilladas", "enchillada", "enchiladas"), "enchilada"),
    (_tok("chat"), "chaat"),
    (_tok("coullie", "coulli"), "coulis"),
    (r"blue_berry", "blueberry"),
    (_tok("dryfruit"), "dry_fruit"),
    (_tok("hydrabadi", "hyderabadi"), "hyderabadi"),
    (_tok("lashooni", "lassoni", "lasooni"), "lasooni"),
    # --- second pass: typos found by diffing imported tokens against the
    # vocabulary the ontology already uses. Only clear misspellings and
    # run-together words are here. Words that are merely NEW (dabeli, tukpa,
    # dhansak, foogath, couscous, enchilada) are left alone — Booking's menu is
    # more international than the existing list, so new vocabulary is expected.
    # So are real words a fuzzy match would have wrecked: `kalan` is a Kerala
    # yogurt curry (not `kala`), `nadan` is Kerala-style (not `naan`), `atta` is
    # wheat flour (not `patta`), `kolakkatai` is a dumpling (not `kolkata`), and
    # `cole_salw_salad` is coleslaw — the typo there is `salw`, not `cole`.
    (_tok("detaox", "deto"), "detox"),
    (_tok("kozambu", "kozhambu", "karakozambu"), "kuzhambu"),
    (_tok("khorma"), "korma"),
    (_tok("oranch"), "orange"),
    (_tok("pineaaple", "pinepple", "pipeapple"), "pineapple"),
    (_tok("strawbery"), "strawberry"),
    (_tok("porial"), "poriyal"),
    (_tok("koffta", "kofft"), "kofta"),
    (_tok("simlamirch"), "shimlamirch"),
    (_tok("parippu", "parupu", "parpu"), "paruppu"),
    (_tok("sarbat", "sharabhat", "rooafza"), "sharbath"),
    (_tok("bhajji"), "bhaji"),
    (_tok("kushka", "kuska"), "khuska"),
    (_tok("adaraki"), "adraki"),
    (_tok("awadi"), "awadhi"),
    (_tok("badhushai"), "badushahi"),
    (_tok("basill"), "basil"),
    (_tok("bhath"), "bhat"),
    (_tok("burffi"), "burfi"),
    (_tok("carroy"), "carrot"),
    (_tok("cinnaman"), "cinnamon"),
    (_tok("cury"), "curry"),
    (_tok("darshni", "dharsini"), "darshini"),
    (_tok("drumstik"), "drumstick"),
    (_tok("ghilli", "chiulli", "chilly"), "chilli"),
    (_tok("jinger"), "ginger"),
    (_tok("kosambri", "kuchambari"), "kosambari"),
    (_tok("leaks"), "leeks"),
    (_tok("majjiga", "majjihe"), "majjige"),
    (_tok("minestronie", "minstrone", "minestorne"), "minestrone"),
    (_tok("moongh"), "moong"),
    (_tok("muligatawany", "mullaguthwanny", "muligatawny"), "mulligatawny"),
    (_tok("murg"), "murgh"),
    (_tok("phindi"), "pindi"),
    (_tok("pulaov", "pulav", "pylao"), "pulao"),
    (_tok("pumpkine"), "pumpkin"),
    (_tok("rasagulla"), "rasgulla"),
    (_tok("sabudhana", "sagoo"), "sabudana"),
    (_tok("salw"), "slaw"),
    (_tok("sarru"), "saru"),
    (_tok("tehari"), "tehri"),
    (_tok("tika"), "tikka"),
    (_tok("tortila"), "tortilla"),
    (_tok("vanila"), "vanilla"),
    (_tok("szchuan"), "schezwan"),
    (_tok("goosberry"), "gooseberry"),
    (_tok("pappaya"), "papaya"),
    (_tok("navarathan"), "navratan"),
    (_tok("panchamel"), "panchmel"),
    (_tok("mohabat"), "mohabbat"),
    (_tok("shajahani"), "shahjahani"),
    (_tok("thondeka"), "thondekkai"),
    (_tok("varutha", "varutharaicha"), "varutharacha"),
    (_tok("urandi", "urndai"), "urundai"),
    (_tok("zhuccuni"), "zucchini"),
    (_tok("maleysian"), "malaysian"),
    (_tok("singaporian"), "singaporean"),
    (_tok("vindolaloo"), "vindaloo"),
    (_tok("thalakappati"), "thalappakatti"),
    (_tok("chetinadu"), "chettinad"),
    # run-together words the printed menu lost the space in
    (r"vaniyambadichicken", "vaniyambadi_chicken"),
    (r"tomatosoup", "tomato_soup"),
    (r"rawbanana", "raw_banana"),
    (r"clusterbeans", "cluster_beans"),
    (r"ashgourd", "ash_gourd"),
    (r"staranise", "star_anise"),
    (r"spawater", "spa_water"),
    (r"kachekela", "kache_kela"),
    (_tok("baingun"), "baingan"),
    (_tok("jalferezi"), "jalfrezi"),
    (_tok("luki"), "louki"),
    (_tok("parata"), "paratha"),
    (_tok("meeta"), "meetha"),
    (_tok("thondekkai"), "thondekai"),
]

SOUTH = ("sambar", "rasam", "poriyal", "kootu", "pappu", "kuzhambu", "thoran",
         "palya", "dosa", "idli", "pongal", "chettinad", "kerala", "andhra",
         "malabar", "thalassery", "avial", "erissery", "olan", "puliyogare",
         "bisibele", "kozhambu", "varutharacha", "kadamba", "payasam",
         "mysore", "curry_leaf", "karuvepillai", "medu", "uttapam", "appam",
         "idiyappam", "kanji", "sagu", "saagu", "gassi", "koottu",
         "puliyogare", "vangi", "kosambri", "kootu", "poriyal", "usili",
         "podi", "molagootal", "pachadi", "thokku", "kara", "milagu",
         "arachuvitta", "ven_pongal", "kalan", "theeyal", "puttu")
CHINESE = ("manchurian", "schezwan", "szechuan", "hakka", "kung_pao",
           "noodle", "chowmein", "chow_mein", "dimsum", "wonton", "pho")
CONTINENTAL = ("pasta", "lasagna", "lasagne", "burrito", "enchilada",
               "quesadilla", "couscous", "mediterranean", "thai", "mexican",
               "ratatouille", "gratin", "stroganoff", "penne", "spaghetti",
               "hummus", "falafel", "taco", "risotto", "minestrone")
NONVEG = {"chicken": "chicken", "mutton": "mutton", "lamb": "lamb",
          "fish": "fish", "prawn": "prawn", "egg": "egg", "crab": "crab",
          "keema": "chicken", "murgh": "chicken", "kozhi": "chicken",
          "meen": "fish", "anda": "egg"}


def norm(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = re.sub(r"\s+", " ", str(v).replace("\n", " ")).strip()
    return s


def to_item(name: str) -> str:
    """Source spelling -> the ontology's snake_case dish name."""
    s = str(name).strip().lower()
    s = s.replace("&", " and ").replace("/", " ")
    s = re.sub(r"[()\[\],.\'\"`]", " ", s)
    s = re.sub(r"^\s*\d+\s*[.)]\s*", "", s)   # printed-menu numbering
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    s = re.sub(r"^\d+_", "", s)
    # NB: `\b` does not fire next to `_` — an underscore is a word character —
    # so `\bchciken\b` never matched `chciken_mulligatawny`, and every
    # correction below was silently inert on multi-word names. The lookarounds
    # below are the boundary that actually holds for snake_case.
    for pat, rep in SPELLING:
        s = re.sub(pat.replace(r"\b", ""), rep, s)
    return re.sub(r"_+", "_", s).strip("_")


#: Pairs that LOOK alike but are different dishes. Similarity cannot tell these
#: from a misspelling — `greek_salad` vs `green_salad` differ by one letter and
#: both words are real — so they are adjudicated by hand rather than guessed.
KEEP_APART = {
    ("greek", "green"),
    # Kadai is the wok, kadhi is the yogurt curry — two different paneer dishes.
    # This is the same wrong merge `ncr_fuzzy_unmerge.py` had to reverse.
    ("kadai", "kadhi"),
}

#: Pairs where both spellings are real vocabulary but name ONE dish, so the fold
#: cannot use "is this a known word?" to decide. Left of the pair is kept.
SAME_DISH = {
    ("navratan", "navaratan"),
    ("mysore_pak", "mysorepak"),
    ("chettinad", "chettinadu"),
    ("potato", "potatoes"),      # singular/plural, one dish
    ("chaat", "chat"),           # `chaat` is the ontology's spelling
    ("ice", "iced"),             # peach ice / iced tea
    ("badushahi", "badhushai"),  # one Karnataka sweet, two transliterations
}


def _tokens(name):
    return [t for t in re.split(r"[^a-z0-9]+", name) if t]


def _differing(a, b):
    """The token pair that distinguishes two same-length names, else None."""
    ta, tb = _tokens(a), _tokens(b)
    if len(ta) != len(tb):
        return None
    diff = [(x, y) for x, y in zip(ta, tb) if x != y]
    return diff[0] if len(diff) == 1 else None


def fold_similar(names, vocab=None, cutoff=0.90, report=None):
    """Collapse near-identical names, keeping the BETTER-SPELLED one.

    Two defects made the first version worse than not folding at all:

    * it kept whichever name sorted first, which is the *misspelling* about half
      the time — `chciken_mulligatawny` over `chicken_mulligatawny`,
      `aiwain_chapathi` over `ajwain_chapathi`. These names get printed on a
      menu, so that is not cosmetic.
    * it merged `greek_salad` into `green_salad`, which are different dishes.

    So a merge now needs evidence. `vocab` is the token frequency of the dish
    names Bangalore already carries: a token nobody has ever used is a typo, and
    the variant built from real words wins. When BOTH sides are real words the
    pair is ambiguous and is only merged if it is listed in SAME_DISH — anything
    else is kept apart and reported, because a silent wrong merge loses a dish.
    """
    vocab = vocab or {}

    def support(name):
        return sum(vocab.get(t, 0) for t in _tokens(name))

    kept = []
    for n in sorted(names):
        match = difflib.get_close_matches(n, kept, n=1, cutoff=cutoff)
        if not match:
            kept.append(n)
            continue
        other = match[0]
        pair = _differing(n, other)
        if pair:
            x, y = pair
            if tuple(sorted((x, y))) in {tuple(sorted(p)) for p in KEEP_APART}:
                kept.append(n)                      # different dishes
                if report is not None:
                    report.setdefault("kept_apart", []).append((other, n))
                continue
            known = (vocab.get(x, 0) > 0, vocab.get(y, 0) > 0)
            same = tuple(sorted((x, y))) in {tuple(sorted(p)) for p in SAME_DISH}
            if all(known) and not same:
                kept.append(n)                      # both real words: ambiguous
                if report is not None:
                    report.setdefault("ambiguous", []).append((other, n))
                continue
        # a merge: keep whichever spelling the existing vocabulary supports
        if support(n) > support(other):
            kept[kept.index(other)] = n
            if report is not None:
                report.setdefault("merged", []).append((n, other))
        elif report is not None:
            report.setdefault("merged", []).append((other, n))
    return kept


#: Leading words that describe how a dish is served rather than what it is, so
#: `plain_chapati` and `chapati` are one bread. Deliberately tiny: `veg_biryani`
#: is NOT `biryani`, so `veg` is not here.
NOISE_MODIFIERS = {"plain", "simple", "regular", "normal", "home_style"}


def _existing_twin(candidate, existing_names, vocab, cutoff=0.90):
    """The ontology dish *candidate* is a spelling of, or None.

    Same evidence as `fold_similar`: a one-token difference where the
    candidate's token is unknown vocabulary (a typo or a variant) folds into the
    dish already present; two real words are different dishes and are kept.
    """
    # A whole-token difference scores far below the similarity cutoff —
    # "plain_chapati" vs "chapati" is 0.70 — so difflib never offers the pair.
    # Strip a leading serving-style word and look the dish up directly.
    toks = _tokens(candidate)
    if len(toks) > 1 and toks[0] in NOISE_MODIFIERS:
        stripped = "_".join(toks[1:])
        if stripped in existing_names:
            return stripped
    for other in difflib.get_close_matches(candidate, existing_names, n=3,
                                           cutoff=cutoff):
        pair = _differing(candidate, other)
        if pair is None:
            # differs by a whole token ("plain_chapati" vs "chapati")
            ta, tb = set(_tokens(candidate)), set(_tokens(other))
            extra = ta ^ tb
            if extra and all(vocab.get(t, 0) > 0 for t in extra):
                return other
            continue
        x, y = pair
        key = tuple(sorted((x, y)))
        if key in {tuple(sorted(p)) for p in KEEP_APART}:
            continue
        if key in {tuple(sorted(p)) for p in SAME_DISH}:
            return other
        if not (vocab.get(x, 0) > 0 and vocab.get(y, 0) > 0):
            return other
    return None


def vocab_from(frame) -> dict:
    """Token frequency of the dish names the ontology carries BEFORE this import.

    Rows this script added (``client`` is exactly the Booking token) are
    excluded, or the script would not be idempotent: after a first run those
    names are in the vocabulary, so a pair that merged as "one side is a typo
    nobody uses" now reads as "both sides are known words", splits, and the
    re-run adds 14 dishes that were deliberately folded away.
    """
    if "client" in frame.columns:
        mine = frame["client"].astype(str).str.strip().str.lower() \
            == CLIENT_TOKEN.lower()
        frame = frame[~mine]
    counts = {}
    for name in frame["item"].astype(str):
        for t in _tokens(name.strip().lower()):
            counts[t] = counts.get(t, 0) + 1
    return counts


def cuisine_for(item: str, course: str) -> str:
    if any(t in item for t in CHINESE):
        return "chinese"
    if any(t in item for t in CONTINENTAL):
        return "continental"
    if any(t in item for t in SOUTH):
        return "south_indian"
    if course in ("sambar", "rasam"):
        return "south_indian"
    return "north_indian"


def protein_for(item: str, course: str) -> str:
    for token, protein in NONVEG.items():
        if re.search(rf"\b{token}", item):
            return protein
    return "" if course not in ("nonveg_main", "nonveg_soup") else "chicken"


def parse_source() -> dict:
    """{'<Sheet>||<Label>': [raw dish, …]} for the Lunch and Dinner sheets."""
    LABEL_HINTS = {"menu pattern", "dinner menu", "lunch", "menu spread",
                   "descrption", "description", "breakfast"}
    DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday"}
    out = defaultdict(set)
    for sheet in ("Lunch", "Dinner"):
        d = pd.read_excel(SOURCE, sheet_name=sheet, header=None)
        label_cols = []
        for c in range(d.shape[1]):
            vals = [norm(v).lower() for v in d[c] if norm(v)]
            if len(vals) >= 5 and (any(v in LABEL_HINTS for v in vals)
                                   or len(set(vals)) < len(vals) * 0.9):
                label_cols.append(c)
        for lc in label_cols:
            end = next((c for c in label_cols if c > lc), d.shape[1])
            for r in range(d.shape[0]):
                label = norm(d.iat[r, lc])
                if not label or label.lower() in LABEL_HINTS:
                    continue
                for c in range(lc + 1, end):
                    dish = norm(d.iat[r, c])
                    low = dish.lower()
                    if (not dish or low in DAYS
                            or re.match(r"^\d{4}-\d{2}-\d{2}", dish)
                            or re.fullmatch(r"[\d.]+", low)):
                        continue
                    out[f"{sheet}||{label}"].add(dish)
    return {k: sorted(v) for k, v in out.items()}


def build(blr: pd.DataFrame, raw: dict):
    """Return (new_rows_df, retag_count, report)."""
    existing = {str(i).strip().lower(): idx for idx, i in blr["item"].items()}
    by_course = defaultdict(set)
    for key, dishes in raw.items():
        label = key.split("||", 1)[1]
        if label in SKIP_LABELS:
            continue
        course = CATEGORY_MAP.get(key)
        if not course:
            continue
        for d in dishes:
            item = to_item(d)
            if not item:
                continue
            # The printed rows are coarser than the app's categories: "Dal
            # (Buffet 1)" and "Pulses - 2" both carry sambars, so
            # `traditional_sambar` landed in rasam and `karnataka_sambar` in
            # dal. The dish name is the better evidence — file by it.
            tail = item.rsplit("_", 1)[-1]
            if course in ("dal", "rasam", "sambar"):
                if tail == "sambar":
                    course_final = "sambar"
                elif tail in ("rasam", "saru"):
                    course_final = "rasam"
                elif "majjige_huli" in item or "more_curry" in item:
                    course_final = "curd_side"   # a yogurt curry, not a lentil
                else:
                    course_final = course
            else:
                course_final = course
            by_course[course_final].add(item)

    # A dish named for its CATEGORY ("sambar", "salad") is not a dish — the menu
    # cannot print it and no colour or ingredient rule can reason about it.
    # `remove_generic_rows.py` deletes these; importing one straight back in
    # would undo that, so reuse its list rather than keeping a second copy.
    try:
        from remove_generic_rows import GENERIC_ROWS
        generic = {str(g).strip().lower() for g in GENERIC_ROWS}
    except Exception:                                    # pragma: no cover
        generic = {"sambar", "rasam", "salad", "dal", "sweet", "chutney",
                   "rice", "veg_gravy", "curd", "soup"}

    # One dish, one category: walk the courses in priority order and let the
    # first claim win.
    claimed: set = set()
    ordered = ([c for c in COURSE_PRIORITY if c in by_course]
               + [c for c in sorted(by_course) if c not in COURSE_PRIORITY])
    for course in ordered:
        keep = set()
        for item in by_course[course]:
            if item in generic or item in claimed:
                continue
            claimed.add(item)
            keep.add(item)
        by_course[course] = keep

    template = blr.iloc[0]
    flag_cols = [c for c in blr.columns if c.startswith("is_")]
    nid = max(
        (int(m.group(1)) for s in blr["item_id"].dropna().astype(str)
         for m in [re.search(r"(\d+)", s)] if m), default=0) + 1

    vocab = vocab_from(blr)
    existing_by_course = defaultdict(set)
    for _, r in blr.iterrows():
        existing_by_course[str(r["course_type"]).strip().lower()].add(
            str(r["item"]).strip().lower())
    fold_log: dict = {}
    rows, report, retag = [], {}, 0
    for course in ordered:
        items = by_course[course]
        folded = fold_similar(items, vocab=vocab, report=fold_log)
        # "Unique" means unique against the ONTOLOGY, not just within this
        # import. Exact-matching alone let `plain_chapati` in beside the
        # existing `chapati` — the same dish under another name — and that had
        # a real consequence: Booking pins "plain chapati" as its daily bread,
        # a pin that is stamped as text while the dish is absent but becomes a
        # solver constraint the moment it exists. Pinned to one dish for five
        # days with no staple declaration, `unique_items` made the counter
        # INFEASIBLE. So each candidate is folded against the dishes this
        # course_type already carries, under the same evidence rules.
        here = sorted(existing_by_course.get(course, set()))
        new, seen = [], []
        for i in folded:
            if i in existing:
                seen.append(i)
                continue
            twin = _existing_twin(i, here, vocab)
            if twin:
                seen.append(twin)
                fold_log.setdefault("matched_existing", []).append((twin, i))
            else:
                new.append(i)
        report[course] = {"folded": len(folded), "new": len(new),
                          "existing": len(seen)}
        # Booking also makes the dishes Bangalore already has: add it to their
        # client list, promoting to `common` at the threshold.
        for i in seen:
            idx = existing[i]
            cur = str(blr.at[idx, "client"] or "").strip()
            toks = [t.strip() for t in cur.split(",") if t.strip()]
            if any(t.lower() == "common" for t in toks):
                continue
            if any(t.lower() == CLIENT_TOKEN.lower() for t in toks):
                continue
            toks.append(CLIENT_TOKEN)
            blr.at[idx, "client"] = ("common" if len(toks) >= COMMON_AT
                                     else ",".join(toks))
            retag += 1
        for item in new:
            r = template.copy()
            for c in flag_cols:
                r[c] = 0
            r["item_id"] = f"MENU{nid:06d}"
            nid += 1
            r["item"] = item
            r["course_type"] = course
            r["cuisine_family"] = cuisine_for(item, course)
            protein = protein_for(item, course)
            r["primary_protein"] = protein
            r["sub_category"] = ""
            r["key_ingredient"] = ""
            r["item_color"] = ""
            r["client"] = CLIENT_TOKEN
            if protein == "egg" and "is_egg_dish" in r.index:
                r["is_egg_dish"] = 1
            if protein in ("fish", "prawn", "crab"):
                for c in ("is_seafood", "is_fish_dish"):
                    if c in r.index:
                        r[c] = 1
            rows.append(r)
    return pd.DataFrame(rows), retag, report, fold_log


def main(dry_run=False):
    blr = pd.read_excel(BLR)
    blr.columns = [c.strip() for c in blr.columns]
    before = len(blr)
    raw = parse_source()
    new_df, retag, report, fold_log = build(blr, raw)

    print(f"{'COURSE_TYPE':<16} {'folded':>7} {'already':>8} {'NEW':>5}")
    print("-" * 40)
    for course, s in sorted(report.items()):
        print(f"{course:<16} {s['folded']:>7} {s['existing']:>8} {s['new']:>5}")
    for label, note in (("kept_apart", "different dishes, kept apart"),
                        ("ambiguous", "both spellings are real words, kept")):
        for a, b in fold_log.get(label, []):
            print(f"  ! {note}: {a} / {b}")
    print(f"\nmerged spellings: {len(fold_log.get('merged', []))}"
          f"   folded into a dish already in the ontology: "
          f"{len(fold_log.get('matched_existing', []))}")
    print(f"\nnew dishes: {len(new_df)}   rows re-tagged with "
          f"{CLIENT_TOKEN}: {retag}")
    print(f"bangalore: {before} -> {before + len(new_df)} rows")

    if dry_run:
        print("[dry-run] nothing written")
        return blr, new_df
    out = pd.concat([blr, new_df], ignore_index=True) if len(new_df) else blr
    out.to_excel(BLR, index=False)
    print(f"wrote {BLR.name}")
    return out, new_df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(dry_run=ap.parse_args().dry_run)
