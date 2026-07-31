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
`data/raw/city_items/pune.xlsx` is tagged `common`).

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

* **The single "Rice item" row is two slots.** "white rice daily" + "flavour rice
  on Tue and sun" means the row shows the day's headline rice: the `white_rice`
  constant most days, the flavoured `rice` slot on Tuesday and Sunday. So the
  generated menu prints a `white_rice` row every day and a `rice` row on those
  two days.
* **Sunday's Salad column is a raita.** `raita` and `boondi_raita` are real Pune
  dishes, but the ontology files them under `curd_side`, so they are not
  candidates for the `salad` slot. The pin is stamped as text (see the note under
  R-Sun below).

### Stated rules → implementation

| # | Stated | Status | Where |
|---|---|---|---|
| 1 | weekly 1 panner | DONE | `amadeus_pune_paneer_weekly` — `selector_frequency`, `key_ingredient: paneer`, `exact: 1`. No `base_slot`, so it counts across every slot: the Pune list has 13 paneer gravies and one paneer-based veg dry |
| 2 | weekly 1 soya | DONE | `amadeus_pune_soya_weekly` — same shape, `key_ingredient: soy` (3 veg dries + 1 gravy) |
| 3 | white rice daily | DONE | `white_rice` is a constant slot the counter already serves; `amadeus_pune_white_rice_mon_sat` takes it off Sunday (rule 9 overrides "daily" there) |
| 4 | flavour rice on Tue and sun | DONE | `amadeus_pune_flavour_rice_tue_sun` — `slot_day_restriction` on `rice`, `allowed_weekdays: [tue, sun]` |
| 5 | chapati daily in indain bread | DONE | `amadeus_pune_chapati_daily` — `slot_composition` on `bread` with one `count: 1` component selecting `item: chapati`. On a one-slot family that means "this slot must be a chapati" |
| 6 | welcome drink will have butter milk daily | DONE | `amadeus_pune_buttermilk_daily` (same one-slot mandate, `is_buttermilk`) + `amadeus_pune_buttermilk_is_a_staple` (`repeatable_items`, so the daily repeat is exempt from `unique_items` and the 20-day cooldown) |
| 7 | sat and Sunday also working | DONE | `clients.serve_weekends = true` — already set in the live row |
| 8 | sat no veg dry it should be blank | DONE | `amadeus_pune_veg_dry_weekdays_only` — `veg_dry` runs Mon–Fri (Sunday drops it too, per rule 9) |
| 9 | in sun we server only flvour rice(any veg biryani), papad, welcom drinl and sweet that's all | DONE | `amadeus_pune_veg_gravy_mon_sat`, `_dal_mon_sat`, `_bread_mon_sat`, `_white_rice_mon_sat` take those four off Sunday; `amadeus_pune_sunday_veg_biryani` (`slot_composition` with `components_by_weekday: {sun: …}`) makes Sunday's rice a veg biryani. "Any" is why it selects on `is_mixedveg_biryani` rather than pinning a dish — the solver picks between `veg_biryani` and `handi_biryani` |
| Sun | (grid) Sunday's salad row is a raita | DONE, stamped | `constant_items: {"salad": {"sunday": "Raita"}}`. Stamped as text because `raita` is not a `salad` candidate. **Alternative:** add `curd_side` to the counter and restrict it to Sunday — then the solver chooses between the two raitas and the dish is a real ontology item (colour suffix, history). That is a DB config change, so it is left to you |

Generated structure, verified against the grid:

| slot | runs on |
|---|---|
| salad | Mon–Sun (Sunday's is the stamped raita) |
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

The solver draws from `city_items/pune.xlsx`, so it cannot serve a dish the list
does not carry. Nearly every dish in the sample is there — 32 of the 35 named
ones, most under a slightly different spelling:

| Sample | Item in the list |
|---|---|
| Lachchedar onion | `lachchedar_onion_salad` |
| Moong chat | `moong_sprouts_chat` |
| Mix cut salad | `cut_salad` |
| Aloo jeera | `aloo_jeera_dry` |
| Bhendi do pyaza | `bhindi_do_pyaza` |
| Motichur laddoo | `moti_chur_laddu` |
| Gatte nu sak | `gatte_ki_sabzi` |
| Aloo mutter | `aloo_mutter_masala`, `aloo_mutter_homestyle` |
| Seviya kheer | `semiya_kheer` |
| Banana custerd | `banana_custard` |

Genuinely absent: **Mix katol**, **Green gujrat**, **Besan barfi**. None of the
three blocks generation — they change *which* dish fills a row, not whether the
row is filled. Add them to the Pune workbook to bring the generated week closer
to the sample dish for dish.

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
