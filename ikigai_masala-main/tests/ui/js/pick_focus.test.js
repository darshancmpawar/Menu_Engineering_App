// The search box keeps the caret when the table rebuilds underneath it.
//
// The bug this pins, found in real use: typing one character into the in-cell
// search lost focus, so the planner had to click back into the box before the
// next character. `renderResults` was supposed to prevent it by rebuilding
// only the results container — but it is not the only thing that rebuilds.
// Each keystroke changes the result count, which changes the component's
// height, which posts `setFrameHeight`; Streamlit answers a resize with a
// fresh `streamlit:render`, which calls the full `render()` and replaces
// every node including the input.
//
// `restoreFocus` runs after every full render instead of chasing each path
// that can trigger one.
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

let pickCell = null, applying = false, caret = 0;

// Just enough DOM for `restoreFocus`: an input that records focus and range.
let input, active;
const document = {
  get activeElement() { return active; },
  querySelector: (sel) => (sel === '[data-q]' ? input : null),
};
function freshInput() {
  active = null;
  input = {
    focused: 0, range: null,
    focus() { this.focused++; active = this; },
    setSelectionRange(a, b) { this.range = [a, b]; },
  };
  return input;
}

eval(grab('restoreFocus'));

const FAIL = [];
function check(label, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) FAIL.push(`${label}\n   got  ${g}\n   want ${w}`);
  else console.log('ok  ' + label);
}

// 1. The bug. A rebuild happened while editing: the caret must come back to
//    where the planner left it, not to the start and not nowhere.
freshInput();
pickCell = 'dessert|2026-10-21';
caret = 3;                       // they had typed "asa"
restoreFocus();
check('a rebuild while editing puts focus back', input.focused, 1);
check('and the caret returns to where it was', input.range, [3, 3]);

// 2. Already focused — do not steal or reset the caret. Calling focus() on
//    the active element is harmless, but resetting the range mid-selection
//    would fight the planner's own cursor.
freshInput();
active = input;
caret = 1;
restoreFocus();
check('an already-focused input is left alone', input.focused, 0);
check('and its selection is not reset', input.range, null);

// 3. Not editing: nothing to restore, and stealing focus would move the
//    planner's cursor out of whatever they were actually using.
freshInput();
pickCell = null;
restoreFocus();
check('no focus is taken when no cell is being picked', input.focused, 0);

// 4. Mid-apply the input is disabled and about to be replaced by the result.
freshInput();
pickCell = 'dessert|2026-10-21';
applying = true;
restoreFocus();
check('no focus is taken while an apply is in flight', input.focused, 0);

if (FAIL.length) {
  console.error('\n' + FAIL.length + ' FAILED\n' + FAIL.join('\n'));
  process.exit(1);
}
console.log('\nall ok');
