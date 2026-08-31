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
| 1.1 | **TCL** | `serve_weekends = true` | "it working on sat and sun as well" | Only Monday to Friday is planned, and the ten rules that describe the reduced Saturday and Sunday menus never fire. |
| 1.2 | **TCL** | add `white_rice` and `papad` to the counter's categories | The sample serves steamed rice on six of the seven days and appalam on all seven | Two rows the kitchen actually plates are missing from the printed menu. |
| 1.4 | **World Bank** | `slot_counts.nonveg_main = 4` on **Full Lunch Menu** (it is 2) | "non veg main will have chicken gravys, chicken biryani, boiled egg and Bone Salna daily" — four items, and the sample prints all four | Only the biryani pin lands. The boiled-egg and bone-salna pins name slots the counter does not have and are dropped (with a warning naming the slot count to raise). |
| 1.5 | **Corning Chakan** | add `starter` to the counter's categories, `slot_counts.starter = 1` | "On Thursday only we will give a starter. Starter should be a chaat item" | Both starter rules are inert; `/diagnose` reports them as targeting a slot the counter does not serve. Every other Corning rule works. |
| 1.6 | **Moengage** | fill in the counter's `slot_counts` (only `nonveg_main: 2` is set) and its empty `theme_map` | Every other slot falls back to a default of 1 and the counter inherits the app-wide theme map | Works, but the counter is not configured — a slot count the client wanted is invisible. |
| 1.7 | **Stryker** (Bangalore) | fill in `slot_counts` (empty) and `theme_map` (empty) | Same as above | Same as above. |

Clario (working days and the Monday biryani theme) and Booking.com
(`slot_counts.starter = 2`) were on this list and **are now applied live** —
the 23 Aug export carries both.

### SQL for 1.1 and 1.4

```sql
update clients set serve_weekends = true, version = version + 1
 where name = 'TCL';
```

`slot_counts` lives inside the `counters` JSONB, so 1.4 is easiest from the
editor: Edit Logic → Chennai → World Bank → Full Lunch Menu → non-veg count 4.

---

## 2. Data the rules would like more of

Not blocking — every one of these degrades gracefully (a `min` caps itself to
what the pool can supply and `/diagnose` reports the shortfall) — but the menu is
thinner than the client asked for until the dishes exist.

| Where | Today | Needed | For | Status |
|---|---|---|---|---|
| **`item_color`, all cities** | 1,696 blank of 8,977 | — | `MenuSolver._add_color_constraints` clamps the day's required distinct colours to the number PRESENT, so a blank colour quietly relaxes the rule rather than merely going unchecked | ⚠️ **needs you** — 744 filled from measured evidence; the rest cannot be inferred. `docs/colours_to_confirm_by_family.csv` asks **455 questions** instead of 1,696: the top 25 answers colour half the backlog, the top 100 three quarters |
| Chennai `welcome_drink` | **0** | ~25 | TCL, World Bank and both ICON lunch counters declare the slot; three state a buttermilk rule | ✅ closed — `scripts/chennai_client_pools.py` imports 28 (10 buttermilks incl. `sambaram` and `tadka_neer_mor`, the dishes TCL's own grid names) |
| Chennai `dal`, kootu | 0 in the dal pool | ~16 | "in dal need to give only Kootu item" — TCL, World Bank and ICON Chn, in the same words | ✅ closed — the 8 existing kootus re-filed `veg_gravy` → `dal` and 8 more imported |
| Chennai veg biryani | 14 (4 reachable) | ~20 | TCL serves one in its first rice slot every weekday | ✅ closed — 8 imported, and `chennai` joining `FULL_POOL_CITIES` makes the other 10 reachable |
| Chennai `boiled_egg`, `bone_salna` | absent | — | World Bank daily and ICON Premium on three days | ✅ closed — added as real `nonveg_main` rows, so the pins narrow a cell instead of stamping text |
| Chennai liquid desserts | 9 | ~12 | TCL's "liquid based sweet 3 a week" | ✅ closed — 17 now (2 flag fixes + 6 imports) |
| Chennai chicken gravies | 13 reachable | ~20 | World Bank serves one every day; `ThemeSlotFilterRule` hid the other 12 because they were tagged `continental` | ✅ closed — `scripts/chennai_cuisine_corrections.py`; six saved weeks now hold at 5/5 |
| Chennai `veg_gravy`, **south** paneer | 1 dish | 3-4 | Tekion CHN's "paneer gravy every Wednesday" — Wednesday is a *south* day at that site, so only `paneer_kurma` qualifies | ⚠️ open — the rule is met on one Wednesday per cooldown window and relaxes on the others |
| Pune `veg_dry` leafy · Pune chaat starters · Chennai Chinese veg gravy | — | — | Corning Chakan, and a Chennai Chinese day | ✅ closed — `scripts/deepen_thin_pools.py` |
| **`is_paneer_fry`, all cities** | **0 rows** | — | Zscaler's "exactly one paneer fry a week" selects on it, so the rule had never constrained anything (`min` caps to what the pool can place, and an empty selector places nothing) | ✅ closed — `scripts/definitional_flags.py` now derives it, and its twin `is_paneer_gravy`, from `primary_protein` + the dish name |
| **`is_paneer_gravy`, Bangalore + NCR** | wrong both ways | — | it was derived from `key_ingredient`, which here is the default for a *Chinese* dish: Bangalore counted `thai_green_curry` and `veg_in_hot_garlic_sauce` as paneer gravies, NCR counted `chilli_chiken`, `lemon_water` and a `lemon_mint_mojito` while missing `butter_paneer_masala` and `matar_paneer`. Tekion, Tekion CHN, Corning Chakan and Zscaler all select on it | ✅ closed — same script; **this changes what those four clients can be served**, in the direction of the rule's meaning |
| `nonveg_main` form flags, all cities | 0 unflagged | — | the daily non-veg composition can never place a dish with no form flag | ✅ closed — all 51 adjudicated |

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
python scripts/nonveg_structural_flags.py      # dry vs gravy, and chicken flags off non-chicken dishes
python scripts/chennai_client_pools.py         # kootu -> dal, welcome drinks, boiled egg, bone salna
python scripts/chennai_cuisine_corrections.py  # 31 Indian dishes wrongly tagged continental
python scripts/deepen_thin_pools.py            # the three pools a rule outgrew
python scripts/complete_ontology.py            # last of the learners
python scripts/definitional_flags.py           # is_liquid_dessert / is_buttermilk, both ways
python scripts/build_pool_token_map.py         # refresh the committed token map
python scripts/audit_course_types.py           # must exit 0
pytest -m "not slow"                           # the guards
```

Worth knowing about the two newest:

* **`chennai_client_pools.py`** — the five holes the new Chennai clients found.
  Includes a **re-file**: Chennai's kootus move from `veg_gravy` to `dal`, which
  is a deliberate divergence from Bangalore (43 kootus in `veg_gravy`) and is
  argued in the script's docstring. Three clients state "in dal need to give
  only Kootu item" in the same words and all four sample weeks print the kootu
  as its own row, never as the day's gravy.
* **`definitional_flags.py`** also now carries the two paneer flags (`COURSE_INGREDIENT_FLAGS`). Re-running it is what makes Zscaler's paneer-fry rule
  live for the first time and stops a Thai green curry counting as a paneer gravy.
* **`definitional_flags.py`** — `is_liquid_dessert` and `is_buttermilk` in both
  directions. It runs **after** `complete_ontology.py`, whose token vote is what
  put `is_liquid_dessert` on 55 NCR pethas, laddus and cakes; both flags are now
  in that script's `OWNED_ELSEWHERE` so the chain converges either way round.

Also re-run `scripts/dump_client_fixtures.py --clients <clients export>` whenever
the live `clients` table changes shape, or the 85-counter sweep silently stops
covering the clients that were added since. That is how it fell 13 clients
behind. It reads the `INSERT INTO … VALUES` SQL export as well as CSV.

And `scripts/dump_client_rules_index.py` after editing anything under
`data/configs/clients/`; the test suite fails if `docs/client_rules_index.md` is
stale.

---

## 4. Decisions still open

| Topic | Question | Where it bites |
|---|---|---|
| **Colours for 1,696 dishes** | The one item that genuinely needs your input. Fill the `item_color` column in `docs/colours_to_confirm_by_family.csv` — one answer per dish family, ordered so stopping early still helps. Vocabulary: brown, red, green, yellow, white, orange, black. Your own colour legend workbook is committed at `data/raw/source_workbooks/client_food_colour_legend.xlsx`; it matched only 3 of these rows (it is a Chennai tiffin list, the blanks are Bangalore and NCR) and agrees with the existing colours 73% of the time, so it is a cross-check rather than a source. | `docs/colours_to_confirm_by_family.csv` |
| **Bangalore: 116 Indian dishes tagged `continental`** | Found while verifying World Bank, whose "chicken gravy daily" quietly relaxed to 3 days of 5 by week three. The mapping pipeline tagged plainly-Indian dishes `cuisine_family = continental`, and `ThemeSlotFilterRule` hides a continental dish on every non-continental day. Chennai's 31 are **fixed** (`scripts/chennai_cuisine_corrections.py`) — no Chennai client runs a continental day, so those rows were simply dead and unblocking them is pure gain. Bangalore's **116** are not, and should not be done blind: 53 `chicken_north_masala` + 52 `pakora_/_bajji` + 11 others whose `sub_category` contradicts the tag, and Bangalore clients DO run continental days (Booking.com and Stripe theme a Tuesday, Amadeus alternates). Correcting them moves dishes OFF those menus as well as onto everyone else's, so it is a menu change to review rather than a cleanup. Worth a pass of its own — say the word. **It is no longer inert.** Filling NCR's `cuisine_family` had to route around it: across the corpus `sub_category == chicken_north_masala` reads 46% north / 45% continental, not because the category is ambiguous but because 53 Bangalore rows (and 53 Hyderabad copies) are tagged continental — which was blocking 64 NCR rows whose own sub_category says "north" from being filled at all. A dedicated tier reads the sub_category directly to get past it; correcting the source would remove the need. | `scripts/chennai_cuisine_corrections.py` is the shape to copy |
| **Bangalore files 246 of 384 dals as `sub_category: leafy_dal`** | Found while adding Hyderabad: the completion pass filled `yellow_dal`, `yellow_dal_tadka` and `mixed_yellow_dal_tadka` as `leafy_dal`, which is wrong — a yellow toor/moong tadka has no greens in it. The token vote is not at fault; it faithfully reported the majority, and the majority is itself the defect. `leafy_dal` looks like the mapping pipeline's default for the dal course rather than a description, and it has now propagated to three more rows. **Inert today** — every shipped leafy rule selects on the `is_leafy_based_dish` FLAG, not on this column, and the flag was not set on any of the three — so this is a landmine rather than a live bug, the same shape as the dessert `cuisine_family` defaults. Fixing it means deciding what the non-leafy dals should say instead (`tadka_/_fry_dal` covers 58 rows today), which is a vocabulary question for you. | `scripts/complete_ontology.py` learn_text; `sub_category` on `course_type == dal` |
| **233 NCR dishes with no cuisine** | The second item that genuinely needs your input, and the smaller one. `cuisine_family` decides which themed day a dish can be served on, and a BLANK means "no themed day at all" — NCR was 1,000 blank, of which 767 are now filled from evidence. The rest split three ways and are listed with the reason in `docs/cuisines_to_confirm.csv`: **no evidence** (mostly `payasam_/_kheer`, which is 50/50 north/south across the whole corpus, so it is genuinely regionless rather than unknown), **carries a chinese/continental flag** (a region would be wrong and those two values are never guessed, since they make a dish appear ONLY on their own theme day — and no NCR client runs one), and **course has no agreed convention** (welcome drinks, which the corpus files 331 `drink` against 139 `north_indian`). Only 56 of the 233 are in a slot the theme filter gates, so this is much less urgent than it was. | `docs/cuisines_to_confirm.csv` |
| **RNTBCI's logic** | On hold at your request. Its sheet in `chennai_client_structure.xlsx` is empty and `Sheet1` lists the client with no rules beside it, so nothing was configured. Its six counters plan from the Chennai city ruleset alone. Send the rules and it wires up like the other four. | `data/configs/clients/` — no file yet |
| **ICON Chn: the same non-veg on two counters** | "same nonveg main is served in Economy Lunch counter and Roti Combo Counter". The cross-counter sync pins from the **primary** counter only, and ICON's primary (Premium Lunch) serves a different lineup entirely. Both counters are configured with the same weekday structure — egg gravy Monday and Wednesday, chicken gravy otherwise — so they serve the same *kind* of dish on the same day, but not the identical dish. Making it identical needs a per-slot SOURCE counter in the planner, which is a bigger change than the exclusion below. Worth doing? | `app.py` multi-counter loop; `api.app._merge_shared_items` |
| **A whole-slot pin is stamped even when the dish is real** | `_rules_and_skip_for_client` narrows a cell for an *indexed* pin (`starter__2`) but stamps a **bare-string** one, dropping the base slot from the model entirely — and its stated reason is that "the same dish cannot occupy five days unless it is a staple", i.e. `unique_items` would make it INFEASIBLE. **That objection no longer holds**: a dish forced into the same base slot on two or more days now declares itself repeatable (`MenuSolver._repeatable_declarations`, added for World Bank's daily pins). So Ather's `mixed veg salad` and every other daily bare-string pin could now be solved rather than stamped, which would make them count toward colour variety, cuisine variety and no-repeat instead of being invisible to all three. Not done here: it changes the plan for every client with such a pin (Ather, Booking.com, F5, Plan View and more), so it wants its own pass with the 85-counter sweep behind it rather than riding along at the end of this one. | `api/app.py:393`, `src/solver/menu_solver.py::_repeatable_declarations` |
| **Bangalore has no plain `boiled_egg`** | F5 and Plan View both pin one and both get stamped text, because the closest Bangalore row is `boiled_egg_with_pepper_masala` — a different dish. Chennai gained a real `boiled_egg` row for World Bank and ICON; Bangalore did not. Add one? | `scripts/chennai_client_pools.py` is the shape to copy |
| **TCL: buttermilk twice, or every day?** | The stated rule says "welcome drink will be buttermilk twice a week", but all five drinks in TCL's own sample week are buttermilks (BUTTERMILK / SAMBARAM / INJI MOORU / BUTTERMILK / NEER MOORU — sambaram and neer mor both count). Configured as stated. If you meant "the plain buttermilk twice and a variant on the other days", say so and the selector narrows to the one dish. | `data/configs/clients/tcl.json` |
| **ToastTab CHN serves an egg dosa as Friday's non-veg** | You confirmed `egg_dosa` and `kal_egg_dosa` are non-veg mains — "an egg dosa is how this site serves its egg" — and `kal_egg_dosa` now lands as ToastTab CHN's Friday non-veg main, on a counter that already plates a chapati and white rice. Correct by the rule you gave; worth confirming it reads right on a full meals menu, since the alternative is to keep those two to a tiffin or combo counter. | `data/configs/clients/toasttab_chn.json` |
| **World Bank: "Sweet/Fruit" as the dessert** | Configured as stated, which means the dessert cell is skipped and the menu prints that text every day rather than rotating a real sweet. Fine if that is what the diners see; say so if you would rather the slot rotated. | `data/configs/clients/world_bank.json` |
| **NCR: twelve vegetarian keemas filed as mutton** | `soya_keema`, `veg_keema`, `nutri_keema` and nine siblings sit in `nonveg_main` with `primary_protein: mutton`. Their wrongly-inherited chicken-gravy flags are cleared, but whether a soya keema belongs on a non-veg counter at all is your call, not a data fix. | `scripts/nonveg_structural_flags.py` |
| ~~**Premium flags**~~ | **DEFERRED by the client.** Applying their cost definition would take Bangalore's `is_premium_gravy` from 174 rows to 463, at which point "one premium veg gravy a week" stops meaning "the week's showcase dish" and starts meaning "paneer at most once a week". Left at the narrower flag. | `scripts/complete_ontology.py::APPLY_PREMIUM` stays `False` |
| **Combined dal / sambar / rasam slots** | **36** counters run two or three of {dal, sambar, rasam} as separate daily slots, so all of them are served every day and there is nothing to alternate. The alternation you asked for ("dal Mon/Wed/Fri, sambar Tue/Thu") only applies to a *combined* slot, which 12 counters already use. Collapsing two dishes into one cell reduces what is on the plate, so it is a menu decision. Switch them? | one `categories` / `slot_counts` edit per counter |
| **Which component gets the three days** | `COMBO_CATEGORIES` names the majority globally: `dal_sambar` and `dal_rasam` give dal three days, `sambar_rasam` gives **rasam** three. A site wanting sambar on Mon/Wed/Fri instead cannot say so today. Make it per-client? | `src/constants.py::COMBO_CATEGORIES` |
| **Six-day weeks cannot alternate cleanly** | With Saturday service the split is dal / sambar / dal / **dal** / sambar / dal — two dal days adjacent, because six days allow only two minority days. Five- and seven-day weeks alternate perfectly. Give a six-day week three sambar days? | `src/constants.py::combo_minority_count` |
| **Bakertilly's biryani day** | Its two rules contradict each other; you called it an outlier and it is left as-is (curd_side kept as a raita on Wednesday) | `data/configs/clients/bakertilly.json` |
