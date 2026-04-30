// DOM test for the class-required inline error.
//
// Catches the bug we shipped in the phase-3 hotfix: <select required>
// blocks the JS submit handler so requireClassPicked() never runs. To pin
// the fix, we run requireClassPicked() against a real (jsdom) DOM and
// assert the styled error span actually lands adjacent to the field.
//
// Run with:  node --test tests/dom/test_inline_error.js
// (cd to tests/dom first, or set NODE_PATH so the local jsdom install is found)

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const UTILS_JS = fs.readFileSync(
    path.join(REPO_ROOT, 'app', 'static', 'js', 'utils.js'),
    'utf-8'
);

function makeDOM() {
    // Minimal page with the toast container utils.js expects, plus a
    // representative invoice-like form with a class select wrapped in a
    // .form-group (matching how the real templates lay it out).
    const dom = new JSDOM(`
        <!DOCTYPE html>
        <html><body>
            <div id="toast-container"></div>
            <form id="invoice-form">
                <div class="form-group">
                    <label>Class *</label>
                    <select name="class_id" id="inv-class-select" aria-required="true">
                        <option value="">— Pick a class —</option>
                        <option value="1">Alex 1099 (US)</option>
                        <option value="2">Ireland Projects</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Customer *</label>
                    <input name="customer_id" value="42">
                </div>
            </form>
        </body></html>
    `, { runScripts: 'dangerously' });

    // Load utils.js into the jsdom window.
    const scriptEl = dom.window.document.createElement('script');
    scriptEl.textContent = UTILS_JS;
    dom.window.document.body.appendChild(scriptEl);
    return dom;
}


test('requireClassPicked returns false when class not picked, and inserts inline error', () => {
    const dom = makeDOM();
    const form = dom.window.document.getElementById('invoice-form');
    const select = dom.window.document.getElementById('inv-class-select');

    // Pre-state: select empty, no error span.
    assert.strictEqual(select.value, '');
    assert.strictEqual(form.querySelectorAll('.field-error').length, 0);

    const result = dom.window.requireClassPicked(form);

    assert.strictEqual(result, false, 'should return false when no class picked');

    // After the call, an inline error must be present in the DOM,
    // adjacent to the select (in the same .form-group).
    const formGroup = select.closest('.form-group');
    const err = formGroup.querySelector('.field-error');
    assert.ok(err, 'inline error span must exist in the same .form-group as the class select');
    assert.match(err.textContent, /Class is required/i);

    // Accessibility: aria-invalid should be set so screen readers
    // announce the field as in error state.
    assert.strictEqual(select.getAttribute('aria-invalid'), 'true');
});


test('inline error clears when user picks a class', () => {
    const dom = makeDOM();
    const form = dom.window.document.getElementById('invoice-form');
    const select = dom.window.document.getElementById('inv-class-select');

    // Trigger the error.
    dom.window.requireClassPicked(form);
    assert.ok(form.querySelector('.field-error'), 'error must be present after failed validation');

    // User picks a class — markFieldError listens for change events and
    // clears the error itself.
    select.value = '2';
    select.dispatchEvent(new dom.window.Event('change'));

    assert.strictEqual(form.querySelectorAll('.field-error').length, 0,
        'inline error must clear after user picks a class');
    assert.strictEqual(select.getAttribute('aria-invalid'), null,
        'aria-invalid must be cleared once the field is fixed');
});


test('requireClassPicked returns true when class IS picked, no error rendered', () => {
    const dom = makeDOM();
    const form = dom.window.document.getElementById('invoice-form');
    const select = dom.window.document.getElementById('inv-class-select');

    select.value = '1';
    const result = dom.window.requireClassPicked(form);

    assert.strictEqual(result, true);
    assert.strictEqual(form.querySelectorAll('.field-error').length, 0);
});


test('repeated failed validations do not stack multiple error spans', () => {
    const dom = makeDOM();
    const form = dom.window.document.getElementById('invoice-form');

    dom.window.requireClassPicked(form);
    dom.window.requireClassPicked(form);
    dom.window.requireClassPicked(form);

    const errs = form.querySelectorAll('.field-error');
    assert.strictEqual(errs.length, 1,
        `expected exactly one .field-error, got ${errs.length} — markFieldError must be idempotent`);
});


test('markFieldError(null) explicitly removes the error span', () => {
    const dom = makeDOM();
    const form = dom.window.document.getElementById('invoice-form');
    const select = dom.window.document.getElementById('inv-class-select');

    dom.window.markFieldError(select, 'Class is required — please select one');
    assert.ok(form.querySelector('.field-error'));

    dom.window.markFieldError(select, null);
    assert.strictEqual(form.querySelectorAll('.field-error').length, 0);
    assert.strictEqual(select.getAttribute('aria-invalid'), null);
});


// Regression guard for the original bug. If anyone re-adds `required` to
// the class select, the JS validation path stops running and the inline
// error never appears. Catch that at the source level.
test('regression guard: no class_id <select> in any form-bearing JS file declares HTML5 `required`', () => {
    const formFiles = [
        'invoices.js', 'bills.js', 'payments.js', 'cc_charges.js',
        'estimates.js', 'credit_memos.js', 'journal.js',
        'batch_payments.js', 'recurring.js',
    ];
    const offenders = [];
    for (const f of formFiles) {
        const src = fs.readFileSync(path.join(REPO_ROOT, 'app', 'static', 'js', f), 'utf-8');
        // Look for any class_id select that still carries the bare `required`
        // attribute. We accept aria-required (announced by screen readers,
        // doesn't trigger native validation).
        const matches = src.match(/<select[^>]*name="class_id"[^>]*\brequired\b[^>]*>/g) || [];
        for (const m of matches) {
            // Filter out matches that are only "aria-required".
            if (!/aria-required/.test(m) || /\srequired\b/.test(m.replace(/aria-required="[^"]*"/g, ''))) {
                offenders.push(`${f}: ${m}`);
            }
        }
    }
    assert.deepStrictEqual(offenders, [],
        `class_id selects must not declare HTML5 \`required\` — it cancels the JS submit handler ` +
        `and prevents the inline error from ever rendering. Offenders:\n  ${offenders.join('\n  ')}`);
});
