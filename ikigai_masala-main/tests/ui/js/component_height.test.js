// `setHeight` reports the region strip's height to Streamlit, which sizes the
// component's iframe from it. The failure it guards is a ONE-WAY RATCHET:
// `document.documentElement.scrollHeight` can never report less than the
// iframe's own viewport, so once an open region menu had grown the frame the
// measurement stayed pinned at the taller value. Closing the menu left a blank
// gap the height of the menu, for the rest of the session — on a wide screen,
// a hole between the strip and the rest of the page.
//
// Pulled straight out of the component so this tests the SHIPPED source
// rather than a copy that can drift from it.
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..', '..');
const src = fs.readFileSync(
  path.join(ROOT, 'ui', 'region_strip', 'index.html'), 'utf8');

function grab(name) {
  const i = src.indexOf('function ' + name);
  if (i < 0) throw new Error('not found: ' + name);
  let depth = 0, j = src.indexOf('{', i);
  for (let k = j; k < src.length; k++) {
    if (src[k] === '{') depth++;
    else if (src[k] === '}' && --depth === 0) return src.slice(i, k + 1);
  }
}

// The shadow allowance is a constant in the component; read it the same way so
// the two cannot drift.
const SHADOW_PX = Number((src.match(/var SHADOW_PX\s*=\s*(\d+)/) || [])[1]);
if (!Number.isFinite(SHADOW_PX)) throw new Error('SHADOW_PX not found');

const CONTENT = 108;   // the closed strip: one row of chips plus the info bar
const MENU_BOTTOM = 332;  // an open region menu, ~292px of options under the chip

// The browser, as far as setHeight is concerned. `scrollHeight` models the real
// thing: it is the content height OR the iframe viewport, whichever is LARGER.
let frame = 96;        // what Streamlit has currently sized the iframe to
let menuOpen = false;
let reported = null;

const document = {
  documentElement: { get scrollHeight() { return Math.max(CONTENT, frame); } },
  getElementById: (id) => (id === 'root'
    ? { getBoundingClientRect: () => ({height: CONTENT, bottom: CONTENT}) }
    : null),
  querySelector: (sel) => (sel === '.menu' && menuOpen
    ? { getBoundingClientRect: () => ({bottom: MENU_BOTTOM}) }
    : null),
};
const window = {scrollY: 0};
function post(type, extra) {
  if (type === 'streamlit:setFrameHeight') { reported = extra.height; frame = extra.height; }
}

eval(grab('setHeight'));

const FAIL = [];
function check(label, got, want) {
  if (got !== want) FAIL.push(`${label}\n   got  ${got}\n   want ${want}`);
  else console.log('ok  ' + label);
}

// 1. Closed, from Streamlit's initial 96px.
setHeight();
check('a closed strip reports its own content height',
  reported, CONTENT + SHADOW_PX);

// 2. Open a region menu — the frame must grow or the menu is clipped silently.
menuOpen = true;
setHeight();
check('an open menu grows the frame to clear its bottom edge',
  reported, MENU_BOTTOM + 12);

// 3. Close it again. This is the regression: the iframe is still 344px tall,
//    so `documentElement.scrollHeight` still answers 344.
menuOpen = false;
setHeight();
check('closing the menu brings the frame back down (no leftover gap)',
  reported, CONTENT + SHADOW_PX);

// 4. And it stays down over repeated open/close cycles.
for (let i = 0; i < 3; i++) { menuOpen = true; setHeight(); menuOpen = false; setHeight(); }
check('the height does not ratchet up over repeated opens',
  reported, CONTENT + SHADOW_PX);

if (FAIL.length) { console.log('\nFAILED:\n' + FAIL.join('\n')); process.exit(1); }
console.log('\nall region-strip height checks passed');

// --- the menu table, same defect ------------------------------------------
// It has no open menu to clear, so its whole job is to shrink when the table
// does: a client with fewer slots makes a shorter table, and the old
// measurement could not report less than the iframe it was already in.
const tsrc = fs.readFileSync(
  path.join(ROOT, 'ui', 'menu_table', 'index.html'), 'utf8');
(function () {
  let tframe = 600, treported = null, content = 600;
  const document = {
    documentElement: { get scrollHeight() { return Math.max(content, tframe); } },
    getElementById: (id) => (id === 'root'
      ? { getBoundingClientRect: () => ({height: content}) } : null),
  };
  function post(type, extra) {
    if (type === 'streamlit:setFrameHeight') { treported = extra.height; tframe = extra.height; }
  }
  let i = tsrc.indexOf('function setHeight');
  let depth = 0, j = tsrc.indexOf('{', i), body = null;
  for (let k = j; k < tsrc.length; k++) {
    if (tsrc[k] === '{') depth++;
    else if (tsrc[k] === '}' && --depth === 0) { body = tsrc.slice(i, k + 1); break; }
  }
  eval(body);
  setHeight();
  check('a 14-slot table reports its own height', treported, 600);
  content = 320;                      // switch to a client with fewer slots
  setHeight();
  check('a shorter table shrinks the frame with it', treported, 320);
})();

if (FAIL.length) { console.log('\nFAILED:\n' + FAIL.join('\n')); process.exit(1); }
console.log('all menu-table height checks passed');
