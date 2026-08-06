# Source workbooks — the provenance of every derived rule

Every workbook that arrived from the client, in one place, one per city where the
city has one. **These are inputs, not runtime data.** Nothing in the app reads
this directory: the app reads `../city_items/<city>.xlsx`, which is what
`scripts/normalize_city_ontology.py` produces *from* the raw lists here.

They are committed because the derived artefacts cite them. `docs/pune_rulebook.md`
transcribes R1–R70 from `pune_menu_rulebook_101.xlsx`; every Toast Tab CHN rule was
read off the grid in `chennai_sample_menu.xlsx`. Without the sources in the repo,
the reasoning behind a rule is unverifiable — you can see *that* a cap is 3 but not
*why* — and re-deriving it means asking the client for the file again.

`bangalore_menu_samples_1.xlsx` was briefly here too and has been removed: all 14
of its sheets are byte-identical to sheets in `bangalore_menu_samples_history.xlsx`
(which has 32), so it was a strict subset and a second copy to keep in sync.

Only Bangalore's sample history was committed before; Pune's and Chennai's raw
lists, the Pune rulebook and Chennai's sample menu existed only as chat
attachments and would have been lost.

| File | City | What it is | Used to produce |
|---|---|---|---|
| `bangalore_menu_samples_history.xlsx` | Bangalore | printed menus as served | `docs/client_logics.md` |
| `pune_menu_items_raw.xlsx` | Pune | raw item list before normalisation | `city_items/pune.xlsx` |
| `pune_menu_rulebook_101.xlsx` | Pune | **the 70-rule rulebook** | `docs/pune_rulebook.md`, `configs/city_rules/pune.json` |
| `chennai_menu_items_raw.xlsx` | Chennai | raw item list, incl. its own `Mapping_Log` sheet | `city_items/chennai.xlsx` |
| `chennai_sample_menu.xlsx` | Chennai | Toast Tab's 7-day service history (sheet `Toasttab`) | `docs/chennai_client_logic.md`, the `ToastTab CHN` client rules |
| `bangalore_client_logics.xlsx` | Bangalore | **the Bangalore rulebook** — 158 logic statements across 32 clients, hard and soft mixed together, in one sheet named `Banglore`. This is the main regional ruleset; it is per-CLIENT logics rather than city-level rules | `docs/client_logics.md`, the Bangalore entries in `configs/client_rules.json` |
| `NCR_menu_items.xlsx` | NCR | pre-mapped item list (already in master schema) for 8 NCR clients, with its own `Mapping_Log` / `Review_Required` / `Data_Quality_Log` sheets. **Its `ACCEPT_REVIEW` fuzzy matches are the provenance for `scripts/ncr_fuzzy_unmerge.py`** — the reversal cites the exact merges it undoes | `city_items/ncr.xlsx`, `docs/ncr_client_logic.md` |

## Adding a city

1. Drop the raw item list here as `<city>_menu_items_raw.xlsx`, plus any rulebook
   or sample menu.
2. `python scripts/normalize_city_ontology.py <city> data/raw/source_workbooks/<city>_menu_items_raw.xlsx --dry-run`
   then again without `--dry-run` to write `city_items/<city>.xlsx`.
3. Re-run the correction scripts — the normaliser rebuilds the workbook from the
   raw list and drops hand-applied fixes: `scripts/seafood_taxonomy.py`,
   `scripts/pune_flag_corrections.py`, `scripts/course_type_corrections.py`,
   `scripts/remove_generic_rows.py`, `scripts/dessert_cuisine_corrections.py`,
   and (NCR only) `scripts/ncr_cuisine_corrections.py` +
   `scripts/ncr_fuzzy_unmerge.py`. Each is idempotent, and each has a test that
   fails if its corrections are missing.
4. Re-run `scripts/build_pool_token_map.py` so `city_items/pool_tokens.json`
   picks up the new city (keeps `/editor-metadata` fast).
5. Declare the city's categories in `city_items/ontology_categories.json`.
