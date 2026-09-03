# 25-day menu generation sweep

Every client, every counter, from the `tests/client_fixtures.py` snapshot
(61 clients / 85 counters). Sweep starts Monday 2026-09-07.

Reproduce with:

```
python scripts/sweep_menu_generation.py --days 25 --mode rolling
```

That runner is committed now. The previous version of this document said
"`scripts/` has no runner for this — it was a one-off harness", which meant the
numbers below could not be re-checked without rebuilding the harness.

Two modes, because they measure different things:

* **Rolling** (what this page reports) — plan a block, SAVE it, plan the next,
  until 25 service days are covered. This is how the product runs, and the only
  mode that exercises the item cooldown, the freshness objective and the
  cross-week cadence rules, because all three need history to read.
* **Single** — one 25-day request. Still not the supported way to plan five
  weeks: `unique_items` is hard, so a count-1 slot needs 25 distinct dishes.

## Result — 82 of 85 counters, 59 of 61 clients

| | counters | pass |
|---|---:|---:|
| Bangalore | 59 | 58 |
| Chennai | 16 | 15 |
| NCR | 8 | 7 |
| Pune | 2 | 2 |

75 counters serve all 25 days. Three serve fewer, correctly — a horizon is
`num_days` **weekdays**, and a client with a restricted working week serves a
subset of them (design note 29):

| client | working days | service days |
|---|---|---:|
| Clario | Mon-Thu | 20 |
| Piramel Finance | Mon/Tue/Thu | 15 |
| Quince | Wed/Thu/Fri | 15 |

## What changed since the last run

The previous sweep's headline was "40 clients are blocked in pre-flight, most
naming a weekly cap — over a 25-day horizon `max: 1` means once in five weeks,
and the theme map forces a biryani on five or more days". That is fixed:
`selector_frequency` and `nonveg_biryani_weekly` now count per ISO calendar week
(`max_per_week`, design note 26), 64 rules were migrated, and the pre-flight is
clean for all 85 counters at 7, 14, 21 and 25 days.

## A timeout is not an impossibility

The raw sweep reported **seven** failures. Four were not failures: ICON Chn's
Roti Combo and all three RNTBCI counters replanned cleanly on a quiet machine at
the same `time_limit`. They had hit the solver's clock, and the error said *"the
rules configured for this counter cannot all be satisfied over the requested
horizon"* — a sentence that asserts a configuration conflict.

That was a real bug and it is fixed: `MenuSolver.solve` now distinguishes
CP-SAT's INFEASIBLE from UNKNOWN and says which happened
(`TIMEOUT_MESSAGE` / `INFEASIBLE_MESSAGE`,
`tests/rules/test_timeout_is_not_infeasible.py`). It is recorded here because
the sweep is what found it: a run at `--time-limit 30` under load will still
show timeouts, and they must not be read as broken configs.

## The three real failures

All three break at the same place — after 5 to 10 days of SAVED history, once
the 20-day cooldown has started removing dishes. None is a broken config.

| client | counter | fails at | thin cells | the binding shortage |
|---|---|---|---:|---|
| ToastTab CHN | Counter 1 | block 2 (5 days in) | 2 | Chennai `curd_rice`: **2 distinct dishes** |
| Siemens | Counter 1 | block 3 (10 days in) | 0 | NCR `is_nonveg_dry`: **11 distinct dishes**, needed daily |
| Stripe | Counter 1 | block 3 (10 days in) | 0 | Bangalore `is_fish_dish`: **3 distinct dishes**, needed weekly |

Attributed by ablation — dropping one rule at a time and re-solving the failing
block:

| client | dropping any ONE of these makes it solvable |
|---|---|
| ToastTab CHN | `item_cooldown_20d`, `unique_items_session`, `theme_cuisine_filter` |
| Siemens | `item_cooldown_20d`, `nonveg_main_daily_pair`, `siemens_nonveg_pair_by_weekday` |
| Stripe | `item_cooldown_20d`, `theme_cuisine_filter`, `nonveg_main_daily_pair`, `stripe_fish_1x_week` |

`item_cooldown_20d` appears in all three, which is the tell: none of these is a
contradiction between rules, it is a pool that runs out once the cooldown has
been eating it for two weeks. Each is arithmetic, and each has a number:

* **ToastTab CHN** — 2 of its 51 cells are thin at the failing block and both
  are `curd_rice`, which Chennai carries exactly two of. Already open as **D4**
  in `docs/data_fixes_for_client.md`.
* **Siemens** — `nonveg_main_daily_pair` and the client's own
  `siemens_nonveg_pair_by_weekday` both want one `is_nonveg_dry` **every day**.
  NCR's non-veg pool is 150 rows but only **11** are dry. A daily component
  needs roughly one distinct dish per working day inside the 20-day cooldown
  window — about 15 — so 11 cannot carry five weeks.
* **Stripe** — `stripe_fish_1x_week` wants a fish once a week and Bangalore has
  **3** fish dishes. Three cannot cover five weekly slots while the cooldown
  holds each one for 20 days.

## Why the pre-flight sees none of this

`POST /diagnose` reports **zero errors** for all three and zero warnings for two
of them. The solver's own tightest-slot hint also finds nothing, and for Siemens
and Stripe there is genuinely nothing to find: every cell has candidates, and
their slot pools are 150 and 596 rows.

The reason is a single mismatch of granularity. **The pre-flight measures
SLOTS; the rules that fail measure SELECTORS INSIDE a slot.** Siemens'
`nonveg_main` is comfortable — 150 dishes for 2 cells a day — and starving on
the 11 of them that are dry. Stripe's is comfortable at 596 and starving on 3
fish. No per-slot count can see that, and the cooldown only makes it visible
once two weeks of history exist, which a single-block diagnose never has.

That is the same gap the previous sweep recorded, and it is still open. Two
specific interactions have been modelled since — `selector_frequency` now
cross-checks the days a `slot_composition` forces (note 9e) and the per-week
caps compare the busiest week rather than a horizon total (note 26) — but both
are interactions somebody went and modelled. The general form, "does this
selector have enough distinct dishes to survive its own cadence against the
cooldown", is not checked anywhere and would catch all three of these.

## Per client

<!-- generated by scripts/sweep_menu_generation.py -->

| client | city | counters | 25 days | reason if not |
|---|---|---:|---|---|
| Airtel Noida | NCR | 1 | PASS |  |
| Amadeus | Bangalore | 3 | PASS |  |
| Amadeus Pune | Pune | 1 | PASS |  |
| Astrazeneca | Bangalore | 1 | PASS |  |
| AT&T | Bangalore | 1 | PASS |  |
| Ather | Bangalore | 1 | PASS |  |
| Bakertilly | Bangalore | 1 | PASS |  |
| Booking.com | Bangalore | 1 | PASS |  |
| Carelon | NCR | 1 | PASS |  |
| Cargil | Bangalore | 1 | PASS |  |
| Cigna | Bangalore | 1 | PASS |  |
| Citrix | Bangalore | 1 | PASS |  |
| Clario | Bangalore | 1 | PASS | 20 service days — restricted working week |
| Cloudera | Bangalore | 1 | PASS |  |
| Computa Centre | Bangalore | 1 | PASS |  |
| Continental | Bangalore | 3 | PASS |  |
| Corning | NCR | 1 | PASS |  |
| Corning Chakan | Pune | 1 | PASS |  |
| DXC | Bangalore | 2 | PASS |  |
| Eli Lilly | Bangalore | 1 | PASS |  |
| F5 | Bangalore | 1 | PASS |  |
| Gartner | Chennai | 1 | PASS |  |
| H&M | Bangalore | 1 | PASS |  |
| Icon Blr | Bangalore | 1 | PASS |  |
| ICON Chn | Chennai | 4 | PASS | `Roti Combo` needed a longer `time_limit`; replanned cleanly on retry |
| Ikea | Bangalore | 1 | PASS |  |
| Infenion | Bangalore | 1 | PASS |  |
| Junglee Games | NCR | 1 | PASS |  |
| Konsberg | Bangalore | 1 | PASS |  |
| L&T | Bangalore | 3 | PASS |  |
| Moengage | Bangalore | 1 | PASS |  |
| Nike | Bangalore | 2 | PASS |  |
| Odessia | Bangalore | 1 | PASS |  |
| Piramel Finance | Bangalore | 1 | PASS | 15 service days — restricted working week |
| Plan View | Bangalore | 1 | PASS |  |
| Plum | Bangalore | 1 | PASS |  |
| Quince | Bangalore | 1 | PASS | 15 service days — restricted working week |
| Rippling | Bangalore | 1 | PASS |  |
| RNTBCI | Chennai | 6 | PASS | `Full Lunch Menu`, `Full Non-Veg Menu`, `North Combo` needed a longer `time_limit`; replanned cleanly on retry |
| SAEL | NCR | 1 | PASS |  |
| **Siemens** | NCR | 1 | **FAIL** | `Counter 1` INFEASIBLE from block 3 — see below |
| Siemens Healthineers | Bangalore | 3 | PASS |  |
| Siemens Technology | Bangalore | 3 | PASS |  |
| Sinch | Bangalore | 1 | PASS |  |
| Sinch NCR | NCR | 1 | PASS |  |
| **Stripe** | Bangalore | 1 | **FAIL** | `Counter 1` INFEASIBLE from block 3 — see below |
| Stryker | Bangalore | 1 | PASS |  |
| Stryker NCR | NCR | 1 | PASS |  |
| Take 2 | Bangalore | 1 | PASS |  |
| TCL | Chennai | 1 | PASS |  |
| Tekion | Bangalore | 1 | PASS |  |
| Tekion CHN | Chennai | 1 | PASS |  |
| Telstra | Bangalore | 1 | PASS |  |
| Tessolve | Bangalore | 1 | PASS |  |
| Thales | Bangalore | 1 | PASS |  |
| ToastTab | Bangalore | 1 | PASS |  |
| **ToastTab CHN** | Chennai | 1 | **FAIL** | `Counter 1` INFEASIBLE from block 2 — see below |
| Vector | Bangalore | 1 | PASS |  |
| Waters | Bangalore | 4 | PASS |  |
| World Bank | Chennai | 2 | PASS |  |
| Zscaler | Bangalore | 1 | PASS |  |

## The pre-flight still cannot see these

`POST /diagnose` reports **zero errors** for all three, and zero warnings for
two of them. The solver's own "tightest slot" hint also finds nothing, because
for Siemens and Stripe no cell is starved — every cell has candidates and the
conflict is in the combination.

This is the same gap the previous sweep recorded, and it is still open: the
pre-flight's per-slot arithmetic cannot see a cross-rule interaction, and the
per-day version of it only exists once history is involved. Two things have been
built against it since — `selector_frequency` now cross-checks the days a
`slot_composition` forces (note 9e) and the per-week caps compare the busiest
week rather than a horizon total (note 26) — but both are specific interactions
somebody modelled. The general case needs a solve, which is what the solve is.
