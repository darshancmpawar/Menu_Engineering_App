# 🚀 Ikigai Masala - Quick Start Guide

## ✅ System is Ready!

Your Indian menu planning system is configured and working with:
- ✅ 530 authentic Indian menu items
- ✅ Traditional 6-course Indian lunch thali
- ✅ North/South Indian cuisine rotation
- ✅ All tests passing (29/29)

---

## 🎯 Quick Command

### Basic Usage (Uses Indian defaults)
```bash
python3 main.py --start-date 2026-01-27 --days 7
```

This will:
1. Load 530 Indian menu items
2. Apply Indian cuisine rules (South/North rotation)
3. Generate 7-day lunch menu plan (6-course thali per day)
4. Export to Excel: `data/outputs/menu_plan_TIMESTAMP.xlsx`

---

## 📋 Command Options

```bash
python3 main.py [OPTIONS]
```

| Option | Description | Default | Example |
|--------|-------------|---------|---------|
| `--start-date` | Planning start date | Today | `2026-01-27` |
| `--days` | Number of days | 7 | `30` |
| `--excel` | Menu data file | `data/raw/menu_items.xlsx` | Custom path |
| `--menu-rules` | Menu rules config | `examples/indian_menu_rules.json` | Custom path |
| `--composition` | Meal structure | `examples/indian_lunch_composition.json` | Custom path |
| `--meal-type` | Meal type | `lunch` | `breakfast`, `dinner` |
| `--force-refresh` | Reprocess data | False | (flag) |

---

## 💡 Common Use Cases

### 1. Plan for Next Week
```bash
python3 main.py --start-date 2026-01-27 --days 7
```

### 2. Plan for Entire Month
```bash
python3 main.py --start-date 2026-02-01 --days 30
```

### 3. Refresh Data & Plan
```bash
python3 main.py --force-refresh --days 14
```

### 4. Custom Date Range
```bash
python3 main.py --start-date 2026-03-01 --days 21
```

---

## 📊 What You Get

### Output File
**Location:** `data/outputs/menu_plan_TIMESTAMP.xlsx`

Contains daily menu plan with:
- Date and day of week
- 6 items per lunch (following thali structure)
- Course types (bread, veg_dry, rice, veg_gravy, nonveg_main, dal)
- Cuisine families (north_indian, south_indian)
- Item names

### Weekly Pattern (Automatic)
| Day | Cuisine | Example Items |
|-----|---------|---------------|
| **Mon** | South Indian | Dosa, Sambar, Chicken 65 |
| **Tue** | North Indian | Roti, Dal Makhani, Paneer |
| **Wed** | South Indian | Idli, Rasam, Fish Curry |
| **Thu** | North Indian | Paratha, Dal, Chicken Curry |
| **Fri** | South Indian | Dosa, Sambar, Egg Curry |

---

## 🔍 Verify Results

### Check Output File
```bash
ls -lh data/outputs/
```

### View Menu Plan
```bash
python3 -c "
import pandas as pd
import glob

files = glob.glob('data/outputs/menu_plan_*.xlsx')
if files:
    df = pd.read_excel(max(files))
    print(df.to_string(index=False))
"
```

### Count Items by Course
```bash
python3 -c "
import pandas as pd
import glob

files = glob.glob('data/outputs/menu_plan_*.xlsx')
if files:
    df = pd.read_excel(max(files))
    print('\nItems per course type:')
    print(df['course_type'].value_counts())
"
```

---

## ✅ Expected Output

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
  Menu items: 530
  Meal type: lunch
  Constraints: 3

Solving with time limit: 300s...
Optimal solution found!

Exported solution to data/outputs/menu_plan_TIMESTAMP.xlsx

✓ Menu planning completed successfully!
```

---

## 🎓 Understanding the System

### 1. Indian Lunch Structure (6 Courses)
Each day's lunch will have:
1. **Bread** (1 item) - Roti, Naan, Dosa, etc.
2. **Veg Dry** (1 item) - Aloo Gobi, Bhindi, etc.
3. **Rice** (1 item) - Jeera Rice, Lemon Rice, etc.
4. **Veg Gravy** (1 item) - Paneer Masala, Curry, etc.
5. **Nonveg Main** (1 item) - Chicken/Egg curry
6. **Dal** (1 item) - Dal Makhani, Dal Tadka, etc.

### 2. Cuisine Constraints
- **Monday, Wednesday, Friday:** South Indian focus
- **Tuesday, Thursday:** North Indian focus

### 3. Menu Database
- **530 authentic items** across 17 course types
- **North Indian:** 225 items (42.5%)
- **South Indian:** 185 items (34.9%)
- **Others:** 120 items (22.6%)

---

## 🛠️ Troubleshooting

### Issue: "No solution found"
**Solution:** Try relaxing rules or adding more items for specific course types

### Issue: "File not found"
**Solution:** Ensure you're in the project root directory
```bash
cd /Users/Abhishek.Ashok/source/ikigai_masala
```

### Issue: "Module not found"
**Solution:** Install dependencies
```bash
pip3 install -r requirements.txt
```

### Issue: Need to reprocess data
**Solution:** Use `--force-refresh` flag
```bash
python3 main.py --force-refresh
```

---

## 📚 Additional Documentation

- **INDIAN_CONTEXT_UPDATE.md** - Detailed transformation to Indian context
- **INDIAN_QUICK_START.md** - Quick reference guide
- **tests/** - Test suite (29 passing tests)

---

## 🎉 You're All Set!

The system is production-ready for Indian lunch menu planning. Simply run:

```bash
python3 main.py --days 7
```

And you'll get a balanced, constraint-compliant 7-day Indian lunch menu! 🍛

---

## 📞 Sample Commands Reference

```bash
# This week
python3 main.py --days 7

# Next month
python3 main.py --start-date 2026-02-01 --days 30

# Force refresh
python3 main.py --force-refresh --days 7

# Specific date range
python3 main.py --start-date 2026-03-15 --days 14
```

**Happy Menu Planning!** 🇮🇳🍛✨
