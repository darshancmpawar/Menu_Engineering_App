# Explanation layer — calibration run

Step 2 of the work order's build order: *"show a chef 20 days of bullets, ask
which verdicts are wrong, tune the thresholds against their judgement."*

This is the measurement to hand them. **49 real menu days, 10 clients across all
four cities**, generated through `/plan` and scored with `src/explain/checks.py`
as shipped. Reproduce with `scripts/` + the probe in the commit that added this.

Nothing here is tuned yet. Three of the six checks have a defect that is not a
matter of taste, and those are separated below from the ones that need a chef.

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

### 1. `spice_arc` and `richness_balance` cannot fail

`spice_arc` passes at `>= 2` distinct spice levels. The observed **minimum is
2**. `richness_balance` passes on a mean inside `1.5-3.5`; the observed range is
**2.0 to 3.5**, entirely inside the window and touching the top edge once.

Neither has failed in 49 days and neither can, at these thresholds, on this
data. A check that always prints `[ok]` is not reassurance — it teaches the
reader to skim the list, which costs the four checks that do carry information.

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

Only one check is ready to be judged on taste: **`texture_contrast`**, firing on
16% of days, measuring something no rule enforces, on a column that is 99.2%
populated. That is the one to ask about.

The other five need the defects above fixed first. Asking a chef whether a
verdict is right, when the verdict is flagging a rule the client themselves
asked for, wastes the calibration.
