/**
 * Decompiled from QBW32.EXE!CQBFormatUtils  Offset: 0x0008C200
 * Original formatting used Win32 GetCurrencyFormat() / GetDateFormat()
 * with the system locale. The BCD-to-string conversion in the original
 * had a special case for negative values that printed parentheses instead
 * of a minus sign — classic accountant move.
 */

function $(sel, parent = document) { return parent.querySelector(sel); }
function $$(sel, parent = document) { return [...parent.querySelectorAll(sel)]; }

function formatCurrency(amount, currencyCode) {
    const code = (currencyCode || 'USD').toUpperCase();
    // en-US locale keeps the existing $ presentation for USD; for CAD/EUR
    // Intl produces "CA$" and "€" respectively, which is what we want.
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: code }).format(amount || 0);
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = dateStr.includes('T')
        ? new Date(dateStr)
        : new Date(dateStr + 'T00:00:00');
    if (Number.isNaN(d.getTime())) return 'Invalid date';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function todayISO() {
    const d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
}

function toast(message, type = 'success') {
    const container = $('#toast-container');
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3000);
}

function openModal(title, html) {
    $('#modal-title').textContent = title;
    $('#modal-body').innerHTML = html;
    $('#modal-overlay').classList.remove('hidden');
}

function closeModal() {
    $('#modal-overlay').classList.add('hidden');
}

function statusBadge(status) {
    return `<span class="badge badge-${status}">${status}</span>`;
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// Show or clear an inline error message immediately after a form field.
// Used by the class-required pre-flight on every transaction form so the
// failure is visible even after the toast auto-dismisses (3s).
//
// Usage:
//   markFieldError(form.class_id, 'Class is required — please select one');
//   markFieldError(form.class_id, null);   // clear
//
// The error span is appended to the field's parent (.form-group) and is
// idempotent — repeated calls update the message rather than stacking spans.
function markFieldError(field, message) {
    if (!field) return;
    const parent = field.closest('.form-group') || field.parentElement;
    if (!parent) return;
    let err = parent.querySelector('.field-error');
    if (message) {
        if (!err) {
            err = document.createElement('div');
            err.className = 'field-error';
            err.style.cssText = 'color:var(--danger); font-size:11px; margin-top:4px; font-weight:600;';
            parent.appendChild(err);
        }
        err.textContent = message;
        field.setAttribute('aria-invalid', 'true');
        // Clear once the user starts fixing it.
        const onChange = () => { markFieldError(field, null); field.removeEventListener('change', onChange); field.removeEventListener('input', onChange); };
        field.addEventListener('change', onChange);
        field.addEventListener('input', onChange);
    } else {
        if (err) err.remove();
        field.removeAttribute('aria-invalid');
    }
}

// Convenience wrapper for the universal "class is required" pre-flight.
// Returns true if the form's class_id field is filled in (and clears any
// stale error); returns false and shows the inline error otherwise.
//
// We resolve the field via querySelector rather than form.class_id, because
// the HTMLFormElement named-control accessor isn't implemented in some test
// runtimes (notably jsdom) — and it's also fragile if the field name ever
// collides with a Form prototype property. querySelector is unambiguous.
function requireClassPicked(form) {
    if (!form) return true;
    const field = form.querySelector('[name="class_id"]');
    if (!field) return true;  // form has no class field — caller's responsibility
    if (!field.value) {
        markFieldError(field, 'Class is required — please select one');
        toast('Pick a class before saving.', 'error');
        return false;
    }
    markFieldError(field, null);
    return true;
}

function disableSubmitButtons() {
    document.querySelectorAll('#modal .btn-primary').forEach(b => { b.disabled = true; b.dataset.origText = b.textContent; b.textContent = 'Saving...'; });
}
function enableSubmitButtons() {
    document.querySelectorAll('#modal .btn-primary').forEach(b => { b.disabled = false; if(b.dataset.origText) b.textContent = b.dataset.origText; });
}

function closeSearchDropdown() {
    const dd = $('#search-results');
    if (dd) dd.classList.add('hidden');
    const input = $('#global-search');
    if (input) input.value = '';
}

const COUNTRIES = [
    { code: 'US', name: 'United States' },
    { code: 'CA', name: 'Canada' },
    { code: 'IE', name: 'Ireland' },
    { code: 'GB', name: 'United Kingdom' },
    { code: 'AU', name: 'Australia' },
    { code: '-', name: '──────────', disabled: true },
    { code: 'AR', name: 'Argentina' },
    { code: 'AT', name: 'Austria' },
    { code: 'BE', name: 'Belgium' },
    { code: 'BR', name: 'Brazil' },
    { code: 'BG', name: 'Bulgaria' },
    { code: 'CL', name: 'Chile' },
    { code: 'CN', name: 'China' },
    { code: 'CO', name: 'Colombia' },
    { code: 'HR', name: 'Croatia' },
    { code: 'CZ', name: 'Czech Republic' },
    { code: 'DK', name: 'Denmark' },
    { code: 'EG', name: 'Egypt' },
    { code: 'EE', name: 'Estonia' },
    { code: 'FI', name: 'Finland' },
    { code: 'FR', name: 'France' },
    { code: 'DE', name: 'Germany' },
    { code: 'GR', name: 'Greece' },
    { code: 'HK', name: 'Hong Kong' },
    { code: 'HU', name: 'Hungary' },
    { code: 'IS', name: 'Iceland' },
    { code: 'IN', name: 'India' },
    { code: 'ID', name: 'Indonesia' },
    { code: 'IL', name: 'Israel' },
    { code: 'IT', name: 'Italy' },
    { code: 'JP', name: 'Japan' },
    { code: 'KE', name: 'Kenya' },
    { code: 'LV', name: 'Latvia' },
    { code: 'LT', name: 'Lithuania' },
    { code: 'LU', name: 'Luxembourg' },
    { code: 'MY', name: 'Malaysia' },
    { code: 'MX', name: 'Mexico' },
    { code: 'MA', name: 'Morocco' },
    { code: 'NL', name: 'Netherlands' },
    { code: 'NZ', name: 'New Zealand' },
    { code: 'NG', name: 'Nigeria' },
    { code: 'NO', name: 'Norway' },
    { code: 'PK', name: 'Pakistan' },
    { code: 'PE', name: 'Peru' },
    { code: 'PH', name: 'Philippines' },
    { code: 'PL', name: 'Poland' },
    { code: 'PT', name: 'Portugal' },
    { code: 'RO', name: 'Romania' },
    { code: 'SA', name: 'Saudi Arabia' },
    { code: 'SG', name: 'Singapore' },
    { code: 'SK', name: 'Slovakia' },
    { code: 'SI', name: 'Slovenia' },
    { code: 'ZA', name: 'South Africa' },
    { code: 'KR', name: 'South Korea' },
    { code: 'ES', name: 'Spain' },
    { code: 'SE', name: 'Sweden' },
    { code: 'CH', name: 'Switzerland' },
    { code: 'TW', name: 'Taiwan' },
    { code: 'TH', name: 'Thailand' },
    { code: 'TR', name: 'Turkey' },
    { code: 'UA', name: 'Ukraine' },
    { code: 'AE', name: 'United Arab Emirates' },
    { code: 'UY', name: 'Uruguay' },
    { code: 'VN', name: 'Vietnam' },
];

function countryOptions(selected) {
    return COUNTRIES.map(c =>
        `<option value="${c.code}"${c.disabled ? ' disabled' : ''}${c.code === selected ? ' selected' : ''}>${c.name}</option>`
    ).join('');
}

const CURRENCIES = [
    { code: 'USD', name: 'US Dollar' },
    { code: 'CAD', name: 'Canadian Dollar' },
    { code: 'EUR', name: 'Euro' },
];

function currencyOptions(selected) {
    return CURRENCIES.map(c =>
        `<option value="${c.code}"${c.code === selected ? ' selected' : ''}>${c.code} — ${c.name}</option>`
    ).join('');
}

// Class dropdown helper used by every transaction form. `classes` is the
// list returned by GET /api/classes (already filtered to non-archived).
// `selectedId` may be undefined for new-form blank state. The dropdown's
// first option is intentionally empty so the user has to pick a class —
// the backend rejects requests without a class_id with HTTP 400.
function classOptions(classes, selectedId) {
    const blank = `<option value="">— Pick a class —</option>`;
    const rows = (classes || []).map(c =>
        `<option value="${c.id}"${c.id == selectedId ? ' selected' : ''}>${escapeHtml(c.name)}${c.is_archived ? ' (archived)' : ''}</option>`
    ).join('');
    return blank + rows;
}

// ============================================================================
// InlineCreate — one shared modal for "+ New X" links on transaction forms.
//
// Used by the four entity types that show up as dropdowns on transaction
// forms: classes, vendors, customers, items. Calling code passes a callback
// that receives the new row's id, so it can refresh and auto-select its
// dropdown without losing the parent form's typed state.
//
// Design choices:
// - Lives in a separate DOM container (#inline-modal-overlay) layered above
//   the main #modal-overlay, so the parent form stays mounted and untouched.
// - One config table (CONFIGS); the modal is rendered from that, no
//   per-entity copies of the modal HTML.
// - The item config's `account` field is a fixed select populated from
//   /accounts; it explicitly does NOT spawn a nested + New account modal
//   (per the no-recursion edge case in the spec).
// ============================================================================
const InlineCreate = {
    CONFIGS: {
        class: {
            endpoint: '/classes',
            title: 'New Class',
            fields: [
                { name: 'name', label: 'Name', required: true },
            ],
            buildBody: (form) => ({ name: form.name.value.trim() }),
        },
        vendor: {
            endpoint: '/vendors',
            title: 'New Vendor',
            fields: [
                { name: 'name', label: 'Name', required: true },
                { name: 'email', label: 'Email', type: 'email' },
                { name: 'phone', label: 'Phone' },
            ],
            buildBody: (form) => ({
                name: form.name.value.trim(),
                email: form.email.value.trim() || null,
                phone: form.phone.value.trim() || null,
            }),
        },
        customer: {
            endpoint: '/customers',
            title: 'New Customer',
            fields: [
                { name: 'name', label: 'Name', required: true },
                { name: 'email', label: 'Email', type: 'email' },
                { name: 'phone', label: 'Phone' },
            ],
            buildBody: (form) => ({
                name: form.name.value.trim(),
                email: form.email.value.trim() || null,
                phone: form.phone.value.trim() || null,
            }),
        },
        item: {
            endpoint: '/items',
            title: 'New Item',
            // Item account dropdown is rendered async (see open()).
            // No "+ New account" link inside — recursion guard.
            fields: [
                { name: 'name', label: 'Name', required: true },
                { name: 'rate', label: 'Default Rate', type: 'number', step: '0.01', required: true },
                { name: 'income_account_id', label: 'Account', type: 'account-select', required: true },
            ],
            buildBody: (form) => ({
                name: form.name.value.trim(),
                rate: parseFloat(form.rate.value) || 0,
                income_account_id: parseInt(form.income_account_id.value),
                item_type: 'service',
            }),
        },
    },

    // Phase-4 addition: optional `prefill` parameter. When provided, each
    // matching form field is populated with the given value before the
    // user sees the modal. Use case: receipt parser extracts a vendor
    // name like "Pret A Manger", we open the inline-create vendor modal
    // with that name already typed in so the user just clicks Save.
    // Calling without prefill is the existing behaviour — purely additive.
    async open(entityType, onCreated, prefill = null) {
        const cfg = InlineCreate.CONFIGS[entityType];
        if (!cfg) { toast(`Unknown inline-create type: ${entityType}`, 'error'); return; }

        // For items, fetch the income/expense accounts before rendering.
        let accountOpts = '';
        if (entityType === 'item') {
            const accts = await API.get('/accounts?account_types=income,expense');
            accountOpts = accts.map(a =>
                `<option value="${a.id}">${escapeHtml(a.account_number)} - ${escapeHtml(a.name)}</option>`
            ).join('');
        }

        const prefillVal = (name) => (prefill && prefill[name] != null) ? String(prefill[name]) : '';

        const fieldHtml = cfg.fields.map(f => {
            if (f.type === 'account-select') {
                return `<div class="form-group full-width"><label>${escapeHtml(f.label)}${f.required ? ' *' : ''}</label>
                    <select name="${f.name}"${f.required ? ' required' : ''}><option value="">Select...</option>${accountOpts}</select>
                </div>`;
            }
            const t = f.type || 'text';
            const step = f.step ? ` step="${f.step}"` : '';
            const value = escapeHtml(prefillVal(f.name));
            return `<div class="form-group full-width"><label>${escapeHtml(f.label)}${f.required ? ' *' : ''}</label>
                <input name="${f.name}" type="${t}"${step}${f.required ? ' required' : ''} value="${value}">
            </div>`;
        }).join('');

        const formId = `inline-form-${Date.now()}`;
        $('#inline-modal-title').textContent = cfg.title;
        $('#inline-modal-body').innerHTML = `
            <form id="${formId}" onsubmit="InlineCreate._submit(event, '${entityType}')">
                <div class="form-grid">${fieldHtml}</div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="InlineCreate.close()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save</button>
                </div>
            </form>`;
        $('#inline-modal-overlay').classList.remove('hidden');
        InlineCreate._activeCallback = onCreated;
        InlineCreate._activeFormId = formId;
        // Focus the first un-prefilled field if there is one (so a prefill
        // doesn't bury the user's first edit point), otherwise the first.
        const firstEmpty = cfg.fields.find(f => !prefillVal(f.name));
        const focusName = (firstEmpty || cfg.fields[0]).name;
        const firstInput = $(`#${formId} [name="${focusName}"]`);
        if (firstInput) firstInput.focus();
    },

    async _submit(e, entityType) {
        e.preventDefault();
        const cfg = InlineCreate.CONFIGS[entityType];
        const form = e.target;
        const body = cfg.buildBody(form);
        try {
            const created = await API.post(cfg.endpoint, body);
            toast(`Created ${cfg.title.replace('New ', '').toLowerCase()} "${created.name || created.id}"`);
            // INVARIANT: capture the callback BEFORE close() — close() nulls
            // _activeCallback as part of cleanup, so reading it afterwards
            // would always return null and the parent dropdown would never
            // refresh. This bit us once (phase 3 hotfix); don't reorder.
            const cb = InlineCreate._activeCallback;
            InlineCreate.close();
            if (typeof cb === 'function') cb(created);
        } catch (err) {
            toast(err.message || 'Save failed', 'error');
        }
    },

    close() {
        $('#inline-modal-overlay').classList.add('hidden');
        $('#inline-modal-body').innerHTML = '';
        InlineCreate._activeCallback = null;
        InlineCreate._activeFormId = null;
    },
};
