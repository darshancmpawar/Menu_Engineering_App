# Version 2.07.01: Corning Chakan's rules corrected, regional dishes marked

**Phase:** 2 Scaling  **Date:** 6 Oct 2026  **Status:** Final

## What changed

**Corning Chakan's menu rules were audited against the site's own written
guidelines**, all twenty-three of them, checked against the sixty-one rules
actually in force for that site rather than against the file they are written
in. Three were wrong, and each was wrong in a way that looked right:

- **Sprouts gravy** was set to "no more than twice a week" for a guideline
  that asks for "at least twice a week". A ceiling is satisfied by serving
  none, so the requirement read as handled and was not. It is now a floor and
  a ceiling: the site gets two, no more and no fewer.
- **Leafy vegetables** was set to "exactly two every week" for a guideline
  that says "only two per week". That forced two leafy dishes into every
  menu. It is now a limit.
- **Biryani once in fifteen days** had nothing enforcing it. The nearest
  existing rule is weekly, which permits two biryanis inside any fifteen
  days, and it only recognised part of the biryani family.

The biryani rule took two attempts, and both failures were found by generating
a real week rather than by reading the configuration:

1. Written against the dish list's biryani flag, it was nearly inert — that
   flag is set on three of the fifteen biryanis in the Pune list. It now also
   matches the dish name. **The twelve unflagged biryanis are a dish-list
   matter for whoever owns the list.**
2. Even then, a real week served a biryani on the Thursday and another on the
   Saturday. A fifteen-day rule only looks backwards at what was saved before;
   it cannot see the week it is planning. It needs a weekly limit beside it,
   which is exactly the pair the Pune rulebook already uses for kadhi.

**The chaat counter is working.** Its two rules were written while the counter
had no starter station and were inert; the station exists now, and a generated
week puts a chaat on the Thursday and nothing on the other six days. The note
in the rule file saying otherwise was out of date and is gone.

**Regional days now show on the menu.** A regional day is a floor, not a
filter — asking for a Maharashtra Thursday serves a few Maharashtrian dishes
and leaves the rest of the plate ordinary — so until now the table said
nothing about either half. The day header names the region beside the cuisine
theme, and the dishes that carry it are marked with a small **R** in the same
colour, because they are one fact seen twice: the header says the day is a
Maharashtra day, the R says which dishes make it one.

## Why it matters

A rule that enforces the opposite of what was asked is worse than a missing
one, because nobody goes looking for it. Corning Chakan had been generating
menus that could serve no sprouts gravy at all while the requirement sat in
the file looking satisfied, and that could serve two biryanis in a week
against a guideline of one per fortnight.

The site now has a test that generates a real seven-day menu and reads ten of
its guarantees off the **menu** rather than off the configuration — the
sprouts floor, the leafy limit, one biryani, soup only on its four days,
sweets only on their three, a chaat only on Thursday, no liquid sweets, and
exactly one paneer gravy. All three defects above were invisible in the
configuration: two were limits pointing the wrong way, and the third loaded,
validated, and constrained nothing.

The regional marking closes a gap of the same kind. The planner could ask for
a Tamil Nadu Thursday and then had no way to see what that bought: the menu
looked like any other day. Now the dishes the region paid for are visible, so
a planner can tell a thin regional day from a full one at a glance instead of
checking dish by dish.

## Known limits

Four of Corning Chakan's guidelines remain unenforced, three of them because
they need something outside the rules:

- **"Besan items no more than twice a week"** needs a besan marker in the Pune
  dish list; five dishes carry the word in their name and thirty-one are
  pakoda, bhaji or bajji.
- **"Variety across the chutney option"** — the site's counter has no chutney
  station configured.
- **"Whenever kadi is served in dal, rice should be dal khichdi"** needs a new
  kind of rule: nothing today can say "this dish on a day requires that dish
  on the same day". It also needs a question settled first — the Pune list
  files kadhi as a gravy and as a curd side, never as a dal, so a rule written
  against the dal station would match nothing.
- **The Wednesday sweet list** (gajar halwa, moong dal halwa, stuffed kala
  jamun, mawa burfi, jalebi-rabadi, chocolate brownie) is not enforced; all
  six are in the Pune list.

Separately, the site serves seven days a week but its weekday themes are set
for Monday to Friday only, so Saturday and Sunday carry no theme.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.07.01 | 5–6 Oct | Darshan + Claude Code | Corning Chakan audit: sprouts gravy and leafy corrected (both enforcing the opposite of the guideline), biryani once-in-15-days added (nothing enforced it), stale chaat-counter note removed, and a test that reads ten guarantees off a generated week. Regional days marked on the table: the region named in the day header, an R on the dishes that carry it |

**Previous:** [v2.07.00](IkigaiMasala_Final_v2.07.00_2026-10-05.md)  **Next:** —
