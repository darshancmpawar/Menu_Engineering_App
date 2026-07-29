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

**Source:** `menu_samples.xlsx` (committed alongside) — one printed week per client for 14 clients
(Infenion, Continental, Ikea, AstraZeneca, H&M, Cloudera, Thales, Icon,
Computacenter, Zscaler, Plan View, Kongsberg, Vector, Quince).

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

### What the samples contradict — needs a decision

| Client | Written requirement | What the sample serves | Currently configured |
|---|---|---|---|
| AstraZeneca | "daily just raita" | **Curd**, all five days | `constant_items.curd_side = 'raita'` |
| AstraZeneca | "plain chapati twice a week, phulka once, Tue phulka + ragi mudde, other days flavoured, no south bread" | **Plain Chapati daily** (Fri adds Poori) | nothing |
| Cloudera | "curd rice daily in healthy rice" | Curd Rice Tue–Thu, **Red Rice on Monday** | `constant_items.healthy_rice = 'curd rice'` (forces it daily) |

The AstraZeneca curd/raita conflict matters because the config actively forces
the opposite of what was served. Resolve before promoting either row.

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

## Capability gaps

Requirements that cannot be expressed with today's rule types. Ordered by how
many clients need them.

### 1. Shared items across counters
*L&T, Nike, Waters, Amadeus, Siemens Technology*

> "categories such as indian bread, dessert, curd/raita, salad, papad and white
> rice are all same items for the day across counters" — L&T

Counters are solved **independently** today: the planner calls `/plan` once per
counter with a `counter_index`, and each solve knows nothing about its siblings.
Making a category resolve to the same dish across counters needs either a joint
solve or a second pass that fixes the shared slots first and pins them into each
counter. This is the one genuinely architectural item in the list.

### 2. Slot suppression driven by the day's theme
*Eli Lilly, Nike, Siemens Technology*

> "on biryani day we serve salad, flavored rice, non veg main (biryani), raita,
> in veg gravy write 'salan', dessert and no other item that day" — Eli Lilly

`slot_day_restriction` keys on **weekday**, so "no white rice on the biryani day"
is not expressible when the biryani day is set by the theme map rather than
hard-coded to a weekday. Needs the restriction to accept day *types*.

### 3. Composition keyed to the weekday — **BUILT**
*Infenion (wired), Thales, Kongsberg, Cloudera, Plum, Sinch (not yet wired)*

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

Infenion is wired and reproduces its sample menu exactly — chicken gravy Monday,
blank Tuesday, egg Wednesday, blank Thursday, chicken biryani Friday — on both an
even and an odd ISO week. The other five clients need the same treatment; their
weekday patterns are in the per-client tables below.

### 4. Frequency windows longer than the horizon, and co-occurrence
*Icon, Telstra, Take 2, Vector, Piramel Finance*

> "mushroom or kofta should come once in 10 days, but not with paneer" — Icon

Two separate needs. A **multi-week window** ("once in 10 days", "2 weeks once")
spans more than one plan, so it has to be evaluated against history rather than
within the horizon — `item_cooldown` does this per item, but not per category with
a target count. And **co-occurrence exclusion** ("not with paneer") is a
mutual-exclusion between two selectors on the same day, which no rule type
expresses.

### 5. Weekly alternation between two dishes
*L&T, Siemens Technology*

> "alternates between chicken biryani, mutton biryani one week and other week we
> give chicken biryani and fish item on biryani day" — Siemens Technology

The parity mechanism already exists — `chinese_continental` resolves per ISO week
in `weekday_type_for_config` — but only for *themes*, not for item choices. The
same trick applied to a composition component would cover both clients.
Siemens Technology additionally needs data (see gap 8).

### 6. Day-set-restricted frequency
*Continental*

> "Ragi Mudde will be served once a week, either on Tuesday or Thursday" — Continental

`selector_frequency` can ask for one day out of the horizon, and
`allowed_day_types` can restrict by theme, but neither restricts to a *set of
named weekdays*. A small addition to the existing rule type.

### 7. A new category row
*Siemens Healthineers*

> "add new row in north indian and south indian counter as jain dal and will get
> jain dal daily in it" — Siemens Healthineers

Needs a `jain_dal` base slot in `src/constants.py` plus the ontology rows to fill
it. Mechanically small; it is listed here because it is a schema change, not a
config one.

### 8. Ontology data
*Siemens Technology, Icon, Zscaler*

| Missing | Needed by | Detail |
|---|---|---|
| Mutton, fish | Siemens Technology | `primary_protein` has only `chicken` (270 rows) and `egg` (68) for non-veg. No mutton, fish or prawn exists anywhere in the 4,321-row ontology, so those dishes cannot be selected. A pin naming one prints as text; add the rows and the same pin starts going through the solver with no config change. |
| Breakfast-item flag | Icon | "no breakfast item in lunch for flavoured rice / Indian bread" needs a flag marking which dishes are breakfast items. |
| `is_paneer_fry` | Zscaler | The flag exists as a column but matches 0 rows, so `zscaler_paneer_fry_1` is inert. Populate it or change the selector. |
| Kebab flag | L&T | No kebab flag exists; the 5-dish station's kebab component matches on `is_tandoor` / `is_tandoor_nonveg_dry` instead. Works, but it is a proxy. |

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
| Non-Veg Lunch counter: 5 items daily — biryani, non-veg gravy, non-veg dry, chicken kebab (common daily), egg | DONE | `nonveg_main_five_dish` + the kebab as a staple. **Requires the counter's `nonveg_main` frequency set to 5 in the editor** — the live row still says 1. |
| Salad is green salad daily | TODO | `constant_items.salad`, as Amadeus has |
| Indian bread: chapati and phulka alternately in the south lunch counter | BLOCKED | Gap 5 |
| Non-veg counter: chapati and phulka alternately, raita daily | BLOCKED | Gap 5 for the bread; the daily raita is a constant |
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
| Non-veg twice weekly only, other days blank | TODO | `slot_day_restriction` + a 2×/week cap |
| Every Friday chicken gravy or dry | BLOCKED | Gap 3 |

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
