# Explanation layer — calibration run

Step 2 of the work order's build order: *"show a chef 20 days of bullets, ask
which verdicts are wrong, tune the thresholds against their judgement."*

This is the measurement to hand them. **49 real menu days, 10 clients across all
four cities**, generated through `/plan` and scored with `src/explain/checks.py`
as shipped. Reproduce with `scripts/` + the probe in the commit that added this.

Nothing here is tuned yet. Three of the six checks have a defect that is not a
matter of taste, and those are separated below from the ones that need a chef.

---

## ⚠ Correction — the method below was wrong for two of the checks

**Rule adjacency was used as a proxy for rule compulsion.** The method was: see
a flag, find a rule that touches that slot, conclude the solver was forced. That
reasoning is unfalsifiable — in a system with 57 city rules and 175 client
rules there is always a rule nearby — and it produced a confident 64%
false-positive rate for something closer to 14%.

`no_ingredient_echo`'s chicken repeats were attributed to
`nonveg_main_daily_pair`. Reading the rule (`bangalore.json`) shows only its
*gravy* component is pinned to chicken; the dry component selects on
`is_nonveg_dry`, which says nothing about protein. Measured against the pool the
solver actually had:

| flagged repeat | pool | alternatives | verdict |
|---|---:|---|---|
| `chicken` x2 | `is_nonveg_dry` = 127 | 32 non-chicken (25%) — egg 30, fish 2 | **true** |
| `wheat` x2 | `bread` = 335 | 210 non-wheat (63%) — ragi 42, rice 25, maida 23 | **true** |
| `mixed_vegetables` x2 | sentinel, 375 rows | ingredient unknown | **abstain** |

The solver had a way out and repeated anyway. `no_ingredient_echo` is the
**strongest** check in the set, not the weakest, and the arithmetic in the
original table was also wrong (5 + 4 + 2 = 11, not 9).

**The rule to apply from here on:** a verdict about solver behaviour must be
tested against *pool availability*, not rule adjacency. "Could the solver have
done otherwise?" is always answerable from `pre_filter_pool()`, and it is the
only question a false-positive claim rests on.

**Two checks below were calibrated by the same flawed method and have not been
re-derived**: `colour_variety` (31%, and §2 explains why its number is wrong
anyway) and `texture_contrast` (16%, never checked against whether the pool
offered a different texture). `texture_contrast` is still the one to take to a
chef; that it is unre-derived is a reason to ask, not a reason to trust.

---

## How often each check fires

| check | flagged | rate | verdict |
|---|---:|---:|---|
| `colour_variety` | 15/49 | 31% | **measuring a different set than the rule it mirrors** |
| `no_ingredient_echo` | 14/49 | 29% | **9 of 14 are the menu obeying a rule** |
| `non_dal_protein` | 8/49 | 16% | reads a column blank on 59% of main dishes |
| `texture_contrast` | 8/49 | 16% | healthy — this one is working |
| `richness_balance` | 0/49 | 0% | **cannot fire** |
| `spice_arc` | 0/49 | 0% | **cannot fire** |

## What the plates actually look like

| quantity | min | median | max | mean |
|---|---:|---:|---:|---:|
| main dishes / day | 4 | 6 | 9 | 6.14 |
| distinct colours / day | 2 | 4 | 6 | 3.86 |
| distinct textures / day | 2 | 4 | 5 | 3.82 |
| distinct spice levels / day | 2 | 3 | 4 | 2.67 |
| mean richness / day | 2.0 | 2.5 | 3.5 | 2.55 |
| share of mains with no `primary_protein` | 0.2 | 0.6 | 1.0 | 0.59 |

---

## The three defects

### 1. `spice_arc` and `richness_balance` fire on under 6% of days

`spice_arc` passes at `>= 2` distinct spice levels. The observed **minimum is
2**. `richness_balance` passes on a mean inside `1.5-3.5`; the observed range is
**2.0 to 3.5**, entirely inside the window and touching the top edge once.

An earlier draft of this file said they "cannot fire". That is wrong twice over
and the phrasing would have been read as settled a year later. Both *can*:
`spice_level` has four distinct values with 45.7% of dishes at level 1, so an
all-level-1 plate is possible; `richness_score` has six values and the seven
richest dishes mean 5.0 against a 3.5 ceiling the observed data already grazes,
so a day at 3.51 fires. And zero events in 49 trials bounds the rate at about
**6%** (rule of three), not at zero.

The action is unchanged — 6% is still too loose to earn a line — but the reason
is "too rare to be worth a reader's attention", not "impossible". Either narrow
richness to roughly 1.8-3.2 and re-measure, or drop both and keep the raw
numbers in `plate_profile`, which already carries them. A check that almost
always prints `[ok]` teaches the reader to skim the list, which costs the checks
that do carry information.

Either the threshold moves (`spice_arc` at `>= 3` would bite the observed
floor; `richness_balance` needs a window narrower than the data's own range) or
the check is measuring the wrong thing. "Two spice levels" may be the wrong
question — a plate of mild and medium has two levels and no heat at all.

### 2. `colour_variety` demands four when the solver was asked for fewer

The check requires 4 distinct colours flat. The solver does not: design note 13
clamps its requirement to `min(configured, colour-slots-configured,
colour-cells-this-day, colours-present)`, so a counter with few colour slots is
legitimately asked for two or three.

The data shows the mismatch exactly — median 4, minimum 2. The 31% are mostly
days that satisfied the rule that generated them and fail a check claiming to
mirror it. That is the worst kind of false alarm: the chef cannot act on it,
because the menu is already correct by the constraint it was built under.

It also uses a different dish set. `checks.MAIN_COURSES` is a fixed seven
courses; the solver counts `cfg.color_slots`, which excludes `white_rice` and
`curd`. Two different questions with one name.

### 3. `no_ingredient_echo` flags the menu for obeying the rules

The repeats it found, across 14 flagged days:

| ingredient | days | is it really an echo? |
|---|---:|---|
| `chicken` | 5 | **No** — `nonveg_main_daily_pair` MANDATES one dry plus one chicken gravy every day |
| `wheat` | 4 | **No** — a counter with two bread slots serves two wheat breads |
| `mixed_vegetables` | 2 | **No** — the ontology's catch-all, and CLAUDE.md records it as the de-facto default for a mixed salad |
| `corn`, `potato`, `paneer` | 1 each | **Yes** — these are the real ones |

Nine of fourteen are false. The check is sound in principle — a paneer gravy
beside a paneer dry is legal today and reads as lazy, and `paneer` does appear
once here — but as written it reports a composition rule doing its job. It needs
to exclude ingredients a `slot_composition` mandates for that counter, and the
known catch-all values.

Note the true rate is also **understated**: `key_ingredient` is 16.9% blank, so
some real echoes are invisible.

---

## The one that needs data, not tuning

`non_dal_protein` reads `primary_protein`, which is blank on **59% of main
dishes on average and 100% on some days**. It flags 16%, and a day flagged "dal
is the only vegetarian protein" may well have paneer that simply is not
recorded.

The column is blank by design, not by accident: the client's enriched workbooks
spell "no protein focus" as the literal string `none`, and
`merge_enriched_ontology._norm` folds that to blank because `none` would
otherwise be a *matchable* value in a column `_nonveg_mask`,
`ingredient_ban_rule` and `selector_frequency` all select on. Correct for the
solver, thin for this check.

`key_ingredient` is the better signal here — 16.9% blank rather than 66.5%, and
it demonstrably carries `paneer`, `chicken`, `potato`, `corn`. Reading both
columns would recover most of the missing verdicts without touching the
ontology.

---

## What to take to the chef

**Three checks, and they are what `src/explain/checks.py::CALIBRATED` now
gates the UI to** — the rest still ride in the `/explain` response for whoever
is measuring them, but they are not rendered as a judgement.

| check | why it is ready |
|---|---|
| `texture_contrast` | measures something no rule enforces, on a column 99.2% populated. Its 16% has NOT been re-derived against pool availability — ask, do not assume |
| `no_ingredient_echo` | re-derived above: the solver had 32 non-chicken dry dishes and 210 non-wheat breads and repeated anyway. Sentinels now abstain |
| `non_dal_protein` | the non-veg false-positive class is fixed — 59 of 85 counters run a `nonveg_main`, and every one of them was flagging for nothing |

One check is not enough to justify a chef's hour, and a broken one costs their
attention permanently — which is why the gate exists and why it starts at three
rather than at one or at six.

`colour_variety` is now handed the counter's own target instead of a fixed 4,
so it no longer contradicts the rule that generated the menu; it stays out of
the gate until its flag rate is re-measured against the corrected target.
`spice_arc` and `richness_balance` stay out until their thresholds are narrowed.
