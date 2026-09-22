"""Assembling one solve: request values in, `SolverInputs` out.

This was 593 lines in the middle of `api/app.py`, which is why that file read
as a 2,600-line "API" built on roughly 950 lines of actual API. None of it is
an HTTP concern: resolving a client's rules, widening the history window,
folding shared and excluded dishes into the ban map and building a
`SolverConfig` are all statements about a menu.

It stayed there because it looked like it needed the web layer — 27 external
names, per the note this module retires. It did not. The dependency was on
*request parsing*, not on Flask: clamping `num_days`, defaulting `start_date`
to the app timezone's today, validating the client name and memoising the
client row on `g`. All of that stays in `api/app.py` and its results arrive
here as plain values, which leaves exactly ONE thing to inject — `worker_count`,
a callable, because how many CP-SAT workers to use depends on how many solves
the process is serving and the domain has no business reaching up for it. That
is the same injection `SolverConfig.worker_count_provider` already existed for.

So this module imports no `api`, no Flask, and no request context, and its
functions can be exercised by handing them a dict and a client config.

One thing that is NOT free to move: the operator-facing warnings here keep
emitting under `api.app` (`src/log_names.APP_LOGGER_NAME`). Log records are
observable output — the last time code moved out of that module the origin
name changed silently and anything filtering on it stopped matching.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from src.constants import CONST_SLOTS
from src.log_names import APP_LOGGER_NAME
from src.menu_rules.diagnostics import (
    DiagnoseContext, run_diagnostics, summarize as _summarize_diags,
)
from src.menu_rules.menu_rule_loader import MenuRuleLoader
from src.menu_rules.selector_history_window_rule import SelectorHistoryWindowRule
from src.ontology import repository
from src.preprocessor.pool_builder import _base_slot
from src.solver.menu_solver import SolverConfig
from src.solver._helpers import weekday_type_for_config as _weekday_type_cfg

from .constant_items import (
    _canonical_item_name, _exclusive_siblings, _resolve_constant_items,
    _slot_item_names, _validate_constant_values,
)
from .history import (
    _HISTORY_WINDOW_DAYS, _HISTORY_WINDOW_SLACK_DAYS, _build_history_context,
)
from .horizon import (
    _client_base_slots, _filter_dates_by_working_days, _weekdays_from,
)

#: Operator-facing warnings keep their old emitting name — see the docstring.
logger = logging.getLogger(APP_LOGGER_NAME)


# SolverConfig fields a rule may override via solver_overrides(). Restricted to
# the colour parameters on purpose: the ruleset is the per-city config surface
# for menu policy, not a back door for rewriting the horizon or the time limit.
_RULE_OVERRIDABLE_CFG_FIELDS = frozenset({
    'min_distinct_colors_per_day',
    'min_distinct_colors_per_day_chinese',
    'min_distinct_colors_per_day_biryani',
    'max_same_color_per_day',
    'max_same_color_reach',
    'max_colors_at_reach',
    'ignore_rice_gravy_color_diff_on_chinese_day',
})


@dataclass
class SolverInputs:
    """Bundle of everything MenuSolver / MenuRegenerator need for one request."""
    client_name: str
    client_cfg: Any
    df: Any
    pools: Dict[str, Any]
    start_date: dt.date
    num_days: int
    time_limit: int
    weekday_dates: List[dt.date]
    rules: List[Any]
    skip_cells: Set[Any]
    banned: Dict[Any, Any]
    rb_ban: Dict[Any, Any]
    recent_sigs: List[Any]
    cfg: SolverConfig
    # {item_base: days-since-last-served} — the solver's soft freshness map.
    # Defaulted so older construction sites / tests stay valid.
    recency_by_item: Dict[str, int] = field(default_factory=dict)
    # The client's city — selects which ontology `df`/`pools` came from, so
    # anything derived from the ontology downstream (the non-veg name set that
    # colours the rendered menu) reads the same list the solver did.
    city: Optional[str] = None
    # Every date the horizon SPANS, including the ones this client does not
    # serve. `weekday_dates` above is the subset the solver plans; this is what
    # the menu is rendered against, so a non-working day shows as a blank
    # column instead of vanishing (see `span_dates`). Same list for a client
    # with no `working_days` restriction, which is all but three of them.
    span_dates: List[dt.date] = field(default_factory=list)
    # {iso date: region name} actually in force for this solve, and the picks
    # that could not be honoured (wrong cuisine for the day's theme, a region
    # this city cannot theme, a name that matches nothing). Both ride on the
    # response so the planner can badge the day and SAY WHY when it cannot —
    # learning that a Tamil Nadu Thursday was dropped by reading a plate with no
    # Tamil food on it is the worst way to find out.
    region_days: Dict[str, str] = field(default_factory=dict)
    region_problems: List[Dict[str, Any]] = field(default_factory=list)



def rules_and_skip_for_client(
    client_name, dates, city=None, client_cfg=None, pools=None,
):
    """Return ``(rules, skip_cells, constant_items, whole_slot_bases, forced_items)``.

    Merges the city ruleset with per-client overrides (by name + disable) and
    resolves ``constant_items`` against *client_cfg* — the counter being
    planned. A pinned cell is skipped so it is not solved and then thrown
    away, and so is every cell of any mutually-exclusive sibling slot on that
    day: without that, a counter serving ``curd_side`` still solves a raita on
    the days a ``curd`` constant is stamped and the menu shows two yogurt rows.
    """
    generic = repository.rules_for_city(city)
    loader = MenuRuleLoader()
    # Per-counter scoping: an override meant for one station (e.g. L&T's
    # biryani-only non-veg counter) must not apply to the client's other
    # counters.
    counter_name = getattr(client_cfg, 'counter_name', None)
    rules = loader.load_for_client(client_name, generic, counter_name)
    constant_items, whole_slot_bases = _resolve_constant_items(
        client_name,
        loader.get_client_constant_items(client_name, counter_name),
        client_cfg,
        # Pins written inside THIS counter's block are unambiguous even on a
        # multi-counter client, so they print as fixed items without the slot
        # being configured as a rotating category.
        counter_scoped_keys=loader.get_counter_scoped_constant_keys(
            client_name, counter_name),
    )
    skip_cells = set()
    for rule in rules:
        if hasattr(rule, 'compute_skip_cells'):
            skip_cells |= rule.compute_skip_cells(dates)
    from src.solver.menu_solver import _resolve_client_constant
    from src.solver._helpers import weekday_name as _weekday_name_fn

    # A pin is honoured one of two ways, and which one depends on whether the
    # dish is a candidate for THAT SLOT:
    #
    #   * it is     -> the cell stays in the model with its candidates narrowed to
    #                 that dish (`forced_items`), so every other rule sees it and
    #                 the day is composed around it.
    #   * it is not -> the cell is skipped and the text is stamped verbatim
    #                 after the solve, which is how off-ontology dishes ("Mutton
    #                 Biryani", "Fish Tikka Masala") print today. Add the dish to
    #                 the city's item list and the same pin starts going through
    #                 the solver with no config change.
    #
    # Slot-scoped, not ontology-scoped, because "in the ontology" is the wrong
    # test: a dish the ontology carries under a DIFFERENT course type has no
    # candidate in this slot to narrow to, so the solver logs the miss and solves
    # the cell normally — while the stamping pass skips it for being in
    # `forced_items`. The pin then vanished from the menu with only an INFO line
    # to show for it. Amadeus Pune's Sunday raita is exactly that shape: `raita`
    # is a real Pune dish, filed under `curd_side`, pinned into `salad`.
    forced_items: Dict[Any, str] = {}
    # Only a slot this counter actually SOLVES can be narrowed. `pools` holds
    # every slot the ontology can fill, not the ones this counter serves, so a
    # pin for an unserved slot used to resolve to a real dish, land in
    # `forced_items`, and then be dropped by BOTH paths: the solver has no cell
    # to narrow, and the post-solve stamp skips anything in `forced_items` on
    # the grounds that the solver already placed it. The row vanished from the
    # menu with nothing logged. Booking.com's daily curd was exactly this — the
    # pin resolves (its `curd_side` sibling is served, so it is kept) and
    # Bangalore has a real `curd` dish for it to match, which is what put it on
    # the forcing path. Anything outside this set is stamped instead.
    solved_slots = set(getattr(client_cfg, 'active_slots', None) or [])
    for slot_id, spec in constant_items.items():
        base = _base_slot(slot_id)
        slot_items = _slot_item_names(pools, base) if pools is not None \
            else repository.item_names(city)
        siblings = _exclusive_siblings(base)
        for d in dates:
            value = _resolve_client_constant(
                spec, _weekday_name_fn(d), d.isocalendar()[1])
            if value is None:
                continue
            # Sibling entries are base-level on purpose: every expansion of
            # the excluded slot goes away for that day. This holds either way —
            # a pinned curd still removes curd_side.
            skip_cells.update((d, sib) for sib in siblings)
            canonical = _canonical_item_name(value, slot_items)
            # A pin that replaces the slot for the WHOLE horizon must still be
            # stamped, even when it names a real dish. Its base slot is dropped
            # from the model (`whole_slot_bases`), so there is no cell to narrow
            # — and solving one anyway would be INFEASIBLE under unique_items,
            # which is why the slot is dropped in the first place: the same dish
            # cannot occupy five days unless it is a staple.
            solvable = (not solved_slots) or slot_id in solved_slots
            if (canonical is not None and base not in whole_slot_bases
                    and solvable):
                forced_items[(d, slot_id)] = canonical
            else:
                skip_cells.add((d, slot_id))
    return rules, skip_cells, constant_items, whole_slot_bases, forced_items


def apply_item_cooldown_override(rules, cooldown_days):
    """Return *rules* with the item_cooldown rule rebuilt to use
    ``cooldown_days``. A fresh instance is created so the process-wide cached
    generic-rule list is never mutated (which would leak one client's cooldown
    to every other client). ``None`` leaves the rules untouched.
    """
    if cooldown_days is None:
        return rules
    out = []
    for r in rules:
        rt = getattr(getattr(r, 'rule_type', None), 'value', None)
        if rt == 'item_cooldown':
            out.append(type(r)({
                'name': getattr(r, 'name', 'item_cooldown'),
                'type': 'item_cooldown',
                'cooldown_days': int(cooldown_days),
            }))
        else:
            out.append(r)
    return out


def effective_history_window(rules) -> int:
    """Return a window that covers every rule's cooldown + slack.

    Rules expose their cooldown via either ``cooldown_days`` (item /
    week-signature cooldowns) or ``gap_days`` (rice-bread gap). We take
    the max across both attributes on all rules, add slack, and take the
    larger of that and the ``_HISTORY_WINDOW_DAYS`` floor. Widening is
    logged so operators notice a per-client rule is pushing queries
    further back than usual.

    Skipping this check is how "we quietly miss the last 10 days of
    history" bugs happen: ``_HISTORY_WINDOW_DAYS`` is a fixed constant,
    but cooldowns can be overridden per-client or in future rules.
    """
    max_cd = 0
    for r in rules or []:
        for attr in ('cooldown_days', 'gap_days', 'window_days'):
            value = getattr(r, attr, None)
            if isinstance(value, int) and value > max_cd:
                max_cd = value
    effective = max(_HISTORY_WINDOW_DAYS, max_cd + _HISTORY_WINDOW_SLACK_DAYS)
    if effective > _HISTORY_WINDOW_DAYS:
        logger.warning(
            "Widening history lookback from %d to %d days to cover "
            "max rule cooldown %d + %d slack",
            _HISTORY_WINDOW_DAYS, effective, max_cd, _HISTORY_WINDOW_SLACK_DAYS,
        )
    return effective


def _rule_solver_overrides(rules):
    """Collect ``solver_overrides()`` from *rules*, allow-listed.

    How a city ruleset sets its own colour numbers (Pune's rulebook wants 3
    distinct colours and a flat cap of 2 where Bangalore wants 4 and one colour
    allowed to reach 3). A field outside the allow-list is dropped with a
    warning rather than silently applied.
    """
    out: Dict[str, Any] = {}
    for rule in (rules or ()):
        fn = getattr(rule, 'solver_overrides', None)
        if not callable(fn):
            continue
        try:
            proposed = fn() or {}
        except Exception as exc:  # noqa: BLE001 — a bad rule must not stop planning
            logger.warning(
                "Rule %r solver_overrides() raised: %s",
                getattr(rule, 'name', type(rule).__name__), exc,
            )
            continue
        for field_name, value in proposed.items():
            if field_name not in _RULE_OVERRIDABLE_CFG_FIELDS:
                logger.warning(
                    "Rule %r tried to override SolverConfig.%s, which is not "
                    "rule-overridable; ignoring.",
                    getattr(rule, 'name', type(rule).__name__), field_name,
                )
                continue
            out[field_name] = value
    return out


def _apply_region_days(rules, data, dates, client_cfg, city, row):
    """Append the regional-day rules for this counter and horizon.

    Returns ``(rules, {iso: Region}, problems)``. Two inputs are flattened: the
    counter's standing ``region_map`` (a weekday pattern) and the request's
    ``region_days`` (what the planner picked for these dates), the latter
    winning. See `src/application/regions.py` for why weekdays are resolved to
    dates here rather than inside the rule.

    Never raises. Three things make this a no-op and all three are ordinary:
    a workbook without the regional columns (every committed one today), a
    client with no pattern and a request with no picks, or a counter that
    serves none of the region's slots. Nothing about a plan changes until
    somebody asks for a regional day.
    """
    from src.application.regions import (
        normalize_region_map, region_rule_configs, resolve_region_days,
    )

    requested = data.get('region_days') if isinstance(data, dict) else None
    stored = (row or {}).get('region_map') if hasattr(row, 'get') else None
    if not requested and not stored:
        return rules, {}, []

    try:
        regions = repository.regions(city)
    except Exception:  # noqa: BLE001 — a plan must never be lost to this
        logger.warning("could not measure regions for city %r", city,
                       exc_info=True)
        return rules, {}, []
    if not regions:
        # The columns are absent, so a pick cannot be honoured. Say so rather
        # than dropping it: the planner only offers regions this endpoint
        # reported, so a request carrying one here means the two disagree.
        problems = [
            {'date': str(k), 'region': str(v), 'reason': 'no_region_data',
             'message': "This city's item list does not carry regional data."}
            for k, v in (requested or {}).items() if str(v or '').strip()
        ]
        return rules, {}, problems

    day_themes = [
        _weekday_type_cfg(d, getattr(client_cfg, 'theme_map', None) or {})
        for d in dates
    ]
    chosen, problems = resolve_region_days(
        dates, day_themes, regions,
        region_map=normalize_region_map(stored, regions),
        region_days=requested,
    )
    if not chosen:
        return rules, {}, problems

    served = _client_base_slots(client_cfg)
    loader = MenuRuleLoader()
    added = []
    for cfg in region_rule_configs(chosen, served):
        rule = loader._create_rule(cfg)
        # A rule that will not build is dropped WITH a problem entry rather
        # than silently, which is the failure `test_client_disable_targets`
        # exists to stop for the hand-written configs: `load_for_client` logs
        # and moves on, so the client loses the rule while /plan still answers
        # 200 and /diagnose still reports clean.
        if rule is None or not rule.validate_config():
            errs = rule.validation_errors() if rule is not None else ['unbuildable']
            logger.warning("regional rule %s did not build: %s",
                           cfg.get('name'), errs)
            problems.append({
                'date': (cfg.get('only_on_dates') or [''])[0],
                'region': cfg.get('selector', {}).get('state_origin', ''),
                'reason': 'rule_error', 'message': '; '.join(map(str, errs)),
            })
            continue
        added.append(rule)
    if not added:
        # The pick resolved but produced no rule — this counter serves none of
        # the region's deep slots (a non-veg station against a region whose
        # depth is all veg, say). Reported, because a region that quietly does
        # nothing is indistinguishable from one that worked.
        for iso, region in sorted(chosen.items()):
            problems.append({
                'date': iso, 'region': region.name, 'reason': 'no_usable_slot',
                'message': (
                    f"This counter serves none of the slots {region.name} is "
                    f"deep in ({', '.join(region.deep_slots) or 'none'}), so "
                    f"there is nothing for a regional floor to ask for."),
            })
        return rules, {}, problems
    return list(rules) + added, chosen, problems


def build_solver_config(
    df, client_cfg, start_date, num_days, time_limit, weekday_dates,
    constant_items=None, whole_slot_bases=None, forced_items=None,
    rules=None, worker_count=None,
):
    """Shared helper to build SolverConfig.

    *constant_items* keys are already-resolved slot ids (see
    ``_resolve_constant_items``); *whole_slot_bases* are the base slots the
    overlay replaces for the entire horizon, dropped from the model because
    solving them would burn items against unique_items / colour variety and
    then discard the result. *rules* is the resolved ruleset, read only for the
    colour parameters a city may override (see ``_rule_solver_overrides``).
    """
    active_base = _client_base_slots(client_cfg)
    if whole_slot_bases:
        active_base = [s for s in active_base if s not in whole_slot_bases]
    # Constant items are per-client selectable now (not forced on everyone):
    # only append the ones this client actually selected.
    const_selected = [s for s in client_cfg.active_slots if s in CONST_SLOTS]
    return SolverConfig(
        days=num_days,
        start_date=start_date,
        time_limit_sec=time_limit,
        # Injected, not imported by the solver: the worker count is a *web*
        # concern (how many solves this process is serving) and the solver has no
        # business reaching up for it. Passed as a callable so it is still
        # re-read per restart attempt, which is what the old inline import did.
        worker_count_provider=worker_count,
        slot_counts=client_cfg.slot_counts,
        active_base_slots=active_base or None,
        const_slots=const_selected,
        client_constant_items=dict(constant_items or {}),
        forced_items=dict(forced_items or {}),
        working_days=getattr(client_cfg, 'working_days', None),
        explicit_dates=weekday_dates,
        premium_flag_col='is_premium_veg' if 'is_premium_veg' in df.columns and int(df['is_premium_veg'].sum()) > 0 else None,
        theme_map=client_cfg.theme_map or None,
        **_rule_solver_overrides(rules),
    )


def span_dates(plan_dates, inputs):
    """The dates the MENU covers, which is not always the dates it plans.

    A client with a restricted `working_days` list (Clario Mon-Thu, Piramel
    Mon/Tue/Thu, Quince Wed/Thu/Fri) serves fewer days than the horizon spans.
    Those days used to be filtered out before the solve and never came back, so
    a 5-day horizon from Monday returned FOUR days for Clario and the table
    simply had no Friday — the gap closed up, and "5 days" quietly meant
    something different per client.

    The solver still plans only the days the client serves; this widens what is
    RENDERED, so Friday appears as an empty column. `SolutionFormatter` already
    reads `week_plan.get(d, {})`, so a date with no plan formats as a day with
    no items — no solver change and no rule sees an extra day.

    Returns the union, so a solver that dropped a date (an infeasible day it
    could not fill) still has it rendered rather than silently missing.
    """
    span = getattr(inputs, 'span_dates', None) or []
    return sorted(set(plan_dates) | set(span))


def merge_shared_items(forced_items, shared_items, dates):
    """Fold cross-counter shared-category pins into *forced_items*.

    *shared_items* is a request-supplied list of ``[iso_date, slot_id, item]``
    the planner extracts from the primary counter's solution (see
    ``ui.formatters.shared_items_from_solution``). Each becomes a
    ``forced_items[(date, slot_id)] = item.lower()`` pin, using the same
    narrow-the-cell mechanism as a client constant. An explicit constant pin
    already in *forced_items* WINS — a client's own config is never overridden
    by a sibling counter. Entries with an out-of-horizon date or a missing field
    are skipped. Malformed input never raises: syncing is best-effort and must
    not fail a solve.
    """
    if not shared_items or not isinstance(shared_items, list):
        return forced_items
    date_set = {d.isoformat() for d in dates}
    merged = dict(forced_items or {})
    for entry in shared_items:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        date_str, slot_id, item = entry[0], entry[1], entry[2]
        if not date_str or not slot_id or not item:
            continue
        if str(date_str) not in date_set:
            continue
        try:
            d = dt.date.fromisoformat(str(date_str))
        except (ValueError, TypeError):
            continue
        key = (d, str(slot_id))
        if key in merged:
            continue  # an explicit client constant pin wins
        merged[key] = str(item).strip().lower()
    return merged


def merge_excluded_items(banned, exclude_items, dates):
    """Fold caller-supplied per-date dish bans into the cooldown's ban map.

    *exclude_items* is ``{iso_date: [item, …]}`` — the dishes an EARLIER
    service on the same day has already committed. Dinner is solved after
    lunch and must not reprint lunch's dishes, and "this dish is already on
    today's menu" is exactly what ``banned_by_date`` means, so it goes in there
    rather than into a mechanism of its own: every rule and the whole
    pre-flight already respect that map.

    Banned for the DAY, not per slot, because the same dish in a different slot
    is still the same dish appearing twice on one date.

    Malformed input is skipped rather than raised on: a dinner solve must not
    fail because the lunch payload had a bad date in it.
    """
    if not exclude_items or not isinstance(exclude_items, dict):
        return banned
    merged = {d: set(v) for d, v in (banned or {}).items()}
    date_set = set(dates or ())
    for date_str, items in exclude_items.items():
        try:
            d = dt.date.fromisoformat(str(date_str))
        except (ValueError, TypeError):
            continue
        if d not in date_set:
            continue
        names = {
            str(i).strip().lower() for i in (items or []) if str(i).strip()
        }
        if names:
            merged.setdefault(d, set()).update(names)
    return merged


def prepare_solver_inputs(
    data: Dict[str, Any],
    client_cfg: Any,
    *,
    client_name: str,
    row: Dict[str, Any],
    start_date: dt.date,
    num_days: int,
    time_limit: int,
    worker_count=None,
) -> SolverInputs:
    """Assemble everything MenuSolver / MenuRegenerator need for one request.

    The *parsing* half stays in the web layer and its results arrive here as
    plain values: `client_name` validated, `start_date` already defaulted to
    the app timezone's today, `num_days` and `time_limit` already clamped, and
    `row` already read (memoised on the request). That split is what lets this
    module live under `src/` at all — it is also the honest boundary, since
    clamping a query parameter is an HTTP concern and assembling a solve is
    not.

    `data` is still the request body, read for the optional solve INPUTS
    (`shared_items`, `exclude_items`, `region_days`) rather than for anything
    that needs validating.

    `worker_count` is a callable the web layer passes down: how many CP-SAT
    workers to use depends on how many solves this process is serving, which
    the solver has no business reaching up for.
    """
    city = row['city']
    df, pools = repository.filtered_menu_data(city, row['source_pools'])
    # The horizon SPANS `num_days` weekdays (or calendar days for a weekend
    # site); the client then serves some subset of them.
    span_dates = _weekdays_from(
        start_date, num_days, getattr(client_cfg, 'serve_weekends', False),
    )
    # Restrict to the client's working weekdays (e.g. Quince = Wed/Thu/Fri).
    # The dropped dates are NOT lost — `span_dates` keeps them so the menu
    # renders them blank rather than closing the gap (note 29).
    weekday_dates = _filter_dates_by_working_days(
        span_dates, getattr(client_cfg, 'working_days', None),
    )
    rules, skip_cells, constant_items, whole_slot_bases, forced_items = rules_and_skip_for_client(
        client_name, weekday_dates, city=city, client_cfg=client_cfg, pools=pools,
    )
    # Regional days: the counter's standing weekday pattern plus whatever the
    # planner picked for this horizon. Appended as ordinary rules, so nothing
    # downstream — diagnose, the objective, the relaxation channel — needs to
    # know regions exist. A city whose workbook lacks the columns yields none.
    rules, region_days, region_problems = _apply_region_days(
        rules, data, weekday_dates, client_cfg, city, row,
    )
    _validate_constant_values(client_name, constant_items, df)
    # Cross-counter shared categories: the planner passes the primary counter's
    # dish for each shared base slot as `shared_items`; fold them into the
    # forced-item pins so this counter serves the same dish that day. Client
    # constant pins already in `forced_items` win.
    forced_items = merge_shared_items(
        forced_items, data.get('shared_items'), weekday_dates,
    )
    # Per-client item-cooldown override (None = shipped default). Rebuild the
    # rule so the history window + diagnostics reflect the client's value.
    cooldown_days = row['item_cooldown_days']
    rules = apply_item_cooldown_override(rules, cooldown_days)
    window_days = effective_history_window(rules)
    # Cross-week cadence rules: each names a selector + window_days. Resolve the
    # selector to concrete item names against this city's ontology now, so the
    # history layer can ban the whole family on dates within the window of a
    # saved occurrence (see SelectorHistoryWindowRule).
    selector_windows = [
        (r.matching_items(df), r.window_days)
        for r in rules
        if isinstance(r, SelectorHistoryWindowRule) and r.window_days
    ]
    banned, rb_ban, recent_sigs, recency_by_item = _build_history_context(
        df, client_name, start_date, weekday_dates, window_days=window_days,
        cooldown_days=cooldown_days, selector_windows=selector_windows,
    )
    # A second service on the same dates: the dishes lunch has already taken
    # are banned for dinner. Not read from history — lunch is usually not saved
    # yet when dinner is solved, so the caller passes them.
    banned = merge_excluded_items(banned, data.get('exclude_items'), weekday_dates)
    cfg = build_solver_config(
        df, client_cfg, start_date, num_days, time_limit, weekday_dates,
        constant_items=constant_items, whole_slot_bases=whole_slot_bases,
        forced_items=forced_items, rules=rules, worker_count=worker_count,
    )

    return SolverInputs(
        client_name=client_name,
        client_cfg=client_cfg,
        df=df,
        pools=pools,
        start_date=start_date,
        num_days=num_days,
        time_limit=time_limit,
        weekday_dates=weekday_dates,
        rules=rules,
        skip_cells=skip_cells,
        banned=banned,
        rb_ban=rb_ban,
        recent_sigs=recent_sigs,
        recency_by_item=recency_by_item,
        cfg=cfg,
        city=city,
        span_dates=span_dates,
        region_days={k: v.name for k, v in region_days.items()},
        region_problems=region_problems,
    )


def build_diagnose_context(inputs: SolverInputs) -> DiagnoseContext:
    """Project the SolverInputs bundle into a DiagnoseContext the
    rule diagnose() methods can consume.

    Computes the per-date day_types map up front (the rules want
    O(1) lookup, not repeated weekday_type_for_config calls), and
    surfaces the client's active base slots so diagnose() iterates
    over the slots that will actually be solved (not the global
    BASE_SLOT_NAMES list).
    """
    day_types = {
        d: _weekday_type_cfg(d, inputs.cfg.theme_map)
        for d in inputs.weekday_dates
    }
    active_base = inputs.cfg.active_base_slots
    return DiagnoseContext(
        pools=inputs.pools,
        dates=inputs.weekday_dates,
        day_types=day_types,
        cfg=inputs.cfg,
        df=inputs.df,
        banned_by_date=inputs.banned,
        ricebread_ban_day=inputs.rb_ban,
        skip_cells=inputs.skip_cells,
        client_cfg=inputs.client_cfg,
        active_base_slots=active_base,
    )


def run_preflight(inputs: SolverInputs):
    """Shared pre-flight pass used by both /plan and /diagnose.

    Returns ``(diagnostics, summary)`` where:
      - ``diagnostics`` is the full sorted list of Diagnostic objects
        produced by every rule + the synthetic pool_size pass.
      - ``summary`` is the ``{errors, warnings, infos, would_succeed}``
        dict produced by ``summarize()``.

    A single call site for both endpoints keeps the two surfaces in
    lockstep: /diagnose and /plan's gate emit identical diagnostics
    for identical inputs. ``test_diagnose_matches_plan_preflight``
    pins this invariant.
    """
    ctx = build_diagnose_context(inputs)
    diags = run_diagnostics(inputs.rules, ctx)
    return diags, _summarize_diags(diags)
