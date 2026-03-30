# app.py
from __future__ import annotations

import sys
import tempfile
import datetime as dt
import importlib.util
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pandas as pd
import streamlit as st

import client_logic


# -----------------------------
# Page config + paths
# -----------------------------
st.set_page_config(page_title="Menu Engineering – Weekly Generator", layout="wide")
APP_DIR = Path(__file__).resolve().parent

GEN_SCRIPT_PATH = (APP_DIR / "menu_eng_latest_v27.py").resolve()
ONTOLOGY_PATH = (APP_DIR / "Ontology.xlsx").resolve()
NEW_ONTOLOGY_PATH = (APP_DIR / "new_Ontology.xlsx").resolve()
SHEET_NAME = "Sheet1"

HIST_LONG_PATH = APP_DIR / "historical_menu_long.csv"
HIST_WEEKS_PATH = APP_DIR / "historical_menu_weeks.csv"

# Hidden defaults
ITEM_COOLDOWN_DAYS = 20
MENU_COOLDOWN_DAYS = 30
RICE_BREAD_GAP_DAYS = 10
TIME_LIMIT_SEC = 240
MAX_ATTEMPTS = 500_000  # compatibility with generator Config
SEED = 7
DEFAULT_CONST_SLOTS = ("white_rice", "papad", "pickle", "chutney")

st.title("Weekly Menu Generator")


# -----------------------------
# Dynamic import of generator
# -----------------------------
@st.cache_resource(show_spinner=False)
def load_generator_module(script_abs_path: str, mtime_ns: int):
    """
    Important:
    - mtime_ns busts Streamlit cache on every file edit.
    - module must be inserted into sys.modules before exec_module()
      for Python 3.13 dataclass compatibility.
    """
    path_id = hashlib.sha1(script_abs_path.encode("utf-8")).hexdigest()[:12]
    module_name = f"menu_generator_{path_id}_{mtime_ns}"

    spec = importlib.util.spec_from_file_location(module_name, script_abs_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import generator: {script_abs_path}")

    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def get_gen():
    return load_generator_module(str(GEN_SCRIPT_PATH), GEN_SCRIPT_PATH.stat().st_mtime_ns)


# -----------------------------
# Core helpers
# -----------------------------
def resolve_ontology_path() -> Path | None:
    for p in (ONTOLOGY_PATH, NEW_ONTOLOGY_PATH):
        if p.exists():
            return p
    return None


def _slot_profile_for_client(client_name: str) -> Tuple[Dict[str, int], List[str]]:
    return (
        client_logic.get_slot_counts_for_client(client_name),
        client_logic.get_slots_for_client(client_name),
    )


def _apply_runtime_cfg(cfg, start_date: dt.date, days_to_gen: int, slot_counts: Dict[str, int]) -> None:
    cfg.start_date = start_date
    cfg.days = days_to_gen
    cfg.seed = SEED
    cfg.time_limit_sec = TIME_LIMIT_SEC
    cfg.max_attempts = MAX_ATTEMPTS
    cfg.slot_counts = slot_counts


def require_files_or_stop() -> Path:
    if not GEN_SCRIPT_PATH.exists():
        st.error("menu_eng_latest_v27.py not found in this folder.")
        st.stop()

    ontology = resolve_ontology_path()
    if ontology is None:
        st.error("Ontology.xlsx (or new_Ontology.xlsx) not found in this folder.")
        st.stop()

    return ontology


def chk_col(day_col: str) -> str:
    return f"__chk__{day_col}"


def this_weeks_monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def plan_days_mon_to_fri(start_date: dt.date) -> int:
    """Mon->5, Tue->4, Wed->3, Thu->2, Fri->1, Sat/Sun->0."""
    wd = start_date.weekday()
    return 0 if wd > 4 else (5 - wd)


def _norm_client(x: str) -> str:
    return str(x or "").strip().lower()


def _pretty_text(s: str) -> str:
    s = str(s or "").strip()
    if not s:
        return ""
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s.title()


def _pretty_color(s: str) -> str:
    s = str(s or "").strip().lower().replace(" ", "_")
    if s in ("", "na", "nan", "null", "none", "unknown", "unk"):
        return ""
    return _pretty_text(s)


def _build_item_to_color(df: pd.DataFrame) -> Dict[str, str]:
    if df is None or len(df) == 0:
        return {}
    if "item" not in df.columns or "item_color" not in df.columns:
        return {}

    out: Dict[str, str] = {}
    for it, col in zip(df["item"].astype(str), df["item_color"].astype(str)):
        key = it.strip().lower()
        if key:
            out[key] = col.strip().lower()
    return out


def _format_item_for_ui(gen, raw_value: str, item_to_color: Dict[str, str]) -> str:
    raw_value = str(raw_value or "").strip()
    if not raw_value:
        return ""

    base = gen._strip_color_suffix(raw_value) if hasattr(gen, "_strip_color_suffix") else raw_value
    base_norm = str(base).strip().lower()

    pretty_item = _pretty_text(base_norm)
    pretty_col = _pretty_color(item_to_color.get(base_norm, ""))

    return f"{pretty_item} ({pretty_col})" if pretty_col else pretty_item


def _base_slot_id(slot_id: str) -> str:
    if "__" in slot_id:
        left, right = slot_id.rsplit("__", 1)
        if right.isdigit():
            return left
    return slot_id


# -----------------------------
# History I/O
# -----------------------------
def _ensure_history_schema(long_df: pd.DataFrame, weeks_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    # long history: one row per (day, slot)
    long_cols = [
        "saved_at", "week_start", "client_name", "service_date",
        "slot", "item_display", "item_base", "week_signature",
    ]
    for c in long_cols:
        if c not in long_df.columns:
            long_df[c] = ""
    long_df = long_df[long_cols].copy()

    # week history: one row per saved week signature
    week_cols = ["saved_at", "week_start", "client_name", "week_signature"]
    for c in week_cols:
        if c not in weeks_df.columns:
            weeks_df[c] = ""
    weeks_df = weeks_df[week_cols].copy()

    return long_df, weeks_df


def read_history() -> Tuple[pd.DataFrame, pd.DataFrame]:
    long_df = pd.read_csv(HIST_LONG_PATH) if HIST_LONG_PATH.exists() else pd.DataFrame()
    weeks_df = pd.read_csv(HIST_WEEKS_PATH) if HIST_WEEKS_PATH.exists() else pd.DataFrame()
    return _ensure_history_schema(long_df, weeks_df)


def append_history(gen, client_name: str, week_plan: dict, dates: List[dt.date], week_start: dt.date):
    long_df, weeks_df = read_history()
    client_norm = _norm_client(client_name)
    week_sig = gen.compute_week_signature(week_plan, dates)

    # Prevent duplicate save for same (client, week_start, signature)
    if len(weeks_df) > 0:
        w = weeks_df.copy()
        w["week_start"] = pd.to_datetime(w["week_start"], errors="coerce").dt.date
        w["client_name_norm"] = w["client_name"].map(_norm_client)
        dup = (
            (w["week_start"] == week_start)
            & (w["week_signature"] == week_sig)
            & (w["client_name_norm"] == client_norm)
        )
        if dup.any():
            return False, "This week (same signature) is already saved for this client."

    saved_at = dt.datetime.now().isoformat(timespec="seconds")

    weeks_df = pd.concat(
        [
            weeks_df,
            pd.DataFrame(
                [
                    {
                        "saved_at": saved_at,
                        "week_start": week_start.isoformat(),
                        "client_name": client_name,
                        "week_signature": week_sig,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    # Preserve exact slot IDs in save (supports veg_dry__2, etc.)
    slot_order: List[str] = []
    for d in dates:
        if week_plan.get(d):
            slot_order = list(week_plan[d].keys())
            break

    rows: List[dict] = []
    for d in dates:
        for slot in slot_order:
            item_display = week_plan.get(d, {}).get(slot, "")
            # item_base must remain canonical for cooldown checks
            item_base = gen._strip_color_suffix(item_display) if hasattr(gen, "_strip_color_suffix") else str(item_display)
            rows.append(
                {
                    "saved_at": saved_at,
                    "week_start": week_start.isoformat(),
                    "client_name": client_name,
                    "service_date": d.isoformat(),
                    "slot": slot,
                    "item_display": item_display,
                    "item_base": str(item_base).strip().lower(),
                    "week_signature": week_sig,
                }
            )

    long_df = pd.concat([long_df, pd.DataFrame(rows)], ignore_index=True)

    long_df.to_csv(HIST_LONG_PATH, index=False, encoding="utf-8")
    weeks_df.to_csv(HIST_WEEKS_PATH, index=False, encoding="utf-8")

    return True, f"Saved to history for client={client_name} | week_start={week_start.isoformat()}."


# -----------------------------
# Table builders
# -----------------------------
def _display_label_for_slot_id(gen, slot_id: str) -> str:
    base = slot_id
    num = None
    if "__" in slot_id:
        left, right = slot_id.rsplit("__", 1)
        if right.isdigit():
            base = left
            num = int(right)

    display_name_map = getattr(gen, "DISPLAY_SLOT_NAME", {}) or {}
    base_disp = display_name_map.get(base, base)
    return base_disp if num is None else f"{base_disp} {num}"


def build_display_table(
    gen,
    week_plan: dict,
    dates: List[dt.date],
    allowed_slot_ids: List[str],
    item_to_color: Dict[str, str],
):
    # Column labels by day
    col_names: List[str] = []
    col_to_date: Dict[str, dt.date] = {}
    for d in dates:
        day_type = gen._weekday_type(d)
        theme = gen._theme_label(day_type)
        col = f"{theme}-{d.strftime('%A')}({d.isoformat()})"
        col_names.append(col)
        col_to_date[col] = d

    data = {c: [] for c in col_names}
    display_to_slot: Dict[str, str] = {}
    rows: List[str] = []

    # Keep row order exactly as client slot profile
    for slot_id in allowed_slot_ids:
        disp_row = _display_label_for_slot_id(gen, slot_id)
        rows.append(disp_row)
        display_to_slot[disp_row] = slot_id

        for col in col_names:
            dd = col_to_date[col]
            raw = week_plan.get(dd, {}).get(slot_id, "")
            data[col].append(_format_item_for_ui(gen, raw, item_to_color))

    df = pd.DataFrame(data, index=rows)
    return df, col_to_date, display_to_slot


def build_editor_df(menu_df: pd.DataFrame):
    # One checkbox column per day + one text column per day
    df = menu_df.copy()
    df = df.where(pd.notna(df), "")
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    editor_df = pd.DataFrame(index=df.index)

    cols_order: List[str] = []
    item_cols: List[str] = []
    col_config: Dict[str, object] = {}

    for col in df.columns:
        tick = chk_col(col)
        editor_df[tick] = False
        editor_df[col] = df[col]
        cols_order.extend([tick, col])
        item_cols.append(col)
        col_config[tick] = st.column_config.CheckboxColumn("✅", width="small")

    return editor_df[cols_order], item_cols, col_config


def count_selected(edited_df: pd.DataFrame, menu_cols: List[str]) -> int:
    total = 0
    for c in menu_cols:
        t = chk_col(c)
        if t in edited_df.columns:
            total += int(edited_df[t].sum())
    return total


def build_replace_mask(
    edited_df: pd.DataFrame,
    menu_cols: List[str],
    col_to_date: Dict[str, dt.date],
    display_to_slot: Dict[str, str],
    gen,
):
    # replace_mask uses exact slot IDs (including repeated slot suffixes)
    const_slots = set(getattr(gen, "CONST_SLOTS", DEFAULT_CONST_SLOTS))
    replace_mask: Dict[dt.date, Set[str]] = {}

    for day_col in menu_cols:
        tick_col = chk_col(day_col)
        if tick_col not in edited_df.columns:
            continue

        d = col_to_date[day_col]
        for disp_row in edited_df.index:
            if bool(edited_df.loc[disp_row, tick_col]) is not True:
                continue

            slot_id = display_to_slot.get(disp_row)
            if not slot_id:
                continue

            base = _base_slot_id(slot_id)
            if slot_id in const_slots or base in const_slots:
                continue

            replace_mask.setdefault(d, set()).add(slot_id)

    return replace_mask


def menu_df_to_xlsx_bytes(menu_df: pd.DataFrame) -> bytes:
    # Export exactly what user sees in UI
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp_path = Path(tmp.name)
    try:
        menu_df.to_excel(tmp_path, sheet_name="menu", index=True)
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)


def apply_menu_view_state(gen, week_plan: dict, dates: List[dt.date], allowed_slots: List[str], item_to_color: Dict[str, str]):
    menu_df, col_to_date, display_to_slot = build_display_table(gen, week_plan, dates, allowed_slots, item_to_color)
    editor_df, item_cols, col_config = build_editor_df(menu_df)

    st.session_state["menu_df"] = menu_df
    st.session_state["col_to_date"] = col_to_date
    st.session_state["display_to_slot"] = display_to_slot
    st.session_state["editor_df"] = editor_df
    st.session_state["item_cols"] = item_cols
    st.session_state["col_config"] = col_config
    st.session_state["menu_cols"] = list(menu_df.columns)


def refresh_view_if_needed():
    if "week_plan" not in st.session_state or "dates" not in st.session_state:
        return
    if st.session_state.get("_view_client") == st.session_state.get("client_name"):
        return

    gen = get_gen()
    allowed_slots = st.session_state.get("allowed_slots") or []
    item_to_color = st.session_state.get("item_to_color", {})
    apply_menu_view_state(gen, st.session_state["week_plan"], st.session_state["dates"], allowed_slots, item_to_color)

    st.session_state["last_changes"] = []
    st.session_state["_view_client"] = st.session_state.get("client_name")


# -----------------------------
# UI: client + date
# -----------------------------
row = st.columns([1.2, 1.0], gap="medium")
client_names = client_logic.get_client_names()
client_name = row[0].selectbox("Client", options=client_names, index=0)

default_date = this_weeks_monday(dt.date.today())
start_date = row[1].date_input("Start date (Mon–Fri)", value=default_date)

st.session_state["client_name"] = client_name
slot_counts, allowed_slots = _slot_profile_for_client(client_name)
st.session_state["slot_counts"] = slot_counts
st.session_state["allowed_slots"] = allowed_slots

days_to_gen = plan_days_mon_to_fri(start_date)
if start_date.weekday() > 4:
    st.warning(
        f"You selected **{start_date.strftime('%A')}** ({start_date.isoformat()}). "
        "Menu generation is only for **Mon–Fri**."
    )
else:
    end_date = start_date + dt.timedelta(days=days_to_gen - 1)
    if start_date.weekday() != 0:
        st.warning(
            f"You selected **{start_date.strftime('%A')}** ({start_date.isoformat()}). "
            f"Menu will be generated for **{start_date.strftime('%a')} → {end_date.strftime('%a')}** "
            f"({start_date.isoformat()} → {end_date.isoformat()}) only."
        )
    else:
        st.caption(f"Will generate **Mon–Fri**: {start_date.isoformat()} → {end_date.isoformat()}")

btns = st.columns(4, gap="medium")
generate_clicked = btns[0].button("Generate", type="primary", use_container_width=True)
regen_clicked = btns[1].button("Regenerate selected", use_container_width=True, disabled=("week_plan" not in st.session_state))
save_clicked = btns[2].button("Save", use_container_width=True, disabled=("week_plan" not in st.session_state))
clear_clicked = btns[3].button("Clear checks", use_container_width=True, disabled=("editor_df" not in st.session_state))

st.caption("Tip: If you change Bread, also tick Starter (rice-bread ⇒ deep-fried starter).")
st.divider()

refresh_view_if_needed()


# -----------------------------
# Actions
# -----------------------------
if clear_clicked and "editor_df" in st.session_state:
    df0 = st.session_state["editor_df"].copy()
    for c in st.session_state.get("menu_cols", []):
        t = chk_col(c)
        if t in df0.columns:
            df0[t] = False
    st.session_state["editor_df"] = df0
    st.rerun()


if generate_clicked:
    if days_to_gen <= 0:
        st.error("Please select a weekday (Mon–Fri).")
        st.stop()

    ontology_path = require_files_or_stop()
    gen = get_gen()
    history_long, history_weeks = read_history()

    with st.spinner("Generating menu..."):
        df, pools, cfg, meta = gen.load_df(str(ontology_path), SHEET_NAME)
        _apply_runtime_cfg(cfg, start_date, days_to_gen, st.session_state.get("slot_counts", {}))

        st.session_state["item_to_color"] = _build_item_to_color(df)

        week_plan, dates = gen.plan_week(
            df, pools, cfg, meta,
            history_long_df=history_long,
            history_weeks_df=history_weeks,
            client_name=client_name,
            item_cooldown_days=ITEM_COOLDOWN_DAYS,
            menu_cooldown_days=MENU_COOLDOWN_DAYS,
            rice_bread_gap_days=RICE_BREAD_GAP_DAYS,
        )

        st.session_state["df"] = df
        st.session_state["pools"] = pools
        st.session_state["cfg"] = cfg
        st.session_state["meta"] = meta
        st.session_state["week_plan"] = week_plan
        st.session_state["dates"] = dates

        apply_menu_view_state(
            gen=gen,
            week_plan=week_plan,
            dates=dates,
            allowed_slots=st.session_state.get("allowed_slots") or [],
            item_to_color=st.session_state.get("item_to_color", {}),
        )

        st.session_state["last_changes"] = []
        st.session_state["_view_client"] = st.session_state.get("client_name")
        st.session_state["_generated_start_date"] = start_date.isoformat()

    st.success("Menu generated!")


if regen_clicked and "week_plan" in st.session_state:
    gen = get_gen()
    edited_df = st.session_state.get("editor_df")

    if not isinstance(edited_df, pd.DataFrame):
        st.error("Editor data is not a table. Tick ✅ again and retry.")
        st.stop()

    menu_cols = st.session_state["menu_cols"]
    col_to_date = st.session_state["col_to_date"]
    display_to_slot = st.session_state["display_to_slot"]

    replace_mask = build_replace_mask(edited_df, menu_cols, col_to_date, display_to_slot, gen)
    total = sum(len(v) for v in replace_mask.values())

    if total == 0:
        st.info("Tick ✅ cells you want to replace, then click Regenerate selected.")
    else:
        history_long, history_weeks = read_history()
        old_menu_df = st.session_state["menu_df"].copy()

        with st.spinner(f"Regenerating {total} cells..."):
            st.session_state["cfg"].slot_counts = st.session_state.get("slot_counts", {})

            new_plan, _ = gen.regenerate_selected_from_plan(
                df=st.session_state["df"],
                pools=st.session_state["pools"],
                cfg=st.session_state["cfg"],
                base_plan=st.session_state["week_plan"],
                replace_mask=replace_mask,
                history_long_df=history_long,
                history_weeks_df=history_weeks,
                client_name=st.session_state.get("client_name"),
                item_cooldown_days=ITEM_COOLDOWN_DAYS,
                menu_cooldown_days=MENU_COOLDOWN_DAYS,
                rice_bread_gap_days=RICE_BREAD_GAP_DAYS,
            )

            dates = st.session_state["dates"]
            apply_menu_view_state(
                gen=gen,
                week_plan=new_plan,
                dates=dates,
                allowed_slots=st.session_state.get("allowed_slots") or [],
                item_to_color=st.session_state.get("item_to_color", {}),
            )

            new_menu_df = st.session_state["menu_df"]
            changes = []
            for day_col, d in col_to_date.items():
                for disp_row, slot_id in display_to_slot.items():
                    if d in replace_mask and slot_id in replace_mask[d]:
                        old_val = str(old_menu_df.loc[disp_row, day_col])
                        new_val = str(new_menu_df.loc[disp_row, day_col])
                        if old_val != new_val:
                            changes.append({"day": day_col, "category": disp_row, "old": old_val, "new": new_val})

            st.session_state["week_plan"] = new_plan
            st.session_state["last_changes"] = changes
            st.session_state["_view_client"] = st.session_state.get("client_name")

        if len(changes) == 0:
            st.warning("Selected cells could not be changed — no feasible alternative exists under current rules/history.")
        else:
            st.success(f"Regenerated {total} cells (changed {len(changes)}).")


if save_clicked and "week_plan" in st.session_state:
    gen = get_gen()
    gen_start = dt.date.fromisoformat(st.session_state.get("_generated_start_date", start_date.isoformat()))
    anchor = this_weeks_monday(gen_start)

    ok, msg = append_history(
        gen=gen,
        client_name=st.session_state.get("client_name", ""),
        week_plan=st.session_state["week_plan"],
        dates=st.session_state["dates"],
        week_start=anchor,
    )
    if ok:
        st.success(msg)
    else:
        st.warning(msg)


# -----------------------------
# Render
# -----------------------------
if "menu_df" in st.session_state:
    st.subheader("Weekly menu")
    st.caption(
        f"Client: **{st.session_state.get('client_name','')}** | "
        f"Preset: **{client_logic.get_client_menu_category(st.session_state.get('client_name',''))}**"
    )

    editor_df = st.session_state["editor_df"]
    menu_cols = st.session_state["menu_cols"]
    item_cols = st.session_state["item_cols"]
    col_config = st.session_state["col_config"]

    st.caption(f"Selected to replace: **{count_selected(editor_df, menu_cols)}**")

    edited = st.data_editor(
        editor_df,
        key="weekly_menu_editor",
        use_container_width=True,
        num_rows="fixed",
        column_config=col_config,
        disabled=item_cols,
    )
    st.session_state["editor_df"] = edited

    with st.expander("Changes (old → new)", expanded=False):
        changes = st.session_state.get("last_changes", [])
        if not changes:
            st.caption("No changes yet. Tick ✅ and use Regenerate selected.")
        else:
            st.dataframe(pd.DataFrame(changes, columns=["day", "category", "old", "new"]), use_container_width=True)

    if st.toggle("History", value=False):
        with st.expander("Saved history (this client)", expanded=True):
            _, weeks_df = read_history()
            if len(weeks_df) == 0:
                st.info("No saved history yet. Generate → Save to start building history.")
            else:
                w = weeks_df.copy()
                w["week_start"] = pd.to_datetime(w["week_start"], errors="coerce")
                w["client_name_norm"] = w["client_name"].map(_norm_client)
                w = w[w["client_name_norm"] == _norm_client(st.session_state.get("client_name", ""))]
                w = w.sort_values("week_start", ascending=False).drop(columns=["client_name_norm"], errors="ignore")
                if len(w) == 0:
                    st.info("No saved history for this client yet.")
                else:
                    st.dataframe(w.head(12), use_container_width=True)

    xlsx_bytes = menu_df_to_xlsx_bytes(st.session_state["menu_df"])
    st.download_button(
        "Download menu_plan.xlsx",
        data=xlsx_bytes,
        file_name=f"menu_plan_{st.session_state.get('client_name','client')}_{st.session_state.get('_generated_start_date','')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
else:
    st.info("Pick a client, pick a start date (Mon–Fri) and click Generate.")
