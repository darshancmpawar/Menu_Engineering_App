# Client Logics — Bangalore

Per-client menu requirements as stated by the operations team, mapped against
what the tool currently enforces.

**Source:** `menu_Implementation_tracker.xlsx`, sheet `Banglore` — 32 clients.
Two rows describing live-counter / popup service (a tandoori live counter and a
branded lunch popup) are out of scope and are not tracked here.

**Purpose:** this is the bridge between a stated requirement and the rule that
implements it. Every row names the mechanism, so a gap is always one of three
concrete things: a rule that does not exist yet, a rule that exists but is not
wired to this client, or missing ontology data.

**Scope:** Bangalore only. Every client here draws from
`data/raw/city_items/bangalore.xlsx` under `data/configs/city_rules/bangalore.json`.
Pune is a separate item list and a separate ruleset —
see [`pune_rulebook.md`](pune_rulebook.md) for the city rules and
[`pune_client_logic.md`](pune_client_logic.md) for its clients.

**Status is a first-pass reading of the config, not a verified outcome.** A row
marked DONE means a matching rule exists in `data/configs/client_rules.json` (or
the city baseline covers it) — it does not yet mean a generated menu was checked
against it. Confirm against a real week per client, then promote the row.

| Status | Meaning |
|---|---|
| **DONE** | A rule or constant implements this today |
| **PARTIAL** | Implemented in part; the gap is named in the row |
| **TODO** | Not configured, but expressible with existing rule types |
| **BLOCKED** | Needs a capability the engine does not have — see [Capability gaps](#capability-gaps) |
| **DATA** | Needs ontology rows or flags that do not exist |

---

## Coverage summary

| | Clients | Notes |
|---|---|---|
| Have a `client_rules.json` entry | 25 | |
| Entry exists but is empty | 1 | Piramel Finance |
| No entry at all | 7 | Icon, Nike, Take 2, Eli Lilly, Continental, Waters, Siemens Healthineers |

**Key entries by the DB name, byte-for-byte.** `client_rules.json` is looked up by
exact match against `clients.name` with no normalisation, and a mismatch is silent:
every rule for that client loads as zero, `/diagnose` still reports clean, and a
plausible plan comes back having ignored all of them. This already happened once —
`ToastTab CHN` was configured while the file said `Toast Tab CHN`. The names differ
from this document's spellings in ways that are easy to miss:

| This doc / the rulebook says | `clients.name` actually is |
|---|---|
| Icon | **`Icon Blr`** |
| Computacenter | `Computa Centre` |
| Kongsberg | `Konsberg` |

Verified: all 28 current keys match a live client, so there is no other silently
dead config. Re-check after adding any entry.

The seven clients with no entry account for 30 stated requirements with nothing
behind them. Two clients are configured far below what they ask for: Siemens
Technology (12 requirements, 1 config item) and L&T (5 requirements, 1 config
item) — both currently carry only a per-counter rule disable.

Counts of "requirements" and "config items" are not comparable one-to-one: a
single rule can satisfy several stated requirements, and some requirements are
already met by the city baseline. Use the table above to decide where to look,
not as a score.

---

## Verified against real menu samples

**Source:** `data/raw/source_workbooks/bangalore_menu_samples_history.xlsx` — printed menus for
**32 clients**, one week each except Tekion which has two. Supersedes the earlier
14-client file. Tessolve arrived as an image and is transcribed below.

These are what the kitchen actually served, so where a sample and the written
requirement disagree, the sample is the better evidence of intent — but the
disagreement is worth resolving explicitly rather than silently picking one.

### What the samples settle: "biryani day" is two different things

The single biggest ambiguity in the rulebook. "Biryani to be served on Wednesday"
turns out to mean the **veg biryani in the flavoured-rice slot** for some clients
and the **non-veg biryani in the non-veg slot** for others — and several clients
have both, on *different* days:

| Client | Veg biryani (flavoured rice) | Non-veg biryani |
|---|---|---|
| AstraZeneca | Mon + Wed | none — non-veg is plain curry all week |
| H&M | Fri | Wed |
| Icon | Wed | Wed |
| Computacenter | Wed | Tue, Wed, Thu |
| Zscaler | Wed | Tue, Thu |
| Plan View | Fri | Tue |
| Kongsberg | Fri | Fri |
| Infenion | Fri | Fri |
| Ikea | Wed | **never** — non-veg is curry, by rule |

Consequences for the rules:

- A requirement naming a biryani has to say *which* slot it means. Several
  currently-configured rules assume the veg one and the sample shows the client
  meant the non-veg one (see the config notes below).
- The counter's `theme_map` biryani day and the non-veg biryani day are **not the
  same thing**. Plan View's theme day is Tuesday (its non-veg biryani) while its
  veg biryani is Friday; Zscaler serves non-veg biryani on two days that are not
  its veg-biryani day.
- Ikea's non-veg row confirms the reading in its requirement table: no non-veg
  biryani appears at all, and the biryani lives in the veg rice slot on Wednesday.

### What the samples confirm

Requirements the sample matches dish-for-dish — these are safe to promote once
the corresponding rule exists:

- **Infenion** — non-veg is exactly `Mon: Murgh Do Pyaza / Tue: blank / Wed:
  Punjabi Egg Masala / Thu: blank / Fri: Mughlai Chicken Biryani`. Precisely the
  stated weekday pattern, and the clearest specification of capability gap 3 in
  the whole set. Its two bread rows are south (Kali Dosa, Ragi Roti, Onion
  Uttapam, Pesarattu) and north (Jeera/Ajwain/Palak/Carrot Chapati) — so
  "Indian Bread 1" is the south slot and "Indian Bread 2" the north.
- **Kongsberg** — Wed `EGG PEPPER`, Thu chinese (Veg Noodles + Honey Chilli
  Potatoes), Fri `Mughlai Chicken Biryani`. All three stated weekday rules hold.
- **Plan View** — buttermilk daily, a boiled-egg row daily, paneer once (Wed),
  mushroom once (Thu). On its non-veg biryani day (Tue) the veg gravy *and*
  flavoured rice both go chinese — `Veg Dumplings in Manchurian` + `Schezwan
  fried rice` — which is exactly the stated rule and was previously unclear.
- **Vector** — dessert appears **only** on Wednesday and flavoured rice **only**
  on Friday; both blank the other four days. Confirms that a deliberately empty
  slot is a normal outcome, not a failure.
- **Computacenter** — three non-veg rows (dry / gravy / biryani-or-curry), curd
  rice daily, green salad daily, raita daily, a chinese dry once (Chicken
  Manchurian, Tue).
- **Quince** — three service days only (Wed/Thu/Fri) and two non-veg rows, one
  dry ("NON VEG STARTER") and one gravy-or-biryani.
- **Ikea** — no egg anywhere in non-veg; four chicken gravies plus one dry
  (Chilly Chicken, Tue); raita on the Wednesday biryani day, curd otherwise.

### Where the samples contradicted the rulebook — resolved

All three were settled by the client; the config now matches the decision.

| Client | Written requirement | Sample served | **Decision** |
|---|---|---|---|
| AstraZeneca | "daily just raita" | Curd, all five days | **Curd daily.** `constant_items.curd_side = 'Curd'` and `curd_raita_logic` disabled — without the disable, the city rule would still put raita on the biryani day. |
| AstraZeneca | plain chapati 2× + phulka + ragi mudde + flavoured | Plain Chapati daily | **Plain chapati daily.** `constant_items.bread`. |
| Cloudera | "curd rice daily in healthy rice" | Curd Rice Tue–Thu, Red Rice Monday | **Curd rice daily** — the rulebook wins; Monday's red rice was a one-off. Config unchanged. |

### Config notes the samples exposed

- **Zscaler / Computacenter biryani rules target the wrong slot.** Both have a
  `selector_frequency` on `base_slot: rice` whose selector lists
  `is_nonveg_biryani` and `is_premium_biryani` — and **both flags match 0 rows in
  the rice pool**, because non-veg items never enter any slot except
  `nonveg_main`. The rules therefore reduce to "mixed-veg biryani or pulao", which
  the samples do satisfy, so nothing is broken. But the *stated* requirement in
  both cases is about non-veg biryani on named weekdays (Zscaler Tue/Thu,
  Computacenter Tue/Wed/Thu), and that is not implemented at all. Drop the two
  dead flags for clarity and add the weekday rule via gap 3.
- **Printed row labels are not tool slots.** Worth knowing when comparing output
  to a sample: Quince merges curd, raita and papad into one `ACCOMPANIMENTS`
  cell; H&M's `Dal/Raitha` row carries dal on normal days and raita on the
  biryani day; Icon and Computacenter both label a row `NON VEG - EGG` that in
  fact holds chicken gravies and biryanis; Zscaler's `Soup` row holds welcome
  drinks. Do not map these by label.
- **Categories in the samples with no slot in the tool:** `INFUSED WATER`
  (AstraZeneca, Cloudera) and a separate `Compound salad` alongside green salad
  (Plan View, which needs `salad` × 2).
- **Cloudera's sample covers four days and its Wednesday and Thursday columns are
  identical** — likely a draft rather than a rule. Not treated as evidence.

---

## Scope: lunch only

**Decided.** The tool generates the **lunch** menu. Breakfast and dinner are out
of scope.

Tessolve's printed sheet carries three periods and Tekion qualifies some rules
"(Lunch)" or "(Lunch & Dinner)". Under this decision a period-qualified rule is
read as its lunch part: the lunch half is implemented in full and the dinner half
is dropped rather than tracked as an outstanding gap. Nothing in the engine needs
a `meal_period` dimension.

The breakfast and dinner rows transcribed below are kept as reference — they
document what the client serves, not what the tool produces.

### Tessolve — transcribed from the printed menu (20th–24th July)

Recorded here because it arrived as an image, not a sheet.

**Breakfast**

| | Mon | Tue | Wed | Thu | Fri |
|---|---|---|---|---|---|
| Item 1 | Onion Dosa | Chow Chow Bath | Rava Idly | Bathure | Puliogare |
| Item 2 | Veg Sagu | — | Vada | Chole Masala | Masala Vada |
| Accompaniment | Chutney | Chutney | Sambar / Chutney | Chutney | Chutney |

**Lunch**

| | Mon | Tue | Wed | Thu | Fri |
|---|---|---|---|---|---|
| Welcome Drink | Butter Milk | Butter Milk | Butter Milk | Butter Milk | Butter Milk |
| Salad | Green Salad | Mix veg Salad | Kosumbari salad | Green Salad | Corn Salad |
| Indian Bread | Chapathi | Methi Chapathi / Ragi Balls | Beetroot Chapathi | Dosa | Palak Chapathi |
| Veg Dry | Dry Aloo Masala | Shake Gourd Kootu | Tawa Veg Dry | Beetroot Porial | Veg Manchurian |
| Veg Gravy | Kabul Channa Masala | Avarekalu Gussi | Methi Malai Mutter | Bombay Sagu | Mushroom Corn Kadai |
| Dal / Sambar | Drumsticks Sambar | Tomato Dal | Turai Sambar | Green Moong Dal Tadka | Bhendi Kara Sambar |
| Rasam | Mysore Rasam | Tomato Rasam | Pudina Rasam | Pepper Rasam | Gingar Rasam |
| Flavour Rice | Tomato Peas Bath | Puliogare With Chutney | Bread Pualo | Veg Biryani | Jeera Ghee Rice |
| Healthy Rice | Red Rice | Red Rice | Red Rice | Red Rice | Red Rice |
| White Rice | White Rice | White Rice | White Rice | White Rice | White Rice |
| Accompaniment | Ghee | Ghee | Ghee | Ghee | Ghee |
| Curd | Curd | Curd | **Raitha** | Curd | Curd |
| Papad / Pickle | Pappad/Pickle | Pappad/Pickle | Pappad/Pickle | Pappad/Pickle | Pappad/Pickle |
| Dessert | Jamoon | Banana | Hydrabadi phirni | Kova Burfi | Dryfruits Moong Dal Kheer |

**Non-Veg Section** (blank Monday and Friday)

| Day | Content |
|---|---|
| Tue | Salad Section + Soup + Bread + Cut Fruit + Brown Rice Pilaf + Boiled Egg + Steamed Paneer + Steamed Chicken |
| **Wed** | **Bombay Style Chicken Biryani + Salan + Raitha + Chicken Kabab + Boiled Egg + Sweet + Pepper Chicken Dry** |
| Thu | Salad Section + Soup + Bread + Cut Fruit + Dal Kichidi + Boiled Egg + Steamed Paneer + Steamed Chicken |

**Dinner**

| | Mon | Tue | Wed | Thu | Fri |
|---|---|---|---|---|---|
| Indian Bread | Ajwain Chapathi | Chapathi | Beetroot Chapathi | Jeera Chapathi | Chapathi |
| White Rice | White Rice | White Rice | White Rice | White Rice | White Rice |
| Gravy | Babycorn Capsicum Masala | Dum Aloo Masala | Soya Tamator | Veg Handi | Soya Mutter Masala |
| Dal / Sambar | Gungura Pappu | Herekai Soppu Sambar | Sultani Dal | Lauki Sambar | Masoor Dal Tadka |
| Rasam | Ginger Rasam | Tomato Rasam | Mango rasam | Pepper rasam | Mint Rasam |
| Curd | Curd | Curd | Curd | Curd | Curd |
| Papad / Pickle | Fryms/Pickle | Fryms/Pickle | Fryms/Pickle | Fryms/Pickle | Fryms/Pickle |
| Dessert | Mysore Pak | Gajar ka Halwa | Dobble Ka Meeta | Pista Burfi | Pineapple Kesari Bath |
| Salad | Protien Salad | Peanut Salad | Otc Salad | Veg Salad | Cucumber Salad |

What this settles for Tessolve:

- **"non veg only on Wednesday, other days blank" is right after all.** Tuesday
  and Thursday are not non-veg *mains* — they are a health/salad counter (salad,
  soup, bread, cut fruit, a grain, steamed paneer, steamed chicken). Only
  Wednesday carries non-veg dishes as such. Reconciles the requirement with the
  sheet.
- **Wednesday's composition is explicit**: biryani + salan + raita + kebab +
  boiled egg + sweet + a pepper chicken dry. Same shape as L&T's five-dish
  station, plus salan and a sweet.
- Confirmed: buttermilk daily · red rice daily in healthy rice · green salad
  twice (Mon, Thu) · curd daily except raita on the Wednesday biryani day · one
  biryani and one chicken dry on the biryani day.
- **New category not in the tool**: an `Accompaniment` row holding **Ghee** every
  day at lunch.
- Its veg biryani is Thursday (Flavour Rice) while its non-veg biryani is
  Wednesday — another instance of the two-biryanis split.

---

## Rules written inside the sample sheets

Requirements that appear as notes in `data/raw/source_workbooks/bangalore_menu_samples_history.xlsx` rather than in
the tracker. Transferred here so the rulebook is the single source.

### Tekion — eight rules, none currently configured beyond three

Tekion's sheet carries the largest rule block, and it is the only sample with
**two consecutive weeks**, which makes it the right client to test multi-week
rules against.

| Rule as written | Status | Mechanism |
|---|---|---|
| "Chinese Rice & Chinese gravy to be served on Tuesday (Lunch)" | DONE | `tekion_chinese_rice_tuesday` + `tekion_chinese_gravy_tuesday`. Verified. |
| "Paneer Gravy to be served every wednesday (Lunch & Dinner)" | DONE | `tekion_paneer_gravy_wednesday`. Dinner is out of scope, so the lunch rule is the whole of it. Verified. |
| "Khichdi to be served every Thursday (Lunch)" | DONE | `tekion_khichdi_thursday`. No `is_khichdi` flag exists; every khichdi carries `is_liquid_rice` and `tekion_liquid_rice_once` already caps that at one a week, so pinning Thursday lands it there. Verified. |
| "Non-Vegetarian Gravy Items Lunch on Monday and Wednesday" | DONE | `tekion_nonveg_mwf` restricts the slot to Mon/Wed/Fri; `tekion_nonveg_by_weekday` then makes Mon/Wed a chicken gravy and Friday a biryani. Friday **is** its biryani day, confirmed in the live client config. |
| "only infused or flavoured chapthi to be served in indian bread" | TODO | Bread sub-category restriction. The sample's first Monday serves "Plain Chapati", which contradicts it — worth confirming. |
| "curd daily except [biryani day] raitha" | TODO | Both weeks: curd Mon–Thu, raitha Friday. |
| "Chinese Noodles to be served once in a month on Tuesday (Lunch)" | BLOCKED | New gap — a **monthly** window. Longest window the engine has is a per-item cooldown in days. |
| "on any day theme except chinese, if veg dry is south the veg gravy should be north or vice versa, not from same family" | BLOCKED | New gap — cross-slot cuisine complementarity within a day. |

### Other sheet notes

| Client | Note | Reading |
|---|---|---|
| Plum | "Panner once in a week" · "Chicken once in a week" | **Narrows the open question.** The tracker says "weekly twice only non veg"; this note says chicken once. If the second non-veg day is an egg day, that is expressible now — see [Open questions](#open-questions). |
| AstraZeneca | "will give rasam from solver not constant item" | Its sample prints "Rasam" every day, which reads like a pinned constant. The note says it must be **solved**, so the rasam slot stays in the model and varies. No pin — current config is correct; recorded so nobody adds one. |
| Plan View | "weekly 1 starter to be given I have configured it in app also" | Sample serves a starter on Wednesday only. Client states it is already configured on their side. |
| Continental | "Gobi Fried Rice (Gobi should be Deep Fried)" | Preparation instruction, not a selection rule. Out of scope. |
| Vector | "Green salad — Carrot, Cucumber, onion sliced separately with lemon, chilli, coriander" | Preparation/plating detail for the pinned green salad. Out of scope. |

---

## What the 18 new samples add

### Cross-counter shared items is now the most-demanded gap — six clients

Gap 1 was inferred from written requirements. The samples make it concrete, and
**Waters is built entirely on it**:

- **Waters** — four combos (`Roti Veg`, `Roti Non Veg`, `Rice Veg`, `Non Veg
  Rice`). Across all four, **dal, salad, both starters and the sweet are the same
  dish**. The only variation is the carb (roti vs rice) and whether the dry and
  gravy slots hold veg or non-veg. Effectively one veg menu plus a non-veg
  dry/gravy pair, presented four ways.
- **L&T** — bread, dessert, salad and papad are identical across South, North and
  Non-Veg on every day.
- **Nike** — flavoured rice, plain rice, dal, roti and salad identical across its
  veg and non-veg counters; only the dry and gravy differ.
- **Amadeus** — north and south share bread, salad, pickle, papad and curd, and
  differ on dry, gravy, flavoured rice and dessert. **Exactly as its requirement
  states.**
- **Siemens Technology** — the salad row reads literally "Salad" on all three
  counters, and the dessert is the same jaggery-based payasa (renamed "Kheer" on
  the north counter, "Payasa" on the south).
- **Siemens Healthineers** — `Jain Dal` appears as its own row on both veg
  counters, identical.

### Corrections to my earlier reading

Two things I had recorded wrongly:

1. **L&T's bread alternation is daily, not weekly.** I filed it under gap 5
   (weekly alternation). The sample shows `Mon Chapati / Tue Phulka / Wed Chapati
   / Thu Phulka / Fri Chapati` — a within-week alternation on all three counters.
   That is an ordinary weekday pattern and needs no new capability. Gap 5 now has
   only one client (Siemens Technology's biryani alternation), which is a genuine
   week-over-week cycle.
2. **L&T's egg is a staple too.** The sample serves `EGG CURRY` — the same item —
   on all five days, exactly as `CHICKEN KABAB` does. The kebab is already modelled
   as a staple; the egg row should be as well, or `unique_items` will insist on
   five different egg dishes.

### Siemens Technology's non-veg counter, precisely

The sample's rows visibly shift on Wednesday and Friday because **Indian bread and
white rice are not served on those days** — which is the requirement, confirmed:

| | Mon / Tue / Thu | Wed (biryani) | Fri (biryani) |
|---|---|---|---|
| Non-veg dishes | 2 — chicken gravy + chicken dry | 3 — biryani + fish/mutton + egg dry | 2 — biryani + egg |
| Indian bread | served | **not served** | **not served** |
| White rice | served | **not served** | **not served** |
| Lentil | sambar / dal | **salan** | **salan** |
| Raita | not served | **served** | **served** |

The sample week is a *fish* week — Wednesday carries "Boiled Rice with Fish
Masala" — which confirms the stated week-over-week alternation between a
mutton week and a fish week. Neither protein exists in the ontology.

### Other confirmations

- **Nike** — on Wednesday the white-rice slot reads **"Salan"** and **veg dry is
  absent**, on both counters. Its requirement, confirmed exactly.
- **Eli Lilly** — Friday is its biryani day: the bread row carries the veg
  biryani and rasam, veg dry and papad all go blank. Tuesday and Thursday show
  "-" for rasam, matching "north days have no rasam". Note its rows shift on
  Friday, as Siemens Technology's do.
- **Siemens Healthineers** — `Jain Dal` served four of five days (Thursday blank),
  so "daily" is 4/5 in practice.
- **Booking.com** — the sheet named `Sheet6` **is Booking.com** (confirmed by the
  client). It has a `Veg Kati roll` row every day, separate veg and non-veg soup
  rows, chapati daily, and raita on the Wednesday biryani day — all four of its
  stated requirements, confirmed. Its Tuesday is labelled **"Tuesday(Punjabi)"**,
  a regional theme the engine does not have (gap 11).

### More categories with no slot in the tool

Adding to the earlier list (`INFUSED WATER`, a second salad row):

| Category | Client | Note |
|---|---|---|
| `Ghee` accompaniment | Tessolve | Daily at lunch |
| `Jain Dal` | Siemens Healthineers | Own row, both veg counters |
| `Flavoured Bread` | Booking.com | A second bread row alongside plain chapati |
| `Veg Kati roll` | Booking.com | Daily extra row — currently pinned as `starter__2` |
| `Healthy` | Booking.com | Millet khichdi / quinoa / ragi mudde / curd rice |
| Breakfast `Item 1` / `Item 2` / `Accompaniment` | Tessolve | Whole meal period |

---

## Capability gaps

Requirements that cannot be expressed with today's rule types. Ordered by how
many clients need them.

### 1. Shared items across counters — **BUILT (per-day dish sync)**
*Waters, L&T, Nike, Amadeus, Siemens Technology, Siemens Healthineers, DXC*

> "categories such as indian bread, dessert, curd/raita, salad, papad and white
> rice are all same items for the day across counters" — L&T

Counters are still solved **independently** — the planner calls `/plan` once per
counter — but the "second pass that fixes the shared slots first and pins them
into each counter" is now wired. A client declares a `shared_categories` list
(base slots) in `client_rules.json`; the planner solves the primary counter
(index 0), extracts its dish for each shared slot per day
(`ui.formatters.shared_items_from_solution`), and passes them as `shared_items`
to every later counter's `/plan` call, where `_merge_shared_items` folds them
into `forced_items` — the same narrow-the-cell mechanism a client constant uses.
So a common category resolves to the **same dish across counters each day**,
while non-shared slots (e.g. a non-veg station's `nonveg_main`) still solve
independently. An explicit client constant pin always wins over a sibling's
shared item.

**DXC uses it** (`shared_categories: bread, rice, sambar, rasam, curd_side,
dessert, white_rice`), verified in `tests/test_dxc_client_logic.py`.

`shared_categories` can be set two ways: the **multi-counter editor** (a toggle +
a multiselect of base slots present on 2+ counters, persisted to
`clients.shared_categories`) or `client_rules.json` (file-based, e.g. DXC). GET
`/client-config` prefers the DB value and falls back to the file, so both feed
the same planner path.

What is *not* yet built: a true **joint solve**. The pin-from-primary pass covers
"identical shared dishes" (DXC, L&T-style shared bread/dessert/curd/salad). It
does not cover a counter whose shared slot the primary lacks, and it makes the
primary the source of truth rather than optimising all counters together —
adequate for the stated requirements, short of a joint model. **Waters** — four
combo counters whose dal/salad/starters/sweet match, differing only in carb and
veg-vs-non-veg — is expressible with this pass once its `shared_categories` are
configured.

### 2. Slot suppression driven by the day's theme
*Siemens Technology, Eli Lilly, Nike*

> "on biryani day we serve salad, flavored rice, non veg main (biryani), raita,
> in veg gravy write 'salan', dessert and no other item that day" — Eli Lilly

`slot_day_restriction` keys on **weekday**, so "no white rice on the biryani day"
is not expressible when the biryani day is set by the theme map rather than
hard-coded to a weekday. Needs the restriction to accept day *types*.

### 3. Composition keyed to the weekday — **BUILT AND WIRED**
*Infenion, Thales, Kongsberg, Cloudera, Sinch, Plum — all six configured*

> "Monday chicken gravy, Wednesday egg and Friday biryani, other days blank" — Infenion

`slot_composition` now accepts `components_by_weekday` alongside
`components_by_theme`. Weekday wins over theme, which wins over the default list,
because a weekday is the more specific statement — "Friday biryani" means Friday
whatever theme Friday carries. A weekday configured with an **empty list**
composes nothing that day, which is how "other days blank" is expressed.

A component may also carry an `exclude` selector, same grammar as `selector`.
That is needed because the flags are not clean: `egg_drumstick_curry` and
`egg_kurma` carry `is_south_chicken_gravy` despite being egg dishes, so
"a chicken gravy on Monday" was satisfied by an egg curry until Monday's
component excluded `is_egg_dish`.

All six clients are wired. Verified non-veg output:

| Client | Mon | Tue | Wed | Thu | Fri |
|---|---|---|---|---|---|
| Infenion | chicken gravy | *blank* | egg | *blank* | biryani |
| Thales | egg | egg | chicken gravy | egg | biryani |
| Kongsberg | chicken gravy | chicken gravy | egg | chinese (theme) | biryani |
| Cloudera | egg | — | — | — | — |
| Sinch | — | — | biryani | — | — |
| Plum | — | — | — | — | chicken |

A dash means the day is deliberately left to the theme map rather than pinned.
Kongsberg's Thursday is the clearest case: its requirement says "Thursday
chinese", which is already its theme, so pinning a dish family there would only
narrow what the theme filter already handles.

### 4. Frequency windows longer than the horizon, and co-occurrence
*Icon, Telstra, Take 2, Vector, Piramel Finance, Tekion*

> "mushroom or kofta should come once in 10 days, but not with paneer" — Icon

Two separate needs. A **multi-week window** ("once in 10 days", "2 weeks once")
spans more than one plan, so it has to be evaluated against history rather than
within the horizon — `item_cooldown` does this per item, but not per category with
a target count. And **co-occurrence exclusion** ("not with paneer") is a
mutual-exclusion between two selectors on the same day, which no rule type
expresses.

Tekion adds the longest window of all — *"Chinese Noodles once in a month on
Tuesday"* — and is the only client with two consecutive sample weeks, which makes
it the right one to verify any multi-week implementation against.

### 5. Weekly alternation between two dishes
*Siemens Technology*  ~~L&T~~ — see the correction below

> "alternates between chicken biryani, mutton biryani one week and other week we
> give chicken biryani and fish item on biryani day" — Siemens Technology

The parity mechanism already exists — `chinese_continental` resolves per ISO week
in `weekday_type_for_config` — but only for *themes*, not for item choices. The
same trick applied to a composition component would cover it. Siemens Technology
additionally needs data (see gap 8), and its sample week is a fish week, which
confirms the cycle is real rather than aspirational.

**L&T no longer belongs here.** Its "chapati and phulka alternately" reads as
week-over-week but the sample shows `Chapati / Phulka / Chapati / Phulka /
Chapati` *within* the week, on all three counters. That is an ordinary weekday
pattern, already expressible.

### 6. Day-set-restricted frequency
*Continental*

> "Ragi Mudde will be served once a week, either on Tuesday or Thursday" — Continental

`selector_frequency` can ask for one day out of the horizon, and
`allowed_day_types` can restrict by theme, but neither restricts to a *set of
named weekdays*. A small addition to the existing rule type.

### 7. New category rows
*Siemens Healthineers, Tessolve, Booking.com*

> "add new row in north indian and south indian counter as jain dal and will get
> jain dal daily in it" — Siemens Healthineers

Needs a `jain_dal` base slot in `src/constants.py` plus the ontology rows to fill
it. Its sample serves it on four of five days, so "daily" is 4/5 in practice.

Tessolve needs a `Ghee` accompaniment row daily, and Booking.com a `Flavoured
Bread` row alongside plain chapati plus a `Healthy` row. Each is mechanically
small; they are listed here because a new base slot is a schema change, not a
config one, and every one of them also needs ontology rows to draw from.

### 8. Ontology data
*Siemens Technology, Icon, Zscaler*

| Missing | Needed by | Detail |
|---|---|---|
| Mutton, fish | Siemens Technology | `primary_protein` has only `chicken` (270 rows) and `egg` (68) for non-veg. No mutton, fish or prawn exists anywhere in the 4,321-row ontology, so those dishes cannot be selected. A pin naming one prints as text; add the rows and the same pin starts going through the solver with no config change. |
| Breakfast-item flag | Icon | "no breakfast item in lunch for flavoured rice / Indian bread" needs a flag marking which dishes are breakfast items. |
| `is_paneer_fry` | Zscaler | The flag exists as a column but matches 0 rows, so `zscaler_paneer_fry_1` is inert. Populate it or change the selector. |
| Kebab flag | L&T | No kebab flag exists; the 5-dish station's kebab component matches on `is_tandoor` / `is_tandoor_nonveg_dry` instead. Works, but it is a proxy. |

### 9. Meal periods — breakfast and dinner — **OUT OF SCOPE (decided)**
*Tessolve, Tekion*

> "Paneer Gravy to be served every wednesday (**Lunch & Dinner**)" — Tekion

**Decision: the tool generates lunch only.** Breakfast and dinner are not
modelled and will not be. Recorded because it changes how period-qualified rules
are read, not because it is pending:

- A rule marked "(Lunch)" is the whole of that rule as far as the tool is
  concerned — Tekion's chinese-Tuesday, khichdi-Thursday and non-veg-day rules
  are all lunch rules and are implementable in full.
- A rule marked "(Lunch & Dinner)" is implemented for lunch and its dinner half
  is deliberately dropped. Tekion's "Paneer Gravy every Wednesday (Lunch &
  Dinner)" is therefore complete, not partial, under this decision.
- Tessolve's breakfast and dinner sections in the transcription below are
  reference only. The lunch section is what the tool targets.

### 10. Cross-slot cuisine complementarity within a day
*Tekion*

> "on any day theme except chinese, if veg dry is south the veg gravy should be
> north or vice versa, not from same family" — Tekion

A constraint *between two slots on the same day*, conditioned on the day's theme.
The existing rule types cover a slot's own candidates (`attribute_grouping`), a
selector's count across the horizon (`selector_frequency`) and a slot family's
per-day mix (`slot_composition`) — none relates the cuisine of one slot to the
cuisine of a different slot. Closest existing precedent is the built-in
rice≠gravy colour constraint in `MenuSolver`, which is hard-coded rather than
config-driven; this wants the same shape, generalised and driven by config.

### 11. Regional themes beyond the six
*Booking.com*

Booking.com's sample labels its Tuesday **"Tuesday(Punjabi)"**. The engine's theme
vocabulary is `mix / chinese / biryani / south / north / continental` (plus the
alternating `chinese_continental`). A Punjabi day is narrower than "north" and has
no representation. Whether this needs a real theme or is adequately served by a
per-weekday cuisine rule is a judgement call — **flagged as a question** rather
than assumed.

---

## Per-client requirements

### Amadeus
| Requirement | Status | Mechanism |
|---|---|---|
| Salad is just green salad daily | DONE | `constant_items.salad` |
| Indian bread is plain chapathi daily | DONE | `constant_items.bread` |
| North and south counters share all items except veg dry, flavoured rice, veg gravy, dessert | BLOCKED | Gap 1 |
| Chinese counter serves continental daily, not weekly | DONE | `continental_rice_weekly` disabled on the Chinese counter |

### AstraZeneca
| Requirement | Status | Mechanism |
|---|---|---|
| Paneer once a week | DONE | `astra_paneer_exact_1` |
| Daily just raita | DONE | `constant_items.curd_side` |
| Biryani on Wednesday | TODO | Verify the counter's `theme_map` sets Wednesday = biryani |
| Plain chapati 2×, phulka 1×, Tue phulka + ragi mudde, other days flavoured, no south bread | TODO | Several `selector_frequency` rules + a bread cuisine restriction |

### Ather
| Requirement | Status | Mechanism |
|---|---|---|
| Dessert only on Thursday, liquid-based | DONE | `ather_dessert_thu_only` |
| Salad is mix veg salad daily | DONE | `constant_items.salad` |
| Only plain chapati daily | DONE | `constant_items.bread` |
| Weekly 1 paneer | DONE | `ather_paneer_exact_1` |
| 3 days curd, 2 days curd + raita | TODO | `constant_items` for `curd` / `curd_side`, as Telstra has |
| Healthy rice is only red rice daily | TODO | `constant_items.healthy_rice`, as Cloudera has |

### Booking.com
| Requirement | Status | Mechanism |
|---|---|---|
| Curd daily, raita when biryani | DONE | `constant_items` curd/curd_side split |
| Extra item veg kati roll all day | DONE | `constant_items.starter__2` |
| 3 pulao in a week | DONE | `booking_pulao_exact_3` |
| Plain chapati daily | DONE | `constant_items.bread` |
| 2 soups: one veg, one non-veg | TODO | `slot_composition` on `soup` with `min_slot_count: 2` |

### Cigna
| Requirement | Status | Mechanism |
|---|---|---|
| 2 non-veg mains: chicken + egg gravy daily | DONE | `nonveg_main_daily_pair` (per-client) |
| Indian bread: varieties of chapati/paratha in a week | TODO | Bread sub-category restriction |
| White rice weekly once; no flavoured rice that day; never on chinese or biryani day | TODO | Needs gap 2 for the theme exclusion |

### Cloudera
| Requirement | Status | Mechanism |
|---|---|---|
| Curd rice daily in healthy rice | DONE | `constant_items.healthy_rice` |
| Paneer twice a week | DONE | `cloudera_paneer_exact_2` |
| Dosa / puri / paratha weekly once | DONE | `cloudera_special_bread_1x` |
| Biryani once a week | TODO | Verify against the city `nonveg_biryani_once_per_week` baseline |
| Monday egg gravy | TODO | Gap 3 |

### Computacenter
| Requirement | Status | Mechanism |
|---|---|---|
| 1 chinese veg dry weekly once | DONE | `computa_chinese_veg_dry_weekly` |
| Weekly 2 plain chapati and phulka | DONE | `computa_plain_chapati_phulka_2x` |
| Ban mix veg in both gravy and dry | DONE | `computa_no_mixed_veg` + two city rules disabled |
| Paneer once a week | DONE | `computa_paneer_exact_1` |
| Green salad daily | DONE | `constant_items.salad` |
| 3 days biryani (Tue, Wed, Thu) | PARTIAL | `computa_biryani_pulao_rice_3x` sets the count but not the weekdays — gap 3 |
| 2 more non-veg mains (one dry, one gravy); chinese dry once a week | PARTIAL | The dry/gravy pair comes from the city composition; the weekly chinese dry is not configured |

### Continental
No `client_rules.json` entry.

| Requirement | Status | Mechanism |
|---|---|---|
| Flavoured rice every Monday, Wednesday, Friday | TODO | `slot_day_restriction` on `rice`, as Ikea has |
| Paneer curry once a week | TODO | `selector_frequency` exact 1 |
| Ragi mudde once a week, Tuesday or Thursday, south counter | BLOCKED | Gap 6 |

### DXC
Bangalore launch site (created through the launch view), two counters — **Veg
Lunch** and **Non Veg Lunch** — that share the flavoured-rice, bread and curd
logic, so those rules sit at the client level.

| Requirement | Status | Mechanism |
|---|---|---|
| Flavoured rice: biryani ≥3 days/week, even on non-biryani days | DONE | `dxc_flavoured_rice_biryani_3x` (`min: 3`) + base `mixedveg_pulao_biryani_weekly` **disabled** (it caps biryani+pulao at 1/week) |
| Flavoured rice: pulao ≥1/week | DONE | `dxc_flavoured_rice_pulao_1x` (`min: 1`) |
| No South-cuisine flavoured rice | DONE | `dxc_no_south_flavoured_rice` (`max: 0`) |
| Indian bread is plain chapati every day | DONE | `dxc_plain_chapati_daily` (a one-cell `slot_composition` component mandating `sub_category = plain_chapatti/phulka` — **not** `fixed_daily_item`, which only makes the dish consistent, see CLAUDE.md note 20) + `dxc_plain_chapati_repeatable` so the 2-item staple survives the cooldown into week 2 |
| Curd side: raita Mon/Tue/Thu/Fri, plain curd Wednesday | DONE | `dxc_raita_except_wed_curd` (`slot_composition.components_by_weekday`) + base `curd_raita_logic` **disabled** (it forces raita on every biryani/pulao day, which collides with the fixed Wednesday curd) |
| Common categories (bread, rice, sambar, rasam, curd, sweet) identical across both counters each day | DONE | `shared_categories` in `client_rules.json` — the planner pins the primary counter's dish for each shared slot into the Non Veg counter per day (Gap 1, per-day dish sync) |

The theme filter is **not** exempted for `rice`: biryani is already placeable on
DXC's north/mix days, so `min: 3` is satisfiable once the weekly cap above is
lifted. Verified end-to-end in `tests/test_dxc_client_logic.py` (both counters,
each logic, plus a week-1-save → week-2-replan proving the bread staple holds).

### Eli Lilly
No `client_rules.json` entry.

| Requirement | Status | Mechanism |
|---|---|---|
| Biryani day: salad, flavoured rice, non-veg biryani, raita, "salan" in veg gravy, dessert — nothing else | BLOCKED | Gap 2 (suppress the other slots) + literal text in `veg_gravy` |
| North days: flavoured rice + gravy; no sambar, white rice, rasam | BLOCKED | Gap 2 |
| South days: sambar + rasam; no dal, no flavoured rice | BLOCKED | Gap 2 |
| 3 days plain chapati, 1 day flavoured | TODO | Two `selector_frequency` rules |

### F5
| Requirement | Status | Mechanism |
|---|---|---|
| Daily one non-veg main is egg curry/dry, the other chicken | DONE | `nonveg_main_daily_pair` (per-client override) |
| No chicken non-veg on Monday and Friday — blank | DONE | `f5_nonveg_tue_wed_thu` |
| Biryani day: give boiled egg for the egg slot | DONE | `constant_items.nonveg_main` Wednesday |
| Weekly 2 paratha and rice-based breads, plain phulka other days | TODO | Bread frequency rules |

### H&M
| Requirement | Status | Mechanism |
|---|---|---|
| Paneer once a week | DONE | `hm_paneer_exact_1` |
| Welcome drink only buttermilk | DONE | `constant_items.welcome_drink` |
| Salad green salad daily | DONE | `constant_items.salad` |
| Indian bread plain chapathi daily | DONE | `constant_items.bread` |
| Biryani on Wednesday | TODO | Verify `theme_map` |
| Flavoured rice to be north indian | TODO | Cuisine restriction on `rice` |

### Icon
No `client_rules.json` entry.

| Requirement | Status | Mechanism |
|---|---|---|
| Biryani on Wednesday | TODO | Verify `theme_map` |
| Only varieties of chapati and paratha in indian bread | TODO | Bread sub-category restriction |
| Paneer once a week | TODO | `selector_frequency` exact 1 |
| No egg items | TODO | `ingredient_ban` / `selector_frequency` max 0 |
| One non-biryani day may get veg biryani in flavoured rice | TODO | Needs gap 2 to scope "non-biryani day" |
| Mushroom or kofta once in 10 days, never with paneer | BLOCKED | Gap 4 (both halves) |
| No breakfast items in lunch for flavoured rice / indian bread | DATA | Gap 8 — needs a breakfast flag |
| On biryani day append "+ boiled egg" to the non-veg row | TODO | An additive constant, not a replacing one |

### Ikea
| Requirement | Status | Mechanism |
|---|---|---|
| Paneer twice a week | DONE | `ikea_paneer_exact_2` |
| Salad is just green salad daily | DONE | `constant_items.salad` |
| White rice only Tuesday and Thursday | DONE | `ikea_white_rice_tue_thu` |
| Flavoured rice every Monday, Wednesday, Friday | DONE | `ikea_flavoured_rice_mwf` |
| No egg in non-veg | DONE | `ikea_no_egg_nonveg` |
| No non-veg biryani on biryani day — give non-veg curry instead | PARTIAL | `nonveg_main_daily_pair` is disabled, so nothing *mandates* a biryani, but nothing forbids one either. Needs a `selector_frequency` max 0 on `is_nonveg_biryani`. **This inverts the city default** — worth confirming against a real week. |
| Chicken curry 4 days, chicken dry 1 day | TODO | Two `selector_frequency` rules on the non-veg slot |

### Infenion
| Requirement | Status | Mechanism |
|---|---|---|
| Paneer served weekly once | DONE | `infenion_paneer_exact_1` |
| 2 chapati in indian bread — one north, one south | DONE | `infenion_north_south_bread` |
| Non-veg 3×/week: Mon chicken gravy, Wed egg, Fri biryani; other days blank | DONE | `infenion_nonveg_mon_wed_fri` (day restriction) + `infenion_nonveg_by_weekday` (`components_by_weekday`). **Verified against the sample** on two start dates. |
| Chicken curry or dry on Monday | DONE | Monday component, excluding `is_egg_dish` |
| Egg curry on Wednesday | DONE | Wednesday component |
| Chicken biryani on Friday | DONE | Friday component |

### Kongsberg
| Requirement | Status | Mechanism |
|---|---|---|
| Paneer once a week | DONE | `konsberg_paneer_exact_1` |
| Wednesday egg curry | BLOCKED | Gap 3 |
| Thursday chinese | TODO | Verify `theme_map` |
| Friday biryani | TODO | Verify `theme_map` |

### L&T
| Requirement | Status | Mechanism |
|---|---|---|
| Non-Veg Lunch counter: 5 items daily — biryani, non-veg gravy, non-veg dry, chicken kebab (common daily), egg | PARTIAL | `nonveg_main_five_dish` composes the five roles; the gravy and dry components exclude egg and the tandoor flags so each covers one role only. The kebab is a staple; the egg is fixed by `lt_egg_same_every_day` (`fixed_daily_item`) — **client confirmed it is a fixed dish daily, like the kebab**. Verified: one biryani, one chicken gravy, one chicken dry, one kebab and the same egg on every day, across three start dates. **Still requires the counter's `nonveg_main` frequency set to 5 in the editor** — the live row says 1. |
| Salad is green salad daily | TODO | `constant_items.salad`, as Amadeus has |
| Indian bread: chapati and phulka alternately in the south lunch counter | TODO | **Corrected by the sample**: the alternation is *within* the week (`Chapati / Phulka / Chapati / Phulka / Chapati`), not week-over-week, so it needs no new capability — a weekday pattern on `bread`. Previously filed under gap 5. |
| Non-veg counter: chapati and phulka alternately, raita daily | TODO | Same within-week alternation as above; the daily raita is a constant. Sample confirms `Raitha` on all five days of the non-veg counter. |
| Indian bread, dessert, curd/raita, salad, papad, white rice identical across counters for the day | BLOCKED | Gap 1 |

### Nike
No `client_rules.json` entry.

| Requirement | Status | Mechanism |
|---|---|---|
| Indian bread chapati/paratha only | TODO | Bread sub-category restriction |
| No liquid flavoured rice | TODO | `selector_frequency` max 0 |
| Paneer, mushroom or babycorn — any combination twice a week | TODO | `selector_frequency` on a combined selector |
| Common categories identical across counters | BLOCKED | Gap 1 |
| Biryani day: "salan" in white rice, no veg dry | BLOCKED | Gap 2 + literal text |
| Chinese day: veg gravy and chicken gravy are *not* chinese; only flavoured rice and veg dry are | TODO | Inverts the theme filter's slot set for this client |

### Piramel Finance
Entry exists but is empty.

| Requirement | Status | Mechanism |
|---|---|---|
| Works only Monday, Tuesday, Thursday | TODO | `clients.working_days` column — set the value, as Quince has |
| Indian bread chapati/paratha only | TODO | Bread sub-category restriction |
| Paneer once in 2 weeks | BLOCKED | Gap 4 |

### Plan View
| Requirement | Status | Mechanism |
|---|---|---|
| Add a boiled egg row daily | DONE | `constant_items.nonveg_main__2` |
| Buttermilk daily in welcome drink | DONE | `constant_items.welcome_drink` |
| Paneer once a week | DONE | `planview_paneer_exact_1` |
| Mushroom once a week | DONE | `planview_mushroom_exact_1` |
| Biryani day: chinese veg gravy and chinese flavoured rice | TODO | Needs gap 2 to scope by theme |
| Non-biryani days may get 1 veg biryani in flavoured rice | TODO | Needs gap 2 |

### Plum
| Requirement | Status | Mechanism |
|---|---|---|
| 3 pulao a week, 2 varieties of chapati | DONE | `plum_pulao_exact_3`, `plum_chapati_exact_2` |
| 1 day paneer | DONE | `plum_paneer_exact_1` |
| 1 day mushroom | DONE | `plum_mushroom_exact_1` |
| Non-veg **once** weekly, other days blank | DONE | Client corrected the tracker: one a week, not two. `plum_nonveg_fri_only`. Verified. |
| Every Friday chicken gravy or dry | DONE | `plum_nonveg_by_weekday` |

### Quince
| Requirement | Status | Mechanism |
|---|---|---|
| 3 working days (Wed, Thu, Fri), others blank | DONE | `clients.working_days` |
| Curd daily, raita on biryani day | DONE | `constant_items` curd/curd_side split |

### Siemens Healthineers
No `client_rules.json` entry.

| Requirement | Status | Mechanism |
|---|---|---|
| Indian bread chapati/paratha twice a week in the south counter too | TODO | Bread restriction, counter-scoped |
| New jain dal row, daily, in the north and south counters | BLOCKED | Gap 7 |

### Siemens Technology
| Requirement | Status | Mechanism |
|---|---|---|
| Weekly biryani cap does not apply to the non-veg counter | DONE | `nonveg_biryani_once_per_week` disabled on that counter |
| Mushroom must not be served | TODO | `ingredient_ban` |
| Paneer once a week | TODO | `selector_frequency` exact 1 |
| Chicken gravy 2×, chicken dry 1× | TODO | Two `selector_frequency` rules |
| Salad reads "salad" on every counter | TODO | `constant_items.salad` |
| Liquid-based sweet daily | TODO | `selector_frequency` on the dessert slot |
| 3 non-veg mains configured, only 2 served: chicken gravy + chicken dry | TODO | Composition with a cell left unfilled |
| Non-veg counter: 2 dal + 1 sambar; "salan" on biryani days | TODO | Composition + literal text |
| Non-veg counter: raita only on biryani days, blank otherwise | TODO | Needs gap 2 |
| Non-veg counter, biryani day: no white rice | BLOCKED | Gap 2 |
| Non-veg counter, Wednesday biryani day: 3 non-veg (biryani, gravy, egg); no indian bread or white rice | BLOCKED | Gap 2 + gap 3 |
| Non-veg counter, Friday biryani day: 2 non-veg (biryani, egg); no indian bread or white rice | BLOCKED | Gap 2 + gap 3 |
| Non-veg counter alternates weekly: chicken + mutton biryani one week, chicken biryani + fish the next | BLOCKED | Gap 5 (alternation) + gap 8 (no mutton or fish in the ontology) |

### Sinch
| Requirement | Status | Mechanism |
|---|---|---|
| 3 egg gravy per week | DONE | `sinch_egg_gravy_3x` |
| Curd daily, raita on biryani day | DONE | `constant_items` curd/curd_side split |
| 1 chicken gravy and 1 chicken biryani on biryani day | TODO | Composition on the biryani theme |

### Take 2
No `client_rules.json` entry.

| Requirement | Status | Mechanism |
|---|---|---|
| Curd daily except on biryani/pulao days, then raita | TODO | `constant_items` split, as Quince has |
| Pulao and kushka biryani regularly in flavoured rice | TODO | `selector_frequency` |
| 1 day paneer | TODO | `selector_frequency` exact 1 |
| 1 day mushroom | TODO | `selector_frequency` exact 1 |
| Chinese chicken dry/gravy once in 2 weeks | BLOCKED | Gap 4 |

### Telstra
| Requirement | Status | Mechanism |
|---|---|---|
| One day paneer | DONE | `telstra_paneer_exact_1` |
| 3 days curd, 2 days raita | DONE | `constant_items` curd/curd_side split |
| Non-veg dry weekly once | DONE | `telstra_nonveg_dry_1x` |
| Mushroom once in 10 days | BLOCKED | Gap 4 |

### Tessolve
| Requirement | Status | Mechanism |
|---|---|---|
| Welcome drink only buttermilk | DONE | `constant_items.welcome_drink` |
| Green salad twice weekly | DONE | `tessolve_green_salad_2x` |
| Non-veg only on Wednesday, other days blank | DONE | `tessolve_nonveg_wed_only` |
| Curd daily except biryani day, then raita | DONE | `constant_items` curd/curd_side split |
| Healthy rice is only red rice daily | TODO | `constant_items.healthy_rice` |
| Biryani day: one biryani, the other chicken dry | TODO | Composition on the biryani theme |

### Thales
| Requirement | Status | Mechanism |
|---|---|---|
| Paneer once a week | DONE | `thales_paneer_exact_1` |
| Chicken biryani on Friday | BLOCKED | Gap 3 |
| Wednesday chicken gravy | BLOCKED | Gap 3 |
| Other days: egg gravy 2×, egg fry 1× | TODO | Two `selector_frequency` rules |

### Toast Tab
| Requirement | Status | Mechanism |
|---|---|---|
| Weekly 1 paneer | DONE | `toasttab_paneer_exact_1` |
| Weekly 1 mushroom | DONE | `toasttab_mushroom_exact_1` |
| One type of buttermilk weekly once | PARTIAL | `buttermilk_twice_weekly` gives two days, not one |
| Non-veg dish should only be chicken | TODO | `selector_frequency` max 0 on egg |
| Only types of chapati and paratha | TODO | Bread sub-category restriction |
| Non-veg dry on the non-veg main | TODO | Composition |

*Also note:* the `curd_rice` station draws 4 distinct items from `common` against
a 5-day horizon, so one repeats. The remaining 9 curd-rice items in the ontology
are health variants owned by other clients; the resolution is a 5th `common`
item, which the diagnostic asks for.

### Vector
| Requirement | Status | Mechanism |
|---|---|---|
| Dessert only on Wednesday, no liquid | DONE | `vector_dessert_wed_only` + liquid rule disabled |
| Welcome drink only buttermilk | DONE | `constant_items.welcome_drink` |
| 2 days plain chapati, other days infused/flavoured | PARTIAL | `vector_plain_chapati_2x` covers the 2 days; the flavoured remainder is not enforced |
| Chinese or bisibelebath once in 10 days; flavoured rice blank otherwise | BLOCKED | Gap 4 |

### Waters
No `client_rules.json` entry.

| Requirement | Status | Mechanism |
|---|---|---|
| Indian bread chapati/paratha only | TODO | Bread sub-category restriction |
| Common categories identical across counters | BLOCKED | Gap 1 |

### Zscaler
| Requirement | Status | Mechanism |
|---|---|---|
| Starter may have chinese veg dry twice a week | DONE | `zscaler_chinese_veg_dry_starter` |
| Ban all aloo dishes | DONE | `zscaler_no_potato` + two city rules disabled |
| Biryani twice a week (Tue, Thu) | PARTIAL | `zscaler_biryani_pulao_rice_2x` sets the count, not the weekdays — gap 3 |
| Paneer twice a week: once dry, once gravy | PARTIAL | `zscaler_paneer_gravy_1` works; `zscaler_paneer_fry_1` is inert because `is_paneer_fry` matches 0 rows — gap 8 |
| Mushroom and babycorn weekly once, but not on biryani day | PARTIAL | `zscaler_mushroom_exact_1` / `zscaler_babycorn_exact_1` set the counts; the biryani-day exclusion needs gap 2 |

---

## Open questions

Things that need an answer from operations before they can be built correctly.
Each one changes the implementation, not just the wording.

Three of these block a specific client outright and are listed first; the rest
would change what gets built but have a workable default.

| # | Question | Why it blocks | Default if unanswered |
|---|---|---|---|
| 1 | **Waters — how should four combos be modelled?** Its sample is four counters (Roti Veg, Roti Non Veg, Rice Veg, Non Veg Rice) where dal, salad, both starters and the sweet are the **same dish across all four**; only the carb and the veg/non-veg split differ. Is this one menu presented four ways, or four counters that must agree? | Gap 1, and the largest architectural decision left. The answer decides whether cross-counter sharing is a **post-pass** (solve the shared slots once, pin them into each counter) or a **joint solve**. Counters are solved independently today, so Waters cannot be served at all until this is settled. | **None — this one genuinely stalls.** Waters stays unconfigured rather than being built on a guess that has to be thrown away. |
| 2 | **Eli Lilly — which weekdays are north and which are south?** Its rules differ by region (north: no sambar/rasam/white rice; south: no dal/flavoured rice) but nothing states the mapping. | Without it the day restrictions are keyed to the wrong weekdays — the same failure ToastTab CHN would have had if its theme map were guessed wrong. | The sample shows rasam present Mon/Wed and `-` on Tue/Thu, so **Tue/Thu are north**, Mon/Wed/Fri south. Needs confirming. |
| 3 | **Icon — "on biryani day add '+ boiled egg'"**: append to the biryani dish's text, or a separate row? | Text append is a formatting change; a separate row is a slot. Different implementations. | A **separate row**, matching how Plan View pins its egg (`nonveg_main__2`), since that is already a supported shape. |
| 4 | **Booking.com's "Tuesday(Punjabi)"** — a real theme, or just "north Indian on Tuesday"? | Gap 11. A new theme is a vocabulary change; a weekday cuisine rule is config. | Weekday cuisine rule, no new theme. |
| 5 | **Tekion bread:** the rule says "only infused or flavoured chapthi", but the sample's first Monday serves Plain Chapati. Which holds? | Determines whether plain chapati is banned or merely uncommon. | Rule holds; the sample row is treated as a deviation. |
| 6 | **Siemens Healthineers Jain Dal** — served 4 of 5 days in the sample, stated "daily". Is Thursday intentionally blank? | Decides whether the rule is "daily" or "4 days". | Daily, per the requirement. |
| 7 | **Tessolve's Tue/Thu health counter** (salad + soup + bread + cut fruit + grain + boiled egg + steamed paneer + steamed chicken) — should the tool generate this, or is it fixed? | It is a different offering from a non-veg main; modelling it needs new slots. | Out of scope; not generated. |

### Already answered — recorded so they are not re-asked

| Question | Answer |
|---|---|
| AstraZeneca curd vs raita | **Curd daily.** Implemented. |
| AstraZeneca bread | **Plain chapati daily.** Implemented. |
| Cloudera healthy rice | **Curd rice daily** — rulebook wins over the sample. Implemented. |
| L&T non-veg counter shape | 5 dishes: biryani, gravy, dry, kebab (daily staple), egg. Implemented; needs the counter's frequency set to 5 in the editor. |
| Siemens Technology two biryani days | Weekly cap dropped for that counter. Implemented. |
| Live counter / branded popup | Out of scope. |
| Breakfast and dinner | **Out of scope — lunch only.** A period-qualified rule is read as its lunch part. |
| Is `Sheet6` Booking.com? | **Yes.** Its four stated requirements are all confirmed by that sheet. |
| L&T's egg | **A fixed dish daily, like the kebab.** Implemented as `fixed_daily_item`. |
| Plum's non-veg days | **One a week**, on Friday. `plum_nonveg_fri_only` + the Friday chicken component. Verified: non-veg on Friday only. |
| Tekion's Friday | **Friday is its biryani day**, set in the live client config (`fri: biryani`, confirmed by the new DB snapshot). Non-veg gravy Mon/Wed, biryani Fri. Verified against both sample weeks. |

---

## Recurring patterns worth factoring

Several requirements repeat across many clients and are better solved once in the
city baseline than per client:

- **Paneer exactly once a week** — 14 clients state it, each with its own
  near-identical rule. A city-level default with per-client overrides for the
  twice-a-week cases (Ikea, Cloudera, Zscaler) would remove a dozen rules.
- **Bread restricted to chapati/paratha varieties** — 7 clients (Icon, Nike,
  Piramel, Toast Tab, Waters, Cigna, Siemens Healthineers). One reusable rule
  keyed to a bread sub-category set.
- **Curd daily / raita on biryani day** — 7 clients express this with hand-written
  weekday maps in `constant_items`. The city `curd_side` rule already encodes
  "biryani or pulao → raita, else curd"; these clients are mostly re-stating it.
- **Green salad daily** — 5 clients, all via `constant_items.salad`.
