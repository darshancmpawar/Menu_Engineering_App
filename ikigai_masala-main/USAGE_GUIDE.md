# Ikigai Masala - Usage Guide

## Running the Application

```bash
cd ikigai_masala-main
streamlit run app.py
```

The Streamlit app auto-starts the Flask API backend in a daemon thread on port 5000.

---

## Menu Planner View

### Sidebar Controls

| Control | Description |
|---------|-------------|
| Client | Select which client to generate a plan for |
| Start date | First weekday of the plan |
| Weekdays | Number of weekdays to plan (Sat/Sun skipped) |
| Generate Menu Plan | Run the CP-SAT solver |

### Generated Menu Table

- Each column is a day with a **theme badge** (Mix, Chinese, Biryani, South, North)
- Theme badges reflect the client's per-day theme config, not hardcoded weekday defaults
- Each row is a slot (Welcome Drink, Soup, Starter, Bread, Rice, etc.)
- Items show color suffixes like `(Red)`, `(Yellow)` for visual variety tracking

### Pool Warnings

If any (day, slot) has fewer items available than needed after theme filtering,
a warning section appears above the table:

> "Chinese Tuesday 07 Apr: only 4 veg dry items available, need 3"

This helps identify Ontology gaps before they cause solver failures.

### Actions

| Button | Action |
|--------|--------|
| Save to History | Append plan to history CSVs for cooldown tracking |
| Download CSV | Export the current plan as a CSV file |
| Clear | Reset the plan view |

### Regenerate Cells

Expand the **Regenerate cells** section to replace specific slots on specific days
with fresh items while keeping the rest of the plan locked.

---

## Customisation Editor

Click **Edit Logic** (top right) to enter the editor.

### Section 1: Client Management

- **Select Existing** tab: Choose a client from the dropdown
- **Create New** tab: Enter a name, select a menu category, click Create

### Section 2: Slot Customization

Toggle which base slots are active for the client.
Constant slots (white rice, papad, pickle, chutney) are always included.

### Section 3: Multi-Slot Configuration

Set slot counts for each active slot. For example, `veg_dry: 2` means the client
gets two different veg dry items per day.

### Section 4: Day-wise Theme Override

Override the default Mon=Mix, Tue=Chinese, Wed=Biryani, Thu=South, Fri=North
schedule per client. Changes are highlighted with override badges.

### Action Bar

| Button | Action |
|--------|--------|
| Save | Persist all changes to Supabase |
| Reset to Defaults | Restore all settings to category defaults |
| Delete Client | Remove the client (with confirmation) |

---

## History and Cooldown System

### How History Works

When you click **Save to History**, the plan is appended to two CSV files:

1. **`data/history_long.csv`** -- One row per (date, slot, item) with color suffixes stripped
2. **`data/history_weeks.csv`** -- One row per saved week with a deterministic signature

### Cooldown Constraints

On the next **Generate Menu Plan**, the solver automatically:

| Constraint | Window | Effect |
|------------|--------|--------|
| Item cooldown | 20 days | Bans recently used items per date |
| Rice-bread gap | 10 days | Prevents rice-bread in bread slot if used recently |
| Week signature | 30 days | Prevents identical weekly menu patterns |

Items in constant slots and repeatable items (curd) are exempt from cooldowns.

---

## Data Files

| File | Purpose |
|------|---------|
| `data/raw/menu_items.xlsx` | Master item database (530+ items) |
| `data/configs/indian_menu_rules.json` | 14 menu rule definitions |
| `data/configs/clients.json` | Legacy client config (used by seed script) |
| `data/history_long.csv` | Item-level history (created on first save) |
| `data/history_weeks.csv` | Week-level signatures (created on first save) |

---

## API Endpoints

All endpoints are served by the Flask backend at `http://localhost:5000`.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/plan` | POST | Generate menu plan |
| `/api/v1/regenerate` | POST | Regenerate selected cells |
| `/api/v1/save` | POST | Save plan to history |
| `/api/v1/validate-pools` | POST | Check pool sizes |
| `/api/v1/clients` | GET | List clients |
| `/api/v1/client-config/<name>` | GET | Get client config |
| `/api/v1/client-config/<name>` | PUT | Update client config |
| `/api/v1/client` | POST | Create client |
| `/api/v1/client/<name>` | DELETE | Delete client |
| `/api/v1/editor-metadata` | GET | Editor UI metadata |
| `/api/v1/health` | GET | Health check |
