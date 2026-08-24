# Client rules index

Every per-client rule the planner loads, one section per client.

**GENERATED — do not edit.** Run `python scripts/dump_client_rules_index.py`
after changing anything under `data/configs/clients/` and commit the diff;
`tests/platform/test_client_rules_index.py` fails if this file is stale.

## How to read a row

* **Rule** — the rule's `name`. A name that also exists in the city ruleset is an
  *override*: the client's keys are merged over the city rule's, so a rule listed
  here under a city rule's name changes that rule for this client only.
* **What it does** — the constraint, in one line. `≤ N days` / `≥ N days` /
  `exactly N days` count DAYS across the horizon, not dishes, so "≤ 1 day" for a
  two-dish station still allows two of that family on the one day it lands
  (`daily max` is the per-day cap).
* **Client's words** — the requirement as the client stated it, where the config
  records it. Absent means the rule was derived rather than quoted.

Rules that are *not* here are not unconfigured: most requirements are enforced by
the city ruleset (`data/configs/city_rules/<city>.json`), which every client in
that city inherits. See `docs/client_logics.md` (Bangalore),
`docs/pune_client_logic.md`, `docs/chennai_client_logic.md` and
`docs/ncr_client_logic.md` for the per-city reasoning, and `docs/pune_rulebook.md`
for the 70-rule Pune source.

**47 clients have per-client rules.**

## Airtel Noida

NCR site 'Airtel Plot 5'. Lunch-relevant logics encoded below. Deferred (need more input / outside lunch scope): 'fish once a month' and 'paratha/rumali roti once a month' are long-horizon cadences a weekly plan can't express; 'no dish repeated in 15 days' is already covered by item_cooldown_days=20 (stricter); 'every Wednesday regional theme menu' needs the specific regional cuisine named (Wednesday is currently theme=mix).

| Rule | What it does | Client's words |
|---|---|---|
| `airtel_paneer_2x` | primary_protein paneer: exactly 2 day(s) | Paneer to be served twice a week. |
| `airtel_nonveg_wed_fri` | nonveg_main runs only on wed, fri (blank otherwise) | Non-veg dish twice a week, on Wednesday and Friday only. |
| `airtel_potato_max_2` | key_ingredient potato: ≤ 2 day(s) | Potato dish not to be served more than twice a week. |

## Amadeus

**Pinned items:** `salad` — green salad; `bread` — plain chapati

### Amadeus → Chinese

This is a dedicated Chinese/Continental station: every weekday is themed chinese_continental, so on an odd ISO week the theme filter narrows rice to continental rice on all five days. The city-wide 'continental rice at most once a week' cap is meant for a mixed counter that sees continental once, and contradicts a station whose whole purpose is continental — it made this counter INFEASIBLE on every odd week. Scoped off here only; Amadeus's South and North counters still obey it.

**City rules switched off:** `continental_rice_weekly`

## Amadeus Pune

Amadeus Pune — from the client's sample week (docs/pune_client_logic.md). Seven service days: Mon-Fri full, Saturday drops the veg dry, Sunday is flavoured rice (a veg biryani) with raita, papad, buttermilk and a sweet and nothing else. The raita comes from the Curd / Raita category the client configured, restricted to Sunday — the day the biryani wants it.

| Rule | What it does | Client's words |
|---|---|---|
| `amadeus_pune_flavour_rice_tue_sun` | rice runs only on tue, sun (blank otherwise) | flavour rice on Tue and sun' — the flavoured-rice slot runs on those two days only |
| `amadeus_pune_white_rice_off_on_flavour_rice_days` | white_rice runs only on mon, wed, thu, fri, sat (blank otherwise) | white rice daily', but the sample week's single rice row shows ONE rice per day: Tue is Coriander rice and Sun is Veg biryani, with steamed rice on the other five |
| `amadeus_pune_veg_dry_weekdays_only` | veg_dry runs only on mon, tue, wed, thu, fri (blank otherwise) | sat no veg dry it should be blank' — and Sunday serves no veg dry either. |
| `amadeus_pune_veg_gravy_mon_sat` | veg_gravy runs only on mon, tue, wed, thu, fri, sat (blank otherwise) | Sunday serves no veg gravy. |
| `amadeus_pune_dal_mon_sat` | dal runs only on mon, tue, wed, thu, fri, sat (blank otherwise) | Sunday serves no dal. |
| `amadeus_pune_bread_mon_sat` | bread runs only on mon, tue, wed, thu, fri, sat (blank otherwise) | Sunday serves no bread. |
| `amadeus_pune_salad_mon_sat` | salad runs only on mon, tue, wed, thu, fri, sat (blank otherwise) | The sample's Sunday salad column is the raita, not a salad, so the salad slot stops at Saturday and `curd_side` covers Sunday. |
| `amadeus_pune_curd_side_sunday_only` | curd_side runs only on sun (blank otherwise) | Curd / Raita runs on Sunday only — the biryani day, which is the classic pairing and the only day the sample shows it |
| `amadeus_pune_sunday_curd_side_is_a_raita` | is_raita @ curd_side: ≥ 1 day(s) | And it is a RAITA, which the sample's Sunday column says and nothing until now enforced |
| `amadeus_pune_chapati_daily` | bread must include (when the counter serves ≥1 of it): item chapati | chapati daily in indain bread' — a per-day MANDATE, not merely permission to repeat |
| `amadeus_pune_buttermilk_is_a_staple` | is_buttermilk @ welcome_drink: may repeat on any day | Buttermilk runs every day, so it must be exempt from unique_items and from the 20-day cooldown |
| `amadeus_pune_buttermilk_daily` | welcome_drink must include (when the counter serves ≥1 of it): is_buttermilk | welcome drink will have butter milk daily' — the client's answer to the Pune rulebook's R59: the welcome drink IS the buttermilk, not an extra accompaniment |
| `amadeus_pune_paneer_weekly` | key_ingredient paneer: exactly 1 day(s) | weekly 1 panner' — exactly one paneer dish a week, counted across every slot (the Pune list has 13 paneer gravies and one paneer-based veg dry). |
| `amadeus_pune_soya_veg_dry_weekly` | key_ingredient soy @ veg_dry: exactly 1 day(s) | weekly 1 soya' — the sample's soya is a veg DRY (Monday's Soya Chatpata Dry), and all three of Pune's is_premium_veg_dry items are the soya dries, so this is also what makes the city ruleset's pre… |
| `amadeus_pune_soya_total_weekly` | key_ingredient soy: ≤ 1 day(s) | …and no SECOND soya dish anywhere else that week (the Pune list has one soya gravy, soya_masala) |
| `amadeus_pune_sunday_veg_biryani` | rice must include (when the counter serves ≥1 of it): on sun: is_mixedveg_biryani | in sun we server only flvour rice(any veg biryani)' — Sunday's rice must be a veg biryani, and 'any' is why this is a composition over the biryani flag rather than a pinned dish: the solver picks … |

## Astrazeneca

| Rule | What it does | Client's words |
|---|---|---|
| `astra_paneer_exact_1` | shelf component `paneer_once_a_week` |  |

**City rules switched off:** `curd_raita_logic`

**Pinned items:** `curd_side` — Curd; `bread` — plain chapati

## AT&T

Bangalore site, one counter (themes Mon/Tue/Fri = mix, Wed = biryani, Thu = north). Deliberately NOT configured as a rule: 'daily curd except on biryani day it is raita' is already what `curd_raita_logic` (the city ruleset's curd_side rule) does — biryani/pulao days get a raita, every other day a plain curd — so restating it here would be a second copy of the same logic that can drift.

| Rule | What it does | Client's words |
|---|---|---|
| `att_bread_chapati_only` | shelf component `bread_chapati_only` |  |
| `att_paneer_1x` | shelf component `paneer_once_a_week` |  |
| `att_pulao_3x` | shelf component `pulao_three_days_a_week` |  |
| `att_soya_or_kofta_1x` | key_ingredient soy or is_veg_kofta_gravy: ≥ 1 day(s), ≤ 1 day(s) | soya or kofta once a week' — one rule, not two, because the client offered them as alternatives |

## Ather

| Rule | What it does | Client's words |
|---|---|---|
| `ather_paneer_exact_1` | shelf component `paneer_once_a_week` |  |
| `ather_dessert_thu_only` | dessert runs only on thu (blank otherwise) |  |

**City rules switched off:** `liquid_desserts_twice_nonconsecutive`

**Pinned items:** `salad` — mixed veg salad; `bread` — plain chapati

## Bakertilly

Bangalore site, one counter, TWO non-veg dishes (themes Mon/Thu = mix, Tue = south, Wed = biryani, Fri = north). The non-veg station runs on the BIRYANI DAY ONLY and serves chicken dry there — the client's clarification, which replaces the earlier reading that it ran daily with a dry added on Wednesday. Its biryani-day list ('indian bread, rasam, veg curry, flavoured rice, white rice and salad — other will be blank') and its curd rule ('daily curd except of biryani day it is raita') disagree about the curd on a Wednesday; the client called that an outlier, so `curd_side` is KEPT there as a raita and nothing else is inferred from the conflict. 'Daily curd except on the biryani day it is raita' is the city ruleset's `curd_raita_logic` and is not restated here.

| Rule | What it does | Client's words |
|---|---|---|
| `bakertilly_paneer_1x` | shelf component `paneer_once_a_week` |  |
| `bakertilly_no_veg_dry_on_biryani_day` | veg_dry runs only on mon, tue, thu, fri (blank otherwise) | On biryani day we will only serve indian bread, rasam, veg curry, flavoured rice, white rice and salad — other will be blank. |
| `bakertilly_no_dal_on_biryani_day` | dal runs only on mon, tue, thu, fri (blank otherwise) |  |
| `bakertilly_no_sambar_on_biryani_day` | sambar runs only on mon, tue, thu, fri (blank otherwise) |  |
| `bakertilly_no_dessert_on_biryani_day` | dessert runs only on mon, tue, thu, fri (blank otherwise) |  |
| `bakertilly_nonveg_biryani_day_only` | nonveg_main runs only on wed (blank otherwise) | Non veg main 2 is given only on biryani day and it will be chicken dry. Other days blank. |
| `bakertilly_two_chicken_dry_on_the_biryani_day` | nonveg_main must include (when the counter serves ≥2 of it): on a biryani day: 2× is_nonveg_dry or is_tandoor_nonveg_dry | …'and it will be chicken dry |

**City rules switched off:** `nonveg_main_daily_pair`

## Booking.com

Already covered elsewhere, so deliberately NOT duplicated here: 'indian bread chapati daily' is the `bread` constant pin below; 'raita on the biryani day, plain curd otherwise' is the curd/curd_side pins below; 'live is starter items' is how the menu import files the Live row. Tuesday-continental needs the counter's theme_map changed (a DB value), not a rule.

| Rule | What it does | Client's words |
|---|---|---|
| `booking_pulao_exact_3` | shelf component `pulao_three_days_a_week` |  |
| `booking_plain_chapati_is_a_staple` | shelf component `plain_chapati_is_a_staple` |  |
| `booking_paneer_1x` | shelf component `paneer_once_a_week` |  |
| `booking_curd_rice_1x` | shelf component `curd_rice_once_a_week` |  |
| `booking_chicken_only` | shelf component `nonveg_chicken_only` |  |
| `booking_nonveg_dry_1x` | shelf component `nonveg_dry_once_a_week` |  |
| `booking_ragi_buttermilk_1x` | named ragi @ welcome_drink: exactly 1 day(s) | Ragi buttermilk once a week in the welcome drink. |
| `booking_ice_cream_1x` | named ice_cream/icecream @ dessert: exactly 1 day(s) | A scoop of ice cream once a week in the dessert slot |

**City rules switched off:** `mixedveg_pulao_biryani_weekly`

**Pinned items:** `bread` — plain chapati; `starter__2` — veg kathi roll; `curd` — monday=Curd, tuesday=Curd, thursday=Curd, friday=Curd; `curd_side` — wednesday=raita

## Cigna

| Rule | What it does | Client's words |
|---|---|---|
| `nonveg_main_daily_pair` | nonveg_main must include (when the counter serves ≥2 of it): primary_protein chicken + is_egg_dish |  |

## Citrix

Bangalore site, one counter, one dish per slot (themes Mon-Thu = mix, Fri = biryani). The client stated the non-veg schedule for Mon, Tue, Wed and Fri and said nothing about THURSDAY, so Thursday's non-veg dish is left to the solver — except that `citrix_biryani_only_on_biryani_day` stops it taking the week's one chicken biryani, which would then be unavailable on Friday where the client asked for it. `buttermilk_twice_weekly` is disabled because it says the opposite of what this client asked: the city rule puts buttermilk on EXACTLY two non-consecutive welcome-drink days, and Citrix's welcome drink is buttermilk every day — the two together are unsatisfiable and the counter came back INFEASIBLE with the pre-flight reporting a clean bill of health, since neither rule is wrong on its own.

| Rule | What it does | Client's words |
|---|---|---|
| `citrix_bread_chapati_only` | shelf component `bread_chapati_only` |  |
| `citrix_plain_chapati_is_a_staple` | shelf component `plain_chapati_is_a_staple` |  |
| `citrix_welcome_drink_is_buttermilk` | welcome_drink must include (when the counter serves ≥1 and ≤1 of it): is_buttermilk | Welcome drink will be buttermilk only. |
| `citrix_buttermilk_may_recur_across_weeks` | is_buttermilk @ welcome_drink: may recur across plans, but stays distinct within one | 10 distinct buttermilks cannot fill a daily slot across a 20-day no-repeat window, so the history ban has to stand down — but `scope: cooldown` keeps `unique_items`, so the week still serves five d… |
| `citrix_veg_gravy_and_veg_dry_same_region` | prefer (medium): veg_gravy and veg_dry should agree on cuisine_family (north_indian/south_indian) | If veg gravy is north then veg dry should be north. |
| `citrix_rice_and_veg_gravy_same_region` | prefer (medium): rice and veg_gravy should agree on cuisine_family (north_indian/south_indian) | Flavour rice and veg gravy should be of the same region. |
| `citrix_nonveg_by_weekday` | nonveg_main must include (when the counter serves ≥1 of it): on mon: is_north_chicken_gravy or is_south_chicken_gravy (not is_egg_dish); on wed: is_north_chicken_gravy or is_south_chicken_gravy (not is_egg_dish); on tue: is_egg_dish; on fri: is_nonveg_biryani | Nonveg main: Mon & Wed Chicken gravy, Tue - Egg curry, Friday Biryani. |
| `citrix_nonveg_mon_tue_wed_fri` | nonveg_main runs only on mon, tue, wed, fri (blank otherwise) | Nonveg main: Mon & Wed chicken gravy, Tue egg curry, Friday biryani' names four days out of five, and the client confirmed the fifth is deliberate: THURSDAY IS BLANK |
| `citrix_biryani_only_on_biryani_day` | is_nonveg_biryani @ nonveg_main: ≤ 1 day(s), only on biryani days; only on biryani days | Friday is this counter's biryani day and the client asked for the biryani there |
| `citrix_rice_north_not_two_days_running` | prefer (medium): avoid cuisine_family north_indian @ rice on adjacent days | The region should alternate from south and north, should not be the same on 2 continuous days for flavour rice, veg gravy and veg dry. |
| `citrix_rice_south_not_two_days_running` | prefer (medium): avoid cuisine_family south_indian @ rice on adjacent days |  |
| `citrix_veg_gravy_north_not_two_days_running` | prefer (medium): avoid cuisine_family north_indian @ veg_gravy on adjacent days |  |
| `citrix_veg_gravy_south_not_two_days_running` | prefer (medium): avoid cuisine_family south_indian @ veg_gravy on adjacent days |  |
| `citrix_veg_dry_north_not_two_days_running` | prefer (medium): avoid cuisine_family north_indian @ veg_dry on adjacent days |  |
| `citrix_veg_dry_south_not_two_days_running` | prefer (medium): avoid cuisine_family south_indian @ veg_dry on adjacent days |  |

**City rules switched off:** `buttermilk_twice_weekly`

## Clario

Bangalore site. NOT configured as rules because they are DB values, not logic: 'working Mon-Thu only' is clients.working_days, and 'biryani on Monday AND Wednesday' is the counter's theme_map (today Mon=mix, Wed=biryani). 'When non-veg is on it is usually just chapati' is left out until 'usually' is pinned down — a hard rule would forbid the flavoured bread the sample also shows. 'Chinese items restricted to the veg dry and flavoured rice' is the theme filter standing down on the other cuisine-main slots, NOT a frequency cap: the filter narrows veg_gravy/starter/nonveg_main TO chinese on that day, so a `max: 0` on chinese is forced past and the counter goes INFEASIBLE (CLAUDE.md note 9e).

| Rule | What it does | Client's words |
|---|---|---|
| `clario_nonveg_mon_wed` | shelf component `nonveg_on_weekdays`, with `allowed_weekdays` overridden |  |
| `clario_chapati_2x` | shelf component `plain_chapati_twice_a_week` |  |
| `clario_paneer_1x` | shelf component `paneer_once_a_week` |  |
| `clario_mushroom_1x` | shelf component `selector_once_a_week`, with `selector` overridden |  |
| `clario_baby_corn_1x` | shelf component `selector_once_a_week`, with `selector` overridden |  |
| `theme_cuisine_filter` | shelf component `indian_veg_dry_on_chinese_day`, with `indian_slots_by_theme`, `indian_veg_dry_themes` overridden |  |
| `clario_fresh_juice_2x` | named juice/crush @ welcome_drink: ≥ 2 day(s), ≤ 2 day(s) | Fresh fruit juice on two days a week (watermelon, guava, grape, mango, muskmelon…); other days take the remaining welcome-drink varieties. |
| `clario_fried_items_max_2` | is_fried or is_deep_fried_veg_dry or is_deep_fried_starter: ≥ 1 day(s), ≤ 2 day(s) | A fried item once or twice a week to keep the menu appealing; encoded as the upper half of the range. |

## Cloudera

| Rule | What it does | Client's words |
|---|---|---|
| `cloudera_paneer_exact_2` | shelf component `paneer_twice_a_week` |  |
| `cloudera_special_bread_1x` | is_dosa or is_paratha @ bread: ≥ 1 day(s), ≤ 1 day(s) |  |
| `cloudera_nonveg_by_weekday` | nonveg_main must include (when the counter serves ≥1 of it): on mon: is_egg_dish | Monday is egg gravy (sample: Kadai Egg Curry) |

**Pinned items:** `healthy_rice` — curd rice

## Computa Centre

| Rule | What it does | Client's words |
|---|---|---|
| `computa_plain_chapati_phulka_2x` | shelf component `plain_chapati_twice_a_week` |  |
| `computa_paneer_exact_1` | shelf component `paneer_once_a_week` |  |
| `computa_biryani_pulao_rice_3x` | is_nonveg_biryani or is_mixedveg_biryani or is_premium_biryani or is_pulao @ rice: ≥ 3 day(s) |  |
| `computa_chinese_veg_dry_weekly` | cuisine_family chinese @ veg_dry: ≤ 1 day(s) |  |
| `computa_no_mixed_veg` | never serve: mixed_veg, mixed veg |  |

**City rules switched off:** `mixedveg_pulao_biryani_weekly`, `mixed_veg_gravy_weekly`

**Pinned items:** `salad` — green salad

## Corning Chakan

Pune site, one counter, seven days a week (`serve_weekends` is true, which the soup/sweet schedule below depends on). Slots: soup, bread, rice, veg_dry, veg_gravy, dal, dessert, white_rice — one dish each. Five of the client's fourteen rules need no per-client entry because Pune's own ruleset already enforces them at least as tightly: 'kabuli chana gravy max once a week' is `kabuli_chana_gravy_weekly`, 'legume-based gravies max once a week' is `legume_gravy_weekly`, and 'mixed-veg, veg kurma and veg kofta max twice a week' is covered by `mixed_veg_gravy_weekly` + `veg_kurma_gravy_weekly` + `veg_kofta_gravy_weekly` (one day each) — the union cap below is added anyway because the client stated the combined number, and a city rule can be relaxed later without the client's requirement quietly going with it. 'Sweet and soup on alternate days' is not a rule: it is what the two day-restrictions below already produce (sweet Mon/Wed/Fri, soup Tue/Thu/Sat/Sun). 'Soya can be served as one of the vegetable options' is permission, not a constraint, so nothing enforces it — Pune carries soya veg dries and gravies and they are already eligible.

| Rule | What it does | Client's words |
|---|---|---|
| `corning_chakan_soup_tue_thu_sat_sun` | soup runs only on tue, thu, sat, sun (blank otherwise) | Soup should be served on Tuesday, Thursday, Saturday and Sunday. |
| `corning_chakan_dessert_mon_wed_fri` | dessert runs only on mon, wed, fri (blank otherwise) | Sweets should be served on Monday, Wednesday and Friday. |
| `corning_chakan_no_liquid_sweets` | is_liquid_dessert @ dessert: ≤ 0 day(s) | Liquid sweets should not be considered. |
| `corning_chakan_black_dal_weekly` | is_black_dal @ dal: ≤ 1 day(s) | All black dal preparations combined should be served maximum once a week. |
| `corning_chakan_sprouts_gravy_twice_weekly` | named sprout/matki @ veg_gravy: ≤ 2 day(s) | Sprouts gravy should be served maximum twice a week. |
| `corning_chakan_paneer_gravy_weekly` | is_paneer_gravy @ veg_gravy: exactly 1 day(s) | Paneer gravy should be included once a week across all meal sessions. |
| `corning_chakan_paneer_or_kofta_weekly` | key_ingredient paneer or is_veg_kofta_gravy: ≤ 1 day(s) | Paneer/kofta preparations should be served once a week across lunch and dinner. |
| `corning_chakan_mixedveg_kurma_kofta_twice_weekly` | is_mixedveg_gravy or is_kurma_gravy or is_veg_kofta_gravy @ veg_gravy: ≤ 2 day(s) | Mixed-veg, veg kurma and veg kofta gravies should be served maximum twice a week. |
| `leafy_veg_dry_weekly` | is_leafy_based_dish @ veg_dry: ≥ 2 day(s), ≤ 2 day(s) | Leafy-vegetable dry preparations should be served twice a week. |
| `corning_chakan_starter_thursday_only` | starter runs only on thu (blank otherwise) | On Thursday only we will give a starter. |
| `corning_chakan_starter_is_a_chaat` | starter must include (when the counter serves ≥1 and ≤1 of it): named chaat/chat | Starter should be chat item. |

**City rules switched off:** `leafy_veg_dry_15d_window`

## DXC

Bangalore launch site (created via the launch view). Uses the Bangalore regional ruleset + these DXC logics; the two counters (Veg Lunch, Non Veg Lunch) both carry bread/rice/curd_side so these are client-level. The 'common categories are identical across both counters' requirement is handled by shared_categories below: the planner solves the primary counter and pins its dish for each shared slot into the other counter per day (see docs/client_logics.md gap 1).

| Rule | What it does | Client's words |
|---|---|---|
| `dxc_flavoured_rice_biryani_3x` | is_mixedveg_biryani @ rice: ≥ 3 day(s) | Flavoured rice: biryani at least 3 days a week, even on non-biryani days (the client's 'flavour rice biryani 3x even if not biryani day'). |
| `dxc_flavoured_rice_pulao_1x` | is_pulao @ rice: ≥ 1 day(s) | Flavoured rice: pulao at least once a week. |
| `dxc_no_south_flavoured_rice` | cuisine_family south_indian @ rice: ≤ 0 day(s) | No South-cuisine flavoured rice (0 days). |
| `dxc_plain_chapati_daily` | bread must include (when the counter serves ≥1 of it): sub_category plain_chapatti/phulka | Indian bread is plain chapati every day |
| `dxc_plain_chapati_repeatable` | sub_category plain_chapatti/phulka @ bread: may repeat on any day | Plain chapati is a staple: only 2 such items exist, so daily service must repeat them |
| `dxc_raita_except_wed_curd` | curd_side must include (when the counter serves ≥1 of it): on mon: is_raita; on tue: is_raita; on thu: is_raita; on fri: is_raita; on wed: is_plain_curd | Curd side: raita Mon/Tue/Thu/Fri, plain curd on Wednesday |

**City rules switched off:** `mixedveg_pulao_biryani_weekly`, `curd_raita_logic`

## F5

| Rule | What it does | Client's words |
|---|---|---|
| `nonveg_main_daily_pair` | nonveg_main must include (when the counter serves ≥2 of it): is_egg_dish + primary_protein chicken |  |
| `f5_nonveg_tue_wed_thu` | nonveg_main runs only on tue, wed, thu (blank otherwise) |  |

**Pinned items:** `nonveg_main` — wednesday=boiled egg

## Gartner

Chennai, one counter. Four stated rules (data/raw/source_workbooks/chennai_client_structure.xlsx, 'Sheet1' rows 13-16) verified against the 10-15 Aug sample week on the 'Gartner' sheet. Three of the four are about which rice the day serves and are encoded as three complementary day restrictions rather than as frequency caps — the sample settles the weekdays 5/5, and a restriction says the same thing without leaving the solver a choice it would then have to be steered out of. Friday is the counter's chinese day, which is what 'chinese day' means in the client's rules.

| Rule | What it does | Client's words |
|---|---|---|
| `gartner_no_bread_on_the_chinese_day` | bread runs only on mon, tue, wed, thu (blank otherwise) | on chinese day we will not serve indian bread we will serve white rice and flavoured rice |
| `gartner_white_rice_wed_thu_and_the_chinese_day` | white_rice runs only on wed, thu, fri (blank otherwise) | white rice will be served weekly twice excluding chinese day' — Wednesday and Thursday in the sample — plus Friday, which the rule above puts it on and this one excludes from the count |
| `gartner_flavoured_rice_mon_tue_and_the_chinese_day` | rice runs only on mon, tue, fri (blank otherwise) | when there is white rice no flavour rice (except chinese day) |
| `gartner_fish_on_wednesday` | nonveg_main must include (when the counter serves ≥1 and ≤1 of it): on wed: is_fish_dish | fish dish to be served on wednesaday |

## H&M

| Rule | What it does | Client's words |
|---|---|---|
| `hm_paneer_exact_1` | shelf component `paneer_once_a_week` |  |

**City rules switched off:** `buttermilk_twice_weekly`, `welcome_drink_no_repeat_color`

**Pinned items:** `welcome_drink` — buttermilk; `salad` — green salad; `bread` — plain chapati

## ICON Chn

Chennai, four counters — 'Premium Lunch' (primary), 'Economy Lunch', 'Rice Combo', 'Roti Combo'. Eight stated rules (data/raw/source_workbooks/chennai_client_structure.xlsx, 'Sheet1' rows 24-31) against the 10-14 Aug sample on the 'icon chn' sheet. The client's `source_pools` already names all eight Chennai site tokens, which is what `chennai` joining FULL_POOL_CITIES makes uniform for every client in the city.

| Rule | What it does | Client's words |
|---|---|---|
| `theme_cuisine_filter` | theme filter does not narrow: dal, salad, soup, healthy_rice, rice, sambar, rasam, curd, curd_side, curd_rice, dessert, bread, veg_dry, nonveg_main | Overrides chennai.json's rule of the same name (merged by name, so this REPLACES its `exempt_slots`) by adding `nonveg_main` |
| `icon_chn_dal_is_a_kootu` | dal must include (when the counter serves ≥1 and ≤1 of it): sub_category kootu | in dal need to give only Kootu item |
| `icon_chn_bread_is_chapati_daily` | bread must include (when the counter serves ≥1 and ≤1 of it): is_plain_phulka_chapathi | Indian Bread will be chapathi only daily |

**City rules switched off:** `nonveg_biryani_weekly`

**Not synced with the shared categories:** `Rice Combo`

### ICON Chn → Economy Lunch

Same dal/veg-dry alternation as Premium, and one non-veg cell: 'we serve nonveg gravy 2 egg gravy on Monday and Wednesday and rest is chicken gravy'. With a single cell a per-weekday component decides the day outright.

| Rule | What it does | Client's words |
|---|---|---|
| `icon_chn_economy_dal_tue_thu` | dal runs only on tue, thu (blank otherwise) |  |
| `icon_chn_economy_veg_dry_mon_wed_fri` | veg_dry runs only on mon, wed, fri (blank otherwise) |  |
| `icon_chn_economy_nonveg_egg_mon_wed_else_chicken` | nonveg_main must include (when the counter serves ≥1 and ≤1 of it): on mon: is_egg_dish and is_nonveg_gravy; on wed: is_egg_dish and is_nonveg_gravy; on tue: is_north_chicken_gravy or is_south_chicken_gravy; on thu: is_north_chicken_gravy or is_south_chicken_gravy; on fri: is_north_chicken_gravy or is_south_chicken_gravy | The '2 egg' in the client's sentence is a portion count, not a dish count — the sample prints 'Egg Curry (2Egg)' in one cell — so this asks for an egg GRAVY, not two eggs |

### ICON Chn → Premium Lunch

'in Premium Lunch and Economy Lunch counter we have give dal and veg dry alternative days not both on same day'. The counter runs BOTH as mandatory daily slots, so 'alternate' can only be expressed by standing each down on the other's days. The sample settles which is which 5/5: its single 'Kootu or Poriyal' row is a poriyal on Monday, Wednesday and Friday and a kootu on Tuesday and Thursday.

| Rule | What it does | Client's words |
|---|---|---|
| `icon_chn_premium_nonveg_mon_wed_fri` | nonveg_main runs only on mon, wed, fri (blank otherwise) |  |
| `icon_chn_premium_dal_tue_thu` | dal runs only on tue, thu (blank otherwise) |  |
| `icon_chn_premium_veg_dry_mon_wed_fri` | veg_dry runs only on mon, wed, fri (blank otherwise) |  |

**Pinned items:** `nonveg_main__1` — Chicken Biryani; `nonveg_main__2` — Boiled Egg; `nonveg_main__3` — Bone Salna

### ICON Chn → Rice Combo

'rice combo counter will have veg gravy 3 times a week and veg dry twice a week on wed and Friday' and 'it has seprate menu usually south items and flavour rice is biryani (can be north) on Wednesday and on Friday can be a north flavour rice'. The counter is themed south every day, and `rice` is exempt from the theme filter in chennai.json — which is what leaves a north biryani and a north flavoured rice reachable on the two days the client names. Its non-veg pattern is NOT stated and comes from the sample, which serves Egg Masala on Monday, Wednesday and Friday and nothing on Tuesday or Thursday.

| Rule | What it does | Client's words |
|---|---|---|
| `icon_chn_rice_combo_veg_dry_wed_fri` | veg_dry runs only on wed, fri (blank otherwise) |  |
| `icon_chn_rice_combo_veg_gravy_mon_tue_thu` | veg_gravy runs only on mon, tue, thu (blank otherwise) | veg gravy 3 times a week' — the three days the veg dry does not run, so the counter always carries exactly one of the two. |
| `icon_chn_rice_combo_biryani_on_wednesday` | rice must include (when the counter serves ≥1 and ≤1 of it): on wed: is_biryani_item | Wednesday's flavoured rice is a biryani |
| `icon_chn_rice_combo_nonveg_mon_wed_fri` | nonveg_main runs only on mon, wed, fri (blank otherwise) | Sample-derived, not stated: the counter's egg gravy runs on Monday, Wednesday and Friday and the cell is blank on Tuesday and Thursday. |
| `icon_chn_rice_combo_nonveg_is_an_egg_gravy` | nonveg_main must include (when the counter serves ≥1 and ≤1 of it): is_egg_dish and is_nonveg_gravy |  |

### ICON Chn → Roti Combo

'same nonveg main is served in Economy Lunch counter and Roti Combo Counter' — the identical-dish half of that needs a planner change (see `_not_expressible` above), so what is configured is the same weekday structure, which the sample confirms cell for cell: Egg Curry (2Egg), Madars Chicken Gravy, Egg Curry (2Egg), Hyd Chicken Gravy, Pepper Chicken Gravy on both counters.

| Rule | What it does | Client's words |
|---|---|---|
| `icon_chn_roti_nonveg_egg_mon_wed_else_chicken` | nonveg_main must include (when the counter serves ≥1 and ≤1 of it): on mon: is_egg_dish and is_nonveg_gravy; on wed: is_egg_dish and is_nonveg_gravy; on tue: is_north_chicken_gravy or is_south_chicken_gravy; on thu: is_north_chicken_gravy or is_south_chicken_gravy; on fri: is_north_chicken_gravy or is_south_chicken_gravy |  |

## Ikea

| Rule | What it does | Client's words |
|---|---|---|
| `ikea_paneer_exact_2` | shelf component `paneer_twice_a_week` |  |
| `ikea_no_egg_nonveg` | never serve: egg |  |
| `ikea_flavoured_rice_mwf` | rice runs only on mon, wed, fri (blank otherwise) |  |
| `ikea_white_rice_tue_thu` | white_rice runs only on tue, thu (blank otherwise) |  |

**City rules switched off:** `nonveg_main_daily_pair`

**Pinned items:** `salad` — green salad

## Infenion

| Rule | What it does | Client's words |
|---|---|---|
| `infenion_paneer_exact_1` | shelf component `paneer_once_a_week` |  |
| `infenion_nonveg_mon_wed_fri` | shelf component `nonveg_on_weekdays` |  |
| `infenion_north_south_bread` | bread must include (when the counter serves ≥2 of it): cuisine_family north_indian + cuisine_family south_indian |  |
| `infenion_nonveg_by_weekday` | nonveg_main must include (when the counter serves ≥1 of it): on mon: is_north_chicken_gravy or is_south_chicken_gravy (not is_egg_dish); on tue: ; on wed: is_egg_dish; on thu: ; on fri: is_nonveg_biryani | Sample menu serves exactly: Mon Murgh Do Pyaza (chicken gravy), Tue blank, Wed Punjabi Egg Masala, Thu blank, Fri Mughlai Chicken Biryani |

## Junglee Games

NCR site 'Junglee'. Chicken 4 days + egg curry once fills the single nonveg_main across the week; paneer once. Deferred: 'one chaat item once a week' has no slot on this counter (no starter/salad category) — add a starter slot to serve it.

| Rule | What it does | Client's words |
|---|---|---|
| `junglee_egg_curry_1x` | shelf component `egg_dish_once_a_week` |  |
| `junglee_chicken_4x` | primary_protein chicken @ nonveg_main: ≥ 4 day(s) | Chicken dish to be served 4 days a week. |
| `junglee_paneer_1x` | primary_protein paneer: exactly 1 day(s) | Paneer to be served once a week. |

## Konsberg

| Rule | What it does | Client's words |
|---|---|---|
| `konsberg_paneer_exact_1` | shelf component `paneer_once_a_week` |  |
| `konsberg_nonveg_by_weekday` | nonveg_main must include (when the counter serves ≥1 of it): on mon: is_north_chicken_gravy or is_south_chicken_gravy (not is_egg_dish); on tue: is_north_chicken_gravy or is_south_chicken_gravy (not is_egg_dish); on wed: is_egg_dish; on fri: is_nonveg_biryani | Sample: Mon/Tue chicken gravy, Wed EGG PEPPER, Thu ghee-roast chicken on its chinese theme day, Fri Mughlai Chicken Biryani |

## L&T

### L&T → Non Veg Lunch

This counter is themed biryani on all five days, so the theme filter leaves nonveg biryani as the only option every day. The city rule 'nonveg_biryani_once_per_week' is a weekly-variety cap written for a mixed counter and contradicts that by construction. Confirmed with the client that biryani daily is intended, so the cap is dropped here — scoped to this counter, so L&T's South and North Lunch counters keep it if they ever gain a nonveg_main slot. This is also the 5-dish station: with nonveg_main set to 5, 'nonveg_main_five_dish' composes biryani + gravy + dry + kebab + egg each day.

| Rule | What it does | Client's words |
|---|---|---|
| `lt_egg_same_every_day` | is_egg_dish @ nonveg_main: the SAME dish every day | The printed menu serves the same EGG CURRY on all five days, alongside the same CHICKEN KABAB - both are fixtures on this station, not variety slots |

**City rules switched off:** `nonveg_biryani_once_per_week`

## Moengage

Bangalore site (its clients.city is NULL — see scripts/backfill_client_city.sql). Mutton once a month is wired as a CAP now that a client menu import brought `dhaba_style_mutton_curry` into Bangalore; it was inert while the city carried no mutton at all. Cap rather than target for the same reason as Stripe's: with one eligible dish, a positive cadence would force that dish monthly regardless of the rest of the plate.

| Rule | What it does | Client's words |
|---|---|---|
| `moengage_aloo_once_a_week` | shelf component `selector_weekly_max`, with `selector`, `max` overridden |  |
| `moengage_banned_ingredients` | never serve: pumpkin, brinjal, eggplant, yam, elephant_yam | Banned in the main course: pumpkin, brinjal, yam and bisi bele bath |
| `moengage_mutton_30d_window` | primary_protein mutton @ nonveg_main: once per 30 days, read from saved history | Mutton at most once a MONTH, enforced across plans from saved history (30-day window, the same shape as Pune's monthly oil-based bread) |
| `moengage_mutton_max_1` | primary_protein mutton @ nonveg_main: ≤ 1 day(s) | The within-plan half: the history window only reads saved plans, so a single long horizon could otherwise place mutton on two of its own days. |
| `moengage_no_bisibele_bath` | named bisibele/bisi_bele/bise_bele: ≤ 0 day(s) | Bisi bele bath by name — it is a dish, not an ingredient. |
| `moengage_egg_1_or_2_days` | is_egg_dish @ nonveg_main: ≥ 1 day(s), ≤ 2 day(s) | Week 1-2 egg non veg main is compulsory' — an egg dish in the non-veg slot on one or two days of the week, and compulsory, so it is a floor as well as a cap |

## Piramel Finance

_No rules — the city ruleset covers this client._

## Plan View

| Rule | What it does | Client's words |
|---|---|---|
| `planview_paneer_exact_1` | shelf component `paneer_once_a_week` |  |
| `planview_mushroom_exact_1` | shelf component `selector_once_a_week` |  |

**City rules switched off:** `buttermilk_twice_weekly`, `welcome_drink_no_repeat_color`

**Pinned items:** `welcome_drink` — buttermilk; `nonveg_main__2` — boiled egg

## Plum

| Rule | What it does | Client's words |
|---|---|---|
| `plum_pulao_exact_3` | shelf component `pulao_three_days_a_week` |  |
| `plum_chapati_exact_2` | shelf component `plain_chapati_twice_a_week` |  |
| `plum_paneer_exact_1` | shelf component `paneer_once_a_week` |  |
| `plum_mushroom_exact_1` | shelf component `selector_once_a_week` |  |
| `plum_nonveg_by_weekday` | nonveg_main must include (when the counter serves ≥1 of it): on fri: primary_protein chicken | Every Friday is a chicken gravy or dry |
| `plum_nonveg_fri_only` | nonveg_main runs only on fri (blank otherwise) | Client confirmed: ONE non-veg a week |

**Pinned items:** `bread` — plain chapati

## Quince

**City rules switched off:** `curd_raita_logic`

**Pinned items:** `curd` — wednesday=Curd, thursday=Curd; `curd_side` — friday=raita

## Siemens

NCR site 'Seimens' (city NCR, 2 nonveg_main slots). Logics from the client sheet + the 27-Jul / 03-Aug sample weeks. Deferred/outside lunch scope: tetrapack juice (snacks), and brown bread / cut fruit / boiled egg (breakfast) are not lunch slots this engine plans. Kofta 'once per 2 weeks' is capped to <=1/week here (a true fortnightly window needs saved history).

| Rule | What it does | Client's words |
|---|---|---|
| `siemens_nonveg_pair_by_weekday` | nonveg_main must include (when the counter serves ≥2 of it): 2× primary_protein chicken; on tue: primary_protein chicken + is_egg_dish | Two non-veg in the gravy part |
| `siemens_paneer_1x` | primary_protein paneer @ veg_gravy: exactly 1 day(s) | One paneer a week (in the veg gravy). |
| `siemens_soya_1x` | primary_protein soya or primary_protein soy @ veg_gravy: exactly 1 day(s) | One soya a week (soya chaap; primary_protein soya/soy in the veg gravy). |
| `siemens_kofta_max_1` | is_veg_kofta_gravy @ veg_gravy: ≤ 1 day(s) | Kofta at most once a WEEK within a plan (within-plan half of once-per-2-weeks). |
| `siemens_kofta_14d_window` | is_veg_kofta_gravy @ veg_gravy: once per 14 days, read from saved history | Kofta once every 2 WEEKS (14 days) across plans, from saved history: a kofta served in the last 14 days is held off until the window clears |

**City rules switched off:** `deep_fried_coupling`

**Pinned items:** `salad` — green salad; `bread` — chapati

## Siemens Technology

### Siemens Technology → Non Veg Lunch

Themed biryani on two weekdays (Wed + Fri) against the city cap of one biryani day per week. Before the composition rule applied to 3-slot counters this contradiction was hidden — the solver satisfied the cap by putting its one biryani day on a mix day and leaving both biryani days without one. Client confirmed two biryani days are intended, so the weekly cap is dropped for this counter only.

**City rules switched off:** `nonveg_biryani_once_per_week`

**Pinned items:** `nonveg_main__1` — wed=['Hyd Mutton Biryani', 'Fish Tikka Masala']

## Sinch

| Rule | What it does | Client's words |
|---|---|---|
| `sinch_egg_gravy_3x` | is_egg_dish @ nonveg_main: ≥ 3 day(s), ≤ 3 day(s) |  |
| `sinch_nonveg_by_weekday` | nonveg_main must include (when the counter serves ≥1 of it): on wed: is_nonveg_biryani | Wednesday is this counter's biryani day and carries the chicken biryani |
| `sinch_chicken_gravy_once` | is_north_chicken_gravy or is_south_chicken_gravy @ nonveg_main: ≥ 1 day(s), ≤ 1 day(s) (excluding is_egg_dish) | Exactly one chicken gravy in the week. |

**Pinned items:** `curd` — monday=Curd, tuesday=Curd, thursday=Curd, friday=Curd; `curd_side` — wednesday=raita

## Sinch NCR

NCR site 'Sinch' (city NCR). Logics from the client sheet + the two sample weeks. Bread is tawa roti daily (constant). Rice split: flavour rice Mon/Wed, white rice (the const 'white_rice' slot) Tue/Thu/Fri — so exactly one carb each day and never both. Raita (curd_side) Mon/Fri only; welcome drink Tue/Thu only; starter Wednesday only and chaats only (the last two rules are inert until a starter category, count 1, is added to this counter in the editor). The Tue/Wed/Thu drink in the sample 'Curd Prep' row is not a curd_side dish and is out of clean scope.

| Rule | What it does | Client's words |
|---|---|---|
| `sinchncr_nonveg_by_weekday` | nonveg_main must include (when the counter serves ≥1 of it): on mon: primary_protein chicken; on wed: primary_protein chicken; on fri: primary_protein chicken; on tue: is_egg_dish; on thu: is_egg_dish | Chicken three times a week (Mon/Wed/Fri); egg curry twice a week (Tue/Thu). |
| `sinchncr_paneer_1x` | primary_protein paneer @ veg_gravy: exactly 1 day(s) | Paneer once a week (in the veg gravy). |
| `sinchncr_flavour_rice_mon_wed` | rice runs only on mon, wed (blank otherwise) | Flavour rice only Mon and Wed. |
| `sinchncr_white_rice_tue_thu_fri` | white_rice runs only on tue, thu, fri (blank otherwise) | White rice only when there is no flavour rice: Tue/Thu/Fri |
| `sinchncr_raita_mon_fri` | curd_side runs only on mon, fri (blank otherwise) | Raita served only on Monday and Friday. |
| `sinchncr_welcome_drink_tue_thu` | welcome_drink runs only on tue, thu (blank otherwise) | Welcome drink only on Tuesday and Thursday. |
| `sinchncr_starter_wed_only` | starter runs only on wed (blank otherwise) | Starter is served only on Wednesday |
| `sinchncr_starter_chaats_only` | starter must include (when the counter serves ≥1 of it): on wed: sub_category chaat_/_tikki | The Wednesday starter must be a chaat (only chaats to be served) |

**Pinned items:** `bread` — tawa roti

## Stripe

Bangalore site, one counter, nonveg_main x2 (the menu's 'Non-Veg Semi Dry or Dry' + 'Non-Veg Curry or Main Course' pair). Fish is wired now that Stripe's own two sample weeks brought `fish_finger` and `tawa_fish_fry` into the Bangalore list. It is min=max=1 rather than a hard weekly guarantee: two dishes against the 20-day item cooldown support fish roughly every ten days, and `selector_frequency` caps `min` to what is actually placeable, so a week where both are cooled down relaxes instead of going INFEASIBLE. Both dishes needed `is_nonveg_dry` before the rule could be satisfied at all - `nonveg_main_daily_pair` spends both cells on one dry + one chicken gravy, so a dish with no form flag cannot be placed and forcing one made the counter INFEASIBLE (see scripts/nonveg_structural_flags.py). Mutton (2x/month) is now wired as a CAP, the tripwire test having fired: a later client menu import brought `dhaba_style_mutton_curry` into Bangalore, so the rule stopped being inert. It is a cap and not a target on purpose - the client's logic reads as a cost limit, and with exactly one mutton dish in the list a positive cadence would force that same dish twice a month whether or not the rest of the plate wanted it. 'Biryani on Wednesday' needs no rule - Wednesday is already the biryani theme day.

| Rule | What it does | Client's words |
|---|---|---|
| `theme_cuisine_filter` | shelf component `indian_veg_dry_on_chinese_day` |  |
| `stripe_paneer_2_to_3` | shelf component `paneer_twice_a_week`, with `min`, `max` overridden |  |
| `stripe_fish_1x_week` | shelf component `selector_once_a_week`, with `base_slot`, `selector` overridden |  |
| `stripe_mutton_15d_window` | primary_protein mutton @ nonveg_main: once per 15 days, read from saved history | Mutton at most twice a month, enforced ACROSS plans from saved history: 2x/month is roughly once per 15 days, the same cadence shape as Stryker NCR's fish |
| `stripe_mutton_max_1` | primary_protein mutton @ nonveg_main: ≤ 1 day(s) | The within-plan half: at most one mutton day in a single horizon |

## Stryker

Bangalore site (not 'Stryker NCR', which is a separate client). Its theme_map is empty, so the default weekday themes apply and Tuesday is the Chinese day.

| Rule | What it does | Client's words |
|---|---|---|
| `theme_cuisine_filter` | shelf component `indian_veg_dry_on_chinese_day` |  |
| `stryker_protein_source_daily` | shelf component `protein_source_daily` |  |
| `stryker_protein_outside_dal` | shelf component `protein_outside_dal_three_days` |  |
| `stryker_protein_outside_dal_all_days` | shelf component `protein_outside_dal_other_days` |  |

## Stryker NCR

NCR site 'Stryker Sector 59' (city NCR). Logics from the client sheet + the 10-day sample. Salad 1 = green salad daily (salad 2 follows rules); indian bread 1 = tawa roti daily (bread 2 follows rules — needs bread slot_count 2, see the config note); rice split: flavour rice Mon/Wed/Thu/Fri, white rice (const slot) Tue only, so flavour rice is blank whenever white rice runs. The 15-day cadences (fish/biryani/sambar) are now enforced across plans via selector_history_window rules that read saved history (paired with within-plan caps where relevant). Still deferred: 'serve a biryani day once/15 days' (positive cadence) and 'biryani not the same week as fish' (week co-occurrence) are not expressible yet; sambar needs the counter switched dal -> dal_sambar to serve it. 'Thursday special' needs the special defined; 'cut fruits' is a breakfast item.

| Rule | What it does | Client's words |
|---|---|---|
| `strykerncr_egg_curry_1x` | shelf component `egg_dish_once_a_week` |  |
| `strykerncr_paneer_gravy_2x` | primary_protein paneer @ veg_gravy: exactly 2 day(s) | Two paneer gravies a week. |
| `strykerncr_kofta_gravy_1x` | is_veg_kofta_gravy @ veg_gravy: exactly 1 day(s) | One kofta gravy a week. |
| `strykerncr_fish_max_1` | is_fish_dish @ nonveg_main: ≤ 1 day(s) | Fish at most once a WEEK within a plan (the within-plan half of once-per-15-days). |
| `strykerncr_fish_15d_window` | is_fish_dish @ nonveg_main: once per 15 days, read from saved history | Fish once per 15 DAYS, enforced across plans from saved history: a fish served in the last 15 days is banned until the window clears |
| `strykerncr_biryani_15d_window` | is_nonveg_biryani @ nonveg_main: once per 15 days, read from saved history | Biryani (nonveg) at most once per 15 days across plans (history window) |
| `strykerncr_sambar_15d_window` | course_type sambar: once per 15 days, read from saved history | A sambar once per 15 days across plans (history window) |
| `strykerncr_fish_biryani_not_same_week` | is_nonveg_biryani or is_mixedveg_biryani and is_fish_dish never share the same week | Biryani not in the same WEEK as fish (site-specific, Stryker only) |
| `strykerncr_flavour_rice_no_tue` | rice runs only on mon, wed, thu, fri (blank otherwise) | Flavour rice on the days white rice is not served: Mon/Wed/Thu/Fri. |
| `strykerncr_white_rice_tue` | white_rice runs only on tue (blank otherwise) | White rice (const steamed-rice slot) only on Tuesday; flavour rice is blank that day. |
| `strykerncr_green_salad_repeatable` | item green_salad @ salad: may repeat on any day | Green salad is pinned daily in salad 1 (a multi-slot expansion, so the pin is a solved cell, not a whole-slot stamp) |
| `strykerncr_tawa_roti_repeatable` | item tawa_roti @ bread: may repeat on any day | Tawa roti is pinned daily in bread 1 — repeatable so it may recur every day. |

**City rules switched off:** `deep_fried_coupling`

**Pinned items:** `salad__1` — green salad; `bread__1` — tawa roti

## TCL

Chennai. From the client's own 13 stated rules plus a seven-day sample week (data/raw/source_workbooks/chennai_client_structure.xlsx, sheets 'Sheet1' and 'TCL'). The site serves Saturday AND Sunday on reduced menus, which is what most of the rules below are about. TWO of the thirteen are NOT rules at all and need no config: 'in healthy rice we will serve only Curd Rice daily' is already what the `curd_rice` slot does (its pool is the `is_curd_rice` flag, and chennai.json's `curd_rice_is_a_staple` lets the same dish recur), and the client's kuzhambu and kootu requirements are about which SLOT holds what — see the two `_needs_db_change` notes. ONE STATED RULE CONTRADICTS THE SAMPLE: the client says 'welcome drink will be buttermilk twice a week', but all five sampled drinks are buttermilks (BUTTERMILK / SAMBARAM / INJI MOORU / BUTTERMILK / NEER MOORU — sambaram and neer mor both carry `is_buttermilk`). The stated rule is what is configured, since that is what the client wrote down; if they meant 'plain buttermilk twice and a variant otherwise' the fix is to narrow the selector to the one dish.

| Rule | What it does | Client's words |
|---|---|---|
| `tcl_bread_is_chapati_daily` | shelf component `bread_chapati_only` |  |
| `tcl_dal_is_a_kootu` | dal must include (when the counter serves ≥1 and ≤1 of it): sub_category kootu | in dal need to give only Kootu item |
| `tcl_rice_is_a_biryani_and_a_south_rice` | rice must include (when the counter serves ≥2 of it): is_biryani_item + sub_category south_one_pot_rice or sub_category south_rice_bath or sub_category south_veg_pulao | 2 flavoured rice one will be biryani daily and other will be south flavoured rice |
| `tcl_one_rice_on_saturday` | rice runs only on mon, tue, wed, thu, fri, sun (blank otherwise) | Saturday serves ONE rice ('only one south flavoured rice'), so the second rice cell stands down for that day alone — `slot_indices` skips one expansion instead of the whole family, which is what a … |
| `tcl_no_flavoured_rice_on_sunday` | rice runs only on mon, tue, wed, thu, fri, sat (blank otherwise) | Sunday serves white rice and no flavoured rice at all ('on sun chapathi, white rice, samabar, rasam, dal, veg gravy, welcome drink, salad and papad only'). |
| `tcl_salad_is_a_kuzhambu` | salad must include (when the counter serves ≥1 and ≤1 of it): named kuzhambu/kolumbu/kulambu/kuzhumbu/kolambu | in salad need to give only KUZHAMBU item |
| `tcl_one_veg_gravy_on_saturday` | veg_gravy runs only on mon, tue, wed, thu, fri, sun (blank otherwise) | Saturday serves one veg gravy |
| `tcl_liquid_sweet_three_days` | is_liquid_dessert @ dessert: exactly 3 day(s) | liquid based sweet 3 a week |
| `tcl_buttermilk_twice_a_week` | is_buttermilk @ welcome_drink: exactly 2 day(s) | welcome drink will be buttermilk twice a week |
| `tcl_nonveg_egg_mwf_chicken_tue_thu` | nonveg_main must include (when the counter serves ≥1 and ≤1 of it): on mon: is_egg_dish; on wed: is_egg_dish; on fri: is_egg_dish; on tue: primary_protein chicken; on thu: primary_protein chicken | in non veg main egg based to be served on mon, Wednesday and Friday |
| `tcl_no_nonveg_biryani` | is_nonveg_biryani @ nonveg_main: ≤ 0 day(s) | no biryani in non veg main to be served |
| `tcl_no_premium_veg_on_the_weekend` | key_ingredient paneer or primary_protein paneer or key_ingredient mushroom or named baby_corn/babycorn/mushroom/paneer: never on sat, sun | no item like baby corn, panner and mushroom will given on sat and sun |
| `tcl_no_dal_on_saturday` | dal runs only on mon, tue, wed, thu, fri, sun (blank otherwise) | Saturday's menu is 'chapathi, only one south flavoured rice, healthy rice, veg gravy, welcome drink, veg dry and papad only' — so salad, dal, sambar, rasam, dessert and non-veg all stand down |
| `tcl_sambar_not_on_saturday` | sambar runs only on mon, tue, wed, thu, fri, sun (blank otherwise) |  |
| `tcl_rasam_not_on_saturday` | rasam runs only on mon, tue, wed, thu, fri, sun (blank otherwise) |  |
| `tcl_salad_not_on_saturday` | salad runs only on mon, tue, wed, thu, fri, sun (blank otherwise) | Salad appears in Sunday's stated list and not Saturday's |
| `tcl_veg_dry_not_on_sunday` | veg_dry runs only on mon, tue, wed, thu, fri, sat (blank otherwise) |  |
| `tcl_curd_rice_not_on_sunday` | curd_rice runs only on mon, tue, wed, thu, fri, sat (blank otherwise) | Curd rice is in Saturday's list ('healthy rice') and not Sunday's. |
| `tcl_dessert_on_weekdays_only` | dessert runs only on mon, tue, wed, thu, fri (blank otherwise) | Dessert and non-veg appear in neither weekend list. |
| `tcl_nonveg_on_weekdays_only` | nonveg_main runs only on mon, tue, wed, thu, fri (blank otherwise) |  |

**City rules switched off:** `mixedveg_pulao_biryani_weekly`, `kootu_twice_weekly`, `salad_is_not_a_kuzhambu`

## Tekion

| Rule | What it does | Client's words |
|---|---|---|
| `tekion_nonveg_mwf` | shelf component `nonveg_on_weekdays` |  |
| `tekion_bread_chapati_only` | shelf component `bread_chapati_only` |  |
| `theme_cuisine_filter` | shelf component `indian_veg_dry_on_chinese_day` |  |
| `tekion_protein_source_daily` | shelf component `protein_source_daily` |  |
| `tekion_protein_outside_dal` | shelf component `protein_outside_dal_three_days` |  |
| `tekion_protein_outside_dal_all_days` | shelf component `protein_outside_dal_other_days` |  |
| `tekion_no_mushroom` | never serve: mushroom |  |
| `tekion_liquid_rice_once` | is_liquid_rice @ rice: ≥ 1/week, ≤ 1/week |  |
| `tekion_nonveg_by_weekday` | nonveg_main must include (when the counter serves ≥1 of it): on mon: is_north_chicken_gravy or is_south_chicken_gravy (not is_egg_dish); on wed: is_north_chicken_gravy or is_south_chicken_gravy (not is_egg_dish); on fri: is_nonveg_biryani | Non-veg gravy Monday and Wednesday, chicken biryani Friday - Friday is this counter's biryani day (client confirmed, and both sample weeks serve a veg biryani there too) |
| `tekion_chinese_rice_tuesday` | rice must include (when the counter serves ≥1 of it): on tue: is_chinese_fried_rice or is_chinese_carb | Chinese Rice & Chinese gravy to be served on Tuesday. |
| `tekion_chinese_gravy_tuesday` | veg_gravy must include (when the counter serves ≥1 of it): on tue: is_chinese_veg_gravy | The veg-gravy half of the same Tuesday rule. |
| `tekion_paneer_gravy_wednesday` | veg_gravy must include (when the counter serves ≥1 of it): on wed: is_paneer_gravy | Paneer Gravy every wednesday. |
| `tekion_khichdi_thursday` | rice must include (when the counter serves ≥1 of it): on thu: is_liquid_rice | Khichdi every Thursday. |

**City rules switched off:** `deep_fried_coupling`

## Tekion CHN

Chennai site. "Its rules are the same as Tekion BLR" — so this is Tekion's block re-keyed to this site, with the names prefixed so the two counters' diagnostics stay distinguishable. TWO CLIENT DECISIONS shape what is here. (1) The theme map stays Chennai's OWN (Mon/Tue mix, Wed south, Thu biryani, Fri north) rather than copying BLR's — so the weekday rules below land on different themes than they do in Bangalore, and each was checked against what Chennai can actually serve on that day: Friday is north and Chennai has 6 north non-veg biryanis, Wednesday is south and has 10 south chicken gravies, and the Thursday khichdi is unaffected because Chennai's ruleset exempts `rice` from theme filtering altogether. (2) NO CHINESE at this site, so BLR's two Chinese-Tuesday rules are deliberately absent — Tuesday is a `mix` day here and takes whatever the other rules allow. BLR's `indian_veg_dry_on_chinese_day` is absent for the same reason, and would have been anyway: Chennai's ruleset exempts `veg_dry` from theme filtering, so there is nothing for it to narrow. ONE THIN POOL to know about: Chennai has only ONE south paneer gravy (`paneer_kurma`), and Wednesday is a south day, so `tekion_chn_paneer_gravy_wednesday` can be met on one Wednesday per 20-day cooldown window and relaxes on the others. `diagnose()` reports it; the fix is more south paneer gravies in the Chennai list, not a config change. NO `disable` BLOCK, unlike Tekion BLR: that block switches off `deep_fried_coupling`, and the rule is Bangalore's. Chennai's ruleset is standalone rather than an `extends`, and carries no coupling rule at all, so the entry came across with the copy and named nothing. It was inert in the harmless direction — there was no coupling chain to leave running — but it read as a rule being switched off, which is the same silent-mismatch shape as a client name that does not match `clients.name`. `tests/rules/test_client_disable_targets.py` now fails on a `disable` that names no rule in the client's own city.

| Rule | What it does | Client's words |
|---|---|---|
| `tekion_chn_nonveg_mwf` | shelf component `nonveg_on_weekdays` |  |
| `tekion_chn_bread_chapati_only` | shelf component `bread_chapati_only` |  |
| `tekion_chn_protein_source_daily` | shelf component `protein_source_daily` |  |
| `tekion_chn_protein_outside_dal` | shelf component `protein_outside_dal_three_days` |  |
| `tekion_chn_protein_outside_dal_all_days` | shelf component `protein_outside_dal_other_days` |  |
| `tekion_chn_no_chinese` | cuisine_family chinese: ≤ 0 day(s) | No Chinese in Chennai Tekion. |
| `tekion_chn_no_mushroom` | never serve: mushroom |  |
| `tekion_chn_liquid_rice_once` | is_liquid_rice @ rice: ≥ 1/week, ≤ 1/week | Chennai carries 13 liquid rices, so this cap and the Thursday khichdi below both have something to act on. |
| `tekion_chn_nonveg_by_weekday` | nonveg_main must include (when the counter serves ≥1 of it): on mon: is_north_chicken_gravy or is_south_chicken_gravy (not is_egg_dish); on wed: is_north_chicken_gravy or is_south_chicken_gravy (not is_egg_dish); on fri: is_nonveg_biryani | Non-veg gravy Monday and Wednesday, chicken biryani Friday, mirroring Tekion BLR |
| `tekion_chn_paneer_gravy_wednesday` | veg_gravy must include (when the counter serves ≥1 of it): on wed: is_paneer_gravy | Paneer gravy every Wednesday |
| `tekion_chn_khichdi_thursday` | rice must include (when the counter serves ≥1 of it): on thu: is_liquid_rice | Khichdi every Thursday |

## Telstra

| Rule | What it does | Client's words |
|---|---|---|
| `telstra_paneer_exact_1` | shelf component `paneer_once_a_week` |  |
| `telstra_nonveg_dry_1x` | is_nonveg_dry @ nonveg_main: ≥ 1 day(s), ≤ 1 day(s) |  |

**Pinned items:** `curd` — monday=Curd, tuesday=Curd, friday=Curd; `curd_side` — wednesday=raita, thursday=raita

## Tessolve

| Rule | What it does | Client's words |
|---|---|---|
| `tessolve_nonveg_wed_only` | nonveg_main runs only on wed (blank otherwise) |  |
| `tessolve_green_salad_2x` | sub_category fresh_veg_salad @ salad: ≥ 2 day(s), ≤ 2 day(s) |  |

**City rules switched off:** `buttermilk_twice_weekly`, `welcome_drink_no_repeat_color`

**Pinned items:** `welcome_drink` — buttermilk; `curd` — monday=Curd, tuesday=Curd, thursday=Curd, friday=Curd; `curd_side` — wednesday=raita

## Thales

| Rule | What it does | Client's words |
|---|---|---|
| `thales_paneer_exact_1` | shelf component `paneer_once_a_week` |  |
| `thales_nonveg_by_weekday` | nonveg_main must include (when the counter serves ≥1 of it): on mon: is_egg_dish; on tue: is_egg_dish; on wed: is_north_chicken_gravy or is_south_chicken_gravy (not is_egg_dish); on thu: is_egg_dish; on fri: is_nonveg_biryani | Wednesday chicken gravy, Friday chicken biryani, and egg on the other three days |
| `thales_egg_dry_once` | is_nonveg_dry @ nonveg_main: ≥ 1 day(s), ≤ 1 day(s) (excluding primary_protein chicken) | Of the three egg days, one is a dry/fry rather than a gravy. |

## ToastTab

| Rule | What it does | Client's words |
|---|---|---|
| `toasttab_paneer_exact_1` | shelf component `paneer_once_a_week` |  |
| `toasttab_mushroom_exact_1` | shelf component `selector_once_a_week` |  |
| `buttermilk_twice_weekly` | welcome_drink_buttermilk |  |

## ToastTab CHN

Chennai. Derived from a 7-day SERVICE HISTORY (Wed 01 Jul – Thu 09 Jul 2026, weekdays only), not a written rulebook — see docs/chennai_client_logic.md for the grid and how each rule was read off it. THE ONE ASSUMPTION: the sample spans two part-weeks whose weekday→theme mapping conflicts (Wed is south on 01 Jul but biryani on 08 Jul; Thu is north on 02 Jul but south on 09 Jul), so the theme map is inferred from the later, more complete run 06–09 Jul — Mon/Thu/Fri south, Tue north, Wed biryani. That fits 5 of the 7 observed days and reproduces the sample's 4 south : 2 north : 1 biryani ratio scaled to a 5-day week. The weekday lists below FOLLOW from that map: if the real theme map differs, these lists must move with it, because what the sample actually determines is the THEME each slot belongs to, not the weekday.

| Rule | What it does | Client's words |
|---|---|---|
| `toast_tab_chn_white_rice_south_days` | white_rice runs only on mon, thu, fri (blank otherwise) | White rice on the SOUTH days only |
| `toast_tab_chn_flavour_rice_north_biryani_days` | rice runs only on tue, wed (blank otherwise) | Flavoured rice on the NORTH and BIRYANI days only — peas pulao (north), ghee bisibelebath (north), veg biryani (biryani) in the sample |
| `toast_tab_chn_rasam_south_days` | rasam runs only on mon, thu, fri (blank otherwise) | Rasam on the SOUTH days only — the 'RASAM / CURD' cell, which the source workbook auto-split into two servings |
| `toast_tab_chn_curd_side_south_and_biryani_days` | curd_side runs only on mon, wed, thu, fri (blank otherwise) | The curd half of 'RASAM / CURD', same four south days |
| `toast_tab_chn_curd_rice_north_biryani_days` | curd_rice runs only on tue, wed (blank otherwise) | Curd rice on the NORTH and BIRYANI days — the sour/yogurt component when there is no white rice + rasam |
| `maida_bread_weekly` | is_maida_bread @ bread: ≤ 2 day(s) | Overrides the city rule of the same name (merged by name, so this REPLACES chennai.json's max of 1) |
| `toast_tab_chn_bread_is_a_wheat_flatbread` | bread must include (when the counter serves ≥1 of it): is_plain_phulka_chapathi or is_paratha or is_maida_bread or is_tandoori_roti | The bread is always a wheat or maida flat bread, never the dosai/idly family |

## Vector

| Rule | What it does | Client's words |
|---|---|---|
| `vector_plain_chapati_2x` | shelf component `plain_chapati_twice_a_week` |  |
| `vector_dessert_wed_only` | dessert runs only on wed (blank otherwise) |  |

**City rules switched off:** `liquid_desserts_twice_nonconsecutive`, `buttermilk_twice_weekly`, `welcome_drink_no_repeat_color`

**Pinned items:** `welcome_drink` — buttermilk

## World Bank

Chennai, two counters — 'Full Lunch Menu' (primary) and 'Roti and Rice Combos'. Seven stated rules (data/raw/source_workbooks/chennai_client_structure.xlsx, 'Sheet1' rows 17-23) against the 17-21 Aug sample on the 'World Bank' sheet. One of the seven needs no config: 'in counter rice/roti combo now veg will be gravy daily' is already what that counter does — `veg_gravy` is one slot, served every day. The two counters' shared veg dry and veg gravy come from `clients.shared_categories`, which the sample confirms: both counters print the identical poriyal and the identical channa/kurma every day.

| Rule | What it does | Client's words |
|---|---|---|
| `theme_cuisine_filter` | theme filter does not narrow: dal, salad, soup, healthy_rice, rice, sambar, rasam, curd, curd_side, curd_rice, dessert, bread, veg_dry, nonveg_main | Overrides chennai.json's rule of the same name (merged by name, so this REPLACES its `exempt_slots`) by adding `nonveg_main` to the exempt list |
| `world_bank_dal_is_a_kootu` | dal must include (when the counter serves ≥1 and ≤1 of it): sub_category kootu | in dal need to give only Kootu item |

**City rules switched off:** `kootu_twice_weekly`, `nonveg_biryani_weekly`

### World Bank → Full Lunch Menu

The full meals counter: chapati, steamed rice, a gravy, a sambar, a kuzhambu, rasam, poriyal, kootu, buttermilk, appalam and four non-veg items.

| Rule | What it does | Client's words |
|---|---|---|
| `world_bank_bread_is_chapati_daily` | shelf component `bread_chapati_only` |  |
| `world_bank_nonveg_gravy_alongside_the_three_pins` | nonveg_main must include (when the counter serves ≥1 of it): is_north_chicken_gravy or is_south_chicken_gravy | One of the non-veg cells is the day's chicken gravy |
| `world_bank_welcome_drink_is_buttermilk` | welcome_drink must include (when the counter serves ≥1 and ≤1 of it): is_buttermilk | welcome drink will be "buttermilk" daliy |
| `world_bank_buttermilk_may_recur_across_weeks` | is_buttermilk @ welcome_drink: may recur across plans, but stays distinct within one | Chennai carries ten buttermilks, fewer than a daily slot needs across a 20-day cooldown window, so the history ban has to stand down or week three has no drink |

**Pinned items:** `nonveg_main__2` — Chicken Biryani; `nonveg_main__3` — Boiled Egg; `nonveg_main__4` — Bone Salna; `dessert` — Sweet/Fruit

### World Bank → Roti and Rice Combos

The combo counter: two breads (paratha and chapati in the sample, so NOT chapati-only), a flavoured rice, the shared poriyal and gravy, and one chicken gravy.

| Rule | What it does | Client's words |
|---|---|---|
| `world_bank_combo_rice_is_south_daily` | rice must include (when the counter serves ≥1 and ≤1 of it): cuisine_family south_indian | in counter rice/roti combo flavour rice will be south rice daliy |

## Zscaler

| Rule | What it does | Client's words |
|---|---|---|
| `zscaler_mushroom_exact_1` | shelf component `selector_once_a_week` |  |
| `zscaler_biryani_pulao_rice_2x` | is_nonveg_biryani or is_mixedveg_biryani or is_premium_biryani or is_pulao @ rice: ≥ 2 day(s) |  |
| `zscaler_chinese_veg_dry_starter` | cuisine_family chinese @ starter: ≤ 2 day(s) |  |
| `zscaler_no_potato` | never serve: potato |  |
| `zscaler_babycorn_exact_1` | key_ingredient baby_corn: ≥ 1 day(s), ≤ 1 day(s) |  |
| `zscaler_paneer_gravy_1` | is_paneer_gravy: ≥ 1 day(s), ≤ 1 day(s) |  |
| `zscaler_paneer_fry_1` | is_paneer_fry: ≥ 1 day(s), ≤ 1 day(s) |  |

**City rules switched off:** `mixedveg_pulao_biryani_weekly`, `potato_veg_gravy_weekly`, `potato_veg_dry_weekly`

