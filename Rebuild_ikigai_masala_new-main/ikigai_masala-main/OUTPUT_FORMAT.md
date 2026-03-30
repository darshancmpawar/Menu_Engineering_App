# 📊 Output Format - Indian Menu Planner

## ✅ Changes Implemented

### 1. **Clean CSV Output** 
- ✅ Courses as **rows** (Bread, Veg Dry, Rice, Veg Gravy, Nonveg Main, Dal)
- ✅ Dates as **columns** (2026-01-27, 2026-01-28, ...)
- ✅ Shows **only selected items** (1 per course as defined in meal composition)
- ✅ No repetition of all possible solutions

### 2. **Simplified Console Output**
- ✅ Removed verbose solver statistics
- ✅ Shows only: Status, Solve Time, Days generated
- ✅ Clean, minimal output

### 3. **Readable Formatting**
- ✅ Item names: Proper Title Case
- ✅ Underscores replaced with spaces
- ✅ Example: `tandoori_roti` → `Tandoori Roti`

---

## 📄 Output Files

### Primary Output: `menu_plan_TIMESTAMP.csv`

**Format:** Pivot table (courses × dates)

```csv
Course,2026-01-27,2026-01-28,2026-01-29,2026-01-30,2026-01-31,2026-02-01,2026-02-02
Bread,Tandoori Roti,Plain Chapatti,Garlic Naan,Butter Naan,Paratha,Dosa,Roti
Veg Dry,Aloo Gobi,Bhindi Masala,Beans Poriyal,Cabbage Thoran,Carrot Peas,Gobi Manchurian,Mix Veg
Rice,Jeera Rice,Lemon Rice,Coconut Rice,Tomato Rice,Veg Pulao,Biryani,Plain Rice
Veg Gravy,Paneer Masala,Dal Palak,Malai Kofta,Mix Veg Curry,Aloo Matar,Chana Masala,Rajma
Nonveg Main,Chicken Curry,Egg Curry,Chicken 65,Chicken Masala,Egg Masala,Chicken Fry,Fish Curry
Dal,Dal Makhani,Dal Tadka,Sambar,Moong Dal,Masoor Dal,Toor Dal,Dal Fry
```

**Features:**
- Easy to read and share
- Directly opens in Excel/Google Sheets
- One item per course per day
- Following meal composition requirements

### Secondary Output: `menu_plan_detailed_TIMESTAMP.xlsx`

**Format:** Long format with all details

**Columns:**
- `date` - Date of meal
- `item_id` - Unique item identifier
- `item_name` - Item name
- `course_type` - Course category
- `cuisine_family` - Cuisine type (north_indian, south_indian, etc.)

**Usage:** Reference, analysis, detailed records

---

## 🎯 Sample Command

```bash
python3 main.py --start-date 2026-01-27 --days 7
```

---

## 📊 Console Output

### Before (Verbose)
```
MENU PLAN SOLUTION
==================
Solver Statistics:
  Status: OPTIMAL
  Solve Time: 0.01s
  Objective Value: 1554

📅 Menu Plan (7 days):
==================

2026-01-27:
  ACCOMPANIMENT:
    - papad (indian)
    - pickle (indian)
    - schezwan_dip (chinese)
    ... [20+ items listed]
  
  BREAD:
    - tandoori_roti (north_indian)
  
  CHUTNEY:
    - mint_chutney (indian)
    ... [10+ items listed]
```

### After (Clean)
```
============================================================
MENU PLAN SOLUTION
============================================================

Status: OPTIMAL
Solve Time: 0.01s

📅 Generated menu for 7 days
============================================================

============================================================
📊 Exported menu plan to data/outputs/menu_plan_20260123_165826.csv
   Format: Courses (rows) × Dates (columns)
   Courses: 6
   Days: 7
============================================================
   Detailed data: data/outputs/menu_plan_detailed_20260123_165826.xlsx

✓ Menu planning completed successfully!
```

**Improvements:**
- ✅ 90% less console output
- ✅ Only essential information
- ✅ No listing of all possible solutions
- ✅ Focus on actual selected items

---

## 📋 CSV Format Details

### Structure

| Element | Description | Example |
|---------|-------------|---------|
| **First Column** | Course names | Bread, Veg Dry, Rice, etc. |
| **Subsequent Columns** | Dates (YYYY-MM-DD) | 2026-01-27 |
| **Cell Values** | Selected item names | Tandoori Roti |
| **Separator** | For multiple items (if max > 1) | Item1 \| Item2 |

### Meal Composition Compliance

The CSV respects the meal composition configuration:

```json
{
  "course_type": "bread",
  "min_items": 1,
  "max_items": 1  ← Shows exactly 1 item
}
```

If `max_items: 2`, CSV would show: `Item1 | Item2`

---

## 🎨 Formatting Rules

### Item Names
- **Source:** `tandoori_roti`
- **Output:** `Tandoori Roti`
- **Rules:**
  1. Replace underscores with spaces
  2. Apply Title Case
  3. Clean and readable

### Course Names
- **Source:** `veg_dry`
- **Output:** `Veg Dry`
- **Rules:**
  1. Replace underscores with spaces
  2. Apply Title Case

### Dates
- **Format:** `YYYY-MM-DD`
- **Example:** `2026-01-27`
- **Sortable:** Yes (chronological order)

---

## 📈 Example Outputs

### Weekly Menu (7 days)
```csv
Course,2026-01-27,2026-01-28,...
Bread,Tandoori Roti,Chapatti,...
Veg Dry,Aloo Gobi,Bhindi,...
...
```
**Size:** 6 rows × 8 columns (1 course column + 7 date columns)

### Monthly Menu (30 days)
```csv
Course,2026-02-01,2026-02-02,...,2026-02-30
Bread,Naan,Roti,Paratha,...
...
```
**Size:** 6 rows × 31 columns (1 course column + 30 date columns)

---

## 🔍 Viewing the Output

### In Terminal
```bash
cat data/outputs/menu_plan_*.csv
```

### In Excel/Sheets
1. Open `data/outputs/menu_plan_TIMESTAMP.csv`
2. View as spreadsheet
3. Courses are rows, dates are columns

### In Python
```python
import pandas as pd
df = pd.read_csv('data/outputs/menu_plan_*.csv')
print(df.to_string(index=False))
```

---

## ✅ Benefits

### 1. **Easy to Read**
- Clean matrix format
- Clear course-to-date mapping
- No clutter

### 2. **Easy to Share**
- Standard CSV format
- Opens in any spreadsheet software
- Universal compatibility

### 3. **Easy to Use**
- One row per course
- One column per date
- Direct lookup: Course + Date → Item

### 4. **Meal Composition Compliant**
- Shows exact items as defined
- Respects min/max requirements
- No extra items displayed

### 5. **Professional**
- Clean formatting
- Proper capitalization
- Production-ready output

---

## 🎯 Use Cases

### 1. Kitchen Planning
- Print CSV
- Stick on kitchen wall
- Daily reference for chef

### 2. Procurement
- See weekly/monthly requirements
- Plan ingredient purchasing
- Inventory management

### 3. Client Communication
- Share with clients
- Show upcoming menus
- Get approvals

### 4. Record Keeping
- Archive past menus
- Track what was served
- Audit trail

---

## 📞 Quick Reference

```bash
# Generate menu
python3 main.py --days 7

# Output files
data/outputs/menu_plan_TIMESTAMP.csv        ← Main (courses × dates)
data/outputs/menu_plan_detailed_TIMESTAMP.xlsx  ← Detailed

# View output
cat data/outputs/menu_plan_*.csv

# Format
Rows: Courses (6)
Columns: Dates (7/30/90)
Content: Selected items only
```

---

## ✨ Summary

✅ **CSV Format:** Courses as rows, dates as columns
✅ **Shows:** Only selected items (as per meal composition)
✅ **Clean:** Proper formatting, no underscores
✅ **Minimal:** No verbose solver statistics
✅ **Professional:** Production-ready output
✅ **Universal:** Works with Excel, Sheets, Numbers

**Perfect for kitchen planning, client sharing, and record keeping!** 🍛📊✨
