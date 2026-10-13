// The in-cell search: what matches, in what order, and what cannot be chosen.
//
// Pulled out of the SHIPPED component rather than reimplemented, for the
// reason the sibling file gives: a copy drifts, and the drifted copy is the
// one that passes. These four are the behaviours a planner notices
// immediately when they are wrong:
//
//   * typing "paneer lab" finds "Paneer Lababdar" (every token a substring),
//   * a dish that FITS sorts above one carrying a warning,
//   * a dish already on the week is listed but cannot be chosen (decision
//     D5, the one rule a pick may not override), and
//   * the dish already in the cell is never offered back.
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..', '..');
const src = fs.readFileSync(
  path.join(ROOT, 'ui', 'menu_table', 'index.html'), 'utf8');

function grab(name) {
  const i = src.indexOf('function ' + name);
  if (i < 0) throw new Error('not found: ' + name);
  let depth = 0, j = src.indexOf('{', i);
  for (let k = j; k < src.length; k++) {
    if (src[k] === '{') depth++;
    else if (src[k] === '}' && --depth === 0) return src.slice(i, k + 1);
  }
}

// The component's own state names, as the functions below read them.
let ARGS = null, pickCell = null, query = '', serverLocked = {};

eval(grab('key'));
eval(grab('pretty'));
eval(grab('baseSlot'));
eval(grab('isoWeek'));
eval(grab('cellOf'));
eval(grab('norm'));
eval(grab('weekUsedNames'));
eval(grab('matches'));
eval(grab('results'));
eval(grab('selectable'));

const FAIL = [];
function check(label, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) FAIL.push(`${label}\n   got  ${g}\n   want ${w}`);
  else console.log('ok  ' + label);
}

// Mon-Wed of one ISO week. `kadai_paneer` sits in Tuesday's gravy cell, so it
// is used elsewhere in the week; `dal_makhani` is in the cell being edited.
ARGS = {
  city: 'Bangalore',
  cooldown_days: 21,
  days: [
    {iso: '2026-11-02', label: 'Mon 02'},
    {iso: '2026-11-03', label: 'Tue 03'},
    {iso: '2026-11-04', label: 'Wed 04'},
  ],
  rows: [{
    id: 'veg_gravy', label: 'Veg Gravy',
    cells: {
      '2026-11-02': {name: 'Dal Makhani', title: 'dal_makhani(W)'},
      '2026-11-03': {name: 'Kadai Paneer', title: 'kadai_paneer(R)'},
      '2026-11-04': {name: 'Aloo Gobi', title: 'aloo_gobi(Y)'},
    },
  }],
  dishes: {
    veg_gravy: {
      n: ['paneer_lababdar', 'kadai_paneer', 'palak_paneer',
          'dal_makhani', 'paneer_butter_masala'],
      out: [2],                 // palak_paneer is not in this client's pool
      ago: {'4': 6},            // paneer_butter_masala served 6 days ago
    },
  },
};
pickCell = 'veg_gravy|2026-11-02';

// 1. Token matching across an underscore-separated name.
query = 'paneer lab';
check('every token must be a substring of the display name',
  results().map(r => r.name), ['paneer_lababdar']);

// 2. The dish already in the cell is never offered back. Without this,
//    picking it again would look like a repeat of itself.
query = 'dal';
check('the dish already in the cell is not a result',
  results().map(r => r.name), []);

// 3. Ranking: a clean dish before a warned one, and the warnings are the ones
//    the embedded columnar data encodes (`out` and `ago`).
query = 'paneer';
const ranked = results();
// `kadai_paneer` matches "paneer" too and is locked, so it comes LAST
// whatever its warning count — the locked rows are appended after the
// selectable ones, which is the ordering decision D5's panel rests on.
check('a dish that fits ranks above one with a warning, and locked rows last',
  ranked.map(r => [r.name, r.warnings.length, !!r.locked]),
  [['paneer_lababdar', 0, false], ['paneer_butter_masala', 1, false],
   ['palak_paneer', 1, false], ['kadai_paneer', 0, true]]);
check('the cooldown warning is read from `ago` against the client window',
  ranked.filter(r => r.name === 'paneer_butter_masala')[0].warnings,
  ['Served 6 days ago']);
check('the out-of-pool warning is read from `out`',
  ranked.filter(r => r.name === 'palak_paneer')[0].warnings,
  ["Not in this client's pool"]);

// 4. Decision D5: a dish already on the week is shown, last, and locked.
query = 'kadai';
const locked = results();
check('a dish already on the week is listed', locked.map(r => r.name),
  ['kadai_paneer']);
check('and it names the day it is already on', locked[0].locked, 'Tue 03');
check('and it is NOT selectable, so Enter and the arrows skip it',
  selectable().length, 0);

// 5. A dish the SERVER refused (saved history, which the embedded list cannot
//    see) stays locked for the rest of the edit.
query = 'lababdar';
check('before the server refuses it, the dish is selectable',
  selectable().map(r => r.name), ['paneer_lababdar']);
serverLocked['paneer_lababdar'] = 'Sun 01';
check("a server week_repeat locks it too", selectable().length, 0);
serverLocked = {};

// 6. ISO weeks, because "a week" is decision D6 and Thursday decides the year.
check('an ISO week number', isoWeek('2026-11-04'), '2026-W45');
check('a Sunday belongs to the week that started on Monday',
  isoWeek('2026-11-08'), '2026-W45');
check('and the next Monday starts a new one', isoWeek('2026-11-09'), '2026-W46');

if (FAIL.length) {
  console.error('\n' + FAIL.length + ' FAILED\n' + FAIL.join('\n'));
  process.exit(1);
}
console.log('\nall ok');
