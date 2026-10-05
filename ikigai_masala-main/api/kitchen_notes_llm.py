"""Kitchen notes for the month's high-risk vegetables, written for this week's dishes.

The sheet's own notes are generic ("Use tomato purée in place of whole
tomatoes"). Once a menu exists, a model can say what they mean for THIS week:
which mixed-vegetable dish needs which vegetables left out, what to use
instead, how to make a pinned dish without its red-list vegetable.

It shares the explainer's model, key and HTTP call (``api.explain_llm``) and
the same safety shape as the chef's read: the model writes freely, returns a
claim list, and code checks it. A draft that fails goes back with its problems,
up to ``KITCHEN_NOTES_MAX_ATTEMPTS`` times. If it still fails, or the model is
off or unreachable, the kitchen gets the deterministic notes instead: the
sheet's lines, the mixed-vegetable line and one line per clashing pin. Correct
instructions always reach the kitchen; the model only makes them specific.

The checks, each a line the model can act on:
  * every dish it names is on this week's menu (any casing, short forms allowed);
  * every swap comes from the month's safe alternatives, never the red or
    yellow list;
  * a red-list vegetable is only mentioned to say leave it out;
  * every sheet instruction survives (purée, English cucumber, no tomato in salad);
  * every pinned dish with a red-list vegetable gets a note;
  * no health claims, no numbers that are not in the facts, no underscores.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from api import explain_llm as llm
from src.seasonal.bans import MonthBans, VegetableMatcher, default_matcher, vegetable_label

logger = logging.getLogger('explain.kitchen_notes')

KITCHEN_NOTES_ENABLED = os.getenv('KITCHEN_NOTES_ENABLED', 'true').strip().lower() == 'true'
KITCHEN_NOTES_MAX_ATTEMPTS = max(1, int(os.getenv('KITCHEN_NOTES_MAX_ATTEMPTS', '3')))
KITCHEN_NOTES_MAX_TOKENS = int(os.getenv('KITCHEN_NOTES_MAX_TOKENS', '1500'))
KITCHEN_NOTES_PROMPT_VERSION = 'kitchen-notes-v1'
MAX_NOTES = 10
MAX_NOTE_WORDS = 35
MIXED_VEG_LINE = 'Mixed-vegetable dishes stay on the menu: leave out the red-list vegetables when cooking them.'

SYSTEM_PROMPT = """You write short kitchen notes for a corporate cafeteria in \
India. This month some vegetables are high-risk. The facts give the red list \
(never used), the yellow list (avoid where possible), the sheet's own notes, \
the safe alternatives, and this week's dishes that need care.

Write notes a cook can act on today. For a mixed-vegetable dish, say which \
red-list vegetables to leave out and which safe alternatives to use instead. \
For a dish led by a yellow-list vegetable (tomato rice, say), say how to handle \
it, following the sheet's notes. For each pinned dish listed, say how to make \
it without its red-list vegetable. Keep every instruction in the sheet's notes. \
Skip dishes that need nothing. Plain words, one or two short sentences each.

HARD LIMITS. A draft that breaks any of these is sent back to you:
1. Name only dishes from the facts. You may shorten a name.
2. Swaps come only from the safe alternatives. Never suggest a red-list or \
yellow-list vegetable as a swap.
3. Mention a red-list vegetable only to say leave it out.
4. Keep every sheet note's instruction (tomato purée, English cucumber, no \
tomato in salad) in at least one note.
5. No health, nutrition or diet claims. No numbers that are not in the facts. \
No underscores in dish names.
6. At most 10 notes, each under 35 words.

OUTPUT: strict JSON, no markdown:
{"notes": [{"when": "Mon|Tue|...|All week|Pinned", "dish": "dish name or null", "text": "..."}],
 "swaps": [{"dish": "...", "leave_out": ["..."], "use": ["..."]}]}
List every swap your notes suggest in "swaps"."""

_NEGATION = re.compile(r"\b(no|not|without|skip|leave out|leaving out|avoid|instead of|replace|"
                       r"never|drop|omit|minus|off the|swap out)\b", re.IGNORECASE)

_cache: Dict[str, Dict[str, Any]] = {}


def reset_cache_for_tests() -> None:
    _cache.clear()


def _plain(s: Any) -> str:
    return re.sub(r'\s+', ' ', str(s or '').strip().lower().replace('_', ' '))


def deterministic_notes(bans: MonthBans, pinned: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """What the kitchen gets without a model: the sheet, mixed veg, and pins."""
    notes = [{'when': 'All week', 'dish': None, 'text': n, 'pinned': False} for n in bans.notes]
    if bans.red:
        notes.append({'when': 'All week', 'dish': None, 'text': MIXED_VEG_LINE, 'pinned': False})
    for p in pinned:
        veg = ', '.join(p['vegetables']).lower()
        notes.append({'when': 'Pinned', 'dish': p['dish'], 'pinned': True,
                      'text': f"{_pretty(p['dish'])} is pinned for this client: make it without {veg} this month."})
    return notes


def _pretty(name: str) -> str:
    s = _plain(name)
    return s[:1].upper() + s[1:]


def _alternative_words(bans: MonthBans) -> List[str]:
    """'Arbi (Colocasia)' -> ['arbi', 'colocasia']: every name a swap may use."""
    words = []
    for a in bans.alternatives:
        for part in re.split(r'[()]', a):
            for piece in re.split(r',| or ', part):
                p = _plain(piece)
                if p:
                    words.append(p)
    return words


def build_facts(bans: MonthBans, days: List[Dict[str, Any]], pinned: List[Dict[str, Any]],
                matcher: Optional[VegetableMatcher] = None) -> Dict[str, Any]:
    """``days``: [{'day': 'Mon 26 Oct', 'dishes': [{'name', 'key_ingredient', 'leafy'}]}].

    Only dishes that need care are sent: mixed-vegetable dishes, dishes with a
    yellow-list vegetable, salads when there is a salad rule, and pins.
    """
    m = matcher or default_matcher()
    pinned_names = {_plain(p['dish']) for p in pinned}
    out_days = []
    for day in days:
        care = []
        for d in day.get('dishes') or []:
            name = d.get('name')
            ki = str(d.get('key_ingredient') or '').lower()
            yellow = sorted(m.vegetables_in(name, ki, bans.yellow, d.get('leafy')))
            red = sorted(m.vegetables_in(name, ki, bans.red, d.get('leafy')))
            mixed = ki == 'mixed_vegetables'
            salad = str(d.get('slot') or '').startswith('salad') and bool(bans.salad_bans)
            if mixed or yellow or red or salad or _plain(name) in pinned_names:
                care.append({'name': name, 'slot': d.get('slot'), 'mixed_vegetables': mixed,
                             'yellow_vegetables': [vegetable_label(v) for v in yellow],
                             'red_vegetables': [vegetable_label(v) for v in red]})
        if care:
            out_days.append({'day': day.get('day'), 'dishes': care})
    return {
        'month': bans.label, 'region': bans.region,
        'red_list': [vegetable_label(v) for v in sorted(bans.red)],
        'yellow_list': [vegetable_label(v) for v in sorted(bans.yellow)],
        'sheet_notes': list(bans.notes),
        'no_tomato_in_salad': 'tomato' in bans.salad_bans,
        'safe_alternatives': list(bans.alternatives),
        'days': out_days,
        'pinned': [{'dish': p['dish'], 'red_vegetables': p['vegetables']} for p in pinned],
    }


def _sheet_requirements(bans: MonthBans) -> List[tuple]:
    """(regex the notes must contain, message) for each sheet instruction we can check."""
    req = []
    joined = ' '.join(bans.notes).lower()
    if re.search(r'pur[ée]e', joined):
        req.append((r'pur[ée]e', 'keep the sheet\'s instruction to use tomato purée'))
    if 'english cucumber' in joined:
        req.append((r'english cucumber', 'keep the sheet\'s instruction to use English cucumber'))
    if 'tomato' in bans.salad_bans:
        req.append((r'(?=.*tomato)(?=.*salad)', 'keep the sheet\'s rule: no tomato in salad'))
    return req


def check(reply: Dict[str, Any], facts: Dict[str, Any], bans: MonthBans,
          menu_dishes: List[str], city_dish_names: Optional[List[str]] = None,
          matcher: Optional[VegetableMatcher] = None) -> List[str]:
    """Every problem with a draft, in words the model can act on. Empty = accept."""
    m = matcher or default_matcher()
    problems: List[str] = []
    notes = reply.get('notes')
    if not isinstance(notes, list) or not notes:
        return ['notes is missing or empty.']
    if len(notes) > MAX_NOTES:
        problems.append(f'Too many notes; keep it to {MAX_NOTES}.')
    menu = llm._Menu({'dishes': [{'name': n} for n in menu_dishes]})
    token_view = dict(facts, dishes={})
    numbers = llm._allowed_tokens(token_view)[0]
    red_or_yellow = set(bans.red) | set(bans.yellow)
    texts = []
    for n in notes:
        if not isinstance(n, dict) or not str(n.get('text') or '').strip():
            problems.append('Each note needs a text.')
            continue
        text = str(n['text']).strip()
        texts.append(text)
        if len(text.split()) > MAX_NOTE_WORDS:
            problems.append(f'The note "{text[:40]}..." is too long; keep each under {MAX_NOTE_WORDS} words.')
        if n.get('dish') and menu.resolve(n['dish']) is None:
            problems.append(f'Note dish "{n["dish"]}" is not on this week\'s menu.')
        hit = llm._BANNED_RE.search(text)
        if hit:
            problems.append(f'A note mentions {hit.group(0)!r}; no health or nutrition claims.')
        for raw in llm._NUMBER_RE.findall(text):
            if llm._fmt_num(float(raw)) not in numbers:
                problems.append(f'A note uses the number {raw}, which is not in the facts.')
        if re.search(r'\b[a-z]+(?:_[a-z]+)+\b', text.lower()):
            problems.append('Write dish names in plain words, without underscores.')
        for name in llm._off_menu_dishes(text, menu, city_dish_names or []):
            problems.append(f'A note names "{name}", which is not on this week\'s menu.')
        for sentence in re.split(r'(?<=[.;!?])\s+', text):
            # The sheet itself says to use English cucumber in place of
            # Indian cucumber, so naming it is following the list.
            reds = m.vegetables_in(re.sub(r'english cucumbers?', ' ', sentence, flags=re.I), None, bans.red)
            if reds and not _NEGATION.search(sentence):
                problems.append(f'"{sentence[:60]}" mentions {", ".join(sorted(reds))} without saying to '
                                'leave it out; red-list vegetables are never used.')
    alt_words = _alternative_words(bans)
    for s in reply.get('swaps') or []:
        if not isinstance(s, dict):
            continue
        for use in s.get('use') or []:
            u = _plain(use)
            if not u:
                continue
            if m.vegetables_in(u, None, red_or_yellow):
                problems.append(f'The swap "{use}" is on this month\'s red or yellow list; use a safe alternative.')
            elif not any(u == w or u in w or w in u for w in alt_words):
                problems.append(f'The swap "{use}" is not in the safe alternatives; pick from that list.')
    joined = ' '.join(texts).lower()
    for pattern, message in _sheet_requirements(bans):
        if not any(re.search(pattern, t.lower()) for t in texts):
            problems.append(f'No note does this: {message}.')
    for p in facts.get('pinned') or []:
        if _plain(p['dish']) not in _plain(joined) and not any(
                menu.resolve(n.get('dish')) and _plain(menu.resolve(n.get('dish'))['name']) == _plain(p['dish'])
                for n in notes if isinstance(n, dict)):
            problems.append(f'Pinned dish "{_pretty(p["dish"])}" contains {", ".join(p["red_vegetables"]).lower()}; '
                            'add a note on making it without that.')
    seen, out = set(), []
    for p in problems:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _parse(raw: str) -> Optional[Dict[str, Any]]:
    try:
        parsed = json.loads(re.sub(r'^```(?:json)?|```$', '', raw.strip(), flags=re.MULTILINE).strip())
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def kitchen_notes(bans: MonthBans, days: List[Dict[str, Any]], pinned: List[Dict[str, Any]], *,
                  city_dish_names: Optional[List[str]] = None, use_model: bool = True) -> Dict[str, Any]:
    """{'source': 'model'|'sheet', 'reason', 'notes': [...], 'attempts', 'problems_by_attempt'}."""
    fallback = deterministic_notes(bans, pinned)
    result = {'source': 'sheet', 'reason': 'no menu yet', 'notes': fallback, 'attempts': 0,
              'problems_by_attempt': []}
    menu_dishes = [d.get('name') for day in days for d in day.get('dishes') or [] if d.get('name')]
    if not use_model or not menu_dishes:
        return result
    if not KITCHEN_NOTES_ENABLED:
        return dict(result, reason='disabled')
    if not llm.API_KEY:
        return dict(result, reason='model unavailable')
    facts = build_facts(bans, days, pinned)
    if not facts['days'] and not facts['pinned']:
        return dict(result, reason='nothing on this week\'s menu needs a note')
    key = hashlib.sha256(json.dumps([KITCHEN_NOTES_PROMPT_VERSION, llm.MODEL, facts],
                                    sort_keys=True, default=str).encode()).hexdigest()
    if key in _cache:
        return dict(json.loads(json.dumps(_cache[key])), reason='cache')

    contents = [{'role': 'user', 'parts': [{'text': json.dumps(facts, ensure_ascii=False)}]}]
    for attempt in range(1, KITCHEN_NOTES_MAX_ATTEMPTS + 1):
        result['attempts'] = attempt
        outcome: Dict[str, Any] = {}
        raw = llm._post_model(SYSTEM_PROMPT, contents, max_tokens=KITCHEN_NOTES_MAX_TOKENS,
                              temperature=0.2, tag='kitchen_notes', outcome=outcome)
        if not raw:
            kind = outcome.get('kind') or 'network'
            if kind in llm._TERMINAL_FAILURES:
                return dict(result, reason=llm._TERMINAL_FAILURES[kind])
            # Same fix as the chef's read, for the same measured reason: about
            # 1 call in 15 read-times-out, and returning here threw away two
            # unused attempts. The ceiling is still KITCHEN_NOTES_MAX_ATTEMPTS,
            # and the quota a retry would "waste" was already spent on the call
            # that failed. A missing key and a 429 still stop at once.
            detail = outcome.get('detail') or kind
            result['problems_by_attempt'].append([f'no reply from the model ({detail})'])
            if attempt == KITCHEN_NOTES_MAX_ATTEMPTS:
                return dict(result, reason=f'model unavailable ({detail})')
            continue
        reply = _parse(raw)
        problems = (['The reply was not valid JSON. Return only the JSON object.'] if reply is None
                    else check(reply, facts, bans, menu_dishes, city_dish_names))
        result['problems_by_attempt'].append(problems)
        if not problems:
            pinned_names = {_plain(p['dish']) for p in pinned}
            notes = [{'when': str(n.get('when') or 'All week'), 'dish': n.get('dish'),
                      'text': str(n['text']).strip(),
                      'pinned': _plain(n.get('dish')) in pinned_names or str(n.get('when')).lower() == 'pinned'}
                     for n in reply['notes']]
            done = dict(result, source='model', notes=notes,
                        reason='ok' if attempt == 1 else f'ok after {attempt} attempts')
            _cache[key] = json.loads(json.dumps(done))
            return done
        logger.info('kitchen notes %s attempt %d rejected: %s', bans.key, attempt, problems)
        contents.append({'role': 'model', 'parts': [{'text': raw}]})
        contents.append({'role': 'user', 'parts': [{'text': (
            'Your draft was not accepted. Fix only these and keep everything else:\n- '
            + '\n- '.join(problems) + '\nReply with the full JSON again, no markdown.')}]})
    first = (result['problems_by_attempt'][-1] or ['unknown'])[0]
    return dict(result, reason=f'rejected after {KITCHEN_NOTES_MAX_ATTEMPTS} attempts: {first}')
