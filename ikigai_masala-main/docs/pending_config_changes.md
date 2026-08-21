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
| 1.4 | **Tekion CHN** | counter `theme_map` → Tekion BLR's: `mon` mix, `tue` chinese, `wed` north, `thu` mix, `fri` biryani | "Its rules are the same as Tekion BLR", and Tekion's rules are pinned to BLR's weekday themes | The Chinese Tuesday lands on a `mix` day and the Friday chicken biryani on a `north` day. Nothing fails — a composition with nothing eligible relaxes — but the menu is not the one the client pictured. |
| 1.5 | **Booking.com** | `slot_counts.starter = 2` (it is 1 live; the config's `starter__2` pin expects 2) | The live counter serves two starters and the second is the pinned Veg Kati Roll | The `starter__2` constant is dropped silently. |
| 1.6 | **Moengage** | fill in the counter's `slot_counts` (only `nonveg_main: 2` is set) and its empty `theme_map` | Every other slot falls back to a default of 1 and the counter inherits the app-wide theme map | Works, but the counter is not configured — a slot count the client wanted is invisible. |
| 1.7 | **Stryker** (Bangalore) | fill in `slot_counts` (empty) and `theme_map` (empty) | Same as above | Same as above. |

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

| Where | Today | Needed | For |
|---|---|---|---|
| Pune `veg_dry`, leafy | 5 dishes | ~8 | Corning Chakan's "leafy dry twice a week" across a 20-day cooldown |
| Pune `starter`, chaat | 4 dishes | 5-6 | Corning Chakan's Thursday chaat — four Thursdays fit inside the cooldown window with nothing spare |
| Pune `bread`, South Indian | 0 dishes | — | Amadeus Pune themes Tuesday `south`; the client confirmed **chapati only**, so this is now closed by exempting `bread` from Pune's theme filter rather than by adding dosas |
| Chennai `veg_gravy`, Chinese | 1 dish | 3-4 | Tekion CHN's Chinese-Tuesday gravy; one dish covers one Tuesday per cooldown window |
| Bangalore `nonveg_main` | 17 rows carry no form flag | — | `scripts/nonveg_structural_flags.py` reports them; each needs the client's menu to say whether it is a dry or a gravy (`afghani_chicken`, `kolhapuri_chicken` — a place plus a protein says nothing about form) |

---

## 3. Scripts to run after any workbook re-import

The correction chain is idempotent and convergent — running it twice reports
"already correct" everywhere — so the safe move after **any** re-import or new
client menu is to run the whole thing in order. The order matters and is
documented with reasons in `data/raw/source_workbooks/README.md`.

```bash
cd ikigai_masala-main
python scripts/canonical_dish_spellings.py     # one dish, one spelling
python scripts/bread_form_flags.py             # is_plain_phulka_chapathi, both ways
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

Also re-run `scripts/dump_client_fixtures.py --clients <clients.csv>` whenever the
live `clients` table changes shape, or the 71-counter sweep silently stops
covering the clients that were added since. That is how it fell 13 clients behind.

---

## 4. Decisions still open

| Topic | Question | Where it bites |
|---|---|---|
| **Premium flags** | The client's cost definition (paneer / baby corn / mushroom / rich continental) would take Bangalore's `is_premium_gravy` from 174 rows to 463. At that point "one premium veg gravy a week" stops meaning "the week's showcase dish" and starts meaning "paneer at most once a week" — which fights the paneer rules. Apply it or keep the narrower flag? | `scripts/complete_ontology.py::APPLY_PREMIUM` (currently `False`); run with `--report-premium` to see the full list |
| **Combined dal / sambar / rasam slots** | ~20 counters run two of {dal, sambar, rasam} as separate daily slots. The alternation rule only applies to a *combined* slot (see below). Switch them? | one `slot_counts` / `categories` edit per counter |
| **Bakertilly's biryani day** | Its two rules contradict each other; you called it an outlier and it is left as-is (curd_side kept as a raita on Wednesday) | `data/configs/clients/bakertilly.json` |
