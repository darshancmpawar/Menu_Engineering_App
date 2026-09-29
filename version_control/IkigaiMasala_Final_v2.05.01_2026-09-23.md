# Ikigai Masala (Menu_Engineering_App): Version Control

**Current version:** 2.05.01, 2026-09-23
**Reconstructed from:** git history of `main` (30 Mar – 23 Sep 2026). No git tags or GitHub releases exist yet; approvals are to be confirmed.

## 1. Numbering scheme (P.MM.mm)

- **P (phase):**
  - **1 = Simple tool.** Single city (Bangalore), under 10 known sites, one shared rulebook.
  - **2 = Scaling.** Multi-city ontologies and rulebooks, client-level configuration across the fleet, launch sites, multi-service planning.
  - Reset MM and mm to 00 when P increments.
- **MM (major):** approved by the Project Manager. Each major version bundles 3–4 related features.
- **mm (minor):** operationally approved by team leads. Bug fixes, refactors, performance, UI polish, docs, tests, data corrections within an existing model.

## 2. File naming convention

`<Title>_<Status>_v<P.MM.mm>_<YYYY-MM-DD>`, e.g. `IkigaiMasala_Draft_v2.05.01_2026-09-23`

For releases, tag the merge commit: `git tag -a v2.05.01 -m "..."`

## 3. Change control table (newest first)

Author convention: "Darshan + Claude Code" means commits written in Claude Code sessions and merged by Darshan. Dates show the span of work in each version.

### Phase 2: Scaling

| Version | Date | Author(s) | Principal changes / reason | Key commits |
|---|---|---|---|---|
| 2.05.01 | 23 Sep | Darshan + Claude Code | Installed five corrected city workbooks and re-ran the correction chain; solve-input assembly moved out of api/app.py | d51363a, eeacb12 |
| **2.05.00** | 21–22 Sep | Darshan + Claude Code | **Regional theme days.** Design measured against five new client workbooks; regional days placed on the planner (not the config editor) behind a toggle; region-cache deadlock fixed | a6d6ed9, c09a9e7, 272da95, d72b6cc |
| **2.04.00** | 16–21 Sep | Darshan + Claude Code | **Multi-service planning.** (1) Meal dimension in menu_history; meal-aware /plan, /save, /saved-plan. (2) Dinner planner screen below lunch with its own controls; lunch ≠ dinner rule. (3) Services as a list: breakfast / lunch / snacks / dinner. (4) Plate variety rules built alongside: texture, same-day and 3-day key ingredient, protein | 3df41aa, ff93209, f9bd992, 607b0ea, d074255, 19d76b8, 84b3066, c8f0518, 340ceee |
| **2.03.00** | 4–17 Sep | Darshan + Claude Code | **Explainer.** (1) Deterministic plate checks, calibrated against 49 real menu days. (2) Solver relaxations routed into the explanation; `/explain` endpoint. (3) LLM layer with cache, made to disagree when warranted rather than agree. (4) Reframed as an overview of the meal, not a rule report; stepped explain UI | 81918dc, 0e1f316, b724f66, 4311800, 1590a36, cdc401e, f46f2b9 |
| **2.02.00** | 31 Aug–9 Sep | Darshan + Claude Code | **Data quality.** (1) Hyderabad ontology; NCR cuisine fill; client's enriched ontology merged. (2) Dish fold: 330 duplicate groups. (3) Veg/non-veg line corrections, made to survive re-import. Also: min_per_week replaces item_frequency, honest timeout messages | f45b4e8, 915afa6, 49477de, 9030d7a, 335a20f, 9a4010b, 37d735a |
| **2.01.00** | 5–19 Aug | Darshan + Claude Code | **Fleet expansion.** (1) NCR ontology (1,544 items) and site logic. (2) Launch sites: flag, launch view, Launch→Ops promotion. (3) Shared categories across counters, cross-week cadence rule, regenerate anti-cycling, freshness objective. (4) Client menu importers: Bangalore 4,988 → 6,183 dishes, Chennai 425 → 616 | fc4ff3c, 431b9ca, d8ace6b, 2086bd3, b2b15f0, 9975bc1, 297c39d, df9bb84 |
| 2.00.01 | 4 Aug | Darshan + Claude Code | Application layer and ontology repository split out of Flask; /editor-metadata cold start 4,828 ms → 12 ms | 661c6b4, 50f120a, fca866b |
| **2.00.00** | 27 Jul–3 Aug | Darshan + Claude Code | **Multi-city foundation (start of scaling).** (1) Per-city rule files with inheritance. (2) Client-level configuration: client-specific rules go from 1 client to 24; counter-scoped overrides, constant items, working days, weekday composition. (3) Pune and Chennai ontologies and rulesets, pools scoped to city | d9fcf9e, f20f1c9, 29b7e63, 7c7d8c9, 6c9e792, 713cd9a |

### Phase 1: Simple tool

| Version | Date | Author(s) | Principal changes / reason | Key commits |
|---|---|---|---|---|
| **1.03.00** | 22–25 Jul | Darshan + Claude Code | **Rulebook engine.** (1) Client item-pool filtering. (2) Cuisine exclusivity and ingredient ban. (3) Rule families: selector_frequency, premium, attribute grouping, colour, deep-fried coupling, soft preferences. (4) Lexicographic objective tiers and ranked alternate menus | 8c84001, 4f70f12, 9187314, f3cfe43, 0dc2c97, b95035e, f52a8a1 |
| **1.02.00** | 15–21 Jul | Darshan + Claude Code | **Counters and richer data.** (1) Multi-cuisine counters with per-counter generation; schema 7 → 4 tables; Pulse theme. (2) Client city field and city filter. (3) Formatted Excel export and non-veg highlighting. (4) Enriched ontology (~530 → 4,656 items) with Continental theme, weekend service, combination categories, per-client cooldown | 2e41cd8, e1fc766, bdae2a6, acd8b1e, c98c2e8, d2f019f, 990d413 |
| 1.01.01 | 27–30 Apr | Darshan + Claude Code | Docker; from→to changes log; smoother regenerate panel | 0ca4915, 7899ef2 |
| **1.01.00** | 22 Apr–11 May | Darshan + Claude Code | **Production readiness.** (1) CI with coverage gate. (2) Observability: structured logging, /health, /metrics, rate limits, optimistic concurrency on config writes. (3) Saved plans: overwrite-on-save, replay saved plan. (4) Pre-flight diagnostics explaining failed plans | b548253, d383b8f, 70456cb, 64cad9a, 69a563c, ba55813, 7d83588 |
| 1.00.02 | 3–17 Apr | Darshan + Claude Code | Dark UI redesign; solver pipeline split; rule files consolidated | af26bd0, d17c357, 70cd5c3 |
| 1.00.01 | 31 Mar–1 Apr | Darshan + Claude Code | Pre-solve pool validation; editor Create New flow; save fixes | ca02059, 7de1bd8 |
| **1.00.00** | 30 Mar–16 Apr | Darshan + Claude Code | **Core planner.** (1) CP-SAT menu solver, Streamlit UI, Flask API. (2) Client config in Supabase. (3) Concurrent generation for 5+ users. (4) Per-client custom rules | 0ffecc7, c181eef, 6a1f798, 133b35b, 259ea39 |

## 4. Feature-to-version map

| Feature | Introduced | Last significantly changed | Where it lives |
|---|---|---|---|
| CP-SAT menu solver | 1.00.00 | 1.03.00 | src/solver/ |
| Supabase client config | 1.00.00 | 1.02.00 | src/db.py, src/client/ |
| Concurrent solve queue | 1.00.00 | 1.01.00 | api/concurrency.py |
| Per-client custom rules | 1.00.00 | 2.00.00 | src/menu_rules/ |
| Regenerate | 1.00.00 | 2.01.00 | src/solver/regenerator.py |
| Observability (logs, health, metrics, rate limit) | 1.01.00 | 1.01.00 | api/logging_config.py, api/metrics.py, api/rate_limit.py |
| Saved plans and history | 1.01.00 | 2.04.00 | src/history/, src/application/history.py |
| Pre-flight diagnostics | 1.01.00 | 2.00.00 | src/menu_rules/diagnostics.py |
| Multi-cuisine counters | 1.02.00 | 2.01.00 | customisation/counter_editor.py |
| City per client | 1.02.00 | 2.00.00 | src/application/regions.py |
| Excel export | 1.02.00 | 1.02.00 | ui/planner_view.py |
| Themes (Chinese, Continental, biryani) | 1.02.00 | 2.05.00 | src/menu_rules/theme_rules.py |
| Client item-pool filtering | 1.03.00 | 2.00.00 | src/preprocessor/client_pool_filter.py |
| Rulebook rule types | 1.03.00 | 2.01.00 | src/menu_rules/ |
| Lexicographic tiers and alternate menus | 1.03.00 | 1.03.00 | src/solver/menu_solver.py |
| Per-city rule inheritance | 2.00.00 | 2.00.00 | src/ontology/ |
| Constant items, working days, weekday composition | 2.00.00 | 2.02.00 | src/application/constant_items.py, horizon.py |
| City ontologies (Bangalore, Pune, Chennai, NCR, Hyderabad) | 2.00.00 | 2.05.01 | src/ontology/, data/ |
| Launch sites | 2.01.00 | 2.01.00 | api/app.py, ui/ |
| Shared categories and cross-week cadence | 2.01.00 | 2.01.00 | selector_history_window_rule.py |
| Client menu importers | 2.01.00 | 2.02.00 | scripts/ |
| Explainer | 2.03.00 | 2.03.00 | src/explain/, api/explain_llm.py |
| Multi-service planning (breakfast, lunch, snacks, dinner) | 2.04.00 | 2.04.00 | src/application/, ui/ |
| Plate variety rules | 2.04.00 | 2.04.00 | src/menu_rules/ |
| Regional theme days | 2.05.00 | 2.05.00 | src/application/regions.py |

## 5. Review notes

- **Phase boundary.** Phase 2 starts at 2.00.00 (27 Jul), with per-city rule files. The next day client-specific rules went from 1 client (Tekion) to 24, and Pune followed three days later.
- **Grouping.** Each major version bundles 3–4 features that were built together and share a theme. Minor versions hold the fixes and refactors between them.
- **Approvals.** No tags exist, so sign-off is not recorded in git. Record the approver and date for each major version here.
- **Overlapping dates.** 2.02.00 (data quality) and 2.03.00 (explainer) were built in parallel in early September; they are split by theme, not by date.
- **Plate variety rules** are placed in 2.04.00 because they were built alongside the dinner work. Move them to their own version if you consider them separate.
- **Next versions:** next major = 2.06.00; next minor = 2.05.02; next phase = 3.00.00.
