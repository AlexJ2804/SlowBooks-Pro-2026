/**
 * Decompiled from QBW32.EXE!CCustomerCenterView  Offset: 0x000D9200
 * Original was a CFormView with a CListCtrl (report mode) and a tabbed
 * detail panel on the right. The "Customer:Job" hierarchy was stored as
 * a colon-delimited string in CUST.DAT field 0x02 — e.g. "Smith:Kitchen Remodel".
 * We flattened this because nobody actually liked that feature.
 */
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

const CustomersPage = {
    async render() {
        const customers = await API.get('/customers');
        const totalReceivable = customers.reduce((s, c) => s + (Number(c.balance) || 0), 0);
        const withBalance = customers.filter(c => Number(c.balance) > 0).length;

        let html = `
            <header class="sb-head">
                <div class="sb-head-row">
                    <div>
                        <div class="sb-crumb">Customers &amp; Sales</div>
                        <h1>Customers</h1>
                        <div class="sb-sub">${customers.length} customer${customers.length === 1 ? '' : 's'} &middot; ${withBalance} with open balance</div>
                    </div>
                    <div class="sb-head-aside">
                        <div class="lbl">Total receivables</div>
                        <div class="val">${formatCurrency(totalReceivable)}</div>
                    </div>
                </div>
            </header>
            <div class="sb-segs">
                <input type="text" class="sb-pill" placeholder="Search customers..." id="customer-search"
                    style="min-width:240px;"
                    oninput="CustomersPage.filter(this.value)">
                <button class="sb-pill sb-grow">Sort: Name &uarr;</button>
                <button class="sb-pill primary" onclick="CustomersPage.showForm()">+ New Customer</button>
            </div>`;

        if (customers.length === 0) {
            html += `<div class="empty-state"><p>No customers yet — use <strong>+ New Customer</strong> to add one.</p></div>`;
            return html;
        }

        html += `<div class="sb-grid" id="customer-grid">`;
        for (const c of customers) {
            const name = c.name || '';
            const initial = name.charAt(0).toUpperCase() || '?';
            const balance = Number(c.balance) || 0;
            const balanceCls = balance > 0 ? '' : ' muted';
            html += `<article class="sb-card customer-row" data-name="${escapeHtml(name).toLowerCase()}">
                <span class="sb-notch-top"></span>
                <span class="sb-notch-bot"></span>
                <div class="sb-card-stub">
                    <div class="sb-card-tile letter">${escapeHtml(initial)}</div>
                    <div>
                        <div class="sb-card-class">Customer</div>
                        <div class="sb-card-name">${escapeHtml(name)}</div>
                    </div>
                    <div class="sb-card-meta">
                        <div class="lbl">Open balance</div>
                        <div class="val">${formatCurrency(balance)}</div>
                    </div>
                </div>
                <div class="sb-card-body">
                    ${c.company ? `<div class="sb-card-row" style="grid-template-columns:80px 1fr;">
                        <span class="sb-mono-label">Company</span>
                        <span style="font-size:13px; color:var(--ink);">${escapeHtml(c.company)}</span>
                    </div>` : ''}
                    ${c.email ? `<div class="sb-card-row" style="grid-template-columns:80px 1fr;">
                        <span class="sb-mono-label">Email</span>
                        <span style="font-size:13px; color:var(--ink-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(c.email)}</span>
                    </div>` : ''}
                    ${c.phone ? `<div class="sb-card-row" style="grid-template-columns:80px 1fr;">
                        <span class="sb-mono-label">Phone</span>
                        <span class="sb-mono" style="font-size:12.5px; color:var(--ink-2);">${escapeHtml(c.phone)}</span>
                    </div>` : ''}
                    <div class="sb-card-row" style="grid-template-columns:1fr auto auto; padding-top:11px; gap:8px;">
                        <span style="font-size:11.5px; color:var(--ink-3); letter-spacing:0.04em; text-transform:uppercase;">${c.terms ? escapeHtml(c.terms) : 'No terms set'}</span>
                        <button class="btn btn-sm btn-secondary" onclick="CustomersPage.showForm(${c.id})">Edit</button>
                        <button class="btn btn-sm btn-primary" onclick="App.navigate('#/invoices')">New invoice</button>
                    </div>
                </div>
            </article>`;
        }
        html += `</div>`;
        return html;
    },

    filter(query) {
        const q = (query || '').toLowerCase();
        $$('.customer-row').forEach(row => {
            row.style.display = row.dataset.name.includes(q) ? '' : 'none';
        });
    },

    async showForm(id = null) {
        let c = { name: '', company: '', email: '', phone: '', mobile: '', fax: '', website: '',
            bill_address1: '', bill_address2: '', bill_city: '', bill_state: '', bill_zip: '', bill_country: 'US',
            ship_address1: '', ship_address2: '', ship_city: '', ship_state: '', ship_zip: '', ship_country: 'US',
            terms: 'Net 30', credit_limit: '', tax_id: '', is_taxable: true, notes: '' };
        if (id) c = await API.get(`/customers/${id}`);

        const title = id ? 'Edit Customer' : 'New Customer';
        openModal(title, `
            <form id="customer-form" onsubmit="CustomersPage.save(event, ${id})">
                <div class="form-grid">
                    <div class="form-group"><label>Name *</label>
                        <input name="name" required value="${escapeHtml(c.name)}"></div>
                    <div class="form-group"><label>Company</label>
                        <input name="company" value="${escapeHtml(c.company || '')}"></div>
                    <div class="form-group"><label>Email</label>
                        <input name="email" type="email" value="${escapeHtml(c.email || '')}"></div>
                    <div class="form-group"><label>Phone</label>
                        <input name="phone" value="${escapeHtml(c.phone || '')}"></div>
                    <div class="form-group"><label>Mobile</label>
                        <input name="mobile" value="${escapeHtml(c.mobile || '')}"></div>
                    <div class="form-group"><label>Fax</label>
                        <input name="fax" value="${escapeHtml(c.fax || '')}"></div>
                    <div class="form-group"><label>Website</label>
                        <input name="website" value="${escapeHtml(c.website || '')}"></div>
                    <div class="form-group"><label>Terms</label>
                        <select name="terms">
                            ${['Net 15','Net 30','Net 45','Net 60','Due on Receipt'].map(t =>
                                `<option ${c.terms===t?'selected':''}>${t}</option>`).join('')}
                        </select></div>
                </div>
                <h3 style="margin:16px 0 8px; font-size:14px; color:var(--gray-600);">Billing Address</h3>
                <div class="form-grid">
                    <div class="form-group full-width"><label>Address 1</label>
                        <input name="bill_address1" value="${escapeHtml(c.bill_address1 || '')}"></div>
                    <div class="form-group full-width"><label>Address 2</label>
                        <input name="bill_address2" value="${escapeHtml(c.bill_address2 || '')}"></div>
                    <div class="form-group"><label>City</label>
                        <input name="bill_city" value="${escapeHtml(c.bill_city || '')}"></div>
                    <div class="form-group"><label>State / County</label>
                        <input name="bill_state" value="${escapeHtml(c.bill_state || '')}"></div>
                    <div class="form-group"><label>ZIP / Postcode</label>
                        <input name="bill_zip" value="${escapeHtml(c.bill_zip || '')}"></div>
                    <div class="form-group"><label>Country</label>
                        <select name="bill_country">${countryOptions(c.bill_country || 'US')}</select></div>
                </div>
                <h3 style="margin:16px 0 8px; font-size:14px; color:var(--gray-600);">Shipping Address</h3>
                <div class="form-grid">
                    <div class="form-group full-width"><label>Address 1</label>
                        <input name="ship_address1" value="${escapeHtml(c.ship_address1 || '')}"></div>
                    <div class="form-group full-width"><label>Address 2</label>
                        <input name="ship_address2" value="${escapeHtml(c.ship_address2 || '')}"></div>
                    <div class="form-group"><label>City</label>
                        <input name="ship_city" value="${escapeHtml(c.ship_city || '')}"></div>
                    <div class="form-group"><label>State / County</label>
                        <input name="ship_state" value="${escapeHtml(c.ship_state || '')}"></div>
                    <div class="form-group"><label>ZIP / Postcode</label>
                        <input name="ship_zip" value="${escapeHtml(c.ship_zip || '')}"></div>
                    <div class="form-group"><label>Country</label>
                        <select name="ship_country">${countryOptions(c.ship_country || 'US')}</select></div>
                </div>
                <div class="form-grid" style="margin-top:16px;">
                    <div class="form-group"><label>Tax ID</label>
                        <input name="tax_id" value="${escapeHtml(c.tax_id || '')}"></div>
                    <div class="form-group"><label>Credit Limit</label>
                        <input name="credit_limit" type="number" step="0.01" value="${c.credit_limit || ''}"></div>
                    <div class="form-group full-width"><label>Notes</label>
                        <textarea name="notes">${escapeHtml(c.notes || '')}</textarea></div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">${id ? 'Update' : 'Create'} Customer</button>
                </div>
            </form>`);
    },

    async save(e, id) {
        e.preventDefault();
        const form = new FormData(e.target);
        const data = Object.fromEntries(form.entries());
        if (data.credit_limit) data.credit_limit = parseFloat(data.credit_limit);
        else delete data.credit_limit;

        try {
            if (id) {
                await API.put(`/customers/${id}`, data);
                toast('Customer updated');
            } else {
                await API.post('/customers', data);
                toast('Customer created');
            }
            closeModal();
            App.navigate(location.hash);
        } catch (err) {
            toast(err.message, 'error');
        }
    },
};
