# 25-day menu generation sweep

Every client, every counter, against the 24 Aug DB export (61 clients / 85
counters) with the real `menu_history`, `week_signatures` and `app_settings`
seeded. Sweep starts Monday 2026-09-14, just after the newest saved day, so it
plans forward while that history still sits inside the 20-day cooldown.

Two modes, because they measure different things:

* **Rolling** — plan a block, SAVE it, plan the next, until 25 service days are
  covered. This is how the product runs and what exercises the cooldown, the
  freshness objective and the cross-week history rules.
* **Single** — one 25-day request. `MAX_NUM_DAYS` is 30 so a user can ask for it,
  but see the note below: it is not a supported way to plan five weeks.

## Rolling 25 service days — 56 of 61 clients, 72 of 85 counters

| client | city | counters | 25 days | reason if not |
|---|---|---:|---|---|
| AT&T | Bangalore | 1 | PASS |  |
| Amadeus | Bangalore | 3 | PASS |  |
| Astrazeneca | Bangalore | 1 | PASS |  |
| Ather | Bangalore | 1 | PASS |  |
| Bakertilly | Bangalore | 1 | PASS |  |
| Booking.com | Bangalore | 1 | PASS |  |
| Cargil | Bangalore | 1 | PASS |  |
| Cigna | Bangalore | 1 | PASS |  |
| Citrix | Bangalore | 1 | PASS |  |
| Clario | Bangalore | 1 | PASS |  |
| Cloudera | Bangalore | 1 | PASS |  |
| Computa Centre | Bangalore | 1 | PASS |  |
| Continental | Bangalore | 3 | PASS |  |
| DXC | Bangalore | 2 | PASS |  |
| Eli Lilly | Bangalore | 1 | PASS |  |
| F5 | Bangalore | 1 | PASS |  |
| H&M | Bangalore | 1 | PASS |  |
| Icon Blr | Bangalore | 1 | PASS |  |
| Ikea | Bangalore | 1 | PASS |  |
| Infenion | Bangalore | 1 | PASS |  |
| Konsberg | Bangalore | 1 | PASS |  |
| L&T | Bangalore | 3 | PASS |  |
| Moengage | Bangalore | 1 | PASS |  |
| Nike | Bangalore | 2 | PASS |  |
| Odessia | Bangalore | 1 | PASS |  |
| Piramel Finance | Bangalore | 1 | PASS |  |
| Plan View | Bangalore | 1 | PASS |  |
| Plum | Bangalore | 1 | PASS |  |
| Quince | Bangalore | 1 | PASS |  |
| Rippling | Bangalore | 1 | PASS |  |
| Siemens Healthineers | Bangalore | 3 | PASS |  |
| Siemens Technology | Bangalore | 3 | PASS |  |
| Sinch | Bangalore | 1 | PASS |  |
| Stripe | Bangalore | 1 | **FAIL** | cooldown exhaustion week 3 — `nonveg_main_daily_pair` wants one regional chicken gravy AND one dry every day; by week three the 20-day ban has left too few of one of them. No single client rule unblocks it. |
| Stryker | Bangalore | 1 | PASS |  |
| Take 2 | Bangalore | 1 | PASS |  |
| Tekion | Bangalore | 1 | PASS |  |
| Telstra | Bangalore | 1 | PASS |  |
| Tessolve | Bangalore | 1 | PASS |  |
| Thales | Bangalore | 1 | PASS |  |
| ToastTab | Bangalore | 1 | PASS |  |
| Vector | Bangalore | 1 | PASS |  |
| Waters | Bangalore | 4 | PASS |  |
| Zscaler | Bangalore | 1 | PASS |  |
| Gartner | Chennai | 1 | PASS |  |
| ICON Chn | Chennai | 4 | **FAIL** | Roti Combo only: cooldown exhaustion week 3 — dropping `icon_chn_roti_nonveg_egg_mon_wed_else_chicken` makes it solvable. Chennai's egg-gravy pool is too thin to carry Mon+Wed for three weeks. The other three counters stall at 15 days only because the harness stops the client once one counter fails. |
| RNTBCI | Chennai | 6 | **FAIL** | Full Lunch Menu, Full Non-Veg and North Combo: cooldown exhaustion week 3. RNTBCI has NO client rules file, so the conflict is the Chennai city ruleset against pool depth — the counter runs 2 salads and 2 veg dries off pools of 6. |
| TCL | Chennai | 1 | PASS |  |
| Tekion CHN | Chennai | 1 | PASS |  |
| ToastTab CHN | Chennai | 1 | **FAIL** | cooldown exhaustion week 2 (earliest of the five) — 2 veg gravies from a 5-dish south pool and a 2-dish curd_rice pool. No single client rule unblocks it. |
| World Bank | Chennai | 2 | PASS |  |
| Airtel Noida | NCR | 1 | PASS |  |
| Carelon | NCR | 1 | PASS |  |
| Corning | NCR | 1 | PASS |  |
| Junglee Games | NCR | 1 | PASS |  |
| SAEL | NCR | 1 | PASS |  |
| Siemens | NCR | 1 | **FAIL** | cooldown exhaustion week 3 — dropping `siemens_nonveg_pair_by_weekday` makes the block solvable, so that rule plus the drained NCR non-veg pool is the pair. |
| Sinch NCR | NCR | 1 | PASS |  |
| Stryker NCR | NCR | 1 | PASS |  |
| Amadeus Pune | Pune | 1 | PASS |  |
| Corning Chakan | Pune | 1 | PASS |  |

## Why the five fail — and what they have in common

All five pass the same block with the history cleared, and all five pass it with
only the seeded history. They fail **only after the replayed weeks**, so the
cause in every case is the 20-day item cooldown draining a thin pool by week
three (ToastTab CHN by week two), meeting a rule that still demands a dish from
it. Nothing is starved outright — no cell has zero candidates — so this is a
combination, not a missing pool.

Two are attributable to one client rule apiece: removing
`siemens_nonveg_pair_by_weekday` (Siemens NCR) or
`icon_chn_roti_nonveg_egg_mon_wed_else_chicken` (ICON Chn's Roti Combo) makes the
failing block solve. The other three are the city ruleset against pool depth —
RNTBCI has no client rules file at all.

The fix in each case is **more dishes in the named category for that city**, not
a config change. Note 25: no-repeat is hard and the escape is a declared staple
list, never a silent relaxation.

## The pre-flight does not catch this — a real gap

`POST /diagnose` reports **zero ERRORs** for all five failing blocks, then the
solve returns 500. `diagnose()` is supposed to be the thing that reports a slot
about to starve, and here it is silent because no single slot IS starved — the
shortfall only appears when the rules are combined. Worth its own pass: the
pre-flight's per-slot arithmetic cannot see a cross-rule interaction.

## One 25-day horizon — 1 of 61, and that is expected

Only Airtel Noida passes. This is **not** a fleet of broken configs; it is that a
frequency rule counts across the HORIZON, not per calendar week:

* 40 clients are blocked in pre-flight, most naming a weekly cap —
  `nonveg_biryani_weekly`, `mixedveg_pulao_biryani_weekly`. Over a 25-day horizon
  `max: 1` means "once in five weeks", and the theme map forces a biryani on five
  or more days, so the rule and the themes contradict each other. The 422 is
  correct and its message says exactly that.
* 20 more go INFEASIBLE, mostly on `unique_items`: a count-1 slot needs 25
  distinct dishes for a 25-day horizon and few categories have that.

So the horizon IS the counting window a rule is written against. Planning five
weeks means five blocks of five days, which is what the rolling mode does and
what the planner UI generates. A single 25-day request is a different question
and the answers above are the right ones.

## Reproducing

`scripts/` has no runner for this — it was a one-off harness. The shape is: seed
`FakeSupabase` from the SQL exports, loop `POST /plan` per counter passing the
primary's `shared_items`, `POST /save` the block, advance seven days, repeat.
