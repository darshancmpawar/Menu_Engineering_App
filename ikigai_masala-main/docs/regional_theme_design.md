# Regional theme days — design

**Status: design only. Nothing here is built.** It depends on the five
`*_cleaned_final_1.xlsx` workbooks, which are not installed (four dish-level
verdicts are still open). Every number below was measured from those uploads on
2026-09-21; the script is `scripts/` material once the feature is approved.

The ask: *on the client config, for a given day, pick a regional theme* — a
Tamil Nadu Thursday, a Maharashtra Friday — on top of the cuisine theme the day
already has.

---

## 1. What the data actually supports

### 1.1 `state_origin` is 100% filled and ~26% informative

The new workbooks add six columns: `state_origin`, `admin_type`,
`is_single_state`, `state_confidence`, `region_authority`, `region_reason`.
`state_origin` has no blanks. That is not the same as having a region for every
dish.

| city | rows | rows naming a single state | share |
|---|---|---|---|
| bangalore | 5,884 | 1,540 | 26% |
| hyderabad | 5,994 | 1,337 | 22% |
| ncr | 1,416 | 260 | 18% |
| pune | 1,318 | 208 | 16% |
| chennai | 667 | 211 | 32% |

The other ~75% sit in pan-level buckets that **restate `cuisine_family`**. All
2,724 Bangalore rows reading `Pan-North India` carry `cuisine_family:
north_indian` and `region_reason: no sub-regional signal`. NCR words it "no
state signal; kept at pan level". They are not regional facts; they are the
absence of one, spelled as a value.

This is the `fill_cuisine_family.py` situation exactly: a column that looks
complete, where the majority value means "we don't know".

### 1.2 Do not gate on `state_confidence` or `region_authority`

Both are tempting and both are unusable:

- `state_confidence: high` is **9 rows** in Bangalore, 1 in Chennai, 73 in NCR,
  and **0 in Pune and Hyderabad**. There is no threshold here to stand on.
- `region_authority` is not comparable between cities. Pune and Hyderabad are
  **100% `NAME_LEXICON` with no `UNRESOLVED` bucket at all**; Bangalore is 66%
  `UNRESOLVED`, NCR 70%. The same pipeline did not run the same way on every
  city, so a rule reading this column means something different per city.

Gate on **`admin_type ∈ {state, union_territory}`** instead. It is consistent in
every city, and it is exactly `is_single_state` (verified: the crosstab is
perfectly diagonal, 1,521 `state` + 19 `union_territory` = 1,540 `True`, zero
off-diagonal). `is_single_state` carries no information `admin_type` lacks;
prefer `admin_type`, which also distinguishes `foreign` from `non_state`.

### 1.3 A hard regional filter reproduces a failure this repo already had

Distinct dishes per slot, Bangalore, single-state rows only:

| region | rice | veg_gravy | veg_dry | starter | nonveg | bread | dal | sambar | rasam | dessert |
|---|---|---|---|---|---|---|---|---|---|---|
| Tamil Nadu | 37 | 50 | 95 | 4 | 18 | 9 | 48 | 155 | 102 | 8 |
| Karnataka | 40 | 53 | 171 | 11 | 11 | 23 | 15 | 39 | 17 | 17 |
| Punjab | **0** | 47 | 9 | 1 | 20 | **0** | 21 | 0 | 0 | 6 |
| Kerala | **4** | 28 | 21 | **0** | 21 | 15 | 1 | 0 | 0 | 0 |
| Andhra Pradesh | 9 | 15 | 8 | 12 | 19 | 5 | 17 | 1 | 2 | 1 |
| Maharashtra | 10 | 10 | 14 | 8 | 5 | **0** | 2 | 1 | 0 | 10 |
| Telangana | 27 | 18 | **2** | 0 | 11 | 0 | 4 | 0 | 0 | 0 |

**Bangalore holds zero Punjabi rice and zero Punjabi bread.** A
`ThemeSlotFilterRule`-style narrowing on a Punjabi Thursday empties both slots.
That is `scripts/ncr_south_bread.py`'s incident verbatim — NCR had three south
breads, the cuisine lock narrowed to them, the cooldown drained them, and the
solve went INFEASIBLE with no starved slot to point at.

**So: a regional theme is a FLOOR, never a FILTER.** This is the single
load-bearing decision in this document and it is measured, not preferred.

### 1.4 Which regions are themeable at all

A weekly regional day recurs ~3× inside the 20-day cooldown window, plus the
week being planned, so a 1-cell slot needs **4 distinct regional dishes** to
carry it every week. Counting slots that clear that floor:

| city | full day (7+ deep slots) | partial (5-6) | accent only (3-4) | not themeable |
|---|---|---|---|---|
| bangalore | Tamil Nadu 10, Karnataka 11, Andhra 7 | Punjab 6, Kerala 5, Maharashtra 6 | Telangana 4, West Bengal 4 | Rajasthan, UP, Gujarat, J&K (≤3) |
| hyderabad | Tamil Nadu 8, Karnataka 11, Andhra 8 | Punjab 5, Kerala 5, Maharashtra 6 | Telangana 4, West Bengal 3 | Gujarat, Rajasthan, UP, J&K |
| chennai | Tamil Nadu 11 | — | — | everything else (≤2) |
| ncr | — | — | Punjab 4, Tamil Nadu 4, Rajasthan 3, Maharashtra 3 | everything else |
| pune | — | Maharashtra 6 | Punjab 3, Tamil Nadu 3 | everything else |

The honest answer to "can I pick a regional theme" is **yes, for one to three
regions per city**. Bangalore and Hyderabad support a real regional programme;
Chennai supports exactly one region; NCR and Pune support a partial day at best.
The UI must offer only what the city can serve — offering Rajasthan in Bangalore
is offering a day that will quietly degrade to an ordinary plate.

### 1.5 Every region nests inside one cuisine family

| region | cuisine_family of its dishes |
|---|---|
| Tamil Nadu, Karnataka, Kerala, Andhra, Telangana | `south_indian` (100%, bar a handful of `drink` rows) |
| Punjab, Maharashtra, West Bengal, Rajasthan, UP, Gujarat, J&K | `north_indian` (100%) |

Two consequences. First, **the theme↔region compatibility matrix is derivable
from the workbook** rather than hand-written, so it cannot drift. Second, this
is precisely why the regional layer is worth having: `cuisine_family` files
Maharashtra, Punjab and Bengal under one label and structurally cannot tell a
Maharashtrian Friday from a Punjabi one.

---

## 2. The design

### 2.1 Data layer — no new column

Use `state_origin` scoped by `admin_type`. Nothing to add, nothing to derive.

### 2.2 Engine — one selector key, one config key. No new rule type.

**(a) Add `state_origin` and `admin_type` to `_SELECTOR_KEYS` / `_TEXT_COLS`**
in `selector_frequency_rule.py`. Four rule types delegate to
`SelectorFrequencyRule._matches` — `selector_frequency`, `slot_composition`,
`soft_preference`, `same_day_exclusion` — so one edit makes regions expressible
in all of them. `attribute_grouping` already accepts any column as `group_by`.

**(b) Add `allowed_weekdays`** to `selector_frequency` — the positive twin of
the `forbidden_weekdays` it already has, and the only thing missing for a
per-weekday floor. Roughly ten lines, mirroring the existing parser.

That is the whole engine change. The regional day is then an ordinary rule:

```json
{
  "name": "region_thu_tamil_nadu",
  "type": "selector_frequency",
  "selector": {"state_origin": "Tamil Nadu"},
  "base_slot": ["veg_gravy", "veg_dry", "rice", "dal", "sambar", "rasam"],
  "daily_min": 3,
  "allowed_weekdays": ["thu"]
}
```

`daily_min` is already the right primitive and for the right reason: it caps to
`min(daily_min, len(lits), len(day_cells))` per day, so a thin day **relaxes
instead of failing**, and it already stamps a `RELAXATION` when it caps (note
31). A Punjabi day whose bread slot has nothing Punjabi degrades to a floor of 2
*and says so in the explanation*, rather than silently serving a plate with no
region on it.

### 2.3 The control lives on the PLANNER, not in Edit Logic

A region is a weekly editorial decision — "let's do a Tamil Thursday this week"
— not a structural fact about the site, so it belongs where the menu is, and it
has to work **after** a plan exists. A strip of per-day pickers sits above the
menu table; picking one and hitting **Apply** re-solves that day alone.

The mechanism already exists: `POST /api/v1/regenerate`
(`MenuRegenerator.regenerate`) locks every cell outside a replace mask and
re-solves the rest. Applying a region is exactly that call with the mask set to
the chosen day's regional-capable cells, plus the §2.2 rule for that date. So
the week's `unique_items`, the 20-day cooldown, the freshness objective and the
cross-counter `shared_items` sync all still hold — the day is solved **against**
the rest of the week rather than in place of it, and no new solve path is
introduced.

So the region reaches the solver as a **per-date request field** on `/plan` and
`/regenerate`:

```json
"region_days": {"2026-09-25": "Tamil Nadu"}
```

Config persistence is the second step, not the entry point. A **Save as this
client's weekly default** action writes the weekday map onto the counter:

```json
"region_map": {"thu": "Tamil Nadu"}
```

which seeds the strip on every later generation and can still be overridden for
one week from the planner. That covers "before is fine too" without making the
editor the only way in. The map is normalised at write time against the city's
themeable-region list, and an unthemeable region is **rejected at the PUT** —
note 9's lesson, that a config key which silently matches nothing is the
expensive failure, because the plan still comes back and looks fine.

The rules in §2.2 are **generated from the map or the request field**, never
hand-written per client. 36 client files each hand-rolling a regional floor is
how `rule_library.json` came to exist.

**Page-level, not per-counter.** One strip for the client, because "Thursday is
a Tamil Nadu day at this site" is how the decision is actually made. It applies
to every counter whose theme admits the region and skips the others, saying so
("applies to 2 of 3 counters") rather than silently doing nothing on the Chinese
station.

### 2.3b The floor's slot list is derived from the region's own depth

Not a fixed set. Punjab's floor of 3 runs over
`[veg_gravy, veg_dry, dal, nonveg_main, dessert]` — the slots §1.4 measured as
deep enough — so it is always satisfiable, and rice and bread are simply not
part of it. "Thin" is then an editor note about what the day *will not* carry,
not a runtime relaxation.

That distinction matters because it keeps `RELAXATION` meaning one thing: the
pool ran out **this week** under the cooldown, which is worth telling a chef.
A region that never had a Punjabi rice to begin with is a fact about the city
list and belongs in the picker, where it is visible before anyone generates
anything.

### 2.4 The compatibility guard — an ERROR, not a degradation

A Tamil Nadu Thursday on a `chinese`-themed Thursday is not satisfiable: the
theme filter removes every south dish from the cuisine-main slots before the
floor is evaluated, so the floor caps to 0 and drops. That is note 9e's case —
"a frequency cap can be forced past, and that must be detected, not discovered
as INFEASIBLE".

`diagnose()` computes the region's `cuisine_family` set from the pool and
reports an ERROR when the day's theme admits none of it. Derived from the data
(§1.5), so it stays correct as the workbooks change.

Compatible pairings follow from §1.5: Tamil Nadu / Karnataka / Kerala / Andhra /
Telangana go with `south` or `mix`; Punjab / Maharashtra / Bengal / Rajasthan
with `north` or `mix`. `chinese`, `continental` and `biryani` days take no
region.

### 2.5 Soft top-up, so the day reads as regional

The hard floor puts 3 regional dishes on the plate. A `soft_preference`
`prefer_daily` on the same selector and slots, `priority: low`, scoped to the
same weekday, makes the solver prefer regional dishes in the *remaining* cells
without ever trading a real rule for one.

Tier arithmetic, since note 32 says the ladder must be checked rather than
trusted: ~6 slots × 25 days × 1e6 = 1.5e8, which is 0.15 of one MEDIUM unit and
negligible against the 1.86e15 already measured below THEME. This adds no
meaningful mass, and `tests/rules/test_objective_tier_headroom.py` fails if that
estimate is wrong.

### 2.6 UI — a strip on the planner, under the Save row

`app.py` gains a **Regional days** panel between the Save/Download/Clear row and
the counter tabs: one card per date in the horizon, each with the day's theme
badge and a compact region select, laid out with `st.columns(len(dates))` so the
cards line up over the table beneath. Changing one marks that day pending and
reveals **Apply to menu** / **Reset**; applying calls `/regenerate` for that day
and reports how many cells moved.

The select is where the §1 measurements become visible:

- compatible regions carry their depth — `Karnataka · 11 slots`
- incompatible ones are **disabled with the reason** — `West Bengal — wrong
  cuisine for this day`
- regions below the §1.4 floor are **disabled, not hidden** — `Rajasthan — too
  few dishes in Bangalore` — so an operator can see they were weighed
- a `chinese` or `biryani` day disables the control outright and says why

Options come from `/editor-metadata` as `themeable_regions_by_city`, computed by
the §1.4 depth measurement and committed as a small JSON the way
`pool_tokens.json` already is (note 22) — the endpoint must not open five
workbooks to answer.

`customisation/theme_editor.py` gets nothing new. The only config surface is the
**Save as weekly default** action in §2.3, which writes `region_map` from the
planner.

### 2.7 Explanation

`src/explain/` gains one line per regional day, built from the pack the same way
a pairing is: *"Thursday is a Tamil Nadu day — the kara kuzhambu, the kootu and
the vathal kuzhambu are Tamil, and the sambar and rasam carry it too."* And when
the floor relaxed, it says that instead. `explain_llm.validate` keeps policing
provenance unchanged, because every word of it comes from dish rows in the pack.

---

## 3. What must not be built

- **No hard per-slot regional narrowing.** §1.3. This is the whole decision.
- **No gate on `state_confidence` or `region_authority`.** §1.2 — inconsistent
  across cities, and `high` is 9 rows in the largest one.
- **No region offered below the depth floor.** §1.4. A Rajasthan day in
  Bangalore is a day that degrades to nothing and reports a relaxation nobody
  asked for.
- **No change to `cuisine_family` or `theme_map`.** The regional layer sits on
  top. A Tamil Nadu day is still a `south` day to every existing rule, which is
  what keeps this additive.

---

## 4. Dependency, and why it cannot be prototyped on today's data

The committed workbooks carry `cuisine_family_region`, which is the same idea at
a quarter of the coverage: **377 granular Bangalore rows** (punjabi 43, andhra
43, kerala 42, mughlai 29, chettinad 26) spread across every slot — below the
§1.4 floor for every region. NCR has 44, Pune 172 of which 135 are
`indian_drink`.

Where the two overlap they **agree**: andhra → Andhra Pradesh 37 of 43,
chettinad → Tamil Nadu 25 of 26, bengali → West Bengal 17 of 17, awadhi → Uttar
Pradesh 18 of 24. That is independent corroboration that the new column is
accurate, from a column nobody built it from.

So the feature is real and the data is credible, and it waits on the four open
dish verdicts before the workbooks can be installed.
