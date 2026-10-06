# Pending config changes

Everything that has to happen **outside this repository** for the rules now
committed to take effect, plus the commands to run inside it. Nothing here is a
code change — it is all Supabase values and scripts.

Ordered by whether a client's menu is wrong without it.

---

## 1. Database values a rule depends on — ALL APPLIED

Nothing outstanding. Every row that was on this list is live in the current
`clients` export, verified against `tests/client_fixtures.py`:

| # | Client | Change | Verified |
|---|---|---|---|
| 1.1 | TCL | `serve_weekends = true` | `serve_weekends: True` |
| 1.2 | TCL | add `white_rice` + `papad` to the counter's categories | both present |
| 1.4 | World Bank | `slot_counts.nonveg_main = 4` on Full Lunch Menu | `4` |
| 1.5 | Corning Chakan | add `starter` to the counter's categories | present |
| 1.6 | Moengage | fill the counter's `slot_counts` and `theme_map` | 11 slots, theme map set |
| 1.7 | Stryker (Bangalore) | fill `slot_counts` and `theme_map` | both set |

Clario (working days, Monday biryani) and Booking.com (`slot_counts.starter = 2`)
were applied earlier.

The table is kept rather than deleted because each row names the client
requirement the value serves — a future export that loses one should be
recognisable as a regression rather than read as a new request. If you add an
item here, put it back above this line.

---

## 2. Data the rules would like more of

Not blocking — every one of these degrades gracefully (a `min` caps itself to
what the pool can supply and `/diagnose` reports the shortfall) — but the menu is
thinner than the client asked for until the dishes exist.

| Where | Today | Needed | For | Status |
|---|---|---|---|---|
| **`item_color`, all cities** | **51 blank of 9,118**, all Hyderabad | — | `MenuSolver._add_color_constraints` clamps the day's required distinct colours to the number PRESENT, so a blank colour quietly relaxes the rule rather than merely going unchecked | ✅ **closed by you** — the enriched workbooks answered it: Bangalore, Chennai, NCR and Pune are 0% blank. The 51 left are Quest's own Hyderabad additions, which have no enriched file; the deleted chain's `colours_to_confirm_by_family.csv` report is down from 455 questions to **26**. NB the client's own `chef_review` sheet flags 720 Bangalore + 354 NCR of the supplied colours as low-confidence |
| Chennai `welcome_drink` | **0** | ~25 | TCL, World Bank and both ICON lunch counters declare the slot; three state a buttermilk rule | ✅ closed — the deleted `chennai_client_pools` step imports 28 (10 buttermilks incl. `sambaram` and `tadka_neer_mor`, the dishes TCL's own grid names) |
| Chennai `dal`, kootu | 0 in the dal pool | ~16 | "in dal need to give only Kootu item" — TCL, World Bank and ICON Chn, in the same words | ✅ closed — the 8 existing kootus re-filed `veg_gravy` → `dal` and 8 more imported |
| Chennai veg biryani | 14 (4 reachable) | ~20 | TCL serves one in its first rice slot every weekday | ✅ closed — 8 imported, and `chennai` joining `FULL_POOL_CITIES` makes the other 10 reachable |
| Chennai `boiled_egg`, `bone_salna` | absent | — | World Bank daily and ICON Premium on three days | ✅ closed — added as real `nonveg_main` rows, so the pins narrow a cell instead of stamping text |
| Chennai liquid desserts | 9 | ~12 | TCL's "liquid based sweet 3 a week" | ✅ closed — 17 now (2 flag fixes + 6 imports) |
| Chennai chicken gravies | 13 reachable | ~20 | World Bank serves one every day; `ThemeSlotFilterRule` hid the other 12 because they were tagged `continental` | ✅ closed — the deleted `chennai_cuisine_corrections` step; six saved weeks now hold at 5/5 |
| Chennai `veg_gravy`, **south** paneer | 1 dish | 3-4 | Tekion CHN's "paneer gravy every Wednesday" — Wednesday is a *south* day at that site, so only `paneer_kurma` qualifies | ⚠️ open — the rule is met on one Wednesday per cooldown window and relaxes on the others |
| Pune `veg_dry` leafy · Pune chaat starters · Chennai Chinese veg gravy | — | — | Corning Chakan, and a Chennai Chinese day | ✅ closed — the deleted `deepen_thin_pools` step |
| **`is_paneer_fry`, all cities** | **0 rows** | — | Zscaler's "exactly one paneer fry a week" selects on it, so the rule had never constrained anything (`min` caps to what the pool can place, and an empty selector places nothing) | ✅ closed — the deleted `definitional_flags` step now derives it, and its twin `is_paneer_gravy`, from `primary_protein` + the dish name |
| **`is_paneer_gravy`, Bangalore + NCR** | wrong both ways | — | it was derived from `key_ingredient`, which here is the default for a *Chinese* dish: Bangalore counted `thai_green_curry` and `veg_in_hot_garlic_sauce` as paneer gravies, NCR counted `chilli_chiken`, `lemon_water` and a `lemon_mint_mojito` while missing `butter_paneer_masala` and `matar_paneer`. Tekion, Tekion CHN, Corning Chakan and Zscaler all select on it | ✅ closed — same script; **this changes what those four clients can be served**, in the direction of the rule's meaning |
| `nonveg_main` form flags, all cities | 0 unflagged | — | the daily non-veg composition can never place a dish with no form flag | ✅ closed — all 51 adjudicated |

---

## 3. The correction chain — DELETED, and must not come back

**There is nothing to run.** This section used to list the ~40 scripts that
rebuilt `data/raw/city_items/*.xlsx` from the raw lists and re-applied every
hand fix on top, in order, and told you to re-run them after a raw re-import.

The owner has replaced that arrangement with cleaned workbooks, one per city,
and **those workbooks are now the SOURCE**. The chain is deleted, and the
instruction that used to be here is not merely obsolete, it is dangerous: the
chain's whole job was injecting dishes — ten sambars copied into NCR from
Bangalore, sixteen north rices, seven side dishes per city — and every one of
those would now be an unrequested change to the owner's data.

So:

* **Nothing writes to a city workbook.** A dataset problem is the owner's to
  fix at source: report it with the measurement, do not edit the file.
* **A thin pool is a normal state**, not a gap to fill. Code that narrows a
  pool degrades and says so rather than failing.
* What the corrections existed to guarantee is kept as standing guards in
  `tests/data/test_dataset_guards.py`, which read the workbooks and nothing
  else: no meat-named dish in a veg pool, no misspelled protein word, no
  `nonveg_main` row without a form flag. Those must keep passing.

`data/raw/city_items/pool_tokens.json` and `tests/client_fixtures.py` were both
generated by scripts in that chain and now have no generator — they are
committed artefacts, maintained by hand, and each says so at the top.

---

## 3b. Three pools that run out over five weeks

Found by the 25-day rolling sweep.
Each is the same shape: a **selector inside a slot** has fewer distinct dishes
than its own cadence needs once the 20-day cooldown has been removing them for
two weeks. The slot itself looks healthy, which is why nothing reports it.

| Where | Today | Needed | Who it stops | Status |
|---|---:|---:|---|---|
| NCR `is_nonveg_dry` | **11** | ~15 | Siemens — `nonveg_main_daily_pair` wants one dry dish EVERY day; its slot has 150 rows, of which 11 are dry | ⚠️ open |
| Bangalore `is_fish_dish` | **3** | ~5 | Stripe — `stripe_fish_1x_week` wants a fish weekly; three cannot cover five weeks under a 20-day hold | ⚠️ open |
| Chennai `curd_rice` | **2** | ~5 | ToastTab CHN — already **D4** in `data_fixes_for_client.md` | ⚠️ open |

All three degrade the same way: the counter plans two weeks fine and then
returns 500. Adding dishes is the fix in every case — none is a rule conflict,
and no rule should be relaxed for them.

---

## 3c. The two Pune rulebook sites

Both are configured and both generate, but the sheets ask for more than the
counter rows and the Pune list can currently carry.

**Database values** — nothing here is a code change:

| Client | Change | Why |
|---|---|---|
| ChrysCapital Advisors | `working_days = ["monday","tuesday","wednesday"]` | The sheet's first rule. The column is null, so the counter plans five days. |
| PhonePe | `item_cooldown_days`: 20 → 10? | The sheet asks for a 10-day cooldown; the row says 20, which is stricter. Left alone — confirm which you want. |
| PhonePe | add `salad`, `dessert`, `curd_side` and `starter` to the counter | Fourteen of its 47 rules name a slot the counter does not run: the Mon/Wed/Fri salad and Tue/Thu chaat swap, everything about sweets, the pulao→raita / else→curd pairing and the Mon/Wed/Fri curd staple, and the three starter rules. None of them can be written until the slot exists. |

**Pune item list** — three gaps, each blocking a stated rule:

| Missing | Blocks |
|---|---|
| `boiled_egg`, `boiled_chicken` | 'Non Veg 2 & 3 will serve Boiled egg and boiled chicken daily as staple'. Both are pinned and print correctly, but as TEXT — invisible to colour, variety and the cooldown. Adding the two rows upgrades the same pins to solved cells with no config change. |
| a `masala_buttermilk` row | '2 welcome drinks … mon,wed,fri plain buttermilk and tue,thur masala buttermilk, both staple'. Both halves are pinned in `constant_items.welcome_drink__2`; `buttermilk` is a real Pune row and solves, `masala buttermilk` is not and prints as text. Adding the row upgrades it to a solved cell with no config change — and the no-repeat-colour rule is already scoped to drink 1 (`slot_indices`), which it has to be: a buttermilk is white every day, and unscoped that rule makes the counter INFEASIBLE the moment this row exists. Measured. |
| a `chaat` course_type, in any city | 'Tuesday and Thursday, chaat will be served instead of salad, with 2 chaat items'. No city carries one. |

**Flags that made a rule miss.** `is_pulao` is set on 10 of Pune's 110 rices while
47 of them are pulaos — with the flag alone, '3 days rice 2 day pulao' let three
pulaos through and still reported satisfied. PhonePe's rule selects on flag OR
name as a result. Two others are inert in Pune and were deliberately not written:
no bread carries `is_rice_bread`, and `is_mellow` is 0 on every veg gravy.
Correcting the flags would let both be written as stated.

---

## 3d. `menu_history` has drifted off the ontology

**38 of 392 dish placements (10%) in the 2026-09 `menu_history` export match no
row in the current Bangalore list** — 28 distinct dishes across Clario, H&M,
Siemens Technology and Zscaler. A dish stored under a spelling the ontology does
not use matches no pool row, so it is never banned by the 20-day item cooldown,
never ages for the freshness objective and never counts toward a cross-week
cadence — with no log line and a plausible menu every week (note 28). Those
dishes can be re-served tomorrow.

Two causes, mixed together:

* **Spelling drift from the workbook swap** — `plain_chapatti` → `plain_chapati`,
  `tempared_buttermilk` → `tempered_buttermilk`, `malasa_buttermilk` →
  `masala_buttermilk`, `motichoor_laddu` → `motichur_laddu`, and the other
  `_chapatti` → `_chapati` rows.
* **Dishes the corrected list no longer carries** — `dal_adraki`, `lasooni_dal`,
  `panchmel_dal`, `rava_ladoo`, `hyd mutton biryani`, `lahori_murgh`.

**Do not fuzzy-match these automatically.** The nearest names to
`awadhi_murgh_korma` and `punjabi_anda_curry` are `awadhi_veg_korma` and
`punjabi_paneer_curry` — an automated backfill would quietly rewrite chicken as
veg and egg as paneer in the history the cooldown reads, which is the one error
whose consequence is outside the software (note 34).

Two ways to close it, both the client's call: a REVIEWED rename map applied to
`menu_history` (the candidates can be generated, each verdict approved), or leave
the pre-swap history and accept that the cooldown restarts from the swap date.

Same root cause as the client-importer drift in §4 and the twelve Hyderabad rows
that still carry spellings Bangalore has changed.

---

## 3e. Two compositions can stack on one slot, and nothing says so

Rules merge by **name**. A client composition on `nonveg_main` written under the
client's own name therefore **stacks** on the city's `nonveg_main_daily_pair`
(one non-veg dry + one gravy daily) instead of replacing it, and what the solver
must satisfy is the *intersection* of the two. Usually that is harmless and even
desirable — the city rule is about ROLE, a client rule is usually about PROTEIN,
so "two chicken, one dry one gravy" is a good plate. It bites where the
intersection is thin, and there is no warning of any kind: the pre-flight gate
reports `would_succeed: true` and the solve then returns INFEASIBLE naming no
rule, because no individual *slot* is starved.

Siemens is the live case. It serves two non-veg, and week 3 is INFEASIBLE from
three separate start Mondays (3 Aug, 7 Sep, 5 Oct) with weeks 1-2 saved. With
the history pinned so each trial differs by exactly one rule, **three single
removals fix it**: the city `nonveg_main_daily_pair`, the client
`siemens_nonveg_pair_by_weekday`, or `item_cooldown_20d`. Its own sentence
("Tue one egg + one chicken, other days two chicken") fully specifies both cells
and says nothing about dry/gravy, so the city composition is now disabled for
that client. **The mechanism is still unexplained** — the obvious story, that the
chicken-dry pool empties, is disproven: NCR has 10 chicken dry rows and week 3
still has 6 available, so the dry half is not what runs out.

| Client | Composition | Stacks on | Counter's nonveg_main |
|---|---|---|---|
| Siemens | `siemens_nonveg_pair_by_weekday` | `nonveg_main_daily_pair` | 2 — **fixed, city rule disabled** |
| Citrix, Cloudera, Infenion, Konsberg, Plum, Sinch, Sinch NCR, Tekion, Thales | `*_nonveg_by_weekday` | `nonveg_main_daily_pair` | 1, so the city pair is inactive — latent |
| Bakertilly | `bakertilly_two_chicken_dry_on_the_biryani_day` | `nonveg_main_five_dish` | 5 |
| Cigna, F5 | named `nonveg_main_daily_pair` | — | correctly REPLACE it |

Cigna and F5 show the intended shape: reuse the city rule's name and it
overrides. Worth a guard test that a client composition sharing a `base_slot`
with an active city composition either reuses its name or disables it.

## 3f. NCR is thin on non-veg dry

`is_nonveg_dry` is set on **12** NCR rows (10 of them chicken) against **108**
non-veg gravies. Any counter whose composition wants a dry dish daily draws on
those 12 under a 20-day cooldown. Not the cause of the Siemens failure above,
but the same shape as the north-rice shortage that `add_ncr_north_rice.py` was
written for, and worth an import while the item list is being cleaned.

Also in NCR's bread pool and reached by the unpinned bread slots: `bhelpuri`,
`bhel_poori` and `cholay_poori` are filed as **bread**. A bhel puri is a chaat.

---

## 3g. A pin a theme filter removes is dropped SILENTLY — six live cases

`theme_slot_filter` narrows a day's pool before cells are built. When the
narrowing removes a `constant_items` dish, the pin is dropped with **no warning,
no relaxation stamp and HTTP 200** — note 31's failure mode exactly. Junglee
Games served `wheat_dosa` on its south Thursday this way while its `tawa_roti`
staple looked configured (fixed: a client `theme_cuisine_filter` override adding
`bread` to `exempt_slots`, the same shape World Bank uses for `nonveg_main`).

Swept fleet-wide and **confirmed on real solves**, not on the pool check alone —
a pool-level hit does not always reach the plate, because `_filter_cuisine` falls
back when narrowing would empty a slot. Three of the nine pool hits held fine.

| Client | Pin | Day | Served instead |
|---|---|---|---|
| Ather | `bread` = plain chapati | Tue (south) | `millet_dosa` |
| Ather | `bread` = plain chapati | Thu (south) | `plain_dosa_with_red_chutney` |
| Astrazeneca | `bread` = plain chapati | Thu (south) | `ragi_roti_with_khara_chutney` |
| Booking.com | `starter__2` = veg kathi roll | Tue (continental) | `karela_kurkure` |
| Quince | `curd` = Curd | Wed (north) | `mint_curd` |
| Sinch | `curd` = Curd | Fri (north) | `mixed_curd` |

Booking.com/Telstra/Tessolve `curd` were pool hits that **held** on the plate.

All six are Bangalore. The curd and starter cases have an obvious reading — the
client pinned a specific dish and got a different one — while the two bread cases
are a genuine question: is a dosa wanted on a south day, or the chapati staple?

**The underlying defect is not fixed.** Per-client `exempt_slots` overrides close
each case one at a time; what would stop it recurring is stamping a dropped pin
as a relaxation so it reaches the explanation instead of vanishing.

---

## 4. Decisions still open

| Topic | Question | Where it bites |
|---|---|---|
| **Colours — 26 dish families left** | Was the headline open item at 1,696 dishes; your enriched workbooks closed all but Quest's own Hyderabad additions. What remains is in the deleted chain's `colours_to_confirm_by_family.csv` report, 26 questions, one per dish family. Vocabulary: brown, red, green, yellow, white, orange, black. Separately and more usefully: your files flag **720 Bangalore + 354 NCR** supplied colours as low confidence, and those are now in the city lists indistinguishable from the verified ones. | the enriched workbooks' own `chef_review` sheet |
| **Bangalore: 116 Indian dishes tagged `continental`** | Found while verifying World Bank, whose "chicken gravy daily" quietly relaxed to 3 days of 5 by week three. The mapping pipeline tagged plainly-Indian dishes `cuisine_family = continental`, and `ThemeSlotFilterRule` hides a continental dish on every non-continental day. Chennai's 31 are **fixed** (the deleted `chennai_cuisine_corrections` step) — no Chennai client runs a continental day, so those rows were simply dead and unblocking them is pure gain. Bangalore's **116** are not, and should not be done blind: 53 `chicken_north_masala` + 52 `pakora_/_bajji` + 11 others whose `sub_category` contradicts the tag, and Bangalore clients DO run continental days (Booking.com and Stripe theme a Tuesday, Amadeus alternates). Correcting them moves dishes OFF those menus as well as onto everyone else's, so it is a menu change to review rather than a cleanup. Worth a pass of its own — say the word. **It is no longer inert.** Filling NCR's `cuisine_family` had to route around it: across the corpus `sub_category == chicken_north_masala` reads 46% north / 45% continental, not because the category is ambiguous but because 53 Bangalore rows (and 53 Hyderabad copies) are tagged continental — which was blocking 64 NCR rows whose own sub_category says "north" from being filled at all. A dedicated tier reads the sub_category directly to get past it; correcting the source would remove the need. | the deleted `chennai_cuisine_corrections` step is the shape to copy |
| **Bangalore files 246 of 384 dals as `sub_category: leafy_dal`** | Found while adding Hyderabad: the completion pass filled `yellow_dal`, `yellow_dal_tadka` and `mixed_yellow_dal_tadka` as `leafy_dal`, which is wrong — a yellow toor/moong tadka has no greens in it. The token vote is not at fault; it faithfully reported the majority, and the majority is itself the defect. `leafy_dal` looks like the mapping pipeline's default for the dal course rather than a description, and it has now propagated to three more rows. **Inert today** — every shipped leafy rule selects on the `is_leafy_based_dish` FLAG, not on this column, and the flag was not set on any of the three — so this is a landmine rather than a live bug, the same shape as the dessert `cuisine_family` defaults. Fixing it means deciding what the non-leafy dals should say instead (`tadka_/_fry_dal` covers 58 rows today), which is a vocabulary question for you. | the deleted `complete_ontology` step learn_text; `sub_category` on `course_type == dal` |
| ~~233 NCR dishes with no cuisine~~ | ✅ **Closed.** `cuisine_family` decides which themed day a dish can be served on, and a blank means "no themed day at all" — NCR was 1,000 blank. the deleted `fill_cuisine_family` step filled 767 from measured evidence and your enriched workbook supplied the rest: the deleted chain's `cuisines_to_confirm.csv` report is now **empty**. Kept as a line because the *reason* matters — the vote is still forbidden from ever proposing `chinese` or `continental`, since those make a dish appear ONLY on their own theme day and no NCR client runs one. | — |
| **~1,400 dishes with no `sub_category` or `key_ingredient`** | The largest remaining gap, and the one a better heuristic cannot close — measured, not assumed. These are the two attribute columns shipped rules actually select on (8 and 12 client files), and they are 18-23% blank in Bangalore and Hyderabad, 16-19% in Chennai and Pune, 1.4% in NCR. `complete_ontology.py` already fills what the corpus agrees about; held out on a fifth of the classified rows its current corpus-wide setting scores **95.5% at 36.5% coverage** for sub_category and **96.7% at 31.5%** for key_ingredient, and a city-scoped variant — the trick that worked for `cuisine_family` — is WORSE on both counts (93.0% at 27.0%), because a cuisine is a property of the city's cooking while a sub-category is a property of the dish. What is left has genuinely unique names the ontology shares no token for: `dingri_mutter`, `kumbh_kaju_shabnam`, `mix_veg_kurchan`. Every one is listed with the column it is missing in the deleted chain's `ontology_gaps.csv` report; they need a person who knows the dish. | the deleted chain's `ontology_gaps.csv` report |
| **66 biryanis with no `nonveg_biryani_region`** | Low priority, recorded so the number is not mistaken for something worse. Scoped to `nonveg_main` the column reads 94% blank, which looks alarming; it is filled ONLY on `is_nonveg_biryani` rows and never outside them, so the real gap is 30 Bangalore + 33 Hyderabad + 3 Chennai biryanis. **No shipped rule reads this column** (nor `dal_region`, `drink_type`, `drink_rule_group` or `flavoured_rice_region` — `gravy_region` likewise). Each of the 66 is derivable from the row's own now-complete `cuisine_family`; say the word and it is a one-line pass. | `complete_ontology.py` COLUMN_SCOPE |
| **RNTBCI's logic** | On hold at your request. Its sheet in `chennai_client_structure.xlsx` is empty and `Sheet1` lists the client with no rules beside it, so nothing was configured. Its six counters plan from the Chennai city ruleset alone. Send the rules and it wires up like the other four. | `customisation/client rules/` — no file yet |
| **ICON Chn: the same non-veg on two counters** | "same nonveg main is served in Economy Lunch counter and Roti Combo Counter". The cross-counter sync pins from the **primary** counter only, and ICON's primary (Premium Lunch) serves a different lineup entirely. Both counters are configured with the same weekday structure — egg gravy Monday and Wednesday, chicken gravy otherwise — so they serve the same *kind* of dish on the same day, but not the identical dish. Making it identical needs a per-slot SOURCE counter in the planner, which is a bigger change than the exclusion below. Worth doing? | `app.py` multi-counter loop; `api.app._merge_shared_items` |
| **Bangalore has no plain `boiled_egg`** | F5 and Plan View both pin one and both get stamped text, because the closest Bangalore row is `boiled_egg_with_pepper_masala` — a different dish. Chennai gained a real `boiled_egg` row for World Bank and ICON; Bangalore did not. Add one? | the deleted `chennai_client_pools` step is the shape to copy |
| **TCL: buttermilk twice, or every day?** | The stated rule says "welcome drink will be buttermilk twice a week", but all five drinks in TCL's own sample week are buttermilks (BUTTERMILK / SAMBARAM / INJI MOORU / BUTTERMILK / NEER MOORU — sambaram and neer mor both count). Configured as stated. If you meant "the plain buttermilk twice and a variant on the other days", say so and the selector narrows to the one dish. | `customisation/client rules/tcl.json` |
| **ToastTab CHN serves an egg dosa as Friday's non-veg** | You confirmed `egg_dosa` and `kal_egg_dosa` are non-veg mains — "an egg dosa is how this site serves its egg" — and `kal_egg_dosa` now lands as ToastTab CHN's Friday non-veg main, on a counter that already plates a chapati and white rice. Correct by the rule you gave; worth confirming it reads right on a full meals menu, since the alternative is to keep those two to a tiffin or combo counter. | `customisation/client rules/toasttab_chn.json` |
| **World Bank: "Sweet/Fruit" as the dessert** | Configured as stated, which means the dessert cell is skipped and the menu prints that text every day rather than rotating a real sweet. Fine if that is what the diners see; say so if you would rather the slot rotated. | `customisation/client rules/world_bank.json` |
| **NCR: 61 rows whose name IS their category** | Found by a structural audit rather than by reading: a single-token dish name that equals its own `key_ingredient`, `course_type` or `sub_category` is the mapping pipeline describing the row instead of naming a dish — the same fingerprint as `samber`. NCR has 61 of them against 5-15 elsewhere, and they are not all cosmetic: **~17 desserts sit in `veg_gravy`** (`browine`, `custerd`, `icecream`, `milkcake`, `kheer`, `halwa`, `kulfi`, `rabdi`, `firni`, `petha`, `patisa`, `mohanthal`, `sewiyan`, `barfi`, `bananacake`, `muffins`, `rasmadhuri`), so a diner's gravy can be a brownie; **six fruits too** (`mango`, `papaya`, `pineapple`, `watermelon`, `guvava`, `olives`); `roohafza`, a squash, is filed `rice`; and `green`, `special`, `sauce`, `fryems` name nothing at all. Deciding which to remove, which to re-file and which are fine (`chole`, `rajma`, `pulao`, `upma` are real dishes) is a menu question, so nothing was changed — the full list was a report nobody acted on and is no longer generated. NB a fuzzy pass over category names, the obvious alternative, was measured and rejected: at edit distance 2 it flags `adai`/`dal`, `puri`/`curd`, `lime`/`rice`, all real dishes. | re-derive with a single-token name == own category scan |
| **NCR: twelve vegetarian keemas filed as mutton** | `soya_keema`, `veg_keema`, `nutri_keema` and nine siblings sit in `nonveg_main` with `primary_protein: mutton`. Their wrongly-inherited chicken-gravy flags are cleared, but whether a soya keema belongs on a non-veg counter at all is your call, not a data fix. | the deleted `nonveg_structural_flags` step |
| ~~**Premium flags**~~ | **DEFERRED by the client.** Applying their cost definition would take Bangalore's `is_premium_gravy` from 174 rows to 463, at which point "one premium veg gravy a week" stops meaning "the week's showcase dish" and starts meaning "paneer at most once a week". Left at the narrower flag. | the deleted `complete_ontology` step's `APPLY_PREMIUM` stays `False` |
| **Combined dal / sambar / rasam slots** | **36** counters run two or three of {dal, sambar, rasam} as separate daily slots, so all of them are served every day and there is nothing to alternate. The alternation you asked for ("dal Mon/Wed/Fri, sambar Tue/Thu") only applies to a *combined* slot, which 12 counters already use. Collapsing two dishes into one cell reduces what is on the plate, so it is a menu decision. Switch them? | one `categories` / `slot_counts` edit per counter |
| **Bakertilly's biryani day** | Its two rules contradict each other; you called it an outlier and it is left as-is (curd_side kept as a raita on Wednesday) | `customisation/client rules/bakertilly.json` |
