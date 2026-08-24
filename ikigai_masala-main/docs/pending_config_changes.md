# Pending config changes

Everything that has to happen **outside this repository** for the rules now
committed to take effect, plus the commands to run inside it. Nothing here is a
code change — it is all Supabase values and scripts.

Ordered by whether a client's menu is wrong without it.

---

## 1. Database values a rule depends on

Each of these is a `clients` row edit. All of them are reachable from the
**Edit Logic** editor in the app (pick the city, then the client) except
`working_days`, which has no editor control yet and needs a SQL update.

| # | Client | Change | Why | Without it |
|---|---|---|---|---|
| 1.1 | **Corning Chakan** | add `starter` to the counter's categories, `slot_counts.starter = 1` | "On Thursday only we will give a starter. Starter should be a chaat item" | Both starter rules are inert; `/diagnose` reports them as targeting a slot the counter does not serve. Every other Corning rule works. |
| 1.2 | **Clario** | `working_days = ['monday','tuesday','wednesday','thursday']` | "Only operation is from Monday to Thursday" | Friday is planned and the kitchen throws the food away. |
| 1.3 | **Clario** | counter `theme_map`: `monday` → `biryani` | "Biryani will be served on Monday and Wednesday" (today only Wednesday is a biryani day) | Monday gets a normal mixed menu; only one biryani a week. |
| 1.4 | **Booking.com** | `slot_counts.starter = 2` (it is 1 live; the config's `starter__2` pin expects 2) | The live counter serves two starters and the second is the pinned Veg Kati Roll | The `starter__2` constant is dropped silently. |
| 1.5 | **Moengage** | fill in the counter's `slot_counts` (only `nonveg_main: 2` is set) and its empty `theme_map` | Every other slot falls back to a default of 1 and the counter inherits the app-wide theme map | Works, but the counter is not configured — a slot count the client wanted is invisible. |
| 1.6 | **Stryker** (Bangalore) | fill in `slot_counts` (empty) and `theme_map` (empty) | Same as above | Same as above. |

### SQL for 1.2 (no editor control for `working_days`)

```sql
update clients
   set working_days = '["monday","tuesday","wednesday","thursday"]'::jsonb,
       version = version + 1
 where name = 'Clario';
```

---

## 2. Data the rules would like more of

Not blocking — every one of these degrades gracefully (a `min` caps itself to
what the pool can supply and `/diagnose` reports the shortfall) — but the menu is
thinner than the client asked for until the dishes exist.

| Where | Today | Needed | For | Status |
|---|---|---|---|---|
| Pune `veg_dry`, leafy | **9** | ~8 | Corning Chakan's "leafy dry twice a week" | ✅ closed — `scripts/deepen_thin_pools.py` added four Maharashtrian greens (palak, shepu/dill, math/amaranth, radish greens) |
| Pune `starter`, chaat | **8** | 5-6 | Corning Chakan's Thursday chaat | ✅ closed — four Bangalore chaats copied in, ragda pattice among them |
| Chennai `veg_gravy`, Chinese | **5** | 3-4 | a Chennai client with a Chinese day | ✅ closed — four canteen standards copied from Bangalore |
| **`item_color`, all cities** | 1,696 blank of 8,925 | — | `MenuSolver._add_color_constraints` clamps the day's required distinct colours to the number PRESENT, so a blank colour quietly relaxes the rule rather than merely going unchecked | ⚠️ **needs you** — 744 filled from measured evidence (see below); the rest cannot be inferred. `docs/colours_to_confirm_by_family.csv` asks **455 questions** instead of 1,696: the top 25 answers colour half the backlog, the top 100 three quarters |
| Chennai `veg_gravy`, **south** paneer | 1 dish | 3-4 | Tekion CHN's "paneer gravy every Wednesday" — Wednesday is a *south* day at that site, so only `paneer_kurma` qualifies | ⚠️ open — the rule is met on one Wednesday per cooldown window and relaxes on the others |
| Bangalore `nonveg_main` | **0 unflagged** | — | the daily non-veg composition could never place a dish with no form flag | ✅ closed — all 51 adjudicated (`scripts/nonveg_structural_flags.py::STYLE_OVERRIDES`), 4 dry and 35 gravy in Bangalore, 11 dry in Chennai, 1 gravy in NCR |
| Chennai `nonveg_main` | 2 rows queried | — | `egg_dosa` and `kal_egg_dosa` looked like breads filed as non-veg mains | ✅ closed — client-confirmed as non-veg mains: an egg dosa is how the site serves its egg, so the dish IS the meal. Flagged dry, since a dosa arrives unsauced |

---

## 3. Scripts — already applied; re-run only after a raw re-import

**Nothing here is waiting on you.** Every correction below is already applied to
the committed workbooks, so the app serves the corrected data as it stands. The
chain only needs re-running if someone re-imports a **raw** client workbook,
which drops the hand-applied fixes.

The chain is idempotent and convergent — running it twice reports "already
correct" everywhere. The order matters and is documented with reasons in
`data/raw/source_workbooks/README.md`.

```bash
cd ikigai_masala-main
python scripts/canonical_dish_spellings.py     # one dish, one spelling
python scripts/bread_form_flags.py             # is_plain_phulka_chapathi, both ways
python scripts/nonveg_structural_flags.py      # dry vs gravy, incl. the 51 verdicts
python scripts/deepen_thin_pools.py            # the three pools a rule outgrew
python scripts/complete_ontology.py            # last of the writers
python scripts/build_pool_token_map.py         # refresh the committed token map
python scripts/audit_course_types.py           # must exit 0
pytest -m "not slow"                           # the guards
```

Two of these are new and worth knowing about:

* **`bread_form_flags.py`** — `is_plain_phulka_chapathi` is now definitional in
  both directions, derived from the dish name. Any importer that adds a bread row
  leaves the column blank, so this must run after it or a "chapati only" rule
  cannot see the new dish.
* **`dump_client_rules_index.py`** — regenerates `docs/client_rules_index.md`.
  Run it after editing anything under `data/configs/clients/`; the test suite
  fails if the doc is stale.
* **`deepen_thin_pools.py`** — the eight copied dishes and four new Pune greens.
  A re-import from a raw workbook drops them, and the loss is silent: the rules
  that need them relax rather than fail.

Also re-run `scripts/dump_client_fixtures.py --clients <clients.csv>` whenever the
live `clients` table changes shape, or the 71-counter sweep silently stops
covering the clients that were added since. That is how it fell 13 clients behind.

---

## 4. Decisions still open

| Topic | Question | Where it bites |
|---|---|---|
| **Colours for 1,696 dishes** | The one item that genuinely needs your input. Fill the `item_color` column in `docs/colours_to_confirm_by_family.csv` — one answer per dish family, ordered so stopping early still helps. Vocabulary: brown, red, green, yellow, white, orange, black. Your own colour legend workbook is committed at `data/raw/source_workbooks/client_food_colour_legend.xlsx`; it matched only 3 of these rows (it is a Chennai tiffin list, the blanks are Bangalore and NCR) and agrees with the existing colours 73% of the time, so it is a cross-check rather than a source. | `docs/colours_to_confirm_by_family.csv` |
| ~~**Premium flags**~~ | **DEFERRED by the client.** Applying their cost definition would take Bangalore's `is_premium_gravy` from 174 rows to 463, at which point "one premium veg gravy a week" stops meaning "the week's showcase dish" and starts meaning "paneer at most once a week". Left at the narrower flag. | `scripts/complete_ontology.py::APPLY_PREMIUM` stays `False`; `--report-premium` prints the list if it is ever revisited |
| **Combined dal / sambar / rasam slots** | **36** counters run two or three of {dal, sambar, rasam} as separate daily slots, so all of them are served every day and there is nothing to alternate. The alternation the client asked for ("dal Mon/Wed/Fri, sambar Tue/Thu") only applies to a *combined* slot, which 12 counters already use. Collapsing two dishes into one cell reduces what is on the plate, so it is a menu decision. Switch them? | one `categories` / `slot_counts` edit per counter |
| **Which component gets the three days** | `COMBO_CATEGORIES` names the majority globally: `dal_sambar` and `dal_rasam` give dal three days, `sambar_rasam` gives **rasam** three. A site wanting sambar on Mon/Wed/Fri instead cannot say so today. Make it per-client? | `src/constants.py::COMBO_CATEGORIES` |
| **Six-day weeks cannot alternate cleanly** | With Saturday service the split is dal / sambar / dal / **dal** / sambar / dal — two dal days adjacent, because six days allow only two minority days. Five- and seven-day weeks alternate perfectly. Give a six-day week three sambar days? | `src/constants.py::combo_minority_count` |
| **Bakertilly's biryani day** | Its two rules contradict each other; you called it an outlier and it is left as-is (curd_side kept as a raita on Wednesday) | `data/configs/clients/bakertilly.json` |
