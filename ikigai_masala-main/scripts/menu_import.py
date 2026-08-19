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
    # "Haramoonghj mughlai" — not a word in any language; hara moong is the
    # only reading, and a menu printing "Haramoonghj" is worse than a fold.
    (_tok("haramoonghj"), "hara_moong"),
    # --- fourth pass: Stryker Bangalore's seven weekly grids.
    (_tok("saseme"), "sesame"),
    (_tok("kebeb"), "kebab"),
    (_tok("birayni", "biryanai"), "biryani"),
    (_tok("tringa"), "tiranga"),
    (_tok("manchurain"), "manchurian"),
    (_tok("garvy"), "gravy"),
    (_tok("birayani"), "biryani"),
    (_tok("capcicum"), "capsicum"),
    (_tok("shimlamirch"), "shimla_mirch"),
    (_tok("wih"), "with"),
    (_tok("pineaplle"), "pineapple"),
    (_tok("gujarathi", "gujrathi"), "gujarati"),
    (_tok("channadal"), "chana_dal"),
    (_tok("khushka"), "khuska"),
    (_tok("tindly"), "tindli"),
    (_tok("compond"), "compound"),
    (_tok("dalimbe"), "dalimba"),
    (_tok("thalesseri"), "thalassery"),
    # --- fifth pass: Citrix's master menu. Targets checked against Bangalore's
    # own counts: payasam 28 vs payasa 1, handi 26 vs hundi 3, kolhapuri the
    # correct spelling of a three-way split (6/4/3), do_pyaza 13 vs do_pyaz 1.
    (_tok("durmstick"), "drumstick"),
    (_tok("yello"), "yellow"),
    (_tok("punjabhi"), "punjabi"),
    (_tok("chiili"), "chilli"),
    (_tok("pualo"), "pulao"),
    (_tok("guntoor"), "guntur"),
    (_tok("haryali"), "hariyali"),
    (_tok("makhni"), "makhani"),
    (_tok("pudhina"), "pudina"),
    (r"knol_knol", "knol_khol"),
    (r"do_pyaz(?![a-z0-9])", "do_pyaza"),
]

#: **One dish, one spelling** — the minority transliterations the city workbooks
#: are folded onto by `canonical_dish_spellings.py`, which imports this map.
#:
#: It lives here, with the rest of the vocabulary, because the two halves must
#: never disagree: the workbook is renamed to the house spelling AND every
#: incoming name is rewritten to it. Keep them in separate lists and each
#: import quietly adds a second row for a dish already present — `channa`
#: rewritten but `subzi` not, `kolhapuri` rewritten but `lacha` not, and so on.
#: Booking's import drifted from 0 new dishes to 9, then to 3, then to 3 again
#: chasing exactly that gap.
#:
#: Counts behind each choice (Bangalore): chana 153/channa 16, kadhi 13/kadi 2,
#: sabzi 77/subzi 13, payasam 28/payasa 1, handi 26/hundi 3, do_pyaza 13/do_pyaz
#: 1, laccha the standard spelling, kolhapuri correct across a 6/4/3 split.
CANONICAL_SPELLINGS = {
    "channa": "chana",
    "kadi": "kadhi",
    "subzi": "sabzi",
    "sabji": "sabzi",
    "payasa": "payasam",
    "hundi": "handi",
    "kolapuri": "kolhapuri",
    "kholapuri": "kolhapuri",
    "lacha": "laccha",
    # The Kannada saaru/greens family, which four client menus spell five ways:
    # saru 24 rows vs saaru 9, soppu 49 vs soppina 3 vs sappu 2.
    "saaru": "saru",
    "sappu": "soppu",
    # NOT folded: `soppina` -> `soppu`. Only 3 rows, and it would merge
    # `soppina_saru` (spice-based rasam, garlic, brown) into `soppu_saru`
    # (which the client says is a SAMBAR, and whose colour and key_ingredient
    # agree). Those look like two different dishes, and merging two real dishes
    # is the mistake `ncr_fuzzy_unmerge.py` had to reverse.
}

SPELLING += [(_tok(minority), house)
             for minority, house in CANONICAL_SPELLINGS.items()]


#: A parenthesised aside describes how a dish is served or where it is from —
#: "Chicken tikka Masala(Boneless)", "Mysore Rasam (Karnataka)", "Soya veg
#: Cutlet(tasting)". It is not part of the dish name, and keeping it produces a
#: near-duplicate of the same dish written without it.
_PARENTHETICAL = re.compile(r"\([^)]*\)?")


#: Cells that hold a placeholder rather than a dish. Printed menus write "Na",
#: "-", "--" for a day a category is not served; imported literally they become
#: dishes named `na` and `nil`.
PLACEHOLDERS = {"na", "n/a", "n.a.", "nil", "none", "-", "--", "---", "x",
                "tbd", "no", "nothing",
                # a day the site is closed is not a dish
                "holiday", "closed", "off", "leave", "no service"}


def is_placeholder(text: str) -> bool:
    s = str(text).strip().lower().strip(".-–— ")
    return not s or s in PLACEHOLDERS


def norm(v) -> str:
    """A cell's text with newlines and runs of whitespace flattened."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return re.sub(r"\s+", " ", str(v).replace("\n", " ")).strip()


#: A printed cell often holds two dishes — "Puri + Chapti", "Idli + Chutney",
#: "Veg Cutlet /Green Chutney". Imported whole it becomes one dish named after
#: both, which no rule can reason about and no kitchen has an entry for.
_COMBO_SPLIT = re.compile(r"\s*(?:\+|&|,| and )\s*", re.I)


#: Column headers that mark a NON-dish column in a printed grid: portion sizes
#: and nutrition blocks sit between the day columns in several client menus.
#: Their numbers filter out as numeric, but `allergen` holds words ("gluten",
#: "dairy") and `Kg/Pcs` holds "Adq" — both import as dishes if not skipped.
QUANTITY_HEADERS = {"kcal", "pro", "protein", "fat", "carb", "carbs", "fiber",
                    "fibre", "allergen", "allergens", "kg/pcs", "kg", "pcs",
                    "qty", "quantity", "gms", "grams"}


def quantity_columns(sheet, scan_rows: int = 8) -> set:
    """Columns holding a portion size or a nutrition value rather than a dish."""
    cols: set = set()
    for r in range(min(scan_rows, sheet.shape[0])):
        row = [norm(sheet.iat[r, c]).strip().lower()
               for c in range(sheet.shape[1])]
        if sum(1 for v in row if v in QUANTITY_HEADERS) >= 2:
            cols |= {c for c, v in enumerate(row) if v in QUANTITY_HEADERS}
    return cols


def split_combo(text: str) -> list:
    """["Puri", "Chapti"] from "Puri + Chapti"; [text] when there is no combo.

    Only splits on `+` — the separator these menus use for "served with". `&`
    and `and` are left alone because they appear INSIDE dish names ("Aloo
    Gobhi and Methi", "Salt & Pepper"), where splitting would invent two
    dishes that do not exist.
    """
    parts = [p.strip() for p in re.split(r"\s*\+\s*", str(text)) if p.strip()]
    return parts or [str(text).strip()]


#: Whole dish names a menu writes differently from the name the ontology
#: already carries. A token-level SPELLING rule cannot express these: `huli` IS
#: sambar in Kannada, but `majjige_huli` is a buttermilk CURRY and renaming that
#: token would invent a dish. So the mapping is per whole name.
#:
#: Without it the fold and `canonical_dish_spellings.DUPLICATES` fight: the
#: merge drops the duplicate row, the next import re-adds it under the source's
#: own spelling, and the import stops being idempotent. Citrix did exactly that
#: with these four.
ALIASES = {
    "soppu_huli": "soppu_sambar",
    "uppusaaru": "uppu_saru",
    "upsaaru": "uppu_saru",
    "soppu_saaru": "soppu_saru",
}


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
    s = re.sub(r"_+", "_", s).strip("_")
    return ALIASES.get(s, s)


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
    # Transliteration pairs. Each names ONE dish, and both spellings are real
    # words, so without listing them the fold reads the pair as ambiguous and
    # the ontology ends up carrying the dish twice.
    ("kebab", "kabab"),
    ("pakora", "pakoda"),
    ("sukka", "sukha"),
    ("korma", "kurma"),
    ("gobi", "gobhi"),
    ("phulka", "fulka"),
    ("paratha", "parantha"),
    ("ajwain", "ajwaini"),
    # Bangalore is split between `chapatti` (34 rows) and `chapati` (14), and
    # `canonical_dish_spellings.py` deliberately leaves that alone — both are
    # ordinary transliterations and the name is printed on a menu, so which one
    # wins is the client's call. Listing the pair here does not rename anything;
    # it stops each new client import ADDING the other spelling beside a dish
    # the ontology already carries, which is how a split of 48 rows becomes a
    # split of 80.
    ("chapatti", "chapati"),
    # Same treatment, same reason — the ontology is split and an import must
    # not deepen it: lauki 30 / louki 14, tendly 4 / tendli 2, and the
    # three-way pattani 7 / battani 6 / patani 2.
    ("lauki", "louki"),
    ("tendli", "tendly"),
    ("pattani", "battani"),
    ("pattani", "patani"),
    ("battani", "patani"),
    ("sliced", "slice"),
    ("pakoda", "pakodi"),
    ("singaporean", "singapore"),
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


def _same_dish(x: str, y: str) -> bool:
    """Do these two tokens name the same thing?

    Listed pairs, plus the general case they kept turning up as: a trailing
    plural. `millet`/`millets`, `fruit`/`fruits`, `cluster_bean`/`cluster_beans`
    are one dish written two ways, and enumerating every noun a kitchen might
    pluralise is a losing game.
    """
    if tuple(sorted((x, y))) in _SAME_DISH_KEYS:
        return True
    a, b = sorted((x, y), key=len)
    return len(b) > 2 and b in (a + "s", a + "es")


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
            same = _same_dish(x, y)
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
        if _same_dish(x, y):
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


#: Tails that make a dish a RICE whatever row it was printed on. Deliberately
#: narrow: `bath` is excluded because `kesari_bath` is a sweet named for a rice
#: dish, and `rice` because `curd_rice` belongs to the curd-rice station.
_RICE_TAILS = ("khichdi", "khichadi", "pulao", "biryani", "pilaf", "kushka",
               "khuska", "chitranna")

#: Courses that are already a correct home for a rice-named dish.
_RICE_OK = ("rice", "healthy_rice", "nonveg_main")


def refile_rice(item: str, course: str) -> str:
    """A khichdi printed in the dal row is still a rice.

    Printed menus put whatever the day needs in whatever row has space —
    `millets_khichdi` and `red_rice_pilaf` came in under "DAL / SAMBAR", and
    `veg_kofta_biryani` under "Raitha/Chutney". Left there they are served as a
    dal or a raita. `audit_course_types.py` catches exactly this after the fact
    and fails the build, so the import should not create it in the first place.
    """
    if course in _RICE_OK:
        return course
    if item.rsplit("_", 1)[-1] in _RICE_TAILS:
        return "rice"
    return course


#: Name tails that identify a dish's course, most specific first. A printed row
#: says where a dish was SERVED; these say what it IS, which is what decides
#: which pool it belongs in. Order matters — `sambar_rice` is a rice, not a
#: sambar, so the rice tails are consulted before the lentil ones.
_COURSE_TAILS = (
    ("rice", ("rice", "sadam", "biryani", "briyani", "pulao", "pilaf",
              "khichdi", "khichadi", "kushka", "khuska", "chitranna", "bath",
              "noodles", "chowmein")),
    ("sambar", ("sambar", "huli")),
    # `saru` is deliberately absent: most saarus are rasams, but `soppu_saru`
    # is a SAMBAR (the client corrected it, and its colour and key_ingredient
    # agree), so the word does not settle the question on its own.
    ("rasam", ("rasam", "charu")),
    ("dal", ("dal", "paruppu", "pappu")),
    ("veg_gravy", ("gravy", "curry", "masala", "kurma", "korma", "kuzhambu",
                   "kozhambu", "kootu", "kadhi", "makhani", "butter_masala")),
    ("bread", ("dosa", "dosai", "idli", "idly", "uttapam", "uthappam", "appam",
               "idiyappam", "paratha", "parotta", "roti", "chapati", "chapatti",
               "poori", "puri", "naan", "kulcha", "phulka", "adai", "pesarattu",
               "bhatura", "batura", "chapathi", "chappathi", "kali", "koozh",
               "sevai", "upma", "poha", "pongal", "kichadi", "khichadi")),
    ("starter", ("vada", "vadai", "bonda", "bajji", "bhaji", "pakoda",
                 "pakora", "samosa", "cutlet", "tikki", "roll", "kachori",
                 "chaat", "chat", "manchurian", "65")),
    ("veg_dry", ("poriyal", "palya", "thoran", "usili", "sukka", "porial")),
    ("salad", ("salad", "sundal", "kosambari", "kosumalli")),
    ("dessert", ("halwa", "kesari", "payasam", "kheer", "laddu", "laddoo",
                 "burfi", "barfi", "jamun", "jamoon", "pak", "sweet", "poli",
                 "obbattu", "holige", "jalebi", "rasgulla", "basundi")),
    ("welcome_drink", ("juice", "lassi", "milkshake", "sharbath", "sharbat",
                       "mojito", "cooler", "panaka", "neer", "tea", "coffee")),
    ("soup", ("soup", "shorba", "broth")),
    ("curd_side", ("raita", "raitha", "pachadi")),
)


#: Words that join two halves of a printed plate: "Chapathi with Chicken
#: Curry", "Rava Idli with Sambar and Chutney", "Bajji & Bonda".
_PLATE_JOINERS = ("with", "and")


def looks_like_a_plate(item: str) -> bool:
    """Is this a whole plate written as one line rather than a dish?

    A menu bank lists what a site sells, so it mixes dishes with the combos
    they are sold in. "Chapathi with Chicken Curry" is two dishes the file also
    lists separately; imported whole it becomes a "dish" no kitchen has an
    entry for and no rule can reason about — its colour, cuisine and protein
    are all ambiguous because it is two dishes.

    The test is a joiner word with a **course-bearing token on both sides**, so
    genuine names survive: `aloo_gobhi_and_methi` is one dish (no course word),
    `dal_makhani` has no joiner, and `curd_rice_with_tadka` names a dish plus a
    tempering rather than two courses.
    """
    toks = [t for t in str(item).split("_") if t]
    for i, tok in enumerate(toks):
        if tok not in _PLATE_JOINERS:
            continue
        left = course_from_name("_".join(toks[:i]))
        right = course_from_name("_".join(toks[i + 1:]))
        # Same course on both sides is still a plate: "veg biryani and curd
        # rice" and "bajji and bonda" are each two dishes. A genuine compound
        # name has no course word on one of the sides — `aloo_gobhi_and_methi`
        # names three vegetables, `dal_tadka_with_butter` a dal and a fat.
        if left and right:
            return True
    return False


def course_from_name(item: str) -> str:
    """The course a dish NAME implies, or "" when the name does not say.

    Used where a printed category is too coarse or genuinely mixed — Chennai's
    "Tiffin / South Indian" row holds both dosas and vadas, its "Main Meal" row
    holds sambar, rasam and plain rice. Returning "" rather than guessing is
    the point: the caller falls back to the printed category, which is better
    evidence than a shrug.
    """
    # Scan from the END backwards and take the first token that names a
    # course. The last word is usually the dish's form — `sambar_rice` is a
    # rice, `idli_sambar` is a sambar — but not always: `dal_fry` ends in a
    # cooking method, and only the token before it says what the dish is.
    toks = [t for t in str(item).split("_") if t]
    for tok in reversed(toks):
        for course, tails in _COURSE_TAILS:
            if tok in tails:
                return course
    return ""


def refile_lentils(item: str, course: str) -> str:
    """Re-file a lentil-family dish by its NAME rather than its printed row.

    Printed rows are coarser than the app's categories: "Dal (Buffet 1)" and
    "Pulses - 2" both carry sambars, so `traditional_sambar` landed in rasam and
    `karnataka_sambar` in dal. The dish name is the better evidence.
    """
    course = refile_rice(item, course)
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


#: Names that are a CATEGORY, not a dish. A menu printing "Sweet" or "Veg Dry"
#: is useless and no colour or ingredient rule can reason about the row. This is
#: the union across cities plus the app's own base-slot names, because an import
#: reads a grid where the category labels sit in the same columns as the dishes
#: and one always slips through.
_EXTRA_GENERIC = {
    "sambar", "rasam", "salad", "dal", "sweet", "chutney", "rice", "veg_gravy",
    "veg_dry", "curd", "soup", "bread", "dessert", "starter", "gravy", "raita",
    "welcome_drink", "nonveg_main", "non_veg", "veg", "papad", "pickle",
    "indian_bread", "flavour_rice", "flavoured_rice", "spl_item", "special",
    "combo", "accompaniments", "condiments",
}


def generic_row_names() -> Set[str]:
    """Category names an import must never add as dishes.

    `remove_generic_rows.py` deletes these from the workbooks; importing one
    straight back in would undo that, so its list is reused rather than kept in
    a second copy. NB its `GENERIC_ROWS` is a **city -> names** mapping, so it
    has to be flattened — iterating it directly yields the city names
    (`chennai`, `ncr`, `pune`) and the guard silently matched nothing.
    """
    names = set(_EXTRA_GENERIC)
    try:
        from remove_generic_rows import GENERIC_ROWS
        for per_city in GENERIC_ROWS.values():
            names |= {str(g).strip().lower() for g in per_city}
    except Exception:                                    # pragma: no cover
        pass
    return names


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
    #: snake_case dish names to never import: the const-slot staples every
    #: printed menu repeats daily (steamed rice, curd, papad) and the station
    #: names that are not dishes ("make your own salad", "live counter").
    skip_items: Set[str] = field(default_factory=set)
    #: split a cell like "Puri + Chapti" into two dishes. Off by default —
    #: only opt in where the source actually writes combos that way.
    split_combos: bool = False
    #: {snake_case dish: {site, …}} when the source says WHICH of the client's
    #: sites serve each dish. A new row is then tagged with its real sites
    #: (promoted to `common` at `common_at`) instead of one synthetic token.
    #: Matters because a city outside `FULL_POOL_CITIES` narrows each client to
    #: `common` plus its own pools — a dish tagged only "Chennai Bank" would be
    #: invisible to every Chennai client.
    client_by_item: Dict[str, Set[str]] = field(default_factory=dict)
    #: {snake_case dish: item_color} when the source states the food colour.
    #: `item_color` drives the colour-variety rules and a blank is invisible to
    #: them, so a source that supplies it is worth reading.
    colour_by_item: Dict[str, str] = field(default_factory=dict)


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
        raw_dishes = dishes
        if spec.split_combos:
            raw_dishes = [p for d in dishes for p in split_combo(d)]
        for d in raw_dishes:
            if is_placeholder(d):
                continue
            item = spec.clean_name(d)
            if not item or item in spec.skip_items:
                continue
            landing = spec.refile(item, course)
            # A dish whose NAME declares an animal protein must not be filed in
            # a veg slot: `PoolBuilder._nonveg_mask` drops it from that pool and
            # it becomes unservable. Printed menus mix them — Stryker's "Spl
            # item" row runs veg cutlets and an egg pepper masala on alternate
            # days — so the row label cannot be trusted for this one thing.
            if landing not in NONVEG_COURSES and protein_for(item, landing):
                landing = "nonveg_main"
            by_course[landing].add(item)
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
            # Tag with the dish's REAL sites where the source names them, the
            # flat token otherwise. It has to be the same identity the new-row
            # branch writes, or a re-run finds none of its own tags present and
            # appends the flat token to all of them, for ever.
            want = sorted(spec.client_by_item.get(i) or {spec.client_token})
            have = {t.lower() for t in toks}
            fresh = [w for w in want if w.lower() not in have]
            if not fresh:
                continue
            toks.extend(fresh)
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
            r["item_color"] = spec.colour_by_item.get(item, "")
            sites = sorted(spec.client_by_item.get(item, ()))
            r["client"] = ("common" if len(sites) >= spec.common_at
                           else ",".join(sites) if sites
                           else spec.client_token)
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


def write_workbook(frame: pd.DataFrame, path: Path) -> None:
    """Write *frame* to *path* atomically.

    `to_excel` truncates the target and then streams into it, so a run that is
    interrupted part-way — a timeout, a Ctrl-C — leaves a 0-byte workbook and
    the city's whole item list is gone. That happened. Writing to a sibling
    temp file and renaming makes the swap atomic: the workbook is either the
    old one or the new one, never a half-written one.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        frame.to_excel(tmp, index=False)
        tmp.replace(path)
    finally:
        if tmp.exists():                                 # pragma: no cover
            tmp.unlink()


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
    write_workbook(out, spec.city_path)
    print(f"wrote {spec.city_path.name}")
    return out, new_df
