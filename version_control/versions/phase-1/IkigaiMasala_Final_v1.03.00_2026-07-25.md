# Version 1.03.00: The rulebook engine

**Phase:** 1 Simple tool  **Date:** 22–25 Jul 2026  **Status:** Final

## In one line

Menu rules became something written in a configuration file rather than
programmed one at a time, and rules now apply in order of importance.

## Why this version was needed

Every rule in the planner was its own piece of program code. Adding "kofta no
more than once a week" meant writing a new class, and the client's rulebook ran
to dozens of such rules. At that rate the rulebook could not be delivered.

Soft preferences had a second problem. They were all added together into one
score, so a handful of minor preferences could collectively outweigh an
important one. Nothing guaranteed that "keep the premium dishes on separate
days" beat three small nudges pulling the other way.

## What's new

### 1. Sites can draw on their own dish pools

A site can be given its own set of dish pools on top of the shared list. The
planner filters the dish list to the shared pool plus that site's own pools
before doing anything else, so a site's own dishes take part in every rule.

The setup screen gained an Item Pools section showing, live, how many dishes a
chosen combination makes eligible and how they break down by category — so
somebody configuring a site can see the effect before saving it.

### 2. Chinese and Continental dishes stay on their own day

A Chinese dish now appears only on the Chinese day, and a Continental dish only
on the Continental day. This applies to the main courses — rice, gravies, dry
vegetables, starters, the non-veg main — while soups and salads keep their
variety every day, since most of them are tagged Continental and restricting
them would flatten the rest of the week.

If applying this would empty a slot, it is not applied to that slot, so a site
with a small dish list cannot be left with nothing to serve.

### 3. Ingredient bans check both ingredient fields

A mushroom ban now catches dishes where mushroom is recorded as the protein (58
dishes) as well as those where it is the key ingredient (76), rather than only
the latter.

### 4. Rules written as configuration, in four families

Four general rule types replaced the one-class-per-rule approach:

- **How often** — a dish family may appear at most, at least, or exactly N days,
  optionally never on consecutive days, with a per-day cap. "Kofta at most once
  a week" is now three lines of configuration.
- **Grouping by an attribute** — group a slot's dishes by any column and
  constrain each value: dal colours may not repeat on consecutive days; a
  sambar's main ingredient may appear once in the plan.
- **Colour and pairing rules** — including the rule that a rice bread implies a
  liquid rice.
- **Soft preferences** — nudges rather than requirements.

Requirements that ask for more than the dish list can supply are automatically
reduced to what is achievable, so a thin list relaxes instead of failing.

### 5. Priorities, so a small rule cannot outvote a big one

Soft preferences now carry a priority — theme, high, medium or low — and each
level outweighs everything below it by a factor of about a thousand. A high
priority preference cannot be outvoted by any number of medium and low ones.
The random tie-break that keeps menus from being identical sits below all of
them.

### 6. Alternate menus, ranked

The planner can offer several menus for the same week, ranked by that same
priority order, so a planner can choose between genuine alternatives rather
than regenerating and hoping.

## What this means for day-to-day use

A new client rule no longer needs a developer. "No black dal more than once a
week" or "two liquid desserts, not on consecutive days" is written in the
configuration file and takes effect on the next generation.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 1.03.00 | 22–25 Jul | Darshan + Claude Code | **Rulebook engine.** (1) Client item-pool filtering. (2) Cuisine exclusivity and ingredient ban. (3) Rule families: selector_frequency, premium, attribute grouping, colour, deep-fried coupling, soft preferences. (4) Lexicographic objective tiers and ranked alternate menus |

**Previous:** [v1.02.00](IkigaiMasala_Final_v1.02.00_2026-07-21.md)  **Next:** [v2.00.00](../phase-2/IkigaiMasala_Final_v2.00.00_2026-08-03.md)
