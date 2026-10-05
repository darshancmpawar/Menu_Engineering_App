# Version 2.06.00: The chef's read, and a configuration per service

**Phase:** 2 Scaling  **Date:** 29 Sep – 5 Oct 2026  **Status:** Final

## In one line

A planner can ask a model what it thinks of a day's menu and get two short
notes back — one safe to pass to diners, one blunt enough for the kitchen —
and a site can now run a different setup at dinner than it runs at lunch.

## Why this version was needed

**The explanation could not judge.** Version 2.03.00 gave every day a written
overview, but by design the model was never allowed an opinion: everything it
said had already been computed, and it was only choosing the words. That is
the right bet for numbers and the wrong one for food. No table in this repo
knows that rajma chawal is a meal on its own, that a north diner with no wet
dish has nothing to put on a roti, or that a pachadi on a north-themed day is
probably filed wrong. A chef reading the overview could see the counts and
still not know whether the day came together.

**Dinner was configured as if it were lunch.** Since 2.04.00 a site could
serve several services a day and each got its own menu — but all of them were
planned from one counter setup. A site whose dinner runs two stations where
lunch runs four, or whose dinner drops the salad counter, had no way to say
so. The services differed on the plate and were identical in the settings.

## What's new

### 1. Ask the chef

A second button sits beside *Explain this menu*. Pressing it asks a model to
read that day's menu the way someone who knows Indian food would, and write
two notes:

- **For guests** — what is worth knowing today. How to build a good plate, the
  dish worth pointing a friend at, something back after a long absence, or
  simply that it is an easy day.
- **For the kitchen** — the same menu, said plainly. What does not work, where
  a group of diners has no proper plate, whether the theme actually shows,
  whether the day finishes heavy, and which dish looks described wrongly in
  the dish list.

Only the first may leave the building, so the two are labelled rather than
left to be worked out from the prose.

**Nothing is spent unless the button is pressed.** A plain explanation is
computed and free; the chef's read costs up to three model calls per day, and
only the person who asks for it pays. The explanation and the read are two
answers to two different questions, so each button now shows its own and
nothing else.

### 2. The model is allowed an opinion, and is not allowed to invent

The read is free prose with a hidden list of claims behind it: which plates it
suggested, which dish is the star and on what grounds, what is weak, which
rows look mis-tagged. The code checks the claims, never the shape. Every dish
named must be on today's counter. Every number must be in the facts. A
comeback must really be 21 days old. A plate must have a rice or a bread in
it. The guest note may leave a problem out but may never praise what the
kitchen note criticises.

A draft that breaks a rule goes back to the model with the specific problem,
up to three times. If it still fails, the day simply has no read and the
ordinary explanation stands.

In practice it found, unprompted and on every run, that a north-themed day's
most complete plate was the south one, and that a drumstick mango pachadi
filed as north Indian is a southern dish.

### 3. The model was chosen by measurement, not by assumption

The design called for a capability probe before trusting any model. It was
run, against a real key, and the model the system was configured with failed
it outright: it writes its reasoning out loud before its answer, so every
draft was rejected as malformed; a reply took 95–105 seconds against a
20-second limit; and on an identical request sent twelve times, only four
came back at all — the rest errored or timed out. Measured acceptance:
zero, on the chef's read and on the existing overview alike.

The replacement answers the same question in 3–4 seconds with a clean reply
and passed every check on the first draft. Seven days measured between 26 and 64
seconds in total across four runs.

Two faults were found the same way. A single dropped call used to cost a whole
day's read even though the day had three attempts and had used one — so a
seven-day plan came back with six reads and one "could not be reached". And
that message named three possible causes because the code had thrown away
which one it was. Both are fixed: a dropped call now costs an attempt, not the
day, and each cause says what to do about it.

### 4. Lunch and dinner are configured apart

The setup screen keeps the site's own settings — city, services, cooldown — in
one common section at the top. Everything below it, the counters and their
categories, frequencies and day themes, now repeats inside a tab per service.

A site that runs one service sees no tabs at all, exactly the screen it had
before. A site that runs two opens the Dinner tab already filled in with what
Lunch runs, and edits from there. **Nothing is stored differently until the
services genuinely differ**, so an existing site that changes nothing keeps
exactly the configuration it had, and no site was migrated for this.

### 5. The planner is an interactive table, and the workbooks are the source

The menu table and the regional-day strip were rebuilt as proper components,
so selecting cells and opening a region menu no longer reloads the page. The
regional menu lists every region the city has, with the ones that do not fit
shown greyed and carrying their reason, because a region silently missing from
a list reads as forgotten.

Separately, the five corrected city dish lists are now the **source**. The
chain of scripts that used to rebuild and patch them has been deleted, and
what it guaranteed — no meat-named dish in a vegetarian pool, no misspelled
protein, no non-veg row missing its form flag — is kept as standing tests that
read the workbooks and change nothing. A thin dish pool is now a normal state
to be reported, not a gap for a script to fill.

## What this means for day-to-day use

Generate a week as usual. *Explain this menu* behaves as it always has and
costs nothing. *Ask the chef* takes a few seconds per day and adds the two
notes; the guest note can be copied into whatever goes out to diners, and the
kitchen note should not be.

For a site with both services, open the setup screen and you will see Lunch
and Dinner tabs under the client section. Dinner starts as a copy of Lunch.
Change it only if the site really runs different stations at dinner — if you
change nothing, nothing changes.

## Known limits

**The food judgement is not scored yet.** The checks guarantee that the read
is sourced and internally consistent, not that the advice is good. One kitchen
note claimed the south dishes lacked a rice to go with them on a menu that had
steamed rice on it, and no check here can catch that. The golden set described
in the design — about twenty real menus with a chef's own read for each — is
still unwritten, and until it exists the guest note should be reviewed before
it is shown to anyone outside the kitchen.

**It needs a model key.** Without one the button reports that no model is
configured and everything else on the page is unaffected.

**Long horizons.** The read is one request per day, run in order, so a plan
past roughly nine days crosses the free tier's limit of thirty requests a
minute. A working week is comfortable.

**Occasional retries.** Between two and four days in seven still need a second
draft, usually because the model named a dish that is not on the counter. The check
catches it every time; it costs a few seconds.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.06.00 | 29 Sep–5 Oct | Darshan + Claude Code | **The chef's read, and a configuration per service.** (1) Chef's read behind an Ask the chef button: two notes per day, guests and kitchen, every claim fact-checked against the menu. (2) Model chosen by the capability probe the design asked for — the configured one could not return parseable JSON. (3) Lunch and dinner configured apart, counters tagged per service, no migration. (4) Menu table and regional strip as interactive components; the five city workbooks become the source and the correction chain is deleted |

**Previous:** [v2.05.01](IkigaiMasala_Final_v2.05.01_2026-09-23.md)  **Next:** [v2.07.00](IkigaiMasala_Final_v2.07.00_2026-10-05.md)
