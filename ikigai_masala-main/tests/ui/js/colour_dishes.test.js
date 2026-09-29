// `colourDishes` prints each of the day's dishes in its own ink inside the
// explain paragraph. Regex, HTML escaping and match ordering all at once,
// and every way it goes wrong is silent: a name painted into the middle of
// a longer word, a name with an `&` that never matches, or — the one that
// matters — escaped text un-escaped by the replacement.
//
// Pulled straight out of the component so this tests the SHIPPED source
// rather than a copy that can drift from it.
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
let ARGS;
eval(grab('esc') + '\n' + grab('colourDishes'));

const FAIL = [];
function check(label, got, want) {
  if (got !== want) FAIL.push(`${label}\n   got  ${got}\n   want ${want}`);
  else console.log('ok  ' + label);
}

ARGS = {rows: [
  {cells: {'d': {name: 'Chana Masala', color_fg: '#C56A00'}}},
  {cells: {'d': {name: 'Phulka',       color_fg: '#9A7A10'}}},
  {cells: {'d': {name: 'Aloo Gobi',    color_fg: '#1AA45B'}}},
  {cells: {'d': {name: 'Aloo',         color_fg: '#555555'}}},
  {cells: {'d': {name: 'Boondi Raita', color_fg: '#0A58CA'}}},
]};
const S = (n, c) => `<span style="color:${c};font-weight:600">${n}</span>`;

check('names are printed in their own ink',
  colourDishes('Chana Masala and Phulka carry the plate.', 'd'),
  `${S('Chana Masala','#C56A00')} and ${S('Phulka','#9A7A10')} carry the plate.`);

check('the longer name wins over the shorter one it contains',
  colourDishes('Aloo Gobi adds a dry side.', 'd'),
  `${S('Aloo Gobi','#1AA45B')} adds a dry side.`);

check('a dish not on that day is left alone',
  colourDishes('Rajma Masala is elsewhere.', 'd'),
  'Rajma Masala is elsewhere.');

check('the overview is escaped, and stays escaped',
  colourDishes('<script>alert(1)</script> Phulka', 'd'),
  `&lt;script&gt;alert(1)&lt;/script&gt; ${S('Phulka','#9A7A10')}`);

ARGS = {rows: [{cells: {'d': {name: 'Salt & Pepper Paneer', color_fg: '#C40D1B'}}}]};
check('a name with an ampersand still matches after escaping',
  colourDishes('Salt & Pepper Paneer leads.', 'd'),
  `${S('Salt &amp; Pepper Paneer','#C40D1B')} leads.`);

ARGS = {rows: [{cells: {'d': {name: 'Dal', color_fg: '#9A7A10'}}}]};
check('a name inside a bigger word is not highlighted',
  colourDishes('Dalgona is not Dal.', 'd'),
  `Dalgona is not ${S('Dal','#9A7A10')}.`);

ARGS = {rows: []};
check('no cells, no change', colourDishes('Nothing to colour.', 'd'), 'Nothing to colour.');

if (FAIL.length) { console.log('\nFAILED:\n' + FAIL.join('\n')); process.exit(1); }
console.log('\nall colourDishes checks passed');
