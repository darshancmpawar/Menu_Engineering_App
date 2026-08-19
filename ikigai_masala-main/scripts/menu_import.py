#!/usr/bin/env python3
"""Shared machinery for importing a client's printed menu into a city ontology.

Extracted from the Booking import when Stripe needed the same thing. A second
near-copy is exactly the duplication the rule library was built to stop, and the
subtle parts here are the ones you least want two divergent copies of: which
spellings are typos and which look-alike pairs are different dishes
(`greek_salad` / `green_salad`), why the vocabulary must exclude the import's own
rows (or the second run un-folds what the first run merged), and why a dish is
folded against the category it is being filed into rather than against the whole
ontology.

A client importer supplies only what is specific to it — where the workbook is,
how to read its grid, and which printed label maps to which app slot:

    from menu_import import ImportSpec, run_import

    run_import(ImportSpec(
        client_token="Stripe",
        city_path=CITY,
        parse=parse_source,                       # -> {'<block>||<label>': [dish]}
        category_map={"Lunch||Gravy Veg": "veg_gravy", ...},
        skip_labels={"Steamed Rice", "Curd"},
    ))

Everything else is shared: name normalisation, the evidence-based fold, filing
one dish into exactly one category, `common`-at-six client tagging, and the row
builder that sets only the attributes a dish NAME actually supports.
"""
from __future__ import annotations

import difflib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Sequence, Set

import pandas as pd


# ---------------------------------------------------------------------------
# 1. Language: source spelling -> the ontology's snake_case dish name
# ---------------------------------------------------------------------------

def _tok(*variants: str) -> str:
    """A pattern matching any of *variants* as a whole snake_case token.

    NB: `\\b` does NOT fire next to `_` — an underscore is a word character — so
    `\\bchciken\\b` never matched `chciken_mulligatawny` and every correction was
    silently inert on multi-word names. These lookarounds are the boundary that
    actually holds for snake_case.
    """
    return r"(?<![a-z0-9])(?:" + "|".join(variants) + r")(?![a-z0-9])"


#: Spellings a printed menu uses for a dish the ontology writes another way.
#: Shared across clients on purpose: catering menus are typed by hand and the
#: same handful of misspellings recur, so a correction proven on one client's
#: workbook should apply to the next one.
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
    # dhansak, foogath, couscous, enchilada) are left alone — these menus are
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
    # --- third pass: Stripe's two menus. Each target below is the spelling
    # Bangalore already uses, checked against the ontology rather than assumed
    # (`ajwain` 5 rows vs `ajawin` 1; `payasam` 28; `jamun` 10; `manchurian` 28;
    # `amritsari` 11; `gujarati` 10; `lavang_latika`, `kachumber_salad`,
    # `balushahi` present). `muradabadi` is deliberately absent: neither it nor
    # `moradabadi` is in any city list, so both spellings of the place name are
    # merely new vocabulary, not a typo to correct.
    # `chapti` only — NOT `chapathi`. Bangalore is genuinely split between
    # `chapatti` (34 rows) and `chapati` (14), both ordinary transliterations,
    # so rewriting `chapathi` to one of them turns a name the fold would have
    # merged into a third spelling that matches neither. `chapti` is a typo with
    # no rows behind it, so it is safe.
    (_tok("chapti"), "chapati"),
    (_tok("partha"), "paratha"),
    (_tok("ajawni"), "ajwain"),
    (_tok("grean"), "green"),
    (_tok("paysam"), "payasam"),
    (_tok("jammun"), "jamun"),
    (_tok("kuchmber"), "kachumber"),
    (_tok("cucumbar"), "cucumber"),
    (_tok("munchrina"), "manchurian"),
    (_tok("amritasri"), "amritsari"),
    (_tok("gujrati"), "gujarati"),
    (_tok("arahar"), "arhar"),
    (_tok("launk"), "lavang"),
    (_tok("balushai"), "balushahi"),
    (_tok("kolkatta"), "kolkata"),
    (_tok("chickepeas"), "chickpeas"),
    (_tok("pototo"), "potato"),
    (_tok("avacado"), "avocado"),
    (_tok("honye"), "honey"),
    (r"jeerarasam", "jeera_rasam"),
    (r"potatomcauliflower", "potato_cauliflower"),
    # The ontology writes these two overwhelmingly one way, so an import
    # spelling them the other creates a second row for the same dish:
    # `chana` 153 rows vs `channa` 16, `kadhi` 13 vs `kadi` 2. NB `kadhi` (the
    # yogurt curry) is NOT `kadai` (the wok) — that pair is in KEEP_APART.
    (_tok("channa"), "chana"),
    (_tok("kadi"), "kadhi"),
    # "Haramoonghj mughlai" — not a word in any language; hara moong is the
    # only reading, and a menu printing "Haramoonghj" is worse than a fold.
    (_tok("haramoonghj"), "hara_moong"),
]

#: A parenthesised aside describes how a dish is served or where it is from —
#: "Chicken tikka Masala(Boneless)", "Mysore Rasam (Karnataka)", "Soya veg
#: Cutlet(tasting)". It is not part of the dish name, and keeping it produces a
#: near-duplicate of the same dish written without it.
_PARENTHETICAL = re.compile(r"\([^)]*\)?")


def norm(v) -> str:
    """A cell's text with newlines and runs of whitespace flattened."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return re.sub(r"\s+", " ", str(v).replace("\n", " ")).strip()


def to_item(name: str, drop_parentheticals: bool = False) -> str:
    """Source spelling -> the ontology's snake_case dish name.

    *drop_parentheticals* removes "(Boneless)", "(Karnataka)", "(tasting)" and
    the like before normalising. Off by default so an importer opts in only
    when its source actually annotates dish names that way.
    """
    s = str(name).strip().lower()
    if drop_parentheticals:
        s = _PARENTHETICAL.sub(" ", s)
    s = s.replace("&", " and ").replace("/", " ")
    s = re.sub(r"[()\[\],.\'\"`]", " ", s)
    s = re.sub(r"^\s*\d+\s*[.)]\s*", "", s)   # printed-menu numbering
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    s = re.sub(r"^\d+_", "", s)
    for pat, rep in SPELLING:
        s = re.sub(pat, rep, s)
    return re.sub(r"_+", "_", s).strip("_")


# ---------------------------------------------------------------------------
# 2. Similar items: the evidence-based fold
# ---------------------------------------------------------------------------

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
    ("mix", "mixed"),            # mix veg / mixed veg, one dish
    ("chaat", "chat"),           # `chaat` is the ontology's spelling
    ("ice", "iced"),             # peach ice / iced tea
    ("badushahi", "badhushai"),  # one Karnataka sweet, two transliterations
    # The same battered fritter, south (bajji) and west (bhaji). Both spellings
    # are real vocabulary, so only this listing stops `mirchi_bhaji` being
    # imported alongside the `mirchi_bajji` Bangalore already carries. The pair
    # only ever merges names that are otherwise token-for-token identical.
    ("bajji", "bhaji"),
}

_KEEP_APART_KEYS = {tuple(sorted(p)) for p in KEEP_APART}
_SAME_DISH_KEYS = {tuple(sorted(p)) for p in SAME_DISH}


def _tokens(name: str) -> list:
    return [t for t in re.split(r"[^a-z0-9]+", name) if t]


def _differing(a: str, b: str):
    """The token pair that distinguishes two same-length names, else None."""
    ta, tb = _tokens(a), _tokens(b)
    if len(ta) != len(tb):
        return None
    diff = [(x, y) for x, y in zip(ta, tb) if x != y]
    return diff[0] if len(diff) == 1 else None


def fold_similar(names: Iterable[str], vocab: Optional[dict] = None,
                 cutoff: float = 0.90, report: Optional[dict] = None) -> list:
    """Collapse near-identical names, keeping the BETTER-SPELLED one.

    Two defects made the first version worse than not folding at all:

    * it kept whichever name sorted first, which is the *misspelling* about half
      the time — `chciken_mulligatawny` over `chicken_mulligatawny`,
      `aiwain_chapathi` over `ajwain_chapathi`. These names get printed on a
      menu, so that is not cosmetic.
    * it merged `greek_salad` into `green_salad`, which are different dishes.

    So a merge now needs evidence. `vocab` is the token frequency of the dish
    names the city already carries: a token nobody has ever used is a typo, and
    the variant built from real words wins. When BOTH sides are real words the
    pair is ambiguous and is only merged if it is listed in SAME_DISH — anything
    else is kept apart and reported, because a silent wrong merge loses a dish.
    """
    vocab = vocab or {}

    def support(name):
        return sum(vocab.get(t, 0) for t in _tokens(name))

    kept: list = []
    for n in sorted(names):
        match = difflib.get_close_matches(n, kept, n=1, cutoff=cutoff)
        if not match:
            kept.append(n)
            continue
        other = match[0]
        pair = _differing(n, other)
        if pair:
            x, y = pair
            if tuple(sorted((x, y))) in _KEEP_APART_KEYS:
                kept.append(n)                      # different dishes
                if report is not None:
                    report.setdefault("kept_apart", []).append((other, n))
                continue
            known = (vocab.get(x, 0) > 0, vocab.get(y, 0) > 0)
            same = tuple(sorted((x, y))) in _SAME_DISH_KEYS
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


def _existing_twin(candidate: str, existing_names: Sequence[str], vocab: dict,
                   cutoff: float = 0.90):
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
        if key in _KEEP_APART_KEYS:
            continue
        if key in _SAME_DISH_KEYS:
            return other
        if not (vocab.get(x, 0) > 0 and vocab.get(y, 0) > 0):
            return other
    return None


def vocab_from(frame: pd.DataFrame, client_token: Optional[str] = None) -> dict:
    """Token frequency of the dish names the city carries BEFORE this import.

    Rows a previous run of the SAME import added are excluded, or the script
    would not be idempotent: after a first run those names are in the
    vocabulary, so a pair that merged as "one side is a typo nobody uses" now
    reads as "both sides are known words", splits, and the re-run adds back the
    dishes that were deliberately folded away.

    The match is on the client LIST, not on the whole cell. It used to compare
    the cell to the token exactly, which held only while this was the sole
    importer: the moment a second client's import re-tagged one of these rows it
    became "Booking.com,Stripe", stopped matching, rejoined the vocabulary, and
    Booking's re-run started adding dishes again.
    """
    if client_token and "client" in frame.columns:
        token = client_token.strip().lower()
        mine = frame["client"].astype(str).map(
            lambda v: token in {t.strip().lower() for t in str(v).split(",")})
        frame = frame[~mine]
    counts: dict = {}
    for name in frame["item"].astype(str):
        for t in _tokens(name.strip().lower()):
            counts[t] = counts.get(t, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# 3. Attributes a dish NAME supports (and nothing more)
# ---------------------------------------------------------------------------

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

#: Slots whose dishes are non-veg by definition, so a name with no protein word
#: in it still gets the default protein rather than reading as vegetarian.
NONVEG_COURSES = ("nonveg_main", "nonveg_soup")

#: Words that make a meat word in the same name mean the meat-FREE version:
#: `soya_keema`, `keema_veg_biryani`, `veg_seekh_kabab`, `red_velvet_pastry_egg_less`.
#: Without these a soya keema is stamped `primary_protein=chicken`, and
#: `PoolBuilder._nonveg_mask` then drops it from the veg pool it belongs to —
#: the dish becomes unservable rather than merely mislabelled.
VEG_QUALIFIERS = {"veg", "vegetable", "vegetarian", "soya", "soyabean", "soy",
                  "mushroom", "paneer", "tofu", "jackfruit", "less"}


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


#: Name words that say a non-veg dish is served DRY / semi-dry.
DRY_WORDS = ("dry", "fry", "fried", "roast", "sukka", "sukha", "kebab", "kabab",
             "tikka", "65", "finger", "fingers", "tandoori", "grill", "grilled",
             "pepper", "chilli", "manchurian", "crispy", "popcorn", "majestic",
             "varuval", "ghee_roast", "peri")

#: Name words that say it is served in a GRAVY.
GRAVY_WORDS = ("curry", "masala", "korma", "kurma", "gravy", "butter",
               "makhani", "pyaza", "pyaz", "lababdar", "kadai", "handi",
               "salan", "stew", "kuzhambu", "rogan", "tariwala", "do_pyaza",
               "chettinad", "vindaloo", "dopyaza")
#: NB `shorba` is deliberately absent — it is a SOUP, and Bangalore files its
#: shorbas under `nonveg_soup`. Reading it as a gravy would have stamped a
#: gravy flag on five soups.


def nonveg_structural_flags(item: str, protein: str, cuisine: str,
                            style: str = "") -> Set[str]:
    """The flags a non-veg dish needs to be PLACEABLE, from its name and row.

    Not cosmetic. `slot_composition`'s `nonveg_main_daily_pair` composes a 2-4
    slot non-veg counter as "one `is_nonveg_dry` + one north/south chicken
    gravy" every day, so a dish carrying neither flag can never be placed on
    such a counter at all. The first import left every `is_*` at 0 and so added
    18 non-veg dishes that were, in practice, unservable — and forcing one in
    with a `min: 1` frequency rule made the whole counter INFEASIBLE rather
    than simply not choosing it.

    *style* is the printed menu's own verdict ("dry" / "gravy") when its row
    label carries one — Stripe prints "Non-Veg Semi Dry or Dry" and "Non-Veg
    Curry or Main Course" as separate rows, which is better evidence than any
    name heuristic. The name decides when the label does not, and a biryani is
    a biryani whatever row it was printed on.
    """
    toks = set(item.split("_"))
    out: Set[str] = set()

    if "biryani" in toks:
        return {"is_nonveg_biryani", "is_biryani_item"}

    dry = style == "dry" or (not style and bool(toks & set(DRY_WORDS)))
    gravy = style == "gravy" or (not style and bool(toks & set(GRAVY_WORDS)))
    # A name can say both ("chicken tikka masala"): gravy wins, it is the dish's
    # form. With the label present only the label speaks.
    if gravy:
        out.add("is_nonveg_gravy")
        if protein == "chicken":
            out.add("is_south_chicken_gravy" if cuisine == "south_indian"
                    else "is_north_chicken_gravy")
    elif dry:
        out.add("is_nonveg_dry")
    return out


def protein_for(item: str, course: str) -> str:
    """The animal protein a dish NAME declares, or "" if it declares none.

    Two traps, both of which stamped the wrong protein onto real dishes:

    * `\\b` does not fire next to `_`, so `\\bfish` never matched
      `tawa_fish_fry` and the dish fell through to the non-veg default and was
      filed as chicken. Only a name STARTING with the protein word worked.
      Same lookaround boundary as `_tok`.
    * the first dict entry to match won regardless of where it sat in the name,
      so `anda_keema_ghotala` (an egg dish) matched `keema` and became chicken.
      The earliest match in the name is the one that names the dish.
    """
    best, best_at = "", None
    for token, protein in NONVEG.items():
        m = re.search(rf"(?<![a-z0-9]){token}", item)
        if m and (best_at is None or m.start() < best_at):
            best, best_at = protein, m.start()
    if best:
        # a meat word qualified as meat-free — soya keema, keema veg biryani
        if set(item.split("_")) & VEG_QUALIFIERS and course not in NONVEG_COURSES:
            return ""
        return best
    return "" if course not in NONVEG_COURSES else "chicken"


# ---------------------------------------------------------------------------
# 4. Filing: one dish, one category
# ---------------------------------------------------------------------------

#: When the same dish name comes out of two menu rows it must be filed ONCE.
#: A printed menu lists e.g. `mix_veg_sambar` under both Dal and Pulses-1, and
#: importing it twice put one dish in two categories with a duplicate name.
#: More specific category wins; ties resolve by this order.
COURSE_PRIORITY = [
    "nonveg_soup", "infused_water", "sambar", "rasam", "dal", "soup",
    "nonveg_main", "salad", "starter", "healthy_rice", "bread", "rice",
    "veg_gravy", "veg_dry", "dessert", "welcome_drink", "curd_side",
]


def refile_lentils(item: str, course: str) -> str:
    """Re-file a lentil-family dish by its NAME rather than its printed row.

    Printed rows are coarser than the app's categories: "Dal (Buffet 1)" and
    "Pulses - 2" both carry sambars, so `traditional_sambar` landed in rasam and
    `karnataka_sambar` in dal. The dish name is the better evidence.
    """
    if course not in ("dal", "rasam", "sambar"):
        return course
    tail = item.rsplit("_", 1)[-1]
    if tail == "sambar":
        return "sambar"
    if tail in ("rasam", "saru"):
        return "rasam"
    if "majjige_huli" in item or "more_curry" in item:
        return "curd_side"          # a yogurt curry, not a lentil
    return course


def generic_row_names() -> Set[str]:
    """Names that are a CATEGORY, not a dish ("sambar", "salad", "sweet").

    The menu cannot print one and no colour or ingredient rule can reason about
    it. `remove_generic_rows.py` deletes these; importing one straight back in
    would undo that, so reuse its list rather than keeping a second copy.
    """
    try:
        from remove_generic_rows import GENERIC_ROWS
        return {str(g).strip().lower() for g in GENERIC_ROWS}
    except Exception:                                    # pragma: no cover
        return {"sambar", "rasam", "salad", "dal", "sweet", "chutney",
                "rice", "veg_gravy", "curd", "soup"}


# ---------------------------------------------------------------------------
# 5. The import itself
# ---------------------------------------------------------------------------

@dataclass
class ImportSpec:
    """Everything one client's menu import needs beyond the shared machinery."""

    client_token: str
    #: the city workbook this menu is imported into
    city_path: Path
    #: () -> {'<block>||<label>': [raw dish, …]} — each workbook's grid differs
    parse: Callable[[], Dict[str, list]]
    #: '<block>||<label>' -> the app's course_type. A label absent here is
    #: skipped, so the map doubles as the list of rows worth importing.
    category_map: Dict[str, str]
    #: printed labels to ignore outright (fixed condiments, headings)
    skip_labels: Set[str] = field(default_factory=set)
    #: >= this many clients make the dish -> the row becomes `common`
    common_at: int = 6
    #: prefix for the generated item_id
    id_prefix: str = "MENU"
    #: (item, course) -> course, for menus whose printed rows are coarser than
    #: the app's categories. Defaults to the lentil-family re-filing.
    refile: Callable[[str, str], str] = refile_lentils
    course_priority: Sequence[str] = tuple(COURSE_PRIORITY)
    #: raw source name -> snake_case dish name. Override to opt into
    #: `to_item(..., drop_parentheticals=True)` or any source-specific cleanup.
    clean_name: Callable[[str], str] = to_item
    #: '<block>||<label>' -> "dry" or "gravy", when the printed row says which.
    #: A non-veg dish carrying neither `is_nonveg_dry` nor a chicken-gravy flag
    #: cannot be placed by `nonveg_main_daily_pair` at all, and the menu's own
    #: row labels are better evidence than a name heuristic.
    style_by_label: Dict[str, str] = field(default_factory=dict)


def build(frame: pd.DataFrame, raw: Dict[str, list], spec: ImportSpec):
    """Return (new_rows_df, retag_count, per-course report, fold log).

    *frame* is mutated in place for the re-tagging half (existing rows gaining
    this client in their `client` list); the new rows come back separately so a
    dry run can report without writing.
    """
    existing = {str(i).strip().lower(): idx for idx, i in frame["item"].items()}
    by_course: dict = defaultdict(set)
    style_of: dict = {}          # dish -> "dry"/"gravy", from its printed row
    for key, dishes in raw.items():
        label = key.split("||", 1)[1]
        if label in spec.skip_labels:
            continue
        course = spec.category_map.get(key)
        if not course:
            continue
        style = spec.style_by_label.get(key, "")
        for d in dishes:
            item = spec.clean_name(d)
            if not item:
                continue
            by_course[spec.refile(item, course)].add(item)
            if style:
                style_of.setdefault(item, style)

    generic = generic_row_names()

    # One dish, one category: walk the courses in priority order and let the
    # first claim win.
    claimed: set = set()
    ordered = ([c for c in spec.course_priority if c in by_course]
               + [c for c in sorted(by_course) if c not in spec.course_priority])
    for course in ordered:
        keep = set()
        for item in by_course[course]:
            if item in generic or item in claimed:
                continue
            claimed.add(item)
            keep.add(item)
        by_course[course] = keep

    template = frame.iloc[0]
    flag_cols = [c for c in frame.columns if c.startswith("is_")]
    nid = max(
        (int(m.group(1)) for s in frame["item_id"].dropna().astype(str)
         for m in [re.search(r"(\d+)", s)] if m), default=0) + 1

    vocab = vocab_from(frame, spec.client_token)
    existing_by_course: dict = defaultdict(set)
    for _, r in frame.iterrows():
        existing_by_course[str(r["course_type"]).strip().lower()].add(
            str(r["item"]).strip().lower())
    fold_log: dict = {}
    rows, report, retag = [], {}, 0
    for course in ordered:
        items = by_course[course]
        folded = fold_similar(items, vocab=vocab, report=fold_log)
        # "Unique" means unique against the ONTOLOGY, not just within this
        # import. Exact-matching alone let `plain_chapati` in beside the
        # existing `chapati` — the same dish under another name — and that had a
        # real consequence: Booking pins "plain chapati" as its daily bread, a
        # pin that is stamped as text while the dish is absent but becomes a
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
        # This client also makes the dishes the city already has: add it to
        # their client list, promoting to `common` at the threshold.
        for i in seen:
            idx = existing[i]
            cur = str(frame.at[idx, "client"] or "").strip()
            toks = [t.strip() for t in cur.split(",") if t.strip()]
            if any(t.lower() == "common" for t in toks):
                continue
            if any(t.lower() == spec.client_token.lower() for t in toks):
                continue
            toks.append(spec.client_token)
            frame.at[idx, "client"] = ("common" if len(toks) >= spec.common_at
                                       else ",".join(toks))
            retag += 1
        for item in new:
            r = template.copy()
            for c in flag_cols:
                r[c] = 0
            r["item_id"] = f"{spec.id_prefix}{nid:06d}"
            nid += 1
            r["item"] = item
            r["course_type"] = course
            cuisine = cuisine_for(item, course)
            r["cuisine_family"] = cuisine
            protein = protein_for(item, course)
            r["primary_protein"] = protein
            r["sub_category"] = ""
            r["key_ingredient"] = ""
            r["item_color"] = ""
            r["client"] = spec.client_token
            if protein == "egg" and "is_egg_dish" in r.index:
                r["is_egg_dish"] = 1
            if protein in ("fish", "prawn", "crab"):
                for c in ("is_seafood", "is_fish_dish"):
                    if c in r.index:
                        r[c] = 1
                r["key_ingredient"] = protein   # or an ingredient ban misses it
            # Without these the dish is in the pool but no composition can
            # place it — see `nonveg_structural_flags`.
            if course in NONVEG_COURSES:
                for c in nonveg_structural_flags(item, protein, cuisine,
                                                 style_of.get(item, "")):
                    if c in r.index:
                        r[c] = 1
            rows.append(r)
    return pd.DataFrame(rows), retag, report, fold_log


def run_import(spec: ImportSpec, dry_run: bool = False):
    """Read the city workbook, apply *spec*, print the report, write it back."""
    city = pd.read_excel(spec.city_path)
    city.columns = [c.strip() for c in city.columns]
    before = len(city)
    new_df, retag, report, fold_log = build(city, spec.parse(), spec)

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
          f"{spec.client_token}: {retag}")
    print(f"{spec.city_path.stem}: {before} -> {before + len(new_df)} rows")

    if dry_run:
        print("[dry-run] nothing written")
        return city, new_df
    out = pd.concat([city, new_df], ignore_index=True) if len(new_df) else city
    out.to_excel(spec.city_path, index=False)
    print(f"wrote {spec.city_path.name}")
    return out, new_df
