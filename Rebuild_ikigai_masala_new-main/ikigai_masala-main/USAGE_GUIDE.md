# 🍛 Ikigai Masala - Usage Guide

## 🚀 Quick Start

### Generate Indian Lunch Menu Plan

```bash
python3 main.py --start-date 2026-01-27 --days 7
```

**Output:**
- 📄 `menu_plan_TIMESTAMP.csv` - Clean menu plan (courses × dates)
- 📊 `menu_plan_detailed_TIMESTAMP.xlsx` - Detailed data (all items)

---

## 📊 Output Format

### CSV Output (Main File)

**Format:** Courses as rows, dates as columns

```csv
Course,2026-01-27,2026-01-28,2026-01-29,...
Bread,Tandoori Roti,Plain Chapatti,Garlic Naan,...
Veg Dry,Aloo Gobi,Bhindi Masala,Beans Poriyal,...
Rice,Jeera Rice,Lemon Rice,Coconut Rice,...
Veg Gravy,Paneer Masala,Dal Palak,Mix Veg,...
Nonveg Main,Chicken Curry,Egg Curry,Chicken 65,...
Dal,Dal Makhani,Dal Tadka,Sambar,...
```

**Features:**
- ✅ Shows only selected items per course (as defined in meal composition)
- ✅ One item per course per day (traditional thali)
- ✅ Clean, readable format
- ✅ Easy to import into Excel/Google Sheets

### Excel Output (Detailed)

**Format:** Long format with all details

Columns: `date`, `item_id`, `item_name`, `course_type`, `cuisine_family`

---

## 🎯 Command Options

### Basic Command
```bash
python3 main.py [OPTIONS]
```

### Options

| Option | Default | Description | Example |
|--------|---------|-------------|---------|
| `--start-date` | Today | Start date (YYYY-MM-DD) | `2026-01-27` |
| `--days` | 7 | Number of days | `30` |
| `--meal-type` | `lunch` | Type of meal | `lunch` |
| `--excel` | `data/raw/menu_items.xlsx` | Menu data file | Custom path |
| `--menu-rules` | `examples/indian_menu_rules.json` | Menu rules config | Custom path |
| `--composition` | `examples/indian_lunch_composition.json` | Meal structure | Custom path |
| `--force-refresh` | False | Reprocess data | (flag) |

---

## 💡 Use Cases

### 1. Weekly Menu (Default)
```bash
python3 main.py --days 7
```
Generates 7-day Indian lunch menu

### 2. Monthly Menu
```bash
python3 main.py --start-date 2026-02-01 --days 30
```
Generates entire month's menu

### 3. Custom Date Range
```bash
python3 main.py --start-date 2026-03-01 --days 21
```
Generates 3-week menu starting March 1

### 4. Refresh Data
```bash
python3 main.py --force-refresh --days 14
```
Reprocesses Excel data and generates 2-week menu

---

## 📋 Indian Lunch Structure

### 6-Course Traditional Thali

Each day's lunch includes **exactly 1 item** from each course:

| # | Course | Items Available | Example Items |
|---|--------|-----------------|---------------|
| 1 | **Bread** | 57 items | Roti, Naan, Dosa, Paratha |
| 2 | **Veg Dry** | 47 items | Aloo Gobi, Bhindi Masala |
| 3 | **Rice** | 65 items | Jeera Rice, Lemon Rice |
| 4 | **Veg Gravy** | 53 items | Paneer Masala, Mix Veg |
| 5 | **Nonveg Main** | 70 items | Chicken/Egg Curry |
| 6 | **Dal** | 22 items | Dal Makhani, Dal Tadka |

**Total:** 314 core items for 6-course thali

---

## 🎨 Cuisine Distribution

### Weekly Pattern (Automatic)

| Day | Cuisine | Focus |
|-----|---------|-------|
| **Mon** | South Indian | Dosa, Sambar, Rasam |
| **Tue** | North Indian | Roti, Dal, Curry |
| **Wed** | South Indian | Idli, Sambar, Chutney |
| **Thu** | North Indian | Paratha, Paneer, Dal |
| **Fri** | South Indian | Dosa, Vada, Sambar |
| **Sat** | Mixed | Balanced variety |
| **Sun** | Mixed | Balanced variety |

**Configuration:** `examples/indian_menu_rules.json`

---

## 📊 View Generated Menu

### Quick View (Terminal)
```bash
# View CSV
cat data/outputs/menu_plan_*.csv | head -20

# Pretty print
python3 -c "
import pandas as pd
import glob
df = pd.read_csv(max(glob.glob('data/outputs/menu_plan_*.csv')))
print(df.to_string(index=False))
"
```

### Open in Excel/Sheets
1. Navigate to `data/outputs/`
2. Open `menu_plan_TIMESTAMP.csv`
3. View as spreadsheet

### Analyze Menu
```bash
python3 -c "
import pandas as pd
import glob

# Get latest menu
df = pd.read_csv(max(glob.glob('data/outputs/menu_plan_*.csv')))

print(f'📊 Menu Plan Statistics')
print(f'   Courses: {len(df)}')
print(f'   Days: {len(df.columns) - 1}')
print(f'   Total items planned: {len(df) * (len(df.columns) - 1)}')
"
```

---

## ✅ Expected Output

### Console Output
```
============================================================
STEP 1: DATA PREPROCESSING
============================================================
Loaded existing processed data: 530 items

============================================================
STEP 2: LOADING MENU RULES
============================================================
Loaded menu rules
  - cuisine: south_indian_monday
  - cuisine: north_indian_tuesday_thursday
  - cuisine: south_indian_wednesday_friday

============================================================
STEP 3: LOADING MEAL COMPOSITION
============================================================
Loaded 1 meal structures
  - lunch: 6 courses

============================================================
STEP 4: SOLVING MENU PLAN
============================================================
Starting menu planning solver...
Optimal solution found!

============================================================
MENU PLAN SOLUTION
============================================================
Status: OPTIMAL
Solve Time: 0.01s
📅 Generated menu for 7 days

============================================================
📊 Exported menu plan to data/outputs/menu_plan_TIMESTAMP.csv
   Format: Courses (rows) × Dates (columns)
   Courses: 6
   Days: 7
============================================================
   Detailed data: data/outputs/menu_plan_detailed_TIMESTAMP.xlsx

✓ Menu planning completed successfully!
```

### Files Generated
1. **`menu_plan_TIMESTAMP.csv`** ← Main output (courses × dates)
2. **`menu_plan_detailed_TIMESTAMP.xlsx`** ← Detailed reference

---

## 🎓 Understanding the System

### Data Flow
```
Menu Items (530)
    ↓
Constraints (3 cuisine rules)
    ↓
Meal Structure (6-course thali)
    ↓
CP-SAT Solver (Google OR-Tools)
    ↓
CSV Output (courses × dates)
```

### Optimization
- Maximizes variety across days
- Respects cuisine rules (South/North rotation)
- Ensures balanced meal composition
- Minimizes repetition

### Solving Time
- **Small (7 days):** < 1 second
- **Medium (30 days):** 1-5 seconds
- **Large (90 days):** 5-30 seconds

---

## 🛠️ Troubleshooting

### Issue: "No solution found"
**Cause:** Constraints too strict or insufficient items

**Solutions:**
1. Check if all required course types have items
2. Relax some rules
3. Increase planning horizon

### Issue: "File not found"
**Cause:** Running from wrong directory

**Solution:**
```bash
cd /Users/Abhishek.Ashok/source/ikigai_masala
python3 main.py --days 7
```

### Issue: Want different cuisine distribution
**Solution:** Edit `examples/indian_menu_rules.json`

```json
{
  "name": "south_indian_daily",
  "type": "cuisine",
  "cuisine_family": "south_indian",
  "days_of_week": ["monday", "tuesday", "wednesday"],
  "required": true
}
```

---

## 📚 Configuration Files

### 1. Menu Data
**File:** `data/raw/menu_items.xlsx`
**Columns:** `item_id`, `item_name`, `course_type`, `cuisine_family`
**Items:** 530 authentic Indian dishes

### 2. Meal Composition
**File:** `examples/indian_lunch_composition.json`
**Defines:** 6-course thali structure
**Editable:** Yes (change course requirements)

### 3. Constraints
**File:** `examples/indian_menu_rules.json`
**Defines:** Cuisine distribution rules
**Editable:** Yes (modify weekly pattern)

---

## 🎯 Pro Tips

### 1. Plan in Advance
```bash
# Plan next month early
python3 main.py --start-date 2026-02-01 --days 30
```

### 2. Compare Different Plans
```bash
# Generate multiple plans and pick best
python3 main.py --days 7  # Run multiple times
# Compare CSV outputs in data/outputs/
```

### 3. Export for Sharing
```bash
# CSV is universal format
# Share menu_plan_TIMESTAMP.csv directly
# Opens in Excel, Google Sheets, Numbers
```

### 4. Bulk Planning
```bash
# Plan entire quarter
python3 main.py --start-date 2026-01-01 --days 90
```

---

## 📞 Quick Reference

| Task | Command |
|------|---------|
| Generate weekly menu | `python3 main.py --days 7` |
| Generate monthly menu | `python3 main.py --days 30` |
| Start specific date | `python3 main.py --start-date 2026-02-01` |
| Refresh data | `python3 main.py --force-refresh` |
| View latest menu | `cat data/outputs/menu_plan_*.csv` |
| List all outputs | `ls -lh data/outputs/` |

---

## ✨ Key Features

✅ **Clean CSV Output** - Courses × Dates matrix format
✅ **Indian Context** - 530 authentic items, North/South cuisine
✅ **Fast Solving** - Optimal solution in < 1 second
✅ **Balanced Meals** - Traditional 6-course thali
✅ **Smart Distribution** - Automatic cuisine rotation
✅ **Scalable** - Handle 7-90 days easily
✅ **Production Ready** - Tested with real data

---

**Happy Menu Planning!** 🇮🇳🍛✨
