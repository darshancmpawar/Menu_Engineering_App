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
7. Say which dishes work together, using the reasons in `pairings`. If
   `pairings.gaps` is non-empty, say what the plate is missing — do not call a
   plate balanced when a gap is listed.

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

def _allowed_tokens(pack: Dict[str, Any]) -> Tuple[set, set, set]:
    """`(numbers, dish_names, other_pack_words)` the prose may legally contain.

    The third set is the fix for a false rejection that made the guarantee
    stricter than it claims to be. The rule is "anything the pack did not say,
    the prose may not say" — but the underscored-token check treated EVERY
    snake_case word as dish-shaped, so a model quoting an ingredient, a cuisine
    or a slot the pack does carry had its whole reply discarded:

        "Carrot palya carries green_peas, so the plate is not relying on tovve
         alone for protein."   -> rejected, "unknown dish 'green_peas'"

    `green_peas` is in that pack, as the dish's `primary_protein`. So are
    `mixed_veg`, `south_indian`, `veg_gravy` and every other attribute value.
    Rejecting a true, sourced sentence is not caution — it spends the model's
    output for nothing and pushes the feature to bullets on its best replies.

    Every string value anywhere in the pack is therefore quotable. Dish names
    stay a separate set purely so the rejection message can still say "unknown
    dish" for the case that matters.
    """
    numbers: set = set()
    words: set = set()
    names: set = set()

    def harvest(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                harvest(k)
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
            low = obj.strip().lower()
            if low:
                words.add(low)
                words.add(low.replace('_', ' '))
                # A multi-word value's own words, so "not served for 26 days"
                # does not have to be quoted whole to be quotable.
                for part in re.split(r'[^a-z0-9_]+', low):
                    if part:
                        words.add(part)

    harvest(pack)
    for d in (pack.get('dishes') or {}).values():
        n = str(d.get('name') or '').strip().lower()
        if n:
            names.add(n)
            names.add(n.replace('_', ' '))
    # The date's own components are legitimately quotable.
    for m in _NUMBER_RE.findall(str(pack.get('date') or '')):
        numbers.add(_fmt_num(float(m)))
    return numbers, names, words


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


def _sourced_phrase(phrase: str, names: set, words: set) -> bool:
    """Is *phrase* a pack phrase, or does it contain one, on word boundaries?

    Both directions, because a model may write "Boondi Raita" where the pack
    says `boondi_raita` and may also write "Chicken Chettinad Curry" where the
    pack says `chicken_chettinad`.

    **Word-aligned, which is the whole point.** A plain `cand in phrase` passes
    on any substring, and the pack legitimately contains one-letter words — the
    pairing summary "2 pairing(s) hold this plate together" harvests `s`, and
    `s` is inside `masala`, so "Paneer Butter Masala" was accepted as sourced.
    Padding both sides with spaces before comparing is what makes containment
    mean "these whole words".
    """
    padded = f' {phrase} '
    for cand in names | words:
        boxed = f' {cand} '
        if boxed in padded or padded in boxed:
            return True
    return False


def validate(prose: str, pack: Dict[str, Any]) -> Tuple[bool, str]:
    """Return (ok, reason). A rejected reply is discarded whole, not patched.

    **What this guarantees, and what it does not.** Every NUMBER, every
    snake_case WORD and every Title-Case PHRASE in the reply must appear
    somewhere in the pack. That makes a fabricated statistic or an invented
    dish structurally impossible, which is the failure this feature would
    otherwise have.

    The Title-Case half was missing and the guarantee was overstated without
    it: the snake_case check lowercases the prose and then looks for
    underscores, so it could never fire on "Paneer Butter Masala" — a wholly
    invented dish, written in the form the prompt's own examples use, passed
    validation. A single capitalised word is still not checked (it is usually a
    sentence opener) and neither is an all-lowercase phrase, which is
    undecidable: "the paneer gravy" may be referring to a dish the pack does
    carry. So dish invention is now caught in the form a model actually
    produces it, not in every conceivable form.

    It does NOT police judgement. "Only 3 textures appear, so the plate is a
    little soft" passes: the 3 is sourced, and *soft* is an opinion no rule can
    check. Rule 4 of `SYSTEM_PROMPT` forbids contradicting a check's verdict and
    nothing here enforces it — a validator cannot decide whether free text
    agrees with `texture_contrast: passed`. That boundary is why the BULLETS are
    the primary surface and are gated on `checks.CALIBRATED`, and prose is
    additive: the numbers a chef acts on come from Python either way.
    """
    if not prose or not prose.strip():
        return False, 'empty'
    if _BANNED_RE.search(prose):
        return False, f'banned topic: {_BANNED_RE.search(prose).group(0)!r}'

    numbers, names, words = _allowed_tokens(pack)

    for raw in _NUMBER_RE.findall(prose):
        if _fmt_num(float(raw)) not in numbers:
            return False, f'number {raw!r} is not in the evidence'

    # Underscored tokens are dish-shaped; anything the pack does not carry
    # anywhere — as a dish, an ingredient, a cuisine or a slot — is invented.
    for tok in re.findall(r'\b[a-z]+(?:_[a-z]+)+\b', prose.lower()):
        spaced = tok.replace('_', ' ')
        if tok in names or spaced in names or tok in words or spaced in words:
            continue
        return False, f'unknown dish {tok!r}'

    # ...and the way a model ACTUALLY writes a dish name: capitalised, with
    # spaces. The check above lowercases the prose and then looks for
    # underscores, so it can never fire on "Paneer Butter Masala" — a whole
    # invented dish, in the form the prompt's own examples use, walked straight
    # through the guarantee. Title-Case runs of two or more words are therefore
    # matched against the pack as a phrase.
    #
    # Two or more, and capitalised, because that is where the signal is: a
    # single capitalised word is usually a sentence opener, and an all-lowercase
    # phrase is undecidable — "the paneer gravy" may well be referring to a
    # dish the pack does carry. So this narrows a real hole rather than
    # closing the category; `_COMMON_WORDS` keeps ordinary sentence starts and
    # weekday names out of it.
    for run in re.findall(r'\b(?:[A-Z][a-z]+(?:\s+|[.,;:!?)]|$)){2,}', prose):
        phrase = ' '.join(re.split(r'[^A-Za-z]+', run)).strip().lower()
        parts = [p for p in phrase.split() if p]
        if not parts or all(p in _COMMON_WORDS for p in parts):
            continue
        if _sourced_phrase(phrase, names, words):
            continue
        # A trailing sentence word ("Chicken Chettinad Is Hot") should not sink
        # an otherwise sourced name, so retry without the ordinary words.
        trimmed = ' '.join(p for p in parts if p not in _COMMON_WORDS)
        if trimmed != phrase and _sourced_phrase(trimmed, names, words):
            continue
        return False, f'unknown dish {phrase!r}'

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
        # The pairings are what makes a paragraph about the MEAL possible rather
        # than a recital of the day's counts, so they go in the prompt whole —
        # `gaps` included, since rule 7 asks the model to say when the plate is
        # missing something and it cannot follow that from a summary alone.
        'pairings': pack.get('pairings'),
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
