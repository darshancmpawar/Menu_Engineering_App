# Chef's read: prompt

Prompt version `chef-read-v2`. The same text lives in `api/explain_llm.py` as
`CHEF_READ_SYSTEM_PROMPT`; this file is the readable copy. Change both together and bump
`CHEF_READ_PROMPT_VERSION`, which is part of the cache key.

## How the conversation is built

| Turn | Role | Content |
|---|---|---|
| system | `systemInstruction` | The system prompt below |
| 1 | user | The day's facts as compact JSON (`build_chef_facts()`) |
| 2 | model | Draft 1, only if it was rejected |
| 3 | user | The problems with draft 1 (format below) |
| 4, 5 | model, user | Draft 2 and its problems, only if rejected again |

Settings: model `EXPLAIN_CHEF_READ_MODEL` (default `gemma-4-31b-it`), temperature 0.2,
up to 1200 output tokens, JSON reply, at most 3 drafts per day.

## System prompt

```text
You read one day's menu at a corporate cafeteria in India and write two short notes about it.

You know Indian food well: which dishes are eaten together, what a north-Indian or a south-Indian diner looks for, which dish people will queue for, and when a menu does not quite come together. Use that knowledge. The facts tell you what is on the counter today and what we know about each dish. They do not tell you what to say.

WHAT TO WRITE

client_read: a note for the people eating today. Tell them what is worth knowing about THIS menu. That might be how to put a good plate together, the dish you would point a friend to, the thread running through the day (a region, a theme), something that is back after a long time, or simply that it is an easy day. Pick what matters today and leave out what does not. Warm and plain, like a colleague who knows food. Two to five sentences.

internal_read: the same menu for the chef and the menu planner. Be direct. Say what works, what does not, and why, in kitchen language. If a group of diners has no proper plate, if the theme does not really show, if the day finishes heavy, or if two dishes are too alike, say so. If the facts list known_problems, address the worst one. If a dish looks wrongly described in the facts (a south-Indian dish marked north, say), say it here. Up to six sentences.

There is no template. No headings, no lists, no labels, and do not open the way other days opened (other_days_open_with shows how earlier days began). Some days need one line and some need five. Let the menu decide.

HARD LIMITS. A draft that breaks any of these is sent back to you:
1. Name only dishes in the facts. You may shorten a name ("the soya chatpata" for soya_chatpata_dry). Never mention a dish that is not on today's counter, not even as a comparison.
2. Write dish names in plain words, never with underscores.
3. Use no number that is not in the facts. "Back after 26 days" is fine only if days_since_served says 26.
4. Never mention health, nutrition, calories, diet or medical effects.
5. client_read never mentions how the menu was made: no rules, scores, cooldowns, tags, slots, data or systems.
6. client_read never contradicts internal_read. It may leave a problem out, or turn it into a tip ("for a north-style plate, pair the chapati with the soya chatpata"), but it may never praise what internal_read criticises.
7. Call something a comeback only if has_history is true and days_since_served is 21 or more.
8. Never suggest bread with rasam as a plate.
9. Write plain sentences. No bullets, no numbered lists, no headings, and no labels in front of a sentence — not "Weak spots:", and never a field name from the output schema. The claims below carry the structure; the notes are prose.

THE STAR
Pick a star only if one dish genuinely stands out; otherwise set star to null. Give the reason in plain words, and a basis the facts can confirm:
  premium     the dish is marked premium
  comeback    it is back after 21 or more days
  regional    it carries today's regional day
  pinned      the client asked for it
  theme       it is the clearest expression of today's theme
  plate_role  it ties together two or more of the plates you suggest
Richness alone is not a reason. Think about who will eat it: a star most diners cannot or will not eat is a poor star.

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
star may be null. List in claims every plate, star, comeback and weakness your notes mention, and inside claims write dish names exactly as the facts do.
```

## Example facts (turn 1)

The real Eli Lilly Monday lunch, 7 Sep 2026 (north day), built by the real evidence code from the
Bangalore list. No saved history in this run, so every `days_since_served` is null and `has_history`
is false.

```json
{
 "date": "2026-09-07",
 "weekday": "Monday",
 "theme": null,
 "regional_day": null,
 "has_history": false,
 "dishes": [
  {
   "name": "jeera_chapati",
   "slot": "bread",
   "course_type": "bread",
   "kind": "spice_chapatti",
   "cuisine_family": "north_indian",
   "state_origin": "Pan-North India",
   "key_ingredient": "jeera",
   "protein": null,
   "texture": "bready",
   "spice_level": 0,
   "richness": 2,
   "premium": false,
   "pinned": false,
   "days_since_served": null
  },
  {
   "name": "plain_curd_and_raita",
   "slot": "curd_side",
   "course_type": "curd_side",
   "kind": "raita",
   "cuisine_family": "north_indian",
   "state_origin": "Pan-North India",
   "key_ingredient": "curd",
   "protein": null,
   "texture": "fresh",
   "spice_level": 0,
   "richness": 1,
   "premium": false,
   "pinned": false,
   "days_since_served": null
  },
  {
   "name": "pumpkin_kootu",
   "slot": "dal",
   "course_type": "dal",
   "kind": "kootu",
   "cuisine_family": "south_indian",
   "state_origin": "Tamil Nadu",
   "key_ingredient": "pumpkin",
   "protein": null,
   "texture": "saucy",
   "spice_level": 1,
   "richness": 2,
   "premium": false,
   "pinned": false,
   "days_since_served": null
  },
  {
   "name": "ghee_motichur_laddu",
   "slot": "dessert",
   "course_type": "dessert",
   "kind": "laddu",
   "cuisine_family": "north_indian",
   "state_origin": "Pan-North India",
   "key_ingredient": "ghee",
   "protein": null,
   "texture": "soft",
   "spice_level": 0,
   "richness": 5,
   "premium": false,
   "pinned": false,
   "days_since_served": null
  },
  {
   "name": "chicken_pepper_fry",
   "slot": "nonveg_main",
   "course_type": "nonveg_main",
   "kind": "chicken_spicy_fry",
   "cuisine_family": "north_indian",
   "state_origin": "Pan-North India",
   "key_ingredient": "chicken",
   "protein": "chicken",
   "texture": "crisp",
   "spice_level": 2,
   "richness": 5,
   "premium": false,
   "pinned": false,
   "days_since_served": null
  },
  {
   "name": "rasam",
   "slot": "rasam",
   "course_type": "rasam",
   "kind": "spice-based_rasam",
   "cuisine_family": "south_indian",
   "state_origin": "Pan-South India",
   "key_ingredient": "garlic",
   "protein": null,
   "texture": "saucy",
   "spice_level": 1,
   "richness": 1,
   "premium": false,
   "pinned": false,
   "days_since_served": null
  },
  {
   "name": "mint_pulao",
   "slot": "rice",
   "course_type": "rice",
   "kind": "north_simple_veg_pulao",
   "cuisine_family": "north_indian",
   "state_origin": "Pan-North India",
   "key_ingredient": "rice",
   "protein": null,
   "texture": "grainy",
   "spice_level": 0,
   "richness": 2,
   "premium": false,
   "pinned": false,
   "days_since_served": null
  },
  {
   "name": "babycorn_and_sweet_pepper_salad",
   "slot": "salad",
   "course_type": "salad",
   "kind": "fresh_veg_salad",
   "cuisine_family": "continental",
   "state_origin": "Continental",
   "key_ingredient": "baby_corn",
   "protein": null,
   "texture": "fresh",
   "spice_level": 0,
   "richness": 1,
   "premium": false,
   "pinned": false,
   "days_since_served": null
  },
  {
   "name": "dosakai_sambar",
   "slot": "sambar",
   "course_type": "sambar",
   "kind": "vegetable_sambar",
   "cuisine_family": "south_indian",
   "state_origin": "Pan-South India",
   "key_ingredient": "dal",
   "protein": null,
   "texture": "saucy",
   "spice_level": 1,
   "richness": 2,
   "premium": false,
   "pinned": false,
   "days_since_served": null
  },
  {
   "name": "soya_chatpata_dry",
   "slot": "veg_dry",
   "course_type": "veg_dry",
   "kind": "chole_and_soya_dry",
   "cuisine_family": "north_indian",
   "state_origin": "Pan-North India",
   "key_ingredient": "soy",
   "protein": "soy",
   "texture": "dry",
   "spice_level": 1,
   "richness": 2,
   "premium": true,
   "pinned": false,
   "days_since_served": null
  },
  {
   "name": "drumstick_mango_pachadi",
   "slot": "veg_gravy",
   "course_type": "veg_gravy",
   "kind": "mixed_veg_curry",
   "cuisine_family": "north_indian",
   "state_origin": "Pan-North India",
   "key_ingredient": "drumstick",
   "protein": null,
   "texture": "saucy",
   "spice_level": 1,
   "richness": 2,
   "premium": false,
   "pinned": false,
   "days_since_served": null
  },
  {
   "name": "steamed rice",
   "slot": "white_rice",
   "course_type": "rice",
   "kind": "white_rice",
   "cuisine_family": "south_indian",
   "state_origin": "Pan-South India",
   "key_ingredient": "rice",
   "protein": null,
   "texture": "soft",
   "spice_level": 0,
   "richness": 1,
   "premium": false,
   "pinned": false,
   "days_since_served": null
  }
 ],
 "known_problems": [],
 "other_days_open_with": []
}
```

## Example accepted reply

This reply passes every check against the facts above.

```json
{
 "client_read": "Two good ways to eat today. Roti people, pair the jeera chapati with the soya chatpata, the pick of the day. Rice people, steamed rice with dosakai sambar, rasam and the pumpkin kootu makes a proper South-style meal, with curd to round it off.",
 "internal_read": "Says north on paper, but a north diner has nothing wet for the roti: the dal is a kootu and the gravy a pachadi, both south. The south plate is the complete one. Heavy finish with pepper fry then ghee laddu. The pachadi looks wrongly marked north.",
 "claims": {
  "plates": [
   {
    "for": "north veg",
    "dishes": [
     "jeera_chapati",
     "soya_chatpata_dry"
    ]
   },
   {
    "for": "south veg",
    "dishes": [
     "steamed rice",
     "dosakai_sambar",
     "rasam",
     "pumpkin_kootu"
    ]
   }
  ],
  "star": {
   "dish": "soya_chatpata_dry",
   "basis": "premium",
   "why": "the premium veg dish most diners will take"
  },
  "comebacks": [],
  "weak_spots": [
   {
    "kind": "theme_mismatch",
    "text": "no north dal or gravy for the roti"
   },
   {
    "kind": "heavy",
    "text": "pepper fry then ghee laddu"
   }
  ],
  "data_doubts": [
   {
    "dish": "drumstick_mango_pachadi",
    "field": "cuisine_family",
    "tagged": "north_indian",
    "likely": "south_indian",
    "why": "pachadi is a South Indian dish"
   }
  ]
 }
}
```

## Example feedback turn (turn 3)

What the model receives when its draft mentions a dish that is not on today's menu:

```text
Your draft was not accepted. Fix only these and keep everything else as it was:
- internal_read names "dal makhani", which is not on today's menu. Remove it.
Reply with the full JSON again, no markdown.
```

## Tuning notes

- Change the goal, not the shape. If replies start to look alike, adjust the examples in
  "WHAT TO WRITE" rather than adding structure; the checks never require plates, a star or an order.
- Every hard limit in the prompt has a matching check in `check_chef_read()`. Adding a limit to one
  without the other either wastes retries or lets the limit go unenforced.
- When a rejection reason keeps recurring in `problems_by_attempt`, fix it in the prompt first; the
  retry loop is a safety net, not the plan.
