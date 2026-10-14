# Version 2.07.04: Pick a dish, a pairing layer that mostly declined to ship, and a plan that stopped waiting on pandas

**Phase:** 2 Scaling  **Date:** 14 Oct 2026  **Status:** Final

## In one line

A planner can now put a named dish straight into a cell and be told what it
breaks, generating a menu takes about 25 seconds instead of 42, and a proposed
set of six food pairings was measured rather than assumed — one of them was
dropped because the situation it exists for never happens.

## What changed

### 1. Pick a dish

Until now the only way to change a cell was Regenerate, which asks the solver
for *something else* and gives you whatever it picks. If the planner had
already decided — the client asked for paneer lababdar on Wednesday — there
was nowhere to say so.

Switch the table from **Auto** to **Pick**, click a cell, and the cell becomes
a search box over that city's whole list for that course. Type, press Enter,
done. Nothing is solved; the dish is simply put there.

**The obvious way to build this is broken, and silently.** The natural
approach is to pin the dish and re-run the ordinary regenerate. But when a
pinned dish has been filtered out of that day's pool, the planner notes it in
the log and solves the cell normally — so the request succeeds, the menu looks
fine, and **a different dish than the one typed is on the plate**. Nothing on
screen says so. So a pick writes the dish directly and then inspects what it
cost, rather than asking the solver to honour it.

**Two things a pick may not do.**

A **pinned cell** cannot be changed — a staple like papad, or a dish the
client's own configuration fixes. That was always the intention, but it was
enforced only by the table refusing to let you click such a cell. Anything
that was not that table — a browser tab left open since before a config
change, or any other program talking to the planner — could ask and be served.
Both Pick and Regenerate now refuse on the server.

**The same dish cannot appear twice in one week.** This is the one rule a pick
cannot overrule, and it is checked against three things: the plan on screen,
the other dishes in the same request, and **what was already served this week
in a saved plan** — across every counter and both services, the same history
the three-week no-repeat window reads.

Two details of that rule are worth stating because getting either wrong would
be invisible:

- It is checked **before** the three-week window. A dish served on Monday is
  inside that window too, so the other order would report a blocking repeat as
  a mild "served 3 days ago" note and let it through.
- Saved history is consulted only for the days of the week **outside** the plan
  on screen. Saving overwrites per day, so if the planner saved before picking,
  counting those rows would make every dish on the plan block itself.

**Everything else is a warning, not a refusal.** A dish served nine days ago,
or one that is on the city list but not in this client's own pool, goes
through — and is listed under **Exceptions** beneath the table, with the reason
in a sentence. The planner decides.

**The Exceptions list says what it did not look at.** Weekly limits ("biryani
once a week"), composition rules ("one north and one south dry vegetable") and
colour variety exist only inside the solver's model. No amount of reading a
finished menu reveals them, so a pick that breaks one will **not** appear in
the list. Every response therefore carries both halves — what was checked and
what was not — and the panel prints them. A list that looked complete and was
not would be worse than no list.

**Undo** restores the dish the **solver** originally chose, not the previous
pick. Pick twice in one cell to correct yourself and Undo still takes you back
to the start, which is what "undo" has to mean there.

### 2. A pairing layer, mostly declined

Six food pairings were proposed: poori with aloo or chana gravy, south tiffin
with sambar, tandoor bread with a rich north gravy, khichdi with kadhi or
raita, biryani with a salad, biryani with salan.

The layer was built — a new soft preference that says "if A is on the plate, B
should be too" — but each pairing has to earn its place, and the measurements
decided most of it:

- **P1, poori with aloo or chana gravy, was dropped.** Across 150 planned days
  the trigger never once occurred: half the sampled sites pin their bread cell
  outright, and poori is under 4% of the bread pool everywhere else. A rule
  whose condition never arises is weight spent on nothing, and it would have
  read as enforced forever.
- **A pairing aimed at "sambar" would have been inert** on exactly the sites
  where it had something to do. A counter that serves dal and sambar from one
  cell files that cell under a combined name, so the obvious spelling matched
  nothing on 90 of 90 such counters, against 12 with the combined names
  included.
- **The A/B harness that judges these rules now measures its own noise.** It
  did not before, and the figure matters: the planner **does not reproduce its
  own output** — the same client, the same week, the same settings, run twice,
  differ in about **40%** of cells. So a rule that "changed 20% of the menu"
  changed nothing at all. Any figure at or under the floor is now reported as
  noise.

That 40% is a finding in its own right and is not yet explained. It does not
affect the menus — every one of them satisfies the rules — but it means no
before/after comparison of two single runs can be trusted.

### 3. Generating a menu got noticeably faster

A five-day plan took **42.1 seconds**. Half of that was never the solver: it
was the planner reading its own dish lists one row at a time. A city list is
143 columns wide, and the code fetched each candidate dish as its own object —
16,259 times per request — then handed those objects to every rule, each of
which asked them for a column one at a time, about 700,000 times.

Reading each list once instead brings a plan to **25.4 seconds** and the work
done from 38.6 million operations to 7.6 million.

What remains is the solver itself, which now accounts for about 80% of the
time and uses its full allowance by design. Making the tool faster from here
means giving the solver less time to think, which trades menu quality for
speed — an owner's decision, not a code change.

One proposed optimisation was written, measured and **thrown away**: it saved
0.8 milliseconds of a 25-second request and cost 25 lines.

### 4. Smaller things

- **Seasonal bans catch the word the kitchen actually writes.** "Math" for
  amaranth, "adrakh" as well as "adrak", "hara pyaz" for spring onion. Three
  patterns, measured across all five cities.
- **The owner's corrected Pune and Bangalore lists** are installed.
- **Corning Chakan serves flavoured rice or white rice on a day, never both** —
  flavoured on Mon, Tue, Thu, Fri and Sun; plain on Wed and Sat.
- **A shared category the primary counter cannot supply is refused** at
  configuration time instead of quietly diverging later.
- **A plan that pins a dish into a cell a frequency cap forbids** now explains
  the contradiction instead of failing with a blank 500.
- **The page heading tells the truth.** It said "Generated plan for X" from the
  moment a client was selected — before, and during, generating.

## What this does not do

**A pick cannot be saved with its reasons.** The Exceptions list and any note
typed against it live for the session only. Recording them would change the
shape of the saved-menu table that several other features read, and that is
its own piece of work.

**A pick does not re-plan the rest of the day around it.** Put a heavy gravy in
and the rest of the plate stays as it was.

**Weekly limits, composition and colour are not checked on a pick** — see
above. Closing that gap means re-running the solver once per rule with the menu
held fixed, which is a separate design.

**The five remaining pairings are built but not switched on.** P2 to P6 have a
measured opportunity and a budget, and each still needs its own A/B run.

**The planner's own glue for Pick is not covered by tests.** The logic beneath
it is, but the Streamlit layer cannot be reached by the test suite; both bugs
found in this round were found by using it.

**Six sites still cannot plan a third consecutive saved week.** Unchanged from
2.07.03 and still wants a pass of its own.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.07.04 | 6–14 Oct | Darshan + Claude Code | Pick a dish: a planner names the dish, the server refuses only a pinned cell and a repeat inside the ISO week, and reports everything else as a warning while naming what it could not check. A pairing layer built and mostly held back — one pairing dropped on measurement, and the A/B harness now measures a 40% noise floor it did not know it had. A five-day plan 42.1 s → 25.4 s by reading each dish list once. Seasonal bans matched to the kitchen's spelling; corrected Pune and Bangalore lists; Corning Chakan's rice alternation |

**Previous:** [v2.07.03](IkigaiMasala_Final_v2.07.03_2026-10-06.md)  **Next:** —
