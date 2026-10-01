"""LLM layer for menu explanations: the overview paragraph and the chef's read.

Lives in `api/` because it does I/O. `src/explain/` must stay network-free so
the verdicts remain unit-testable offline; `tests/platform/test_architecture.py`
enforces that boundary.

This module holds TWO features that share one model, one key and one HTTP call
path. They make opposite bets, on purpose:

1. **The overview** (`explain_plan`, unchanged). The model does not decide
   anything. `src/explain/` has already computed every claim. This module asks
   a model to phrase those claims nicely, then REJECTS the reply if it contains
   a number or a dish name that did not come from the pack. That validator is
   what makes confabulation structurally impossible rather than merely
   discouraged. Without it, this is a fluent-nonsense generator pointed at a
   client-facing surface.

2. **The chef's read** (`explain_chef_read`, new, off by default). Here the
   model IS asked for judgement: which dishes go together, what the star of the
   day is, what is weak, what looks mis-tagged. It uses its own food knowledge
   for that, because no table in this repo knows that rajma chawal is a meal on
   its own. What it may not do is invent: every dish it names must be on
   today's menu, every number must be in the facts, every star needs a reason
   the code can verify, and the client text may not contradict the chef text.
   Free prose for people, a hidden claim list for the checks: the prose has no
   template, so the checks run on the claims, never on the shape. A failed
   draft goes back to the model with the exact problems, up to
   `CHEF_READ_MAX_ATTEMPTS` times; after that the section is simply omitted and
   the overview above still stands. See `docs/chef_read_architecture.md`.

Model: `gemma-4-31b-it` on Google AI Studio. 30 RPM / 14,400 requests per day
free. For the overview this is a rendering task over supplied facts, and a 31B
model does it as well as a 550B one. The chef's read asks for judgement, so its
model is configurable separately (`EXPLAIN_CHEF_READ_MODEL`) and should be
chosen by the capability probe in the architecture doc, not by assumption.

Batching: the overview is ONE call per plan, all days in, one paragraph per day
out. The chef's read is one call per DAY (plus retries), because each day is a
separate piece of judgement and a whole week does not fit one reply.
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

SYSTEM_PROMPT = """You write a short overview of one day's corporate cafeteria \
menu for the chef who will cook it.

You will receive JSON facts. Those facts are the ONLY things you know. You are \
not judging the menu — the judging is already done and handed to you. Your job \
is to say it in a way a working chef reads in ten seconds.

WHAT THIS IS: an overview of the MEAL — which dishes go WITH which, and what \
the plate is missing. It is NOT a compliance report. Nobody wants a list of \
rule names; they want to know whether today's combination works.

`pairings` is where the answer already is. Each entry names dishes and the \
reason they belong together, and each has a `kind`:

  cooling  a hot dish and the yogurt side that answers it
  relief   a hot dish and the mild one to fall back on, when there is no curd
  lightener a rich dish and something light enough to cut it
  protein  where the plate's protein comes from
  crunch   something with bite on a plate that is otherwise soft
  contrast one dry vegetable against one in sauce
  finish   the dessert, against the meal it follows
  carrier  a gravy and the bread or rice it is eaten with

Lead with the ones a cook could not have predicted. `cooling`, `relief` and \
`lightener` are about whether the meal EATS well and are worth a sentence \
each; `carrier` is true of nearly every Indian plate and is worth a clause at \
most. `pairings.gaps` is the other half and matters as much as any of them.

HOW TO WRITE IT:
- Name the dishes. "Gobi 65 is very hot and the boondi raita is what cools it"
  beats "there is a spicy dish and a cooling one."
- Connect the pairings into a paragraph. Do not restate the `detail` strings
  one after another as a list; that is what the fallback already does.
- Vary the sentences. Two pairings joined by the same "X is Y - Z does W"
  shape twice in a row reads like a form.
- One idea per sentence. No semicolon chains.
- Plain kitchen English. No marketing adjectives: nothing is "delightful",
  "vibrant", "a symphony" or "thoughtfully curated".
- Never hedge a real problem into a compliment.

RULES - a reply breaking any of these is discarded:
1. Never state a number that does not appear in the facts.
2. Never name a dish that does not appear in the facts.
3. Never mention nutrition, calories, health, diet or medical effects.
4. FOUR OR FIVE sentences. Open with what the day is, then the pairings that
   matter, then what it lacks.
5. Do NOT name checks or rules ("texture_contrast", "the colour rule"). Say
   what is true of the FOOD: "most of this plate is saucy" reads; "texture
   contrast failed" does not.
6. If `pairings.gaps` is non-empty you must say what is missing, in the same
   plain voice. Never call a plate balanced when a gap is listed - an overview
   that only reports good news is one nobody reads twice.
7. If a relaxation is listed, say plainly that the menu could not fully meet
   what was asked. That is the one thing here a kitchen can act on.
8. Say what is distinctive, using `theme` and `provenance` - a dish not served
   for a long time, a themed day, a dish the client always has. If nothing is
   distinctive, say the day is routine. Do not manufacture an occasion.
9. A good plate should be called good, briefly. Honesty is not pessimism.

EXAMPLE of the shape (the dishes are illustrative; use only the ones you are \
given):
"Thursday is a north menu of six mains. The gobi 65 is the hot dish and the \
boondi raita is there to take the edge off it. Paneer butter masala is the \
rich one at 4 of 5, so the plain chapati and the cucumber salad are doing the \
work of keeping the plate from feeling heavy. Aloo jeera is the only dry \
vegetable against two gravies. Nothing here has been off the menu for long, so \
it is a routine day."

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

    ok, why = _reports_the_bad_news(prose, pack)
    if not ok:
        return False, why

    return True, 'ok'


def _bad_news(pack: Dict[str, Any]) -> List[str]:
    """Everything about this plate a chef would want said out loud.

    **Gaps and relaxations, NOT check names.** A gap is already a sentence
    about the food — "this is hot and nothing here cools it" — and belongs in
    an overview. A failing check is a sentence about the RULESET, and demanding
    the prose name `texture_contrast` would drag the paragraph back into being
    the compliance report this layer is deliberately not. The checks still ride
    in the response for whoever is auditing them.

    A relaxation stays required because it is the one thing here a kitchen can
    act on: a rule the solver could not hold is a menu that is not what the
    client configured.
    """
    out: List[str] = []
    for g in ((pack.get('pairings') or {}).get('gaps') or []):
        text = g if isinstance(g, str) else (g.get('text') or g.get('reason') or '')
        if text:
            out.append(str(text))
    for r in (pack.get('relaxations') or []):
        rule = str(r.get('rule') or '')
        if rule:
            out.append(rule)
    return out


def _reports_the_bad_news(prose: str, pack: Dict[str, Any]) -> Tuple[bool, str]:
    """Reject a reply that stays silent about a plate's problems.

    Rules 4, 5 and 7 of ``SYSTEM_PROMPT`` tell the model to name a failing
    check, a relaxed rule and a missing pairing. Nothing enforced them, and an
    unenforced instruction against flattery is worth very little: the cheapest
    reply a model can write is the one that says everything is lovely, and it
    would have passed every other rule here — each of which only catches
    INVENTION, never omission.

    This cannot check that the prose is *right*. It checks that when the pack
    carries bad news the prose is at least ABOUT it: one content word from one
    of the problems has to appear. A model that lists the day's failing check
    passes; a model that writes "a well-balanced plate with lovely contrast"
    over a plate with a gap does not, and the deterministic bullets — which
    already lead with failures — stand instead.

    A clean plate constrains nothing, which is correct: there is no bad news to
    demand, and requiring hedging on a good day would be its own dishonesty.
    """
    problems = _bad_news(pack)
    if not problems:
        return True, 'ok'
    low = prose.lower()
    for problem in problems:
        for word in re.split(r'[^a-z]+', problem.lower()):
            # `_COMMON_WORDS` would let "the"/"is" satisfy this trivially, and a
            # two-letter fragment matches almost anything.
            if len(word) > 3 and word not in _COMMON_WORDS and word in low:
                return True, 'ok'
    return False, (
        'says nothing about ' + '; '.join(problems[:3])
        + ' — a reply that only reports good news is discarded'
    )


# --- model call ------------------------------------------------------------

def _post_model(system_prompt: str, contents: List[Dict[str, Any]], *,
                model: Optional[str] = None, max_tokens: int = 900,
                temperature: float = 0.3, tag: str = 'explain') -> Optional[str]:
    """POST one request to the model. Returns raw text, or None on any failure.

    Shared by the overview and the chef's read so there is exactly one place
    that knows the Gemini request shape, the key header and the failure rules.
    `contents` is the Gemini turn list: `[{'role': 'user'|'model', 'parts':
    [{'text': ...}]}]`, which is what lets the chef's read send a rejected
    draft back with its problems.

    Every failure path returns None rather than raising: both features are
    optional and must never be the reason a menu request fails.
    """
    if not API_KEY:
        logger.info('%s: no EXPLAIN_LLM_API_KEY set; using the fallback', tag)
        return None
    try:
        import requests
    except ImportError:  # pragma: no cover
        return None

    url = ENDPOINT.format(model=model or MODEL)
    body = {
        'systemInstruction': {'parts': [{'text': system_prompt}]},
        'contents': contents,
        'generationConfig': {'temperature': temperature, 'maxOutputTokens': max_tokens,
                             'responseMimeType': 'application/json'},
    }
    try:
        t0 = time.time()
        r = requests.post(url, json=body, timeout=TIMEOUT,
                          headers={'x-goog-api-key': API_KEY})
        if r.status_code == 429:
            logger.warning('%s: rate limited; falling back', tag)
            return None
        if r.status_code >= 400:
            logger.warning('%s: model HTTP %s; falling back', tag, r.status_code)
            return None
        data = r.json()
        parts = (data.get('candidates') or [{}])[0].get('content', {}).get('parts', [])
        text = ''.join(p.get('text', '') for p in parts)
        logger.info('%s: model replied in %.2fs (%d chars)',
                    tag, time.time() - t0, len(text))
        return text or None
    except Exception as exc:                    # pragma: no cover - network
        logger.warning('%s: model call failed (%s); falling back', tag, exc)
        return None


def _call_model(payload: str) -> Optional[str]:
    """POST the overview request. Returns raw text, or None on any failure.

    Kept with its original one-argument signature: tests and callers patch it
    by name, and the overview's behaviour must not change because the chef's
    read now shares the HTTP path.
    """
    if not API_KEY:
        logger.info('explain: no EXPLAIN_LLM_API_KEY set; using bullets')
        return None
    return _post_model(SYSTEM_PROMPT,
                       [{'role': 'user', 'parts': [{'text': payload}]}],
                       max_tokens=900, temperature=0.3, tag='explain')


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


# ===========================================================================
# THE CHEF'S READ
# ===========================================================================
# Everything below is the second feature. It shares the model call above and
# reuses `_BANNED_RE`, `_allowed_tokens`, `_fmt_num` and `_reports_the_bad_news`,
# and changes nothing about `explain_plan`. Design: docs/chef_read_architecture.md.

# --- configuration ---------------------------------------------------------
# Off by default, independently of the overview: turning on the overview must
# not silently turn on judgement. Both need EXPLAIN_LLM_API_KEY.
CHEF_READ_ENABLED = os.getenv('EXPLAIN_CHEF_READ_ENABLED', 'false').strip().lower() == 'true'
CHEF_READ_MODEL = os.getenv('EXPLAIN_CHEF_READ_MODEL', '').strip() or MODEL
CHEF_READ_MAX_ATTEMPTS = max(1, int(os.getenv('EXPLAIN_CHEF_READ_MAX_ATTEMPTS', '3')))
CHEF_READ_MAX_TOKENS = int(os.getenv('EXPLAIN_CHEF_READ_MAX_TOKENS', '1200'))
CHEF_READ_TEMPERATURE = 0.2      # low, so the same menu gets the same star

# Bump whenever the prompt or the checks change: it is part of the cache key,
# so an old accepted read is never served against new rules.
CHEF_READ_PROMPT_VERSION = 'chef-read-v1'

# A dish counts as a comeback only past the item cooldown (20 days), so the
# claim says something the cooldown alone would not have produced.
COMEBACK_DAYS = 21

CLIENT_MAX_WORDS = 110
INTERNAL_MAX_WORDS = 170

CHEF_READ_SYSTEM_PROMPT = """You read one day's menu at a corporate cafeteria \
in India and write two short notes about it.

You know Indian food well: which dishes are eaten together, what a \
north-Indian or a south-Indian diner looks for, which dish people will queue \
for, and when a menu does not quite come together. Use that knowledge. The \
facts tell you what is on the counter today and what we know about each dish. \
They do not tell you what to say.

WHAT TO WRITE

client_read: a note for the people eating today. Tell them what is worth \
knowing about THIS menu. That might be how to put a good plate together, the \
dish you would point a friend to, the thread running through the day (a \
region, a theme), something that is back after a long time, or simply that it \
is an easy day. Pick what matters today and leave out what does not. Warm and \
plain, like a colleague who knows food. Two to five sentences.

internal_read: the same menu for the chef and the menu planner. Be direct. Say \
what works, what does not, and why, in kitchen language. If a group of diners \
has no proper plate, if the theme does not really show, if the day finishes \
heavy, or if two dishes are too alike, say so. If the facts list \
known_problems, address the worst one. If a dish looks wrongly described in \
the facts (a south-Indian dish marked north, say), say it here. Up to six \
sentences.

There is no template. No headings, no lists, no labels, and do not open the \
way other days opened (other_days_open_with shows how earlier days began). \
Some days need one line and some need five. Let the menu decide.

HARD LIMITS. A draft that breaks any of these is sent back to you:
1. Name only dishes in the facts. You may shorten a name ("the soya chatpata" \
for soya_chatpata_dry). Never mention a dish that is not on today's counter, \
not even as a comparison.
2. Write dish names in plain words, never with underscores.
3. Use no number that is not in the facts. "Back after 26 days" is fine only \
if days_since_served says 26.
4. Never mention health, nutrition, calories, diet or medical effects.
5. client_read never mentions how the menu was made: no rules, scores, \
cooldowns, tags, slots, data or systems.
6. client_read never contradicts internal_read. It may leave a problem out, or \
turn it into a tip ("for a north-style plate, pair the chapati with the soya \
chatpata"), but it may never praise what internal_read criticises.
7. Call something a comeback only if has_history is true and \
days_since_served is 21 or more.
8. Never suggest bread with rasam as a plate.

THE STAR
Pick a star only if one dish genuinely stands out; otherwise set star to null. \
Give the reason in plain words, and a basis the facts can confirm:
  premium     the dish is marked premium
  comeback    it is back after 21 or more days
  regional    it carries today's regional day
  pinned      the client asked for it
  theme       it is the clearest expression of today's theme
  plate_role  it ties together two or more of the plates you suggest
Richness alone is not a reason. Think about who will eat it: a star most \
diners cannot or will not eat is a poor star.

OUTPUT: strict JSON, no markdown fences:
{"client_read": "...",
 "internal_read": "...",
 "claims": {
   "plates": [{"for": "who this plate suits", "dishes": ["...", "..."]}],
   "star": {"dish": "...", "basis": "premium|comeback|regional|pinned|theme|plate_role", "why": "..."},
   "comebacks": ["..."],
   "weak_spots": [{"kind": "theme_mismatch|incomplete_plate|heavy|repetitive|clash|other", "text": "..."}],
   "data_doubts": [{"dish": "...", "field": "cuisine_family|state_origin", "tagged": "...", "likely": "...", "why": "..."}]
 }}
star may be null. List in claims every plate, star, comeback and weakness your \
notes mention, and inside claims write dish names exactly as the facts do."""

# Words that describe how the menu was MADE. Fine for a chef, meaningless or
# alarming for an HR admin reading the client note.
CLIENT_BANNED_WORDS = (
    'rule', 'rules', 'cooldown', 'solver', 'tag', 'tagged', 'tags', 'ontology',
    'score', 'scores', 'richness', 'slot', 'slots', 'constraint', 'constraints',
    'relaxation', 'relaxed', 'algorithm', 'dataset', 'data', 'system',
)
_CLIENT_BANNED_RE = re.compile(r'\b(' + '|'.join(CLIENT_BANNED_WORDS) + r')\b', re.IGNORECASE)

# The meal-grammar VETO. Deliberately tiny: it blocks pairings no Indian diner
# would call a plate and nothing else. An allow-list was tried first and it
# rejected pulao with a dry vegetable, a perfectly normal plate; the model's
# food knowledge decides what goes well together, this only catches absurdity.
VETO_PAIRS = frozenset({('bread', 'rasam')})

CARB_SLOTS = frozenset({'bread', 'rice', 'white_rice', 'curd_rice', 'healthy_rice', 'biryani'})
_CARB_WORDS = ('biryani', 'pulao', 'rice', 'chawal', 'roti', 'paratha', 'chapati',
               'phulka', 'kulcha', 'naan', 'dosa', 'idli', 'bhature', 'puri', 'khichdi')

STAR_BASES = ('premium', 'comeback', 'regional', 'pinned', 'theme', 'plate_role')
WEAK_KINDS = ('theme_mismatch', 'incomplete_plate', 'heavy', 'repetitive', 'clash', 'other')
DOUBT_FIELDS = ('cuisine_family', 'state_origin')

# Which client words would contradict which internal weakness. Small on
# purpose: it catches the contradictions a model actually writes ("a true north
# spread" over "the north theme is thin"), not every possible one.
_CONTRADICTIONS = {
    'heavy': re.compile(r'\b(light|lighter|easy on the stomach)\b', re.IGNORECASE),
    'repetitive': re.compile(r'\b(varied|variety|something different)\b', re.IGNORECASE),
}
_PRAISE_RE = re.compile(r'\b(perfect|perfectly|balanced|flawless)\b', re.IGNORECASE)

_chef_cache: Dict[str, Dict[str, Any]] = {}
_chef_cache_order: List[str] = []


def reset_chef_read_cache_for_tests() -> None:
    with _cache_lock:
        _chef_cache.clear()
        _chef_cache_order.clear()


def _chef_cache_get(key: str) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        hit = _chef_cache.get(key)
        return json.loads(json.dumps(hit)) if hit is not None else None


def _chef_cache_put(key: str, value: Dict[str, Any]) -> None:
    with _cache_lock:
        if key not in _chef_cache:
            _chef_cache_order.append(key)
        _chef_cache[key] = json.loads(json.dumps(value, default=str))
        while len(_chef_cache_order) > MAX_CACHE_ENTRIES:
            _chef_cache.pop(_chef_cache_order.pop(0), None)


# --- facts -------------------------------------------------------------------

def _plain(name: Any) -> str:
    return re.sub(r'\s+', ' ', str(name or '').strip().lower().replace('_', ' '))


def _base_slot(slot: str) -> str:
    return str(slot).split('__')[0]


def chef_attrs_from_dataframe(df: Any) -> Dict[str, Dict[str, Any]]:
    """Ontology DataFrame -> `{item: {'state_origin': str|None, 'premium': bool}}`.

    The overview's pack (`src/explain/evidence.DISH_COLUMNS`) does not carry
    the state a dish comes from or its premium flags, and the chef's read needs
    both: one for regional days and cuisine doubts, the other for the star.
    Any `is_premium*` column set to 1 marks the dish premium.
    """
    cols = list(getattr(df, 'columns', []))
    premium_cols = [c for c in cols if str(c).startswith('is_premium')]
    keep = ['item'] + (['state_origin'] if 'state_origin' in cols else []) + premium_cols
    out: Dict[str, Dict[str, Any]] = {}
    for rec in df[keep].to_dict('records'):
        name = str(rec.get('item') or '').strip()
        if not name:
            continue
        premium = False
        for c in premium_cols:
            try:
                premium = premium or float(rec.get(c) or 0) == 1
            except (TypeError, ValueError):
                continue
        state = rec.get('state_origin')
        state = None if state is None or str(state).strip().lower() in ('', 'nan', 'none') else str(state).strip()
        row = {'state_origin': state, 'premium': premium}
        out[name] = row
        out.setdefault(_plain(name), row)
    return out


def city_dish_names_from_dataframe(df: Any) -> List[str]:
    """Every dish name in the city list, used to catch off-menu dishes in any casing."""
    return sorted({str(n) for n in df['item'].dropna().tolist() if str(n).strip()})


def build_chef_facts(pack: Dict[str, Any], *,
                     extras: Optional[Dict[str, Dict[str, Any]]] = None,
                     recency: Optional[Dict[str, int]] = None,
                     region: Optional[str] = None,
                     prior_openings: Optional[List[str]] = None) -> Dict[str, Any]:
    """One day's evidence pack -> the facts the chef's read is allowed to use.

    Built FROM the overview's pack, so both features describe the same dishes
    with the same attributes. Adds what judgement needs and the pack lacks:
    state, premium, days since last served, pinned, and the plate's known
    problems (gaps, relaxations, failing checks) so the chef note cannot ignore
    them.
    """
    extras = extras or {}
    recency_norm = {_plain(k): v for k, v in (recency or {}).items()}
    # `client_constant` is how `build_provenance` marks a dish the client pinned.
    pinned = {_plain(p.get('dish')) for p in (pack.get('provenance') or [])
              if str(p.get('reason') or '') == 'client_constant'}
    dishes = []
    for slot, d in (pack.get('dishes') or {}).items():
        name = str(d.get('name') or '').strip()
        if not name:
            continue
        ex = extras.get(name) or extras.get(_plain(name)) or {}
        days = recency_norm.get(_plain(name))
        dishes.append({
            'name': name,
            'slot': _base_slot(slot),
            'course_type': d.get('course_type'),
            'kind': d.get('sub_category'),
            'cuisine_family': d.get('cuisine_family'),
            'state_origin': ex.get('state_origin'),
            'key_ingredient': d.get('key_ingredient'),
            'protein': d.get('primary_protein'),
            'texture': d.get('texture'),
            'spice_level': d.get('spice_level'),
            'richness': d.get('richness_score'),
            'premium': bool(ex.get('premium')),
            'pinned': _plain(name) in pinned,
            'days_since_served': int(days) if days is not None else None,
        })
    problems = list(_bad_news(pack))
    for c in (pack.get('checks') or []):
        if c.get('passed') is False and c.get('detail'):
            problems.append(str(c['detail']))
    return {
        'date': pack.get('date'),
        'weekday': pack.get('weekday'),
        'theme': pack.get('theme'),
        'regional_day': region,
        'has_history': bool(recency),
        'dishes': dishes,
        'known_problems': problems,
        'other_days_open_with': list(prior_openings or []),
    }


# --- checks ----------------------------------------------------------------

class _Menu:
    """Today's dishes, with the lookups the checks need."""

    def __init__(self, facts: Dict[str, Any]):
        self.facts = facts
        self.by_plain = {_plain(d['name']): d for d in facts.get('dishes') or []}

    def resolve(self, name: Any) -> Optional[Dict[str, Any]]:
        """A claimed dish -> today's dish, allowing a shortened name.

        "soya chatpata" resolves to soya_chatpata_dry. A short form that fits
        two of today's dishes is ambiguous and does not resolve.
        """
        p = _plain(name)
        if not p:
            return None
        if p in self.by_plain:
            return self.by_plain[p]
        hits = [d for k, d in self.by_plain.items() if f' {p} ' in f' {k} ']
        return hits[0] if len(hits) == 1 else None

    def is_carb(self, d: Dict[str, Any]) -> bool:
        if d.get('slot') in CARB_SLOTS:
            return True
        hay = f"{_plain(d.get('name'))} {_plain(d.get('kind'))}"
        return any(w in hay for w in _CARB_WORDS)


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-z']+", text or ''))


def _off_menu_dishes(text: str, menu: _Menu, city_names: List[str]) -> List[str]:
    """Real dishes from the city list that the text names but today lacks.

    The overview's validator cannot see an all-lowercase dish name ("the dal
    makhani anchors it"), which is exactly how a model writes when it reaches
    for a dish from memory. Matching against the city list catches that, in
    any casing. Names that are part of one of today's dishes are allowed,
    because "chapati" inside "jeera chapati" is a short form, not an invention.
    """
    low = f' {_plain(text)} '
    today = list(menu.by_plain)
    found = []
    for raw in city_names:
        name = _plain(raw)
        if len(name) < 5 or name in menu.by_plain:
            continue
        first = name.split(' ')[0]
        if f' {first}' not in low:
            continue
        if any(f' {name} ' in f' {t} ' for t in today):
            continue
        if re.search(rf'(?<![a-z]){re.escape(name)}(?![a-z])', low):
            found.append(name)
    return found


def check_chef_read(reply: Dict[str, Any], facts: Dict[str, Any], pack: Dict[str, Any],
                    city_dish_names: Optional[List[str]] = None) -> List[str]:
    """Every problem with a draft, in words the model can act on. Empty = accept.

    Checks TRUTH, never SHAPE: the prose has no template, so nothing here asks
    for a plate, a star, an order or a length beyond a ceiling. Each message is
    written to be sent straight back to the model.
    """
    problems: List[str] = []
    menu = _Menu(facts)
    city = city_dish_names or []

    client = reply.get('client_read')
    internal = reply.get('internal_read')
    claims = reply.get('claims')
    if not isinstance(client, str) or not client.strip():
        problems.append('client_read is missing or empty.')
        client = ''
    if not isinstance(internal, str) or not internal.strip():
        problems.append('internal_read is missing or empty.')
        internal = ''
    if not isinstance(claims, dict):
        problems.append('claims is missing; return it as an object, even if its lists are empty.')
        claims = {}

    # `_allowed_tokens` expects the overview's dish dict; the facts carry a list.
    token_view = dict(facts, dishes={str(i): d for i, d in enumerate(facts.get('dishes') or [])})
    numbers = _allowed_tokens(token_view)[0]
    for label, text in (('client_read', client), ('internal_read', internal)):
        if not text:
            continue
        hit = _BANNED_RE.search(text)
        if hit:
            problems.append(f'{label} mentions {hit.group(0)!r}; never mention health, nutrition or diet.')
        for raw in _NUMBER_RE.findall(text):
            if _fmt_num(float(raw)) not in numbers:
                problems.append(f'{label} uses the number {raw}, which is not in the facts.')
        for tok in re.findall(r'\b[a-z]+(?:_[a-z]+)+\b', text.lower()):
            problems.append(f'{label} writes {tok!r} with underscores; use plain words.')
            break
        for name in _off_menu_dishes(text, menu, city):
            problems.append(f'{label} names "{name}", which is not on today\'s menu. Remove it.')

    # client note: no internals, no contradictions
    if client:
        hit = _CLIENT_BANNED_RE.search(client)
        if hit:
            problems.append(f'client_read says {hit.group(0)!r}; the client note must not talk about how the menu was made.')
        if _words(client) > CLIENT_MAX_WORDS:
            problems.append(f'client_read is too long; keep it under {CLIENT_MAX_WORDS} words.')
        openings = [_plain(o) for o in facts.get('other_days_open_with') or [] if o]
        head = ' '.join(_plain(client).split()[:4])
        if head and any(o.startswith(head) or head.startswith(o) for o in openings if o):
            problems.append('client_read opens the same way as another day; start differently.')
    if internal and _words(internal) > INTERNAL_MAX_WORDS:
        problems.append(f'internal_read is too long; keep it under {INTERNAL_MAX_WORDS} words.')

    weak = claims.get('weak_spots') or []
    if not isinstance(weak, list):
        weak = []
    kinds = {str(w.get('kind') or '') for w in weak if isinstance(w, dict)}
    theme_words = [w for w in (facts.get('theme'), facts.get('regional_day')) if w]
    if client and 'theme_mismatch' in kinds and theme_words:
        alt = '|'.join(re.escape(_plain(w).split()[0]) for w in theme_words)
        if re.search(rf'\b(classic|true|authentic|proper|full|real|pure)\s+({alt})', client, re.IGNORECASE):
            problems.append('client_read praises the theme while internal_read says it does not show; '
                            'turn it into a tip instead.')
    for kind, pattern in _CONTRADICTIONS.items():
        if client and kind in kinds and pattern.search(client):
            problems.append(f'client_read says {pattern.search(client).group(0)!r} but internal_read '
                            f'flags the day as {kind}.')
    if client and facts.get('known_problems') and _PRAISE_RE.search(client):
        problems.append(f'client_read calls the menu {_PRAISE_RE.search(client).group(0)!r} although '
                        'the plate has a known problem.')

    # internal note must face the known problems
    if facts.get('known_problems'):
        if not weak:
            problems.append('The facts list known_problems; name the worst one in internal_read and weak_spots.')
        ok, _why = _reports_the_bad_news(internal, pack) if internal else (False, '')
        if internal and not ok:
            problems.append('internal_read does not address the known problem: '
                            + '; '.join(facts['known_problems'][:2]) + '.')
    for w in weak:
        if isinstance(w, dict) and w.get('kind') not in WEAK_KINDS:
            problems.append(f'weak_spots kind {w.get("kind")!r} is not one of {", ".join(WEAK_KINDS)}.')

    # plates
    plates = claims.get('plates') or []
    if not isinstance(plates, list):
        plates = []
    plate_sets: List[List[str]] = []
    for p in plates:
        if not isinstance(p, dict):
            continue
        resolved = []
        for name in p.get('dishes') or []:
            d = menu.resolve(name)
            if d is None:
                problems.append(f'plate dish "{name}" is not on today\'s menu.')
            else:
                resolved.append(d)
        if not resolved:
            continue
        plate_sets.append([d['name'] for d in resolved])
        if not any(menu.is_carb(d) for d in resolved):
            problems.append('the plate ' + ' + '.join(_plain(d['name']) for d in resolved)
                            + ' has no rice or bread; a plate needs one.')
        slots = {d['slot'] for d in resolved}
        for a, b in VETO_PAIRS:
            if a in slots and b in slots:
                problems.append(f'{a} with {b} is not a plate people eat; pair the {a} with a dry vegetable, '
                                'a gravy, a dal or curd instead.')

    # star
    star = claims.get('star')
    if star not in (None, {}, ''):
        if not isinstance(star, dict):
            problems.append('star must be an object or null.')
        else:
            d = menu.resolve(star.get('dish'))
            basis = str(star.get('basis') or '')
            if d is None:
                problems.append(f'star "{star.get("dish")}" is not on today\'s menu.')
            elif basis not in STAR_BASES:
                problems.append(f'star basis {basis!r} is not one of {", ".join(STAR_BASES)}.')
            else:
                true = {
                    'premium': bool(d.get('premium')),
                    'comeback': bool(facts.get('has_history')) and (d.get('days_since_served') or 0) >= COMEBACK_DAYS,
                    'regional': bool(facts.get('regional_day')) and _plain(d.get('state_origin')) == _plain(facts.get('regional_day')),
                    'pinned': bool(d.get('pinned')),
                    'theme': _matches_theme(d, facts.get('theme')),
                    'plate_role': sum(d['name'] in s for s in plate_sets) >= 2,
                }[basis]
                if not true:
                    problems.append(f'the star basis "{basis}" is not true for {_plain(d["name"])}; '
                                    'pick a basis the facts confirm, another star, or null.')
            if not str(star.get('why') or '').strip():
                problems.append('the star needs a reason in plain words.')

    # comebacks
    for name in claims.get('comebacks') or []:
        d = menu.resolve(name)
        if d is None:
            problems.append(f'comeback "{name}" is not on today\'s menu.')
        elif not facts.get('has_history') or (d.get('days_since_served') or 0) < COMEBACK_DAYS:
            problems.append(f'{_plain(d["name"])} is not a comeback: it needs {COMEBACK_DAYS}+ days since it was last served.')

    # data doubts must quote the facts correctly
    for dd in claims.get('data_doubts') or []:
        if not isinstance(dd, dict):
            continue
        d = menu.resolve(dd.get('dish'))
        field = dd.get('field')
        if d is None or field not in DOUBT_FIELDS:
            problems.append('each data_doubt needs a dish on today\'s menu and field cuisine_family or state_origin.')
        elif _plain(dd.get('tagged')) != _plain(d.get(field)):
            problems.append(f'data_doubt for {_plain(d["name"])} says it is tagged {dd.get("tagged")!r}, '
                            f'but the facts say {d.get(field)!r}.')

    # one message per problem, in order
    seen, out = set(), []
    for p in problems:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _matches_theme(d: Dict[str, Any], theme: Any) -> bool:
    t = _plain(theme)
    if not t or t == 'mix':
        return False
    hay = f"{_plain(d.get('cuisine_family'))} {_plain(d.get('kind'))} {_plain(d.get('name'))}"
    return t.split()[0] in hay


def _feedback(problems: List[str]) -> str:
    return ('Your draft was not accepted. Fix only these and keep everything else as it was:\n- '
            + '\n- '.join(problems)
            + '\nReply with the full JSON again, no markdown.')


def _parse_reply(raw: str) -> Optional[Dict[str, Any]]:
    try:
        parsed = json.loads(re.sub(r'^```(?:json)?|```$', '', raw.strip(), flags=re.MULTILINE).strip())
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


# --- the loop -------------------------------------------------------------

def _empty_read(reason: str) -> Dict[str, Any]:
    return {'source': None, 'reason': reason, 'client_read': None, 'internal_read': None,
            'star': None, 'plates': [], 'comebacks': [], 'weak_spots': [], 'data_doubts': [],
            'attempts': 0, 'problems_by_attempt': []}


def chef_read_day(pack: Dict[str, Any], facts: Dict[str, Any],
                  city_dish_names: Optional[List[str]] = None) -> Dict[str, Any]:
    """Draft, check, send problems back, repeat. One day.

    Returns a filled read with `source='model'`, or an empty one with the
    reason. `problems_by_attempt` keeps every rejection, which is the raw
    material for the learning loop in the architecture doc.
    """
    out = _empty_read('disabled')
    contents: List[Dict[str, Any]] = [{'role': 'user', 'parts': [
        {'text': json.dumps(facts, default=str, separators=(',', ':'))}]}]
    for attempt in range(1, CHEF_READ_MAX_ATTEMPTS + 1):
        out['attempts'] = attempt
        raw = _post_model(CHEF_READ_SYSTEM_PROMPT, contents, model=CHEF_READ_MODEL,
                          max_tokens=CHEF_READ_MAX_TOKENS, temperature=CHEF_READ_TEMPERATURE,
                          tag='chef_read')
        if not raw:
            # A network failure is not a bad draft; retrying would only spend quota.
            out['reason'] = 'model unavailable'
            return out
        reply = _parse_reply(raw)
        problems = (['The reply was not valid JSON. Return only the JSON object.']
                    if reply is None else check_chef_read(reply, facts, pack, city_dish_names))
        out['problems_by_attempt'].append(problems)
        if not problems:
            claims = reply.get('claims') or {}
            out.update(
                source='model', reason='ok' if attempt == 1 else f'ok after {attempt} attempts',
                client_read=reply['client_read'].strip(), internal_read=reply['internal_read'].strip(),
                star=claims.get('star') or None, plates=claims.get('plates') or [],
                comebacks=claims.get('comebacks') or [], weak_spots=claims.get('weak_spots') or [],
                data_doubts=claims.get('data_doubts') or [],
            )
            for dd in out['data_doubts']:
                logging.getLogger('explain.data_doubts').info(
                    'data doubt %s: %s tagged %r, model thinks %r (%s)', facts.get('date'),
                    dd.get('dish'), dd.get('tagged'), dd.get('likely'), dd.get('why'))
            return out
        logger.info('chef_read: %s attempt %d rejected: %s', facts.get('date'), attempt, problems)
        contents.append({'role': 'model', 'parts': [{'text': raw}]})
        contents.append({'role': 'user', 'parts': [{'text': _feedback(problems)}]})
    first = (out['problems_by_attempt'][-1] or ['unknown'])[0]
    out['reason'] = f'rejected after {CHEF_READ_MAX_ATTEMPTS} attempts: {first}'
    return out


def explain_chef_read(packs: List[Dict[str, Any]], *,
                      extras: Optional[Dict[str, Dict[str, Any]]] = None,
                      recency: Optional[Dict[str, int]] = None,
                      region_days: Optional[Dict[str, str]] = None,
                      city_dish_names: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    """{date: chef read} for every day. Never raises, never blocks the overview.

    Days run in order so each one sees how the earlier days opened and can
    start differently. A day that fails keeps `source=None` and its reason; the
    overview from `explain_plan` is unaffected either way.
    """
    if not CHEF_READ_ENABLED or not packs:
        return {p['date']: _empty_read('disabled') for p in packs}
    if not API_KEY:
        return {p['date']: _empty_read('model unavailable') for p in packs}

    result: Dict[str, Dict[str, Any]] = {}
    openings: List[str] = []
    for pack in packs:
        date = pack['date']
        try:
            facts = build_chef_facts(pack, extras=extras, recency=recency,
                                     region=(region_days or {}).get(date), prior_openings=openings)
            key = hashlib.sha256(json.dumps(
                [CHEF_READ_PROMPT_VERSION, CHEF_READ_MODEL, facts],
                sort_keys=True, default=str).encode('utf-8')).hexdigest()
            cached = _chef_cache_get(key)
            if cached is not None:
                cached['reason'] = 'cache'
                read = cached
            else:
                read = chef_read_day(pack, facts, city_dish_names)
                if read.get('source') == 'model':
                    _chef_cache_put(key, read)
        except Exception as exc:                 # pragma: no cover - defensive
            logger.warning('chef_read: %s failed (%s)', date, exc, exc_info=True)
            read = _empty_read('error')
        result[date] = read
        if read.get('client_read'):
            openings.append(' '.join(str(read['client_read']).split()[:6]))
    return result
