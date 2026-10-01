# Chef's Read: Architecture

> Owner's design document, 1 Oct 2026. `api/explain_llm.py` cites this file
> three times and it was the one piece of the drop that never landed in the
> repo. Reproduced here as written, except for the lines marked
> **Since written:** — the shipped code has moved on from the draft in four
> places and a design doc that disagrees with the code is worse than none.

## Summary

The chef's read is an optional section of "Why this menu": an LLM reads each
day's menu like someone who knows Indian food and writes two short notes, one
for the people eating and one for the chef and planner. It changes nothing
about the existing overview.

- **What it says:** whatever matters for that day's menu, in no fixed order —
  how to put a plate together, the star of the day (if there is one), a
  regional or theme thread, comebacks after 20+ days, and, for the chef, what
  is weak and which dish looks wrongly described.
- **Who decides:** the model, using its own food knowledge, for pairings and
  the star.
- **What keeps it honest:** the model also returns a hidden claim list; code
  checks those claims and both notes for truth (dishes, numbers, star reason,
  client vs chef consistency), never for shape. A failed draft goes back with
  its problems, up to 3 times.
- **Delivered:** `api/explain_llm.py` (previous code kept, chef's read added),
  `tests/explain/test_chef_read.py`, and `docs/chef_read_prompt.md`.
- **Verified:** the 300 existing explain and architecture tests still pass with
  the new module; the new tests pass offline. No real model was called — that
  needs the AI Studio key.

**Since written:** it shipped off by default and is now **on** by default; the
key is the gate. See *Configuration*.

## How it fits next to the overview

Both features live in `api/explain_llm.py` and share one model, one API key and
one HTTP function (`_post_model`), but they make opposite bets.

|  | Overview (existing) | Chef's read (new) |
| --- | --- | --- |
| Entry point | `explain_plan(packs)` | `explain_chef_read(packs, ...)` |
| What the model does | Rewords facts Python already computed | Judges the menu with its own food knowledge |
| Calls | One per plan | One per day, plus up to 2 retries |
| On failure | Python's `day_overview()` stands in | Section omitted; overview still shown |
| Switch | `EXPLAIN_LLM_ENABLED` | `EXPLAIN_CHEF_READ_ENABLED` |
| Model | `EXPLAIN_LLM_MODEL` | `EXPLAIN_CHEF_READ_MODEL` (defaults to the same) |

The overview code is unchanged apart from one refactor: `_call_model(payload)`
now delegates to the shared `_post_model`, with its old signature and behaviour
kept because tests patch it by name.

The chef's read reuses four overview helpers rather than copying them:
`_BANNED_RE` (health topics), `_allowed_tokens` and `_fmt_num` (number
sourcing) and `_reports_the_bad_news` (the plate's known problems must be
faced).

## The facts the model receives

`build_chef_facts()` turns one day's existing evidence pack into the facts
below, so both features describe the same dishes. It adds what judgement needs
and the pack lacks.

| Field | Source | Why the model needs it |
| --- | --- | --- |
| `date`, `weekday`, `theme` | evidence pack | The day's frame |
| `regional_day` | `inputs.region_days` | A Tamil Nadu day reads differently |
| `has_history` | `recency` is non-empty | Stops "new" or "comeback" claims with no saved history |
| `dishes[].name`, `slot`, `course_type`, `kind` | pack (`sub_category`) | What the dish is and where it sits |
| `dishes[].cuisine_family`, `state_origin` | pack + ontology | Cuisine groups, regional days, data doubts |
| `dishes[].key_ingredient`, `protein`, `texture`, `spice_level`, `richness` | pack | Lets it reason about obscure names instead of guessing |
| `dishes[].premium` | any `is_premium*` column = 1 | A verifiable star reason |
| `dishes[].pinned` | provenance `client_constant` | The client asked for it |
| `dishes[].days_since_served` | `recency_by_item` | Comebacks, "back after N days" |
| `known_problems` | pairing gaps, relaxations, failing checks | The chef note must face them |
| `other_days_open_with` | earlier days' client notes | So each day opens differently |

`state_origin` and premium flags come from `chef_attrs_from_dataframe(df)`,
because the overview's `DISH_COLUMNS` does not carry them. The full city dish
list (`city_dish_names_from_dataframe(df)`, 5,608 names for Bangalore) is not
sent to the model; it is only used by the checks to catch off-menu dishes.

## Prompt design

The prompt (`CHEF_READ_SYSTEM_PROMPT`, full text in
`docs/chef_read_prompt.md`) gives the model a goal and limits, never a
structure.

- **Goal, not template.** "Tell them what is worth knowing about THIS menu"
  with examples of what that might be. No headings, lists or fixed order; some
  days need one line.
- **Two audiences in one reply.** `client_read` is warm and plain, 2 to 5
  sentences. `internal_read` is direct kitchen language, up to 6 sentences, and
  must face `known_problems`. One reply writes both, so they come from the same
  reading of the menu.
- **Food knowledge is invited.** The model is told to use what it knows about
  which dishes go together and what diners look for.
- **Hard limits, each matched by a check:** only today's dishes, no
  underscores, no unsourced numbers, no health claims, no machinery words for
  clients, no client praise of what the chef note criticises, comebacks need
  21+ days with history, never bread with rasam.
- **The star is optional.** If one dish stands out, the model names it with a
  plain reason and a basis code can confirm: premium, comeback, regional,
  pinned, theme or plate_role. Richness alone is not a reason, and it is told
  to think about who can actually eat the star.
- **Claims for the checks.** Plates, star, comebacks, weak spots and data
  doubts are returned as structured claims, so the checks never have to parse
  the prose.
- **Temperature 0.2**, so the same menu tends to get the same star; the cache
  makes it exact for repeat requests.

**Since written:** the draft had eight hard limits. A ninth was added — no
bullets, no headings and no labels in front of a sentence — because "no
template" was a line in the prompt that nothing enforced, and the model
reliably wrote `Weak spots:` at the front of a sentence. The check vetoes list
and heading SHAPES and the output schema's own field names, not plausible
English, so `An easy day:` survives.

## The checks

`check_chef_read()` checks truth, never shape: it never asks for a plate, a
star, an order or a minimum length. Every message is written to be sent
straight back to the model.

| Check | Applies to | Catches |
| --- | --- | --- |
| Off-menu dish (city list, any casing) | both notes | "the dal makhani would fix it"; short forms of today's dishes are allowed |
| Number not in the facts | both notes | "back after 26 days" with no such fact |
| Health topic | both notes | calories, healthy, diet, vitamins |
| Underscores | both notes | `jeera_chapati` in prose |
| Machinery words | client | rule, cooldown, slot, score, data, system |
| Theme praise vs `theme_mismatch` | client | "a true north spread" while the chef note says the theme is thin |
| "light" vs `heavy`, "variety" vs `repetitive` | client | contradicting the chef note |
| "perfect" or "balanced" with known problems | client | flattery over a gap |
| Same opening as an earlier day | client | template-like weeks |
| Length ceiling | both | over 110 words (client) or 170 (chef) |
| Known problems faced | chef | silence about a gap or relaxation |
| Plate dishes on the menu | claims | a plate with an invented dish |
| Plate has rice or bread | claims | "pepper fry + laddu" as a plate |
| Bread with rasam | claims | the one hard-vetoed pairing |
| Star basis is true | claims | "premium" for a dish not flagged premium |
| Comeback is real | claims | no history, or under 21 days |
| Data doubt quotes the tag correctly | claims | misquoting what the facts say |

The pairing veto is deliberately one row. An earlier allow-list rejected mint
pulao with a dry vegetable, a normal plate; the model's food knowledge decides
what goes well together, the code only blocks absurdity.

## Retry loop, cache and fallback

`chef_read_day()` runs at most `CHEF_READ_MAX_ATTEMPTS` (3) model calls per
day, as one growing conversation.

1. Send the facts as the first user turn.
2. Parse the JSON reply; if it is not valid JSON, that is the only problem sent
   back.
3. Run `check_chef_read()`. No problems → accept.
4. Otherwise append the model's draft as a `model` turn and the problems as a
   `user` turn ("fix only these, keep everything else"), and go back to step 2.
5. After the third rejection, give up: `source=None`,
   `reason="rejected after 3 attempts: <first problem>"`.

**Network failure is not retried.** A timeout, 429 or HTTP error returns
`model unavailable` after one call, because retrying only spends quota.

Every rejection is kept in `problems_by_attempt`, which is the raw material for
the learning loop.

**Cache.** An accepted read is cached in memory under a hash of the prompt
version, the model name and the day's facts (up to 256 entries, cleared on
restart). Rejected reads are never cached. Bumping
`CHEF_READ_PROMPT_VERSION` invalidates old reads when the prompt or checks
change.

**Fallback.** There is no Python version of the chef's read: a failed day
simply has no section, and the existing overview (model or `day_overview()`)
is shown as today. Accepted data doubts are logged on the
`explain.data_doubts` logger for the ontology team.

**Cost.** Worst case 3 calls per day, 15 for a 5-day plan, within Gemma's free
30 requests a minute. Days run in order so each sees earlier openings, so
worst-case latency is about a minute per day at the 20-second timeout.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `EXPLAIN_LLM_API_KEY` | (empty) | Google AI Studio key, shared with the overview |
| `EXPLAIN_CHEF_READ_ENABLED` | **true** | Turns the chef's read on, independently of the overview |
| `EXPLAIN_CHEF_READ_MODEL` | same as `EXPLAIN_LLM_MODEL` (`gemma-4-31b-it`) | Model for the chef's read; set by the probe result |
| `EXPLAIN_CHEF_READ_MAX_ATTEMPTS` | 3 | Drafts per day before giving up |
| `EXPLAIN_CHEF_READ_MAX_TOKENS` | 1200 | Reply limit per call |
| `EXPLAIN_CHEF_READ_CLIENT_WORDS` | 110 | Length the checks accept, diner note |
| `EXPLAIN_CHEF_READ_INTERNAL_WORDS` | 170 | Length the checks accept, kitchen note |
| `EXPLAIN_LLM_ENDPOINT` | Gemini `generateContent` URL | Shared |
| `EXPLAIN_LLM_TIMEOUT_SECONDS` | 20 | Shared, per call |

Code constants worth knowing: `COMEBACK_DAYS = 21`, temperature 0.2,
`CHEF_READ_PROMPT_VERSION = "chef-read-v2"`.

**Since written:** the draft shipped `EXPLAIN_CHEF_READ_ENABLED=false` and
`chef-read-v1`, and the two word ceilings were code constants. The owner turned
the feature on; the version is v2 because the ninth hard limit changed the
prompt; and the ceilings became env vars so the three length dials can move
together — see `docs/setup.md`, which explains why moving fewer than three
changes nothing.

## Wiring it in

`explain_llm.py` alone does nothing until `/api/v1/explain` calls it.

1. Import (replaces the existing `explain_plan` import):

```python
from api.explain_llm import (
    explain_plan, explain_chef_read, chef_attrs_from_dataframe,
    city_dish_names_from_dataframe,
)
```

2. Call it right after `rendered = explain_plan(packs)`:

```python
chef = explain_chef_read(
    packs,
    extras=chef_attrs_from_dataframe(inputs.df),
    recency=inputs.recency_by_item,
    region_days=getattr(inputs, 'region_days', None),
    city_dish_names=city_dish_names_from_dataframe(inputs.df),
)
```

3. Return it per day, beside the existing fields: `'chef_read': chef.get(pack['date'])`.

Two things to get right:

- **Regional days.** `MenuApiClient.explain()` does not send `region_days`, so
  the facts will never say "Tamil Nadu day". Pass the planner's picks through,
  as `plan()` already does.
- **Client surfaces.** Anything a client sees must carry only `client_read`.
  `internal_read` and `data_doubts` are for the kitchen and planners.

**Since written:** both are done. The planner shows the chef's read as the
second view in the "Why this menu" expander — one request, two buttons, and
`_render_chef_read` labels the diner note *safe to share* and the kitchen note
*not for clients* so the split is visible rather than inferred. And
`MenuApiClient.explain()` now sends `region_days` (the regions **applied** to
the plan on screen, not the pending picks), so the regional thread reaches the
facts.

## Testing and the learning loop

The code is tested offline; whether the model is good enough is a separate
question, answered in three steps before it reaches anyone.

**Unit tests (done).** `tests/explain/test_chef_read.py`, on the real Eli Lilly
Monday menu with a scripted model: switches, the retry loop, give-up, no retry
on network failure, cache, every truth check, both audience guards, and that no
template is required.

1. **Capability probe.** Ask the chosen model to label about 60 dishes by
   region and meal role, and score it against rows whose `state_origin` is a
   real state. Below about 85%, try a larger model via
   `EXPLAIN_CHEF_READ_MODEL`. Its confident disagreements double as a list of
   mis-tagged dishes.
2. **Golden set.** About 20 real menus across themes, cities and regional days.
   A chef writes a 3-line read and a star for each.
3. **Score each prompt version on the golden set:**
   - invented facts in accepted reads: must be 0
   - client/chef contradictions: must be 0
   - star agreement with the chef
   - star bias: share of non-veg or richness-5 stars
   - critique recall: did it catch the chef's main complaint
   - attempts per accepted day, and the most common rejection reasons from
     `problems_by_attempt`

Each round, change the prompt or the facts, bump
`CHEF_READ_PROMPT_VERSION`, and rerun. A chef correction that recurs becomes a
fact (a fixed tag) or a check.

## Worked example: Eli Lilly, Monday 7 Sep 2026

A north-theme day whose most complete plate is actually south. The drafts below
are written to show the loop; the checks are the real code, run on the real
menu.

**Menu:** jeera chapati, mint pulao, steamed rice, soya chatpata dry
(premium), drumstick mango pachadi (tagged north), pumpkin kootu, dosakai
sambar, rasam, chicken pepper fry, raita, ghee motichur laddu, babycorn salad.

| Attempt | Draft did | Checks said |
| --- | --- | --- |
| 1 | "A classic north feast"; jeera chapati with rasam; dal makhani; star chicken pepper fry as "premium"; client note mentions the cooldown | 9 problems, sent back |
| 2 | Fixed plates and dishes; star still chicken pepper fry ("everyone loves it"); client says "a true north spread" | 2 problems, sent back |
| 3 | Star soya chatpata (premium); north and south plates; heavy finish named; pachadi doubt logged | Accepted |

**Accepted client note:**

> Two good ways to eat today. Roti people, pair the jeera chapati with the soya
> chatpata, the pick of the day. Rice people, steamed rice with dosakai sambar,
> rasam and the pumpkin kootu makes a proper South-style meal, with curd to
> round it off.

**Accepted chef note:**

> Says north on paper, but a north diner has nothing wet for the roti: the dal
> is a kootu and the gravy a pachadi, both south. The south plate is the
> complete one. Heavy finish with pepper fry then ghee laddu. The pachadi looks
> wrongly marked north.

The client note drops the criticism and turns it into a tip, but contradicts
nothing in the chef note.

## Known limits and open decisions

The checks guarantee the read is sourced and consistent, not that the food
judgement is right; that is what the probe and golden set are for.

- **Food knowledge is unchecked.** A pairing the model likes and a chef would
  not (but that is not bread with rasam) passes. Only the golden set catches
  this.
- **Gemma 31B is unproven here.** It has never been called in this repo, and
  regional dish names are where a general model guesses. Run the probe first.
- **Contradiction guard is narrow.** It catches theme praise, "light",
  "variety" and "perfect" against the chef note; a contradiction phrased
  another way gets through.
- **An invented dish not in the city list is not caught if written in
  lowercase.** The overview's Title-Case check is not applied here, because it
  rejected ordinary food words in testing.
- **Days run in sequence**, so a 5-day plan can take up to about 5 minutes in
  the worst case. Running them in parallel would lose the "open differently"
  hint. A horizon past about 9 days also exceeds the free tier's 30 requests a
  minute.
- **Open:** who in the kitchen writes the golden-set reads, and whether a
  client-facing surface (an exported menu, a display) should show
  `client_read` at all before the golden set is scored.
