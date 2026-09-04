# Implementation Work Order — Menu Explanation Layer

**Target repo:** `Menu_Engineering_App` / `op-menu-engineering`
**Branch:** `feature/explain-layer`
**Estimated:** 5 steps, each independently shippable and testable.

---

## 0. Read this first — the one design rule

**The LLM never decides anything. It only renders facts that Python already computed.**

The obvious build is "send the day's dishes to an LLM and ask why it's a good menu."
Do not build that. An LLM handed only dish names has no access to the rules, the
cooldown map, the theme, or the pool it chose from — so it produces fluent,
plausible, invented rationale. This repo already refuses to guess a
`key_ingredient` without >=5 rows at >=95% agreement (`complete_ontology.py`).
An explanation layer that confabulates would be the single component in the
codebase that makes things up, and it is the one that faces the client.

So the pipeline is:

```
solver output ──► evidence.py (pure Python)  ──► checks.py (deterministic verdicts)
                                                        │
                                    ┌───────────────────┴─────────────────┐
                                    ▼                                     ▼
                        renderer.py (bullets, always works)   explain_llm.py (prose, optional)
                                                                          │
                                                              validator rejects any number
                                                              or dish name not in the pack
```

If the LLM is unavailable, the feature degrades to bullets. It never blocks a menu.
Same discipline as the shared-items fallback in design note 22.

---

## 1. What data this is built on (already in the repo, currently unused)

Verified across all five city workbooks:

| Column | Coverage | Distinct values | Read by today |
|---|---|---|---|
| `spice_level` | **100%** | 4 (0–3) | **nothing** |
| `texture` | **100%** | 7 (saucy, dry, grainy, crisp, fresh, soft, bready) | **nothing** |
| `richness_score` | **100%** | 6 (0–5) | **nothing** |
| `item_color` | 100% | 7 | colour-variety rule |
| `primary_protein` | 100% | 24 | non-veg mask, bans |
| `key_ingredient` | 100% | 195 | attribute_grouping, bans |
| `cuisine_family` | 100% | 6 | theme rules |

`spice_level`, `texture` and `richness_score` arrived with the enriched merge
(schema 134 → 136) and feed nothing. No new data collection is required.

> **Note for the docs pass:** `CLAUDE.md` currently says richness_score is
> "6,092 of 6,169 rows are 0 and nothing reads it". That is stale — the merge
> filled it; only 5 rows are 0 in Bangalore. Fix that line while you are here.

---

## 2. Architecture constraints (`tests/platform/test_architecture.py` enforces these)

| File | Layer | May import | May NOT import |
|---|---|---|---|
| `src/explain/evidence.py` | src | pandas, stdlib | api, ui, flask, streamlit, **any LLM client**, requests |
| `src/explain/checks.py` | src | stdlib | same |
| `src/explain/renderer.py` | src | stdlib | same |
| `api/explain_llm.py` | api | src.explain, requests, api.config | ui, streamlit |

**`src/explain/` must contain zero network calls.** That is what makes the
verdicts unit-testable offline, exactly like `test_freshness_variety.py` pins
the recency map without a database.

---

## STEP 1 — `src/explain/checks.py` (pure verdicts, no LLM, no I/O)

Ship this first. It is the whole product minus the prose.

Six checks over a day's **main** dishes (`starter`, `rice`, `bread`, `veg_dry`,
`veg_gravy`, `dal`, `nonveg_main` — condiments and drinks excluded):

| Check | Fails when | Why it matters |
|---|---|---|
| `colour_variety` | fewer than 4 distinct colours | mirrors the existing city rule; reported, not re-enforced |
| `texture_contrast` | >60% of dishes share one texture, or <3 textures | **new** — five saucy dishes passes every current rule and every diner notices |
| `spice_arc` | all dishes at one spice level | a flat plate reads as monotonous |
| `non_dal_protein` | the only vegetarian protein is dal | catches "dal is the protein" days |
| `no_ingredient_echo` | a `key_ingredient` appears twice | **new** — paneer gravy + paneer dry is legal today and reads as lazy |
| `richness_balance` | mean `richness_score` outside 1.5–3.5 | catches an all-heavy or all-thin plate |

**Deliverable:** `src/explain/checks.py` + `tests/explain/test_checks.py`.
Tests are table-driven and use hand-built dish dicts — no solver, no DB, no network.

**Acceptance:** `pytest tests/explain/test_checks.py` passes; runs in under a second.

---

## STEP 2 — `src/explain/evidence.py` (gather the facts)

Builds an `EvidencePack` for one day from things the solver already has.

**Inputs** (all plain data — no solver object, so it is testable in isolation):

| Input | Where it comes from today |
|---|---|
| `day_items: {slot: item_base}` | `/plan` response `solution[date]['items'][slot]['item_base']` |
| `attrs: {item: {col: value}}` | the cleansed ontology DataFrame |
| `recency: {item: days}` | `PlanContext.recency_by_item` — **already computed, currently discarded after the freshness objective** |
| `theme` | `solution[date]['day_type']` |
| `rules` | `PlanContext.rules` — read `rule.rule_config.get('_comment')` for the client's own sentence |
| `relaxations` | **Step 4** — the `logger.warning` lines the solver already emits |

**Output:** a JSON-serialisable dict with `dishes`, `plate_profile`, `checks`,
`provenance`, `relaxations`. This dict is the *only* thing the LLM ever sees.

**Provenance sources, in priority order** (first match wins per dish):
1. `client_constant` — the dish is pinned in `constant_items`
2. `theme` — the day's theme narrowed the pool
3. `freshness` — `recency[item] >= 14` → "not served for N days"
4. `rule` — a named rule bound the cell; use its `_comment` verbatim if present

> `docs/client_rules_index.md` is already generated and already renders every
> client rule as one plain sentence using the client's own `_comment`. Reuse
> that vocabulary rather than inventing new phrasing.

**Acceptance:** `pytest tests/explain/test_evidence.py` passes. The pack is
JSON-serialisable (`json.dumps` must not raise — watch for numpy scalars from
pandas; the module coerces them).

---

## STEP 3 — `src/explain/renderer.py` (bullets, ships without any LLM)

Turns an `EvidencePack` into plain text. No model involved.

```
Thursday 10 Sep — south
  Plate: 4 colours, 5 textures, spice medium/mild/hot, avg richness 2.4
  ✓ texture contrast    5 textures; 3 of 9 saucy
  ✓ no ingredient echo  no ingredient repeats
  • jowar_roti          south-themed day; bread narrowed to south_indian
  • veg_kurma           not served for 26 days
```

**Ship steps 1–3 to production before touching an LLM.** This is most of the value.

---

## STEP 4 — capture relaxations (the honesty feature)

This is the step I would argue hardest for.

The solver already logs when it quietly gives up:

- `selector_frequency_rule.py` — *"min 2 capped to 1 — the rule is under-enforced; widen this client's item pools"*
- `selector_frequency_rule.py` — *"day N can place only X of the Y required item(s); floor relaxed for that day"*
- theme/weekday bans — *"the slot has nothing else to offer; ban skipped"*

These go to a log nobody reads. Route them into the pack.

**Implementation:** add a `logging.Handler` scoped to the solve that captures
records from the `src.menu_rules.*` loggers at WARNING and above, keyed by rule
name. Attach it in `api/app.py` around the solve, detach in a `finally`. Pass
the captured list into `build_evidence(relaxations=...)`.

The rendered result:

> "Thursday leans south with jowar roti and mango rice. Two vegetarian protein
> sources beside the dal, five textures across nine dishes. **Note: the liquid
> dessert rule asked for two days and the pool offers one, so it ran once.**"

Now a chef learns something. The feature becomes a diagnostic surface rather
than marketing copy — which is consistent with this codebase's existing
conviction that the useful output is the conflict, not a plan that quietly
abandoned the rules.

---

## STEP 5 — `api/explain_llm.py` (prose, last)

**Model:** `gemma-4-31b-it` on Google AI Studio — 30 RPM, 14,400 requests/day,
same API surface the repo may already use. This is a rendering task; a 31B model
is indistinguishable from a 550B one here. Do not reach for a bigger model.

**Batching:** one call per *plan*, not per day. All 5 days in, 5 paragraphs out.
~1,500 tokens in, ~400 out. That is roughly **14,000 plans/day free.**

**Caching is mandatory, not an optimisation.** Streamlit reruns the script on
every widget interaction. Without a cache you will burn the daily quota on a
single user fiddling with a date picker.
Key: `sha256(canonical_json(evidence_packs))`. Store the prose. A regenerate
invalidates one day, not the plan.

**The validator is the point.** After the model replies:

1. Every number in the output must appear in the pack.
2. Every dish name in the output must appear in the pack.
3. No banned words (nutrition/health claims — you are a caterer, not a dietitian;
   this is a liability line, not a style preference).

Fail any check → **discard the prose entirely and fall back to `renderer.py`.**
This makes hallucination structurally impossible rather than merely discouraged.

**Environment:**
```
EXPLAIN_LLM_ENABLED=false      # default OFF; bullets ship first
EXPLAIN_LLM_API_KEY=...
EXPLAIN_LLM_MODEL=gemma-4-31b-it
EXPLAIN_LLM_TIMEOUT_SECONDS=20
```

Follow `api/config.py`'s existing `os.getenv` pattern. Do **not** add the key to
`validate_required_env()` — the feature must be optional.

---

## STEP 6 — wire it up

**New endpoint** (preferred over folding into `/plan`, which is already slow):

```
POST /api/v1/explain
  { "client_name": ..., "start_date": ..., "num_days": ..., "solution": {...} }
  -> { "days": [ {"date":..., "bullets":[...], "prose": "..."|null,
                  "checks":[...], "llm_used": bool} ] }
```

Rate-limit it with the existing `api/rate_limit.py` decorator.

**UI:** an expander per day under the menu table. Prose if present, bullets
always. If a check FLAGS, show it — do not hide failures behind a happy summary.

---

## Definition of done

- [ ] `pytest tests/explain/` green
- [ ] `pytest tests/platform/test_architecture.py` still green (no `src/` → `api/` leak)
- [ ] Full suite still at 1,750+ passing
- [ ] Feature works end-to-end with `EXPLAIN_LLM_ENABLED=false`
- [ ] With the LLM on, a deliberately corrupted model response (inject a fake
      number) is rejected by the validator and falls back to bullets — **add a
      test for this**
- [ ] Coverage stays above the CI floor (82%)

---

## Build order, and why

1. **Steps 1–3 first, ship them.** Bullets in production.
2. **Then show a chef 20 days of bullets.** Ask which verdicts are wrong. Tune
   the thresholds in `checks.py` against their judgement. That is your
   calibration set and it decides whether any of this is useful.
3. **Then Step 5.**

If you invert this and start with the LLM, you never find out whether the
underlying verdicts were right — the prose sounds convincing either way.

---

## Known issues to fix while you are in here

Found while auditing the repo; unrelated to this feature but cheap to fix:

1. **`chuteny`** (Bangalore + Hyderabad, `course_type='starter'`, `client='MOengage'`)
   is a misspelled category row that `remove_generic_rows.py` missed because the
   typo is not the word it looks for. **It is servable — a live solve served it
   as Friday's starter.** Same failure shape as the `chciken`/`chivken` protein
   typos.
2. **`samber`** (NCR, filed as `dal`, `sub_category='leafy_dal'`) is NCR's sambar,
   misspelled and misfiled. `add_ncr_sambar.py` imported 10 sambars *because
   "NCR's raw list carried NO sambar"* — it did, under a typo.
3. **`vegetable`** (NCR, `veg_gravy`) carries `is_premium_gravy`, so a row named
   "Vegetable" consumes the week's `premium_veg_gravy_exactly_one` slot.
4. **`test_client_menu_imports.py::test_rerunning_the_import_adds_nothing[MOengage]`
   is failing** — the import retags 1 row on re-run. The `ambiguous` log shows
   why: `chili_chicken`/`chilli_chicken`, `pepper_chicken_dry`/`pepper_chicken_fry`
   cannot be settled, so the fold re-decides each run.
5. **Objective tier headroom.** Weights are 1e15/1e12/1e9/1e6 — 1000x separation.
   That is not a mathematical guarantee, only a "holds at current scale" property.
   At `MAX_NUM_DAYS=30` the fleet's widest counter (19 slots) yields 570 terms —
   **1.75x headroom**. `client_config` permits 22 base slots x 5 = 110 expanded;
   30d x 40 slots = 1,200 terms would silently break lexicographic ordering and
   return OPTIMAL having optimised the wrong priority. Add a guard test.
