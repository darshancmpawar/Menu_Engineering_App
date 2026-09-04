"""LLM prose layer for menu explanations — the LAST thing to build.

Lives in `api/` because it does I/O. `src/explain/` must stay network-free so
the verdicts remain unit-testable offline; `tests/platform/test_architecture.py`
enforces that boundary.

Design position, restated because it is the whole point:

    The model does not decide anything. `src/explain/` has already computed
    every claim. This module asks a model to phrase those claims nicely, then
    REJECTS the reply if it contains a number or a dish name that did not come
    from the pack.

That validator is what makes confabulation structurally impossible rather than
merely discouraged. Without it, this is a fluent-nonsense generator pointed at
a client-facing surface.

Model: `gemma-4-31b-it` on Google AI Studio. 30 RPM / 14,400 requests per day
free. This is a rendering task over supplied facts — a 31B model does it as well
as a 550B one, and the daily ceiling is what actually matters.

Batching: ONE call per plan, not per day. All days in, one paragraph per day out.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from src.explain.renderer import render_day

logger = logging.getLogger(__name__)

# --- configuration ---------------------------------------------------------
# Default OFF. Steps 1-3 ship without any of this, and the feature must remain
# usable with no key configured. Do NOT add these to validate_required_env().
ENABLED = os.getenv('EXPLAIN_LLM_ENABLED', 'false').strip().lower() == 'true'
API_KEY = os.getenv('EXPLAIN_LLM_API_KEY', '').strip()
MODEL = os.getenv('EXPLAIN_LLM_MODEL', 'gemma-4-31b-it').strip()
TIMEOUT = int(os.getenv('EXPLAIN_LLM_TIMEOUT_SECONDS', '20'))
ENDPOINT = os.getenv(
    'EXPLAIN_LLM_ENDPOINT',
    'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
)

MAX_CACHE_ENTRIES = 256

# Claims this feature is not licensed to make. You are a caterer, not a
# dietitian — this is a liability boundary, not a style preference.
BANNED_PATTERNS = (
    r'\bcalor(?:ie|ies)\b', r'\bprotein\s+(?:intake|requirement|target)\b',
    r'\bhealthy?\b', r'\bnutriti(?:on|ous|onal)\b', r'\bdiet(?:ary)?\s+need',
    r'\bweight\s+loss\b', r'\bdiabet', r'\bcholesterol\b', r'\bvitamin\b',
    r'\bmedical', r'\bcures?\b', r'\bimmunity\b',
)
_BANNED_RE = re.compile('|'.join(BANNED_PATTERNS), re.IGNORECASE)

_NUMBER_RE = re.compile(r'\d+(?:\.\d+)?')

SYSTEM_PROMPT = """You write one short paragraph per day explaining a corporate \
cafeteria menu to the chef who will cook it.

You will receive JSON facts. Those facts are the ONLY things you know.

RULES — a reply breaking any of these is discarded:
1. Never state a number that does not appear in the facts.
2. Never name a dish that does not appear in the facts.
3. Never mention nutrition, calories, health, diet or medical effects.
4. Never claim a check passed or failed unless it says so in the facts.
5. If a relaxation is listed, say so plainly in that day's paragraph.
6. 2-3 sentences per day. Plain language. No marketing adjectives.

OUTPUT: strict JSON, no markdown fences:
{"days": [{"date": "YYYY-MM-DD", "prose": "..."}]}"""


# --- cache -----------------------------------------------------------------
# The menu is deterministic given (client, dates, seed), and Streamlit reruns
# the whole script on every widget interaction. Without this, one user moving a
# date picker burns the daily quota. Caching is required, not an optimisation.
_cache: Dict[str, Dict[str, str]] = {}
_cache_order: List[str] = []
_cache_lock = threading.Lock()


def pack_hash(packs: List[Dict[str, Any]]) -> str:
    payload = json.dumps(packs, sort_keys=True, default=str, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _cache_get(key: str) -> Optional[Dict[str, str]]:
    with _cache_lock:
        return _cache.get(key)


def _cache_put(key: str, value: Dict[str, str]) -> None:
    with _cache_lock:
        if key not in _cache:
            _cache_order.append(key)
        _cache[key] = value
        while len(_cache_order) > MAX_CACHE_ENTRIES:
            _cache.pop(_cache_order.pop(0), None)


def reset_cache_for_tests() -> None:
    with _cache_lock:
        _cache.clear()
        _cache_order.clear()


# --- validator -------------------------------------------------------------

def _allowed_tokens(pack: Dict[str, Any]) -> Tuple[set, set]:
    """Every number and every dish name this day's prose may legally contain."""
    numbers: set = set()
    names: set = set()

    def harvest(obj: Any) -> None:
        if isinstance(obj, dict):
            for v in obj.values():
                harvest(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                harvest(v)
        elif isinstance(obj, bool):
            return
        elif isinstance(obj, (int, float)):
            numbers.add(_fmt_num(obj))
        elif isinstance(obj, str):
            for m in _NUMBER_RE.findall(obj):
                numbers.add(_fmt_num(float(m)))

    harvest(pack)
    for d in (pack.get('dishes') or {}).values():
        n = str(d.get('name') or '').strip().lower()
        if n:
            names.add(n)
            names.add(n.replace('_', ' '))
    # The date's own components are legitimately quotable.
    for m in _NUMBER_RE.findall(str(pack.get('date') or '')):
        numbers.add(_fmt_num(float(m)))
    return numbers, names


def _fmt_num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f'{float(v):g}'


# Words that look like dish names but are ordinary English. Without this the
# validator rejects every well-formed sentence.
_COMMON_WORDS = frozenset("""
a an and are as at be been but by day days dish dishes for from has have in is it
its no not of on one or plate plates repeats run same served serving side since the
this those to two three four five six seven eight nine ten with without across
also only still while which that there here menu counter theme today course main
""".split())


def validate(prose: str, pack: Dict[str, Any]) -> Tuple[bool, str]:
    """Return (ok, reason). A rejected reply is discarded whole, not patched."""
    if not prose or not prose.strip():
        return False, 'empty'
    if _BANNED_RE.search(prose):
        return False, f'banned topic: {_BANNED_RE.search(prose).group(0)!r}'

    numbers, names = _allowed_tokens(pack)

    for raw in _NUMBER_RE.findall(prose):
        if _fmt_num(float(raw)) not in numbers:
            return False, f'number {raw!r} is not in the evidence'

    # Underscored tokens are dish-shaped; anything not in the pack is invented.
    for tok in re.findall(r'\b[a-z]+(?:_[a-z]+)+\b', prose.lower()):
        if tok not in names and tok.replace('_', ' ') not in names:
            return False, f'unknown dish {tok!r}'

    return True, 'ok'


# --- model call ------------------------------------------------------------

def _call_model(payload: str) -> Optional[str]:
    """POST to the model. Returns raw text, or None on any failure.

    Every failure path returns None rather than raising: this feature is
    optional and must never be the reason a menu request fails.
    """
    if not API_KEY:
        logger.info('explain: no EXPLAIN_LLM_API_KEY set; using bullets')
        return None
    try:
        import requests
    except ImportError:  # pragma: no cover
        return None

    url = ENDPOINT.format(model=MODEL)
    body = {
        'systemInstruction': {'parts': [{'text': SYSTEM_PROMPT}]},
        'contents': [{'role': 'user', 'parts': [{'text': payload}]}],
        'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 900,
                             'responseMimeType': 'application/json'},
    }
    try:
        t0 = time.time()
        r = requests.post(url, json=body, timeout=TIMEOUT,
                          headers={'x-goog-api-key': API_KEY})
        if r.status_code == 429:
            logger.warning('explain: rate limited; falling back to bullets')
            return None
        if r.status_code >= 400:
            logger.warning('explain: model HTTP %s; falling back', r.status_code)
            return None
        data = r.json()
        parts = (data.get('candidates') or [{}])[0].get('content', {}).get('parts', [])
        text = ''.join(p.get('text', '') for p in parts)
        logger.info('explain: model replied in %.2fs (%d chars)',
                    time.time() - t0, len(text))
        return text or None
    except Exception as exc:                    # pragma: no cover - network
        logger.warning('explain: model call failed (%s); falling back', exc)
        return None


def _slim(pack: Dict[str, Any]) -> Dict[str, Any]:
    """Trim a pack to what the model needs. Smaller prompt, tighter validator."""
    return {
        'date': pack.get('date'),
        'weekday': pack.get('weekday'),
        'theme': pack.get('theme'),
        'dishes': [d.get('name') for d in (pack.get('dishes') or {}).values()],
        'plate_profile': pack.get('plate_profile'),
        'checks': [{'name': c['name'], 'passed': c['passed'], 'detail': c['detail']}
                   for c in (pack.get('checks') or [])],
        'provenance': pack.get('provenance'),
        'relaxations': pack.get('relaxations'),
    }


def explain_plan(packs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{date: {'prose': str|None, 'bullets': [str], 'llm_used': bool, 'reason': str}}

    Always returns something for every day. `prose` is None whenever the model
    was off, unreachable, or produced something the validator rejected.
    """
    result: Dict[str, Dict[str, Any]] = {
        p['date']: {'prose': None, 'bullets': render_day(p),
                    'llm_used': False, 'reason': 'disabled'}
        for p in packs
    }
    if not ENABLED or not packs:
        return result

    key = pack_hash(packs)
    cached = _cache_get(key)
    if cached is not None:
        for date, prose in cached.items():
            if date in result:
                result[date].update(prose=prose, llm_used=True, reason='cache')
        return result

    raw = _call_model(json.dumps({'days': [_slim(p) for p in packs]},
                                 default=str, separators=(',', ':')))
    if not raw:
        for d in result.values():
            d['reason'] = 'model unavailable'
        return result

    try:
        parsed = json.loads(re.sub(r'^```(?:json)?|```$', '', raw.strip(),
                                   flags=re.MULTILINE).strip())
        days = parsed.get('days') or []
    except Exception as exc:
        logger.warning('explain: unparseable model reply (%s)', exc)
        for d in result.values():
            d['reason'] = 'unparseable reply'
        return result

    by_date = {p['date']: p for p in packs}
    accepted: Dict[str, str] = {}
    for entry in days:
        date = str(entry.get('date') or '')
        prose = str(entry.get('prose') or '')
        pack = by_date.get(date)
        if pack is None:
            continue
        ok, reason = validate(prose, pack)
        if ok:
            accepted[date] = prose
            result[date].update(prose=prose, llm_used=True, reason='ok')
        else:
            # Rejected replies are discarded whole and logged. Do not patch a
            # bad reply into a good one — a half-trusted sentence is worse than
            # a bullet list, because nobody can tell which half to trust.
            logger.warning('explain: rejected prose for %s (%s)', date, reason)
            result[date]['reason'] = f'rejected: {reason}'

    if accepted and len(accepted) == len(packs):
        _cache_put(key, accepted)
    return result
