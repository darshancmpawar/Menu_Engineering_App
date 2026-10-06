# Version 2.07.02: A Chinese day all the way across, and where a dosa belongs

**Phase:** 2 Scaling  **Date:** 6 Oct 2026  **Status:** Final

## In one line

A themed day now reaches the whole plate instead of only its main dishes, a
south Indian bread is served on a south Indian day, the no-repeat window is
three weeks and provably spans lunch and dinner, and Corning Chakan gets its
chapati and its khichdi cadence.

## What changed

### 1. A Chinese day's soup, salad and bread

Until now a Chinese day changed the rice, the gravy and the non-veg dish and
nothing else. The soup came back Indian, the salad came back Indian, and the
bread came back whatever the dish list happened to offer. Nobody had written
the rule wrongly — it had never been written at all, for a reason worth
keeping: a soup or a salad genuinely carries no cuisine most of the time, so
the system deliberately leaves those alone on a south or north day. An
infused water is not a North Indian dish.

The difference is that this is now **written down per theme** rather than
guessed from the dish's own cuisine tag. On a Chinese day the soup is a
Chinese soup, the salad is a Chinese salad, and the bread is from the chapati
family — plain, flavoured, or the staple the day serves, and nothing else.

Measured across all five dish lists before it was switched on:

| City | Chinese soups | Chinese salads | Chapati-family breads |
|---|---|---|---|
| Bangalore | 27 | 19 | 60 |
| Hyderabad | 27 | 23 | 61 |
| Pune | 8 | 7 | 10 |
| NCR | 7 | **1** | 14 |
| Chennai | 4 | **0** | 12 |

The two marked numbers are why the rule **gives way instead of failing**.
Chennai has no Chinese salad at all, and NCR has exactly one — which is worse
than none for a counter that serves two salads a day, because the second cell
has nothing left to take and the whole menu becomes impossible. So the day
keeps its ordinary salad pool whenever the themed one cannot fill the slot,
and says so: the explanation names the rule that did not hold, rather than
showing a plausible menu with a silent gap in it.

### 2. Dosa, idly and akki roti belong to a south day

A dosa on a biryani Tuesday and an idly on a north Friday were both legal.
They are not any more: the dosa family, the idly and steamed-tiffin family,
uthappam, adai and pesarattu, and the akki / ragi / jowar rotti family are
served on a South Indian day and nowhere else. Everything else — chapati,
paratha, naan, kulcha, poori, parotta — is unaffected and still serves every
other day.

**This nearly shipped half-working.** Written against the dish list's own
dosa and rice-bread markers it looked complete, and a generated week showed
what it actually did: it moved the dosas off the biryani Monday and the mix
Wednesday and left `masala_idli` and `tri_color_idli` standing in their
place. Those markers catch 42 of Chennai's 100 breads; the dish categories
catch 61, and the twenty they add include `idli` itself. The rule now reads
the category first and keeps the markers as a backstop for the handful of
rows filed the other way.

It is also **not** matched on the dish name, which is the obvious shortcut and
wrong here: `appam_chapati` is a plain chapati, `dosakai sambar` is a cucumber
sambar, and "akki" sits inside `sabakki` and `avalakki`.

**Pune does not carry this rule, on purpose.** Its list holds no dosa, no idly
and no uthappam, and the one category that would have matched — `rotis` — is
bajara, jowar and rice *bhakari* in Pune, Maharashtrian bread that has no
business being held back for a South Indian day. A category name does not mean
the same thing in every city, so each city's rule is checked against that
city's own list.

**Chennai is the city where this bites**, and the owner should know it: 62 of
Chennai's 100 breads are now held to the south days, which is the heaviest
share of the five lists, and a Chennai canteen does serve dosa on an ordinary
day. Chapati is already a declared staple there, so no day is left without a
bread — but if the intent was "everywhere except Chennai", this is the rule to
change.

### 3. The regional picker stops overruling the planner

Three fixes to the regional-day feature released in 2.07.01:

- **The R reads across the table.** It is a filled black disc with a white
  letter, sized to be seen, pinned to the right edge of the cell.
- **The theme and the region share one line.** A day carrying both used to
  stack them and grow that column taller than its neighbours. The day is a
  North day *and* a Maharashtra day, not two facts in sequence.
- **Continental and Indo-Chinese can carry a regional day**, and every region
  can be picked on every day. The old gate separated Indian states from
  foreign cuisines, which put Continental (525 Bangalore dishes) and
  Indo-Chinese (262) on the same side of the line as "Pan-North India" — a
  label on 2,092 dishes that is not a cuisine at all. A Continental Friday is
  the same editorial decision as a Maharashtrian one. Measured: Bangalore goes
  from 9 usable regions to 14, Hyderabad 9 to 14, Pune 2 to 5, Chennai 1 to 3.

The second half of that change was checked before it was made, because a
picker that offers an impossible choice is worse than one that refuses: a
regional day is a floor, and the floor already caps itself to what the day can
actually place and reports the shortfall. A mismatched pick therefore comes
back honest and thin and can never make a menu impossible. With that true, the
greyed-out list was the picker deciding something that is the planner's to
decide. A region is greyed out now only when the **city** has nothing deep
enough to carry a day — never because of the day's theme.

### 4. No dish repeats for three weeks, and that spans lunch and dinner

The no-repeat window was twenty days. It is now twenty-one — three weeks, as
asked — and the same number is used in all five city rulebooks, by the rule
itself, by the database lookback and by a new client's default. It used to be
written out separately in three places, which is three things that could
disagree about how long "the window" is.

**It already spanned the two services, and now there is a test saying so.**
A dish served at dinner does not come back at lunch for three weeks, and the
other way round. That guarantee was real but nothing was named after it — it
fell out of three unrelated facts (the history query asks for a client and a
date range and not a service; the reader throws the service away when it
flattens the rows; and saving a week saves both services). Any one of those
could have been "tidied up" by someone who had never heard of the
requirement, and nothing would have failed. There are now twelve checks
holding it in place, including one that reads the history query itself and
fails if a service filter is ever added to it.

Within a single generation the mechanism is different and was already there:
the planner hands lunch's dishes to dinner and they are banned on **every
day** of that week, not just their own — which is the "no repetition at all
in the same week" half.

**One thing the owner has to do.** The three-week window is the default, and
sixty-two of the sixty-six client records carry an explicit twenty-day value
that overrides it. Those are data, in the client table, not configuration in
the code — so they are not changed here. Until they are cleared or raised,
those clients keep a twenty-day window. Say the word and that is a one-off
job.

### 5. Corning Chakan: chapati every day, khichdi once a fortnight and a half

- **The Indian bread is chapati, seven days a week.** Written as a pin rather
  than a rule, because a rule on "the chapati family" lets the slot rotate
  between plain, palak, carrot and beetroot chapati, which is variety where
  the site asked for one bread. Same shape as ICON Chn, DXC, SAEL and Corning
  NCR.
- **Khichdi at most once in three weeks.** Two halves, the pair this site
  already uses for biryani: a twenty-one-day backward window that reads saved
  history, and a weekly cap, because a backward window cannot see the week it
  is planning. Selected by dish category rather than by name — the seven
  khichdis in the Pune list are spelled *khichdi*, *khichadi* and *khicha*
  between them, and they share one category.

## What this means for day-to-day use

Nothing to switch on. Generate as usual: a Chinese day arrives Chinese across
the soup, salad and bread as well as the mains, and a dosa or an idly turns up
only on a south day. Corning Chakan's bread row reads Chapati every day.

On the planner's regional picker, every region your city can cook is now
offered on every day, with a line under the off-theme ones saying what the
day's theme will do to them.

## Known limits

**Chennai's Chinese salad.** There is no such dish in the Chennai list, so a
Chennai Chinese day keeps its ordinary salad and the explanation says so every
time. That is a dish-list matter, not a rule to fix.

**NCR has one Chinese salad.** A one-salad counter gets it; a two-salad counter
keeps the ordinary pool, because one dish cannot fill two cells.

**Chennai's bread pool is the one to watch** — see the paragraph above.

**Pune carries no south-bread rule** and will need one written against its own
list if that list ever gains dosas.

**Sixty-two client records still say twenty days** and override the new
three-week default — see section 4.

**"Khichdi once in three weeks" is enforced as a ceiling, not a floor.** The
rule stops a second khichdi inside twenty-one days; it cannot guarantee one
is served every third week, because a week's menu is planned on its own and
has no way to know it is the third one. A cadence that *requires* something
to appear across plans is a kind of rule the system does not have yet.

**Corning Chakan still serves steamed rice and a flavoured rice on the same
day.** The site asked for one or the other, with the system choosing three or
four flavoured days a week. Neither half is buildable as the planner stands:
steamed rice is a stamped daily constant decided before the solve, and every
solved cell takes exactly one dish, so there is no way to say "this slot runs
on four days of the solver's choosing". Naming the days instead would work
today with no new code, exactly as this site's soup and dessert days already
do. The alternative — letting the one rice slot serve either a plain or a
flavoured rice — is a smaller change but prints "Flavoured Rice: steamed
rice" on the menu, because slot labels are fixed for the whole fleet.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.07.02 | 6 Oct | Darshan + Claude Code | A themed day reaches the whole plate: a Chinese day's soup, salad and bread are named per theme and give way (reporting it) where the list is too thin — Chennai has no Chinese salad, NCR has one. South Indian breads (dosa, idly, uthappam, adai, akki/ragi rotti) restricted to south days, written against dish CATEGORY after the dish-list markers were measured to miss 20 of Chennai's 61. Pune excluded deliberately. No-repeat window 20 → 21 days, one copy of the number instead of three, and the lunch↔dinner span it already had put under test. Corning Chakan: chapati pinned as the daily Indian bread, khichdi capped at one per 21 days. Regional picker: the R made legible and right-aligned, theme and region on one line, Continental and Indo-Chinese admitted as regions, and every region pickable on every day |

**Previous:** [v2.07.01](IkigaiMasala_Final_v2.07.01_2026-10-06.md)  **Next:** [v2.07.03](IkigaiMasala_Final_v2.07.03_2026-10-06.md)
