# Output Format

## Generated Menu Table (UI)

The Streamlit UI renders the menu as an HTML table:

- **Columns**: One per weekday, with date and theme badge
- **Rows**: One per active slot (Welcome Drink, Soup, Salad, Starter, Bread, Rice, etc.)
- **Cells**: Item name with color suffix displayed as colored label

### Theme Badges

Each day column shows a badge reflecting the client's theme config:

| Theme | Badge Color | Background |
|-------|------------|------------|
| Mix | Green | `#22543d` |
| Chinese | Orange | `#7c2d12` |
| Biryani | Red | `#7f1d1d` |
| South | Blue | `#1e3a5f` |
| North | Purple | `#4c1d95` |

### Color Suffixes

Items include a color indicator from the item database:

| Code | Color | CSS |
|------|-------|-----|
| R | Red | `#ef4444` |
| G | Green | `#22c55e` |
| B | Brown | `#a16207` |
| Y | Yellow | `#eab308` |
| W | White | `#a1a1aa` |
| O | Orange | `#f97316` |
| K | Black | `#71717a` |

---

## CSV Download

The **Download CSV** button exports a plain-text CSV:

```csv
Slot,2026-03-31,2026-04-01,2026-04-02,...
Welcome Drink,Masala Chaas,Jaljeera,...
Soup,Tomato Soup,Sweet Corn Soup,...
Starter,Paneer Tikka,Hara Bhara Kebab,...
Bread,Tandoori Roti,Garlic Naan,...
Flavor Rice,Jeera Rice,Lemon Rice,...
...
```

- Slot names are display-formatted (e.g. `veg_dry` becomes `Veg Dry`)
- Items are cleaned (color suffixes stripped, title-cased)

---

## API Response Format

The `/api/v1/plan` endpoint returns:

```json
{
  "success": true,
  "message": "Menu plan generated for ClientName",
  "solution": {
    "2026-03-31": {
      "theme": "Mix of South + North",
      "day_type": "mix",
      "items": {
        "welcome_drink": {
          "display_name": "Welcome Drink",
          "item": "masala_chaas(Y)",
          "item_base": "masala_chaas"
        },
        "rice": { ... },
        "veg_dry": { ... }
      }
    }
  },
  "pool_warnings": [
    "Chinese Tuesday 01 Apr: only 4 veg dry items available, need 3"
  ]
}
```

---

## History CSV Schemas

### history_long.csv

Written on **Save to History**. One row per (date, slot, item):

```csv
service_date,slot,item_base,client_name
2026-03-31,rice,jeera_rice,rippling
2026-03-31,veg_dry,aloo_gobi,rippling
```

- `item_base` has color suffixes stripped
- `client_name` is lowercase-normalized

### history_weeks.csv

One row per saved week plan:

```csv
week_start,week_signature,client_name
2026-03-31,2026-03-31|rice=jeera_rice|veg_dry=aloo_gobi|...,rippling
```

- Signature is a deterministic `|`-delimited string of all slot assignments
- Used by the 30-day week signature cooldown rule
