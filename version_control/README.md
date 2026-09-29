# Version control

Every released version has one document here, written for whoever runs a
cafeteria or an account — not for a developer.

## Numbering: P.MM.mm

- **P — phase.** `1` the simple tool (one city, under ten sites, one shared
  rulebook). `2` scaling (many cities, client-level configuration, launch
  sites, several services a day). MM and mm reset to 00 when P increments.
- **MM — major.** Approved by the Project Manager. Bundles three or four
  related features built together.
- **mm — minor.** Approved by a team lead. Fixes, refactors, performance, UI
  polish, docs, tests and data corrections inside an existing model.

## File naming

`<Title>_<Status>_v<P.MM.mm>_<YYYY-MM-DD>.md`, e.g.
`IkigaiMasala_Final_v2.05.01_2026-09-23.md`

Status is `Draft`, `Final` or `Revised`. The date is the **last** day of that
version's span.

## Layout

```
version_control/
├── README.md                                    this file
├── CURRENT.md                                   points at the latest version
├── IkigaiMasala_Final_v2.05.01_2026-09-23.md    the master change control record
├── versions/phase-1/                            one document per version
├── versions/phase-2/
└── archive/                                     superseded master records
```

## Releasing a version

1. Move the current master record into `archive/` with `git mv`.
2. Copy it to a new file carrying the new version and date, and add the new row
   at the top of its change control table.
3. Write the version document in `versions/phase-<P>/` from the template used
   by the existing documents — research the version's key commits with
   `git show` and describe what the code does, not what the table summarises.
4. Update `CURRENT.md` and the Previous/Next links either side of the new
   document.
5. Commit as `docs(version): v<P.MM.mm>` and tag that commit.
