# Client Logics — Pune

Per-client menu requirements for Pune, mapped against what the tool enforces.
City-level rules live in [`pune_rulebook.md`](pune_rulebook.md); Bangalore's
clients are in [`client_logics.md`](client_logics.md).

**Source:** `pune_smaple_menu.xlsx`, sheet `Amadeus Pune` — one sample week plus
nine stated rules. Scope is **lunch**.

**Implementation:** the `"Amadeus Pune"` entry in
`data/configs/client_rules.json`. Asserted end to end by
`tests/test_pune_client_logic.py`.

---

## Amadeus Pune

One counter, seven service days (`serve_weekends` is set), all-north theme map,
`source_pools: []` (the whole Pune list — every row in
`data/raw/city_items/pune.xlsx` is tagged `common`). Categories, as configured in
the editor: Welcome Drink, Salad, Indian Bread, Flavoured Rice, White Rice, Veg
Dry, Veg Gravy, Dal, Dessert, Papad, **Curd / Raita**.

### The sample week

Read as Monday → Sunday. `—` is a deliberately blank row.

| | Mon | Tue | Wed | Thu | Fri | Sat | Sun |
|---|---|---|---|---|---|---|---|
| Salad | Green salad | Lachchedar onion | Boondi chat | Moong chat | Mix cut salad | Salad | **Raita** |
| Gravy veg | Dum aloo banarasi | Mix katol | Gatte nu sak | **Paneer mutter** | Green moong curry | Aloo mutter | — |
| Dry veg | **Soya chatpata dry** | Kadai veg dry | Green gujrat | Aloo jeera | Bhendi do pyaza | — | — |
| Rice item | Steam rice | **Coriender rice** | Steam rice | Steam rice | Steam rice | Rice | **Veg biryani** |
| Dal item | Dal makhani | Dal fry | Marwadi dal | Dal methi | Dal adraki | Dal | — |
| Bread | Chapati | Chapati | Chapati | Chapati | Chapati | Chapati | — |
| Papad | Papad | Papad | Papad | Papad | Papad | Papad | Papad |
| Butter milk | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Dessert | Motichur laddoo | Gulab jamun | Seviya kheer | Banana custerd | Besan barfi | Sweet | Sweet |

Two readings of the grid worth stating, because the rest follows from them:

* **The single "Rice item" row is two slots, and only ONE fills per day.** "white
  rice daily" + "flavour rice on Tue and sun" describe the same row: it shows the
  day's headline rice — the `white_rice` constant on Mon/Wed/Thu/Fri/Sat, the
  flavoured `rice` slot on Tuesday and Sunday. The grid is what settles it: Tue is
  *Coriender rice* and Sun is *Veg biryani*, with no steamed rice beside either.
  So "daily" in rule 3 means "on every day that has no flavoured rice", and a
  flavoured rice **replaces** the white rice rather than joining it. Read the other
  way round the plan served Tawa Pulao and steamed rice together on Tuesday, while
  Sunday came out right — two rules disagreeing on exactly one day.
* **Sunday's Salad column is a raita.** `raita` and `boondi_raita` are real Pune
  dishes filed under `curd_side` — the **Curd / Raita** category. That category is
  configured on the counter and restricted to Sunday, so the salad slot runs
  Mon–Sat and Sunday's row is a solved raita rather than a stamped string.

### Stated rules → implementation

| # | Stated | Status | Where |
|---|---|---|---|
| 1 | weekly 1 panner | DONE | `amadeus_pune_paneer_weekly` — `selector_frequency`, `key_ingredient: paneer`, `exact: 1`. No `base_slot`, so it counts across every slot: the Pune list has 13 paneer gravies and one paneer-based veg dry |
| 2 | weekly 1 soya | DONE | Two rules: `amadeus_pune_soya_veg_dry_weekly` (`exact: 1`, scoped to `veg_dry`) and `amadeus_pune_soya_total_weekly` (`max: 1` across every slot). Together: exactly one soya a week, and it is the veg dry — where the sample has it (Monday's Soya Chatpata Dry), and what makes the city's `premium_veg_dry_weekly` cap non-vacuous, since all three of Pune's `is_premium_veg_dry` items are the soya dries. Drop the `base_slot` if a soya gravy is acceptable instead |
| 3 | white rice daily | DONE | `white_rice` is a constant slot the counter already serves; `amadeus_pune_white_rice_off_on_flavour_rice_days` runs it Mon/Wed/Thu/Fri/Sat — off Sunday (rule 9) and off Tuesday, because a flavoured rice replaces it (see the reading above) |
| 4 | flavour rice on Tue and sun | DONE | `amadeus_pune_flavour_rice_tue_sun` — `slot_day_restriction` on `rice`, `allowed_weekdays: [tue, sun]` |
| 5 | chapati daily in indain bread | DONE | `amadeus_pune_chapati_daily` — `slot_composition` on `bread` with one `count: 1` component selecting `item: chapati`. On a one-slot family that means "this slot must be a chapati" |
| 6 | welcome drink will have butter milk daily | DONE | `amadeus_pune_buttermilk_daily` (same one-slot mandate, `is_buttermilk`) + `amadeus_pune_buttermilk_is_a_staple` (`repeatable_items`, so the daily repeat is exempt from `unique_items` and the 20-day cooldown) |
| 7 | sat and Sunday also working | DONE | `clients.serve_weekends = true` — already set in the live row |
| 8 | sat no veg dry it should be blank | DONE | `amadeus_pune_veg_dry_weekdays_only` — `veg_dry` runs Mon–Fri (Sunday drops it too, per rule 9) |
| 9 | in sun we server only flvour rice(any veg biryani), papad, welcom drinl and sweet that's all | DONE | `amadeus_pune_veg_gravy_mon_sat`, `_dal_mon_sat`, `_bread_mon_sat`, `_white_rice_mon_sat`, `_salad_mon_sat` take those five off Sunday; `amadeus_pune_sunday_veg_biryani` (`slot_composition` with `components_by_weekday: {sun: …}`) makes Sunday's rice a veg biryani. "Any" is why it selects on `is_mixedveg_biryani` rather than pinning a dish — the solver picks between `veg_biryani` and `handi_biryani` |
| Sun | (grid) Sunday's salad row is a raita | DONE | `amadeus_pune_curd_side_sunday_only` — the **Curd / Raita** category, restricted to Sunday, the biryani day and the only day the sample shows it. A real ontology dish (the solver picks between `raita` and `boondi_raita`), so it carries a colour and lands in history like any other. Widen `allowed_weekdays` if the client wants curd or raita on more days |

Generated structure, verified against the grid:

| slot | runs on |
|---|---|
| salad | Mon–Sat |
| curd_side (Curd / Raita) | Sun |
| veg_gravy | Mon–Sat |
| veg_dry | Mon–Fri |
| rice | Tue, Sun |
| white_rice | Mon–Sat |
| dal | Mon–Sat |
| bread | Mon–Sat, always chapati |
| papad | Mon–Sun |
| welcome_drink | Mon–Sun, always buttermilk |
| dessert | Mon–Sun |

### Sample dishes vs the Pune item list

**Every dish in the sample is already in the list** — all 34 of them. Most appear
under a different spelling, which is why an exact-name check finds only 22:

| Sample | Item in the list |
|---|---|
| Lachchedar onion | `lachchedar_onion_salad` |
| Moong chat | `moong_sprouts_chat` |
| Mix cut salad | `cut_salad` |
| Mix katol | `mix_kathol` |
| Gatte nu sak | `gatte_ki_sabzi` |
| Aloo mutter | `aloo_mutter_masala`, `aloo_mutter_homestyle` |
| Green gujrat | `green_gujarat` |
| Aloo jeera | `aloo_jeera_dry` |
| Bhendi do pyaza | `bhindi_do_pyaza` |
| Steam rice | `steamed_rice` (served via the `white_rice` constant slot) |
| Coriender rice | `coriander_rice` |
| Butter milk | `buttermilk` |
| Motichur laddoo | `moti_chur_laddu` |
| Seviya kheer | `semiya_kheer` |
| Banana custerd | `banana_custard` |
| Besan barfi | `besan_burfi` |

So nothing needs adding to the workbook for this client, and the generated week
can in principle be the sample week dish for dish. Two classification questions
the sample raises, neither of which blocks anything:

* **`mix_kathol` is filed as a `veg_dry`** but the sample serves it in the Gravy
  Veg row. Kathol dishes are usually a wet pulse curry, so `veg_gravy` may be the
  right course type — but reclassifying an item on the strength of one printed row
  is your call, not mine. As filed it can still appear, in the veg dry row.
* **`potato_chilli` carries `key_ingredient: paneer`** while being a potato dish.
  That makes it the only paneer-tagged `veg_dry`, so it counts against the "weekly
  1 paneer" rule if it is ever chosen. Looks like a tagging slip.

### Cross-city client rules

Two requirements the client stated for **every** city, so they live in each city
ruleset rather than a client block. Both are new capabilities; both are asserted
by `tests/test_same_day_exclusion.py` and `tests/test_soft_preference.py`.

| Stated | Where | Notes |
|---|---|---|
| Paneer should be served on a mix / south / north day; if not, then chinese or biryani | `paneer_prefers_mix_south_north_days` — `soft_preference` `mode: prefer_day_types`, high priority | **Soft on purpose.** The hard equivalent is `selector_frequency.allowed_day_types`, which forbids the dish on other days — and a counter themed chinese every weekday would then never serve paneer at all. "Prefer these, fall back to the others" needs the others to stay legal. `holiday` (a weekend day on a `serve_weekends` counter) is not in the preferred list either, so paneer lands on a working day |
| No soya, baby corn, chole or mushroom on the same day as paneer | `paneer_not_with_soya_babycorn_chole_mushroom` — the new `same_day_exclusion` rule type | **Hard.** `soft_preference`'s `different_day` mode is the soft cousin and can be outbid by gains elsewhere; "don't serve them together" is a constraint. Counted across every slot, since the point is the day's plate — a paneer gravy beside a soya veg dry is the pairing being avoided |

The four excluded families are one `any_of` selector rather than four rules, which
is what `any_of` was added for — they span both a text column and a flag:

| Family | Selector | Bangalore | Pune |
|---|---|---|---|
| soya | `key_ingredient: soy` | 82 items | 6 items (2 needed a tag fix — below) |
| baby corn | `name_contains: [babycorn, baby_corn]` | 34 items | **absent** |
| chole | `flag: is_chana_gravy` | 92 items | 20 items |
| mushroom | `key_ingredient: mushroom` | 76 items | **absent** — inert there, and `diagnose()` says so |

`is_chana_gravy` is how both ontologies file chole. It also covers the other
whole-legume gravies (chawli, for instance), which fits the intent of not pairing
a heavy legume curry with paneer — say so if chole should be narrower.

**Why baby corn is matched on the name.** `key_ingredient: baby_corn` looks like
the obvious selector and is the wrong one. It tags 67 Bangalore rows, of which
**3** are baby-corn dishes — it is the de-facto default for a mixed salad, and the
list includes `iceberg_lettuce`, `black_olives` and `garden_salad`. Meanwhile the
**34** dishes actually named after baby corn are tagged `corn`, `bell_pepper`,
`cauliflower`, `green_peas`, even `spinach`. A hard rule on that column would have
banned nearly every salad from every paneer day, fleet-wide, while still missing
31 of the 34 real dishes. All 8 Pune rows tagged `baby_corn` are salads and Pune
carries no baby-corn dish at all. The column is worth cleaning up when someone
owns the ontology; the rule should not wait on it.

**Two Pune soya dishes needed a tag fix.** `aloo_soya_sukha` and
`soya_capsicum_chatpata` sat on their vegetable's `key_ingredient` (`potato`,
`bell_pepper`), so the rule could not see them while the list's other four soya
dishes carried `soy`. Corrected in `scripts/pune_flag_corrections.py`, and
`tests/test_same_day_exclusion.py` now asserts every soya-named Pune dish carries
the tag.

**A dish that is both is a paneer dish.** `chole_paneer` and
`chole_paneer_masala` match `key_ingredient: paneer` *and* `is_chana_gravy`.
Counted on both sides, `a + b <= 1` reads `1 + 1 <= 1` and the dish silently
becomes unservable on every counter in every city. `SameDayExclusionRule._hits`
drops such a dish from the exclude side only, so a chole-paneer curry stays
servable and still blocks a *separate* soya dish that day.

Fleet check: all 57 counters still generate and no paneer day anywhere carries an
excluded dish. Bangalore menus do move — 11 of the 57 counters were serving an
excluded pairing before these rules — which is expected, since the client asked
for them in all cities.

### The Curd / Raita slot is a staple

Pune's list carries exactly **two** `curd_side` dishes (`raita`, `boondi_raita`)
and this client serves the slot on Sunday only. Under the 20-day item cooldown
that retires both within three weeks, leaving the slot with no candidate at all —
`/plan` answered 422 *"cooldown banned all 2 curd side candidates on Sunday"*.
Uniqueness was never the problem (the arithmetic starved-slot exception already
lifts it); the history ban was.

`pune.json` now declares `raita_is_a_staple` (`repeatable_items` on
`curd_side`), so both dishes are exempt from `unique_items` and from the cooldown
— exactly what R36 does for chapati/phulka in the bread slot, and consistent with
plain `curd`, which is globally repeatable for the same reason. Pinned by
`tests/test_pune_client_logic.py::TestRaitaSurvivesASavedWeek`, which fails on all
four assertions without the declaration.

### Open questions

1. **R45 (city) — fruit welcome drinks are for premium clients.** Moot for this
   client now that the welcome drink is buttermilk daily, but it still needs an
   answer for the next Pune site.
2. **R54 (city) — "a limited menu shall be served on Saturdays and Sundays".**
   This client's answer is concrete (Saturday drops the veg dry, Sunday drops
   four rows), so R54 is settled *for Amadeus Pune*. Other Pune sites will need
   their own weekend shape.
3. **Sunday's dessert and Saturday's rows read "SWEET" / "SALAD" / "DAL" / "RICE"**
   in the sample — generic labels rather than named dishes. Read as "the solver
   picks", which is what happens. Say so if a specific dish is intended.

---

## Engine changes this client required

Each was a silent failure, and each is pinned by a test in
`tests/test_pune_client_logic.py`.

1. **`fixed_daily_item` counted horizon days, not the slot's own days.** Bread
   runs Mon–Sat, so over a 7-day horizon chapati was available on 6 of 7 days,
   judged ineligible for the fixed choice and pinned to zero — leaving all six
   bread cells with no candidate. Any slot combining `fixed_daily_item` with a
   `slot_day_restriction` was INFEASIBLE.

2. **The colour-variety minimum was clamped from the counter's config, not the
   day's cells.** Amadeus Pune has five colour-bearing slots configured; on
   Sunday only `rice` and `dessert` are served. A minimum of 3 asked two cells
   for three distinct colours. The existing "colours present in the day's pools"
   cap cannot catch this — colours available and cells available are different
   numbers. Checked across the whole fleet: this changes the effective minimum on
   exactly 2 of 961 (counter, day) combinations, both Amadeus Pune Sundays, so no
   Bangalore counter is affected.

3. **A `constant_items` pin naming an ontology dish outside the slot's pool
   vanished.** The force-vs-stamp decision tested "is this dish in the ontology",
   so `raita` (a real Pune dish, filed under `curd_side`) was routed to
   `forced_items`, failed to match any `salad` candidate, and the cell was solved
   normally — while the stamping pass skipped it for being in `forced_items`. The
   test is now slot-scoped. Checked across every pin in `client_rules.json`: only
   this one changes behaviour (Cloudera's `healthy_rice: "curd rice"` looks
   similar but is a whole-horizon pin, which was already stamped).

4. **`slot_composition` did not treat a rule-declared staple as unlimited.**
   "Chapati daily" is one distinct item across six days, which reads as a horizon
   shortfall, so `_horizon_limited_components` would have swapped the daily
   mandate for a floor of one — "chapati daily" becoming "chapati once". It
   consulted only the ontology-wide staple flags; it now reads the same
   `extra_repeatable` declarations `unique_items` and the item cooldown do.

5. **`unique_items.diagnose()` warned about slots whose staples were declared.**
   Bread (chapati daily) and welcome_drink (buttermilk daily) each produced a
   "items will repeat" warning on every plan, which is the configured intent, not
   a shortfall. Two bogus warnings per plan is how a real one gets missed.

6. **`_`-prefixed keys in a `constant_items` block** are documentation now, the
   same convention the rules list uses for `_comment` — they used to log "not a
   known slot" on every plan.
