/**
 * Bills & Bill Payments — Accounts Payable workflow
 * Feature 1: Enter bills, pay bills
 */
const BillsPage = {
    async render() {
        const [bills, settings] = await Promise.all([
            API.get('/bills'),
            API.get('/settings'),
        ]);
        const homeCurrency = (settings.home_currency || 'USD').toUpperCase();

        let html = `
            <div class="page-header">
                <h2>Bills (Accounts Payable)</h2>
                <div class="btn-group">
                    <button class="btn btn-primary" onclick="BillsPage.showForm()">+ Enter Bill</button>
                    <button class="btn btn-secondary" onclick="BillsPage.showPayForm()">Pay Bills</button>
                </div>
            </div>
            <div class="toolbar">
                <select id="bill-status-filter" onchange="BillsPage.applyFilter()">
                    <option value="">All Statuses</option>
                    <option value="unpaid">Unpaid</option>
                    <option value="partial">Partial</option>
                    <option value="paid">Paid</option>
                    <option value="void">Void</option>
                </select>
            </div>`;

        if (bills.length === 0) {
            html += '<div class="empty-state"><p>No bills entered yet</p></div>';
        } else {
            html += `<div class="table-container"><table>
                <thead><tr><th>Bill #</th><th>Vendor</th><th>Date</th><th>Due</th><th>Status</th>
                <th class="amount">Total</th>
                <th class="amount">Total (${escapeHtml(homeCurrency)})</th>
                <th class="amount">Balance</th><th>Actions</th></tr></thead><tbody id="bill-tbody">`;
            for (const b of bills) {
                const ccy = (b.currency || 'USD').toUpperCase();
                html += `<tr class="bill-row" data-status="${b.status}">
                    <td><strong>${escapeHtml(b.bill_number)}</strong></td>
                    <td>${escapeHtml(b.vendor_name || '')}</td>
                    <td>${formatDate(b.date)}</td>
                    <td>${formatDate(b.due_date)}</td>
                    <td>${statusBadge(b.status)}</td>
                    <td class="amount">${formatCurrency(b.total, ccy)}</td>
                    <td class="amount">${formatCurrency(b.home_currency_amount, homeCurrency)}</td>
                    <td class="amount">${formatCurrency(b.balance_due, ccy)}</td>
                    <td class="actions">
                        <button class="btn btn-sm btn-secondary" onclick="BillsPage.view(${b.id})">View</button>
                        ${b.status !== 'void' && b.status !== 'paid' ? `<button class="btn btn-sm btn-danger" onclick="BillsPage.void(${b.id})">Void</button>` : ''}
                    </td>
                </tr>`;
            }
            html += '</tbody></table></div>';
        }
        return html;
    },

    applyFilter() {
        const status = $('#bill-status-filter')?.value;
        $$('.bill-row').forEach(row => {
            row.style.display = (!status || row.dataset.status === status) ? '' : 'none';
        });
    },

    async view(id) {
        const [bill, settings] = await Promise.all([
            API.get(`/bills/${id}`),
            API.get('/settings'),
        ]);
        const ccy = (bill.currency || 'USD').toUpperCase();
        const homeCcy = (settings.home_currency || 'USD').toUpperCase();
        const showHome = ccy !== homeCcy;
        const totalLine = showHome
            ? `${formatCurrency(bill.total, ccy)} <span style="color:var(--gray-500); font-weight:normal;">(≈ ${formatCurrency(bill.home_currency_amount, homeCcy)})</span>`
            : formatCurrency(bill.total, ccy);

        let linesHtml = bill.lines.map(l =>
            `<tr><td>${escapeHtml(l.description || '')}</td><td class="amount">${l.quantity}</td>
             <td class="amount">${formatCurrency(l.rate, ccy)}</td><td class="amount">${formatCurrency(l.amount, ccy)}</td></tr>`
        ).join('');

        openModal(`Bill ${bill.bill_number}`, `
            <div style="margin-bottom:12px;">
                <strong>Vendor:</strong> ${escapeHtml(bill.vendor_name || '')}<br>
                <strong>Date:</strong> ${formatDate(bill.date)}<br>
                <strong>Due:</strong> ${formatDate(bill.due_date)}<br>
                <strong>Status:</strong> ${statusBadge(bill.status)}<br>
                <strong>Currency:</strong> ${escapeHtml(ccy)}${showHome ? ` <span style="color:var(--gray-500);">(rate ${parseFloat(bill.exchange_rate).toFixed(4)} → ${escapeHtml(homeCcy)})</span>` : ''}
            </div>
            <div class="table-container"><table>
                <thead><tr><th>Description</th><th class="amount">Qty</th><th class="amount">Rate</th><th class="amount">Amount</th></tr></thead>
                <tbody>${linesHtml}</tbody>
            </table></div>
            <div class="invoice-totals">
                <div class="total-row grand-total"><span class="label">Total</span><span class="value">${totalLine}</span></div>
                <div class="total-row"><span class="label">Paid</span><span class="value">${formatCurrency(bill.amount_paid, ccy)}</span></div>
                <div class="total-row grand-total"><span class="label">Balance</span><span class="value">${formatCurrency(bill.balance_due, ccy)}</span></div>
            </div>
            <div style="margin-top:16px; border-top:1px solid var(--gray-200); padding-top:12px;">
                <h3 style="font-size:13px; margin-bottom:8px;">Attachments</h3>
                <div id="bill-attachments-list" style="margin-bottom:8px; font-size:11px;">Loading...</div>
                <input type="file" id="bill-attach-file" style="font-size:11px;">
                <button class="btn btn-sm btn-secondary" onclick="BillsPage.uploadAttachment(${bill.id})" style="margin-left:4px;">Upload</button>
            </div>
            <div class="form-actions">
                ${bill.status === 'paid' ? `<button class="btn btn-secondary" onclick="window.open('/api/bills/${bill.id}/pdf','_blank')">Save PDF</button>` : ''}
                <button class="btn btn-secondary" onclick="closeModal()">Close</button>
            </div>`);
        BillsPage.loadAttachments(bill.id);
    },

    _items: [],
    _vendors: [],
    lineCount: 0,

    vendorSelected(vendorId) {
        if (!vendorId) return;
        const vendor = BillsPage._vendors.find(v => v.id == vendorId);
        if (vendor && vendor.default_expense_account_id) {
            // Store for use when adding lines
            BillsPage._defaultExpenseAccountId = vendor.default_expense_account_id;
        } else {
            BillsPage._defaultExpenseAccountId = null;
        }
    },

    async showForm() {
        const [vendors, items, accounts, settings, classes] = await Promise.all([
            API.get('/vendors?active_only=true'),
            API.get('/items?active_only=true'),
            API.get('/accounts?account_type=expense'),
            API.get('/settings'),
            API.get('/classes'),
        ]);
        BillsPage._items = items;
        BillsPage._classes = classes;
        BillsPage.lineCount = 1;

        const homeCurrency = (settings.home_currency || 'USD').toUpperCase();
        BillsPage._homeCurrency = homeCurrency;
        BillsPage._formCurrency = homeCurrency;

        BillsPage._vendors = vendors;
        const vendorOpts = vendors.map(v => `<option value="${v.id}">${escapeHtml(v.name)}</option>`).join('');
        const itemOpts = items.map(i => `<option value="${i.id}">${escapeHtml(i.name)}</option>`).join('');

        openModal('Enter Bill', `
            <form onsubmit="BillsPage.save(event)">
                <div class="form-grid">
                    <div class="form-group"><label>Class *</label>
                        <select name="class_id" id="bill-class-select" required>${classOptions(classes)}</select>
                        <a href="#" style="font-size:11px;" onclick="event.preventDefault(); BillsPage.newClass('bill-class-select')">+ New class</a></div>
                    <div class="form-group"><label>Vendor *</label>
                        <select name="vendor_id" required onchange="BillsPage.vendorSelected(this.value)"><option value="">Select...</option>${vendorOpts}</select></div>
                    <div class="form-group"><label>Bill Number *</label>
                        <input name="bill_number" required></div>
                    <div class="form-group"><label>Date *</label>
                        <input name="date" type="date" required value="${todayISO()}"></div>
                    <div class="form-group"><label>Terms</label>
                        <select name="terms">
                            ${['Net 15','Net 30','Net 45','Net 60','Due on Receipt'].map(t =>
                                `<option ${t==='Net 30'?'selected':''}>${t}</option>`).join('')}
                        </select></div>
                    <div class="form-group"><label>Currency</label>
                        <select name="currency" id="bill-currency" onchange="BillsPage.currencyChanged()">
                            ${currencyOptions(homeCurrency)}
                        </select></div>
                    <div class="form-group"><label>Exchange Rate <span style="color:var(--gray-500); font-weight:normal;">(→ ${escapeHtml(homeCurrency)})</span></label>
                        <input name="exchange_rate" id="bill-exchange-rate" type="number" step="0.00000001" value="1" disabled></div>
                </div>
                <h3 style="margin:12px 0 8px;font-size:14px;">Line Items</h3>
                <table class="line-items-table">
                    <thead><tr><th>Item</th><th>Description</th><th class="col-qty">Qty</th><th class="col-rate">Rate</th><th class="col-amount">Amount</th></tr></thead>
                    <tbody id="bill-lines">
                        <tr data-billline="0">
                            <td><select class="line-item"><option value="">--</option>${itemOpts}</select></td>
                            <td><input class="line-desc"></td>
                            <td><input class="line-qty" type="number" step="0.01" value="1"></td>
                            <td><input class="line-rate" type="number" step="0.01" value="0"></td>
                            <td class="col-amount">$0.00</td>
                        </tr>
                    </tbody>
                </table>
                <button type="button" class="btn btn-sm btn-secondary" style="margin-top:8px;" onclick="BillsPage.addLine()">+ Add Line</button>
                <div class="form-group" style="margin-top:12px;"><label>Notes</label>
                    <textarea name="notes"></textarea></div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save Bill</button>
                </div>
            </form>`);
    },

    addLine() {
        const idx = BillsPage.lineCount++;
        const itemOpts = BillsPage._items.map(i => `<option value="${i.id}">${escapeHtml(i.name)}</option>`).join('');
        $('#bill-lines').insertAdjacentHTML('beforeend', `
            <tr data-billline="${idx}">
                <td><select class="line-item"><option value="">--</option>${itemOpts}</select></td>
                <td><input class="line-desc"></td>
                <td><input class="line-qty" type="number" step="0.01" value="1"></td>
                <td><input class="line-rate" type="number" step="0.01" value="0"></td>
                <td class="col-amount">$0.00</td>
            </tr>`);
    },

    async currencyChanged() {
        const ccy = $('#bill-currency').value;
        const rateField = $('#bill-exchange-rate');
        BillsPage._formCurrency = ccy;
        if (ccy === BillsPage._homeCurrency) {
            rateField.value = '1';
            rateField.disabled = true;
            return;
        }
        rateField.disabled = false;
        try {
            const res = await API.get(`/fx/rate?from=${encodeURIComponent(ccy)}&to=${encodeURIComponent(BillsPage._homeCurrency)}`);
            if (res.rate) {
                rateField.value = parseFloat(res.rate);
                if (res.source === 'bankofcanada-cross') {
                    toast(`FX rate ${ccy}→${BillsPage._homeCurrency}: ${parseFloat(res.rate).toFixed(4)} (cross-rate via CAD)`);
                }
            } else {
                rateField.value = '1';
                toast(`FX rate ${ccy}→${BillsPage._homeCurrency} unavailable; using 1.0`, 'error');
            }
        } catch (err) {
            rateField.value = '1';
            toast('FX lookup failed; using 1.0', 'error');
        }
    },

    newClass(targetSelectId) {
        InlineCreate.open('class', async (created) => {
            const fresh = await API.get('/classes');
            BillsPage._classes = fresh;
            const sel = $(`#${targetSelectId}`);
            if (sel) sel.innerHTML = classOptions(fresh, created.id);
        });
    },

    async save(e) {
        e.preventDefault();
        const form = e.target;
        if (!form.class_id.value) { toast('Pick a class before saving.', 'error'); return; }
        const lines = [];
        $$('#bill-lines tr').forEach((row, i) => {
            lines.push({
                item_id: row.querySelector('.line-item')?.value ? parseInt(row.querySelector('.line-item').value) : null,
                description: row.querySelector('.line-desc')?.value || '',
                quantity: parseFloat(row.querySelector('.line-qty')?.value) || 1,
                rate: parseFloat(row.querySelector('.line-rate')?.value) || 0,
                line_order: i,
            });
        });
        try {
            await API.post('/bills', {
                vendor_id: parseInt(form.vendor_id.value),
                bill_number: form.bill_number.value,
                date: form.date.value,
                terms: form.terms.value,
                notes: form.notes.value || null,
                currency: (form.currency.value || 'USD').toUpperCase(),
                exchange_rate: parseFloat(form.exchange_rate.value) || 1,
                class_id: parseInt(form.class_id.value),
                lines,
            });
            toast('Bill saved');
            closeModal();
            App.navigate('#/bills');
        } catch (err) { toast(err.message, 'error'); }
    },

    async void(id) {
        if (!confirm('Void this bill?')) return;
        try {
            await API.post(`/bills/${id}/void`);
            toast('Bill voided');
            App.navigate('#/bills');
        } catch (err) { toast(err.message, 'error'); }
    },

    async showPayForm() {
        const [vendors, bills, accounts, settings, classes] = await Promise.all([
            API.get('/vendors?active_only=true'),
            API.get('/bills?status=unpaid'),
            API.get('/accounts?account_type=asset'),
            API.get('/settings'),
            API.get('/classes'),
        ]);
        const partials = await API.get('/bills?status=partial');
        const openBills = [...bills, ...partials];

        const homeCurrency = (settings.home_currency || 'USD').toUpperCase();
        BillsPage._homeCurrency = homeCurrency;
        BillsPage._payCurrency = homeCurrency;
        BillsPage._classes = classes;

        const vendorOpts = vendors.map(v => `<option value="${v.id}">${escapeHtml(v.name)}</option>`).join('');
        const acctOpts = accounts.map(a => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join('');

        let billRows = openBills.map(b => {
            const ccy = (b.currency || 'USD').toUpperCase();
            return `
            <tr data-currency="${ccy}">
                <td><input type="checkbox" class="pay-check" data-bill="${b.id}" data-balance="${b.balance_due}"></td>
                <td>${escapeHtml(b.bill_number)}</td>
                <td>${escapeHtml(b.vendor_name || '')}</td>
                <td>${formatDate(b.due_date)}</td>
                <td><span style="font-size:10px; padding:1px 6px; background:var(--gray-100); border-radius:4px;">${escapeHtml(ccy)}</span></td>
                <td class="amount">${formatCurrency(b.balance_due, ccy)}</td>
                <td><input type="number" step="0.01" class="pay-amount" data-bill="${b.id}" value="0" style="width:80px;"></td>
            </tr>`;
        }).join('');

        if (!billRows) billRows = '<tr><td colspan="7" style="color:var(--text-muted);">No open bills</td></tr>';

        openModal('Pay Bills', `
            <form onsubmit="BillsPage.savePay(event)">
                <div style="font-size:11px; color:var(--text-muted); margin-bottom:8px; padding:6px 8px; background:var(--gray-50); border-left:2px solid var(--qb-blue);">
                    <strong>Note:</strong> Cross-currency reconciliation is not supported. If any
                    selected bill is in a different currency than the payment, the server will
                    reject the request with HTTP 400 and no payment will be saved.
                </div>
                <div class="form-grid">
                    <div class="form-group"><label>Class *</label>
                        <select name="class_id" id="billpay-class-select" required>${classOptions(classes)}</select>
                        <a href="#" style="font-size:11px;" onclick="event.preventDefault(); BillsPage.newClass('billpay-class-select')">+ New class</a></div>
                    <div class="form-group"><label>Pay From Account</label>
                        <select name="pay_from_account_id"><option value="">Select...</option>${acctOpts}</select></div>
                    <div class="form-group"><label>Date *</label>
                        <input name="date" type="date" required value="${todayISO()}"></div>
                    <div class="form-group"><label>Method</label>
                        <select name="method">
                            <option value="check">Check</option><option value="ach">ACH</option>
                            <option value="cash">Cash</option><option value="credit_card">Credit Card</option>
                        </select></div>
                    <div class="form-group"><label>Check #</label>
                        <input name="check_number"></div>
                    <div class="form-group"><label>Currency</label>
                        <select name="currency" id="billpay-currency" onchange="BillsPage.payCurrencyChanged()">
                            ${currencyOptions(homeCurrency)}
                        </select></div>
                    <div class="form-group"><label>Exchange Rate <span style="color:var(--gray-500); font-weight:normal;">(→ ${escapeHtml(homeCurrency)})</span></label>
                        <input name="exchange_rate" id="billpay-exchange-rate" type="number" step="0.00000001" value="1" disabled></div>
                </div>
                <div class="table-container" style="margin-top:12px;"><table>
                    <thead><tr><th style="width:30px;"></th><th>Bill #</th><th>Vendor</th><th>Due</th>
                    <th>Ccy</th>
                    <th class="amount">Balance</th><th class="amount">Payment</th></tr></thead>
                    <tbody>${billRows}</tbody>
                </table></div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Pay Selected Bills</button>
                </div>
            </form>`);

        // Auto-fill payment amount on check
        $$('.pay-check').forEach(cb => {
            cb.addEventListener('change', () => {
                const billId = cb.dataset.bill;
                const amtInput = $(`.pay-amount[data-bill="${billId}"]`);
                amtInput.value = cb.checked ? cb.dataset.balance : '0';
            });
        });
    },

    async payCurrencyChanged() {
        const ccy = $('#billpay-currency').value;
        const rateField = $('#billpay-exchange-rate');
        BillsPage._payCurrency = ccy;
        if (ccy === BillsPage._homeCurrency) {
            rateField.value = '1';
            rateField.disabled = true;
            return;
        }
        rateField.disabled = false;
        try {
            const res = await API.get(`/fx/rate?from=${encodeURIComponent(ccy)}&to=${encodeURIComponent(BillsPage._homeCurrency)}`);
            if (res.rate) {
                rateField.value = parseFloat(res.rate);
                if (res.source === 'bankofcanada-cross') {
                    toast(`FX rate ${ccy}→${BillsPage._homeCurrency}: ${parseFloat(res.rate).toFixed(4)} (cross-rate via CAD)`);
                }
            } else {
                rateField.value = '1';
                toast(`FX rate ${ccy}→${BillsPage._homeCurrency} unavailable; using 1.0`, 'error');
            }
        } catch (err) {
            rateField.value = '1';
            toast('FX lookup failed; using 1.0', 'error');
        }
    },

    async savePay(e) {
        e.preventDefault();
        const form = e.target;
        if (!form.class_id.value) { toast('Pick a class before saving.', 'error'); return; }
        const payCcy = (form.currency.value || 'USD').toUpperCase();
        const allocations = [];
        let total = 0;
        let mismatch = null;
        $$('.pay-amount').forEach(input => {
            const amt = parseFloat(input.value) || 0;
            if (amt > 0) {
                const row = input.closest('tr');
                const rowCcy = (row?.dataset.currency || 'USD').toUpperCase();
                if (rowCcy !== payCcy && !mismatch) mismatch = rowCcy;
                allocations.push({ bill_id: parseInt(input.dataset.bill), amount: amt });
                total += amt;
            }
        });
        if (allocations.length === 0) { toast('Select bills to pay', 'error'); return; }
        if (mismatch) {
            toast(`Selected bill is in ${mismatch}, but payment is in ${payCcy}. All selected bills must match the payment currency.`, 'error');
            return;
        }

        // Get vendor from first bill
        const firstBill = await API.get(`/bills/${allocations[0].bill_id}`);

        try {
            await API.post('/bill-payments', {
                vendor_id: firstBill.vendor_id,
                date: form.date.value,
                amount: total,
                method: form.method.value,
                check_number: form.check_number.value || null,
                pay_from_account_id: form.pay_from_account_id.value ? parseInt(form.pay_from_account_id.value) : null,
                currency: payCcy,
                exchange_rate: parseFloat(form.exchange_rate.value) || 1,
                class_id: parseInt(form.class_id.value),
                allocations,
            });
            toast('Bills paid');
            closeModal();
            App.navigate('#/bills');
        } catch (err) { toast(err.message, 'error'); }
    },

    async loadAttachments(billId) {
        const el = $('#bill-attachments-list');
        if (!el) return;
        try {
            const attachments = await API.get(`/attachments/bill/${billId}`);
            if (attachments.length === 0) {
                el.innerHTML = '<span style="color:var(--text-muted);">No attachments</span>';
            } else {
                el.innerHTML = attachments.map(a =>
                    `<div style="display:flex; align-items:center; gap:8px; padding:2px 0;">
                        <a href="/api/attachments/download/${a.id}" target="_blank">${escapeHtml(a.filename)}</a>
                        <span style="color:var(--gray-400);">(${(a.file_size/1024).toFixed(1)} KB)</span>
                        <button class="btn btn-sm btn-danger" onclick="BillsPage.deleteAttachment(${a.id},${billId})" style="padding:0 4px; font-size:10px;">X</button>
                    </div>`
                ).join('');
            }
        } catch (e) { el.innerHTML = ''; }
    },

    async uploadAttachment(billId) {
        const fileInput = $('#bill-attach-file');
        if (!fileInput?.files[0]) { toast('Select a file first', 'error'); return; }
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        try {
            const resp = await fetch(`/api/attachments/bill/${billId}`, { method: 'POST', body: formData });
            if (!resp.ok) { const d = await resp.json(); throw new Error(d.detail || 'Upload failed'); }
            toast('Attachment uploaded');
            fileInput.value = '';
            BillsPage.loadAttachments(billId);
        } catch (err) { toast(err.message, 'error'); }
    },

    async deleteAttachment(attachId, billId) {
        if (!confirm('Delete this attachment?')) return;
        try {
            await API.del(`/attachments/${attachId}`);
            toast('Attachment deleted');
            BillsPage.loadAttachments(billId);
        } catch (err) { toast(err.message, 'error'); }
    },
};
