"""Menu explanation layer — deterministic half.

Network-free by design: every verdict here is a pure function over plain dicts,
so it can be pinned in a unit test without a solver, a database or an LLM. The
prose layer that phrases these facts lives in `api/explain_llm.py`, on the other
side of the layering boundary `tests/platform/test_architecture.py` enforces.
"""

from .checks import Check, plate_profile, run_checks
from .evidence import (
    attach_relaxations, attrs_from_dataframe, build_evidence,
    build_plan_evidence,
)
from .renderer import day_summary, render_day, render_plan

__all__ = [
    'Check', 'plate_profile', 'run_checks',
    'attach_relaxations', 'attrs_from_dataframe', 'build_evidence',
    'build_plan_evidence',
    'day_summary', 'render_day', 'render_plan',
]
