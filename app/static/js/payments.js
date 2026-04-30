/**
 * Decompiled from QBW32.EXE!CReceivePaymentsView  Offset: 0x001A4200
 * The payment allocation grid in the original was a custom MFC control
 * called CQBPaymentGrid that would auto-fill oldest invoices first when
 * you typed a payment amount (FIFO allocation via CQBAllocList::AutoApply
 * at 0x001A2800). We kept the manual allocation approach because the auto
 * version had a known bug with credit memos that Intuit never fixed.
 */
const PaymentsPage = {
    async render() {
        const [payments, settings] = await Promise.all([
            API.get('/payments'),
            API.get('/settings'),
        ]);
        const homeCurrency = (settings.home_currency || 'USD').toUpperCase();
        let html = `
            <div class="page-header">
                <h2>Payments</h2>
                <button class="btn btn-primary" onclick="PaymentsPage.showForm()">+ Record Payment</button>
            </div>`;

        if (payments.length === 0) {
            html += `<div class="empty-state"><p>No payments recorded yet</p></div>`;
        } else {
            html += `<div class="table-container"><table>
                <thead><tr>
                    <th>Date</th><th>Customer</th><th>Method</th><th>Reference</th>
                    <th class="amount">Amount</th>
                    <th class="amount">Amount (${escapeHtml(homeCurrency)})</th>
                    <th>Actions</th>
                </tr></thead><tbody>`;
            for (const p of payments) {
                const ccy = (p.currency || 'USD').toUpperCase();
                html += `<tr>
                    <td>${formatDate(p.date)}</td>
                    <td>${escapeHtml(p.customer_name || '')}</td>
                    <td>${escapeHtml(p.method || '')}${p.is_voided ? ' <span style="color:var(--danger);font-weight:700;">[VOID]</span>' : ''}</td>
                    <td>${escapeHtml(p.reference || p.check_number || '')}</td>
                    <td class="amount">${formatCurrency(p.amount, ccy)}</td>
                    <td class="amount">${formatCurrency(p.home_currency_amount, homeCurrency)}</td>
                    <td class="actions">
                        <button class="btn btn-sm btn-secondary" onclick="PaymentsPage.view(${p.id})">View</button>
                    </td>
                </tr>`;
            }
            html += `</tbody></table></div>`;
        }
        return html;
    },

    async view(id) {
        const [p, settings] = await Promise.all([
            API.get(`/payments/${id}`),
            API.get('/settings'),
        ]);
        const ccy = (p.currency || 'USD').toUpperCase();
        const homeCcy = (settings.home_currency || 'USD').toUpperCase();
        const showHome = ccy !== homeCcy;
        const amountLine = showHome
            ? `${formatCurrency(p.amount, ccy)} <span style="color:var(--gray-500); font-weight:normal;">(≈ ${formatCurrency(p.home_currency_amount, homeCcy)})</span>`
            : formatCurrency(p.amount, ccy);

        let allocHtml = '';
        if (p.allocations.length) {
            allocHtml = `<h4 style="margin:12px 0 8px;">Applied to Invoices</h4>
                <div class="table-container"><table><thead><tr>
                <th>Invoice</th><th class="amount">Amount</th></tr></thead><tbody>`;
            for (const a of p.allocations) {
                allocHtml += `<tr><td>#${a.invoice_id}</td><td class="amount">${formatCurrency(a.amount, ccy)}</td></tr>`;
            }
            allocHtml += `</tbody></table></div>`;
        }

        openModal('Payment Details', `
            <div style="margin-bottom:12px;">
                <strong>Customer:</strong> ${escapeHtml(p.customer_name || '')}<br>
                <strong>Date:</strong> ${formatDate(p.date)}<br>
                <strong>Amount:</strong> ${amountLine}<br>
                <strong>Currency:</strong> ${escapeHtml(ccy)}${showHome ? ` <span style="color:var(--gray-500);">(rate ${parseFloat(p.exchange_rate).toFixed(4)} → ${escapeHtml(homeCcy)})</span>` : ''}<br>
                <strong>Method:</strong> ${escapeHtml(p.method || 'N/A')}<br>
                ${p.check_number ? `<strong>Check #:</strong> ${escapeHtml(p.check_number)}<br>` : ''}
                ${p.reference ? `<strong>Reference:</strong> ${escapeHtml(p.reference)}<br>` : ''}
                ${p.notes ? `<strong>Notes:</strong> ${escapeHtml(p.notes)}<br>` : ''}
            </div>
            ${allocHtml}
            ${p.is_voided ? '<div style="color:var(--danger);font-weight:700;margin:12px 0;">This payment has been voided.</div>' : ''}
            <div class="form-actions">
                ${!p.is_voided ? `<button class="btn btn-danger" onclick="PaymentsPage.void(${p.id})">Void Payment</button>` : ''}
                ${p.method === 'Check' && p.check_number && !p.is_voided ? `<button class="btn btn-secondary" onclick="window.open('/api/checks/print?payment_id=${p.id}','_blank')">Print Check</button>` : ''}
                <button class="btn btn-secondary" onclick="closeModal()">Close</button>
            </div>`);
    },

    async void(id) {
        if (!confirm('Void this payment? Invoice balances will be restored.')) return;
        try {
            await API.post(`/payments/${id}/void`);
            toast('Payment voided');
            closeModal();
            App.navigate(location.hash);
        } catch (err) { toast(err.message, 'error'); }
    },

    _invoices: [],

    async showForm() {
        const [customers, accounts, settings] = await Promise.all([
            API.get('/customers?active_only=true'),
            API.get('/accounts'),
            API.get('/settings'),
        ]);
        const bankAccts = accounts.filter(a => a.account_type === 'asset');
        const homeCurrency = (settings.home_currency || 'USD').toUpperCase();
        PaymentsPage._homeCurrency = homeCurrency;
        PaymentsPage._formCurrency = homeCurrency;

        const custOpts = customers.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
        const bankOpts = bankAccts.map(a => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join('');

        openModal('Record Payment', `
            <form id="payment-form" onsubmit="PaymentsPage.save(event)">
                <div style="font-size:11px; color:var(--text-muted); margin-bottom:8px;">
                    Cross-currency reconciliation is not supported. Payment currency must match the invoice currency.
                </div>
                <div class="form-grid">
                    <div class="form-group"><label>Customer *</label>
                        <select name="customer_id" required onchange="PaymentsPage.loadInvoices(this.value)">
                            <option value="">Select...</option>${custOpts}</select></div>
                    <div class="form-group"><label>Date *</label>
                        <input name="date" type="date" required value="${todayISO()}"></div>
                    <div class="form-group"><label>Amount *</label>
                        <input name="amount" type="number" step="0.01" required></div>
                    <div class="form-group"><label>Method</label>
                        <select name="method">
                            <option value="">--</option>
                            <option>Check</option><option>Cash</option>
                            <option>Credit Card</option><option>ACH/EFT</option><option>Other</option>
                        </select></div>
                    <div class="form-group"><label>Currency</label>
                        <select name="currency" id="payment-currency" onchange="PaymentsPage.currencyChanged()">
                            ${currencyOptions(homeCurrency)}
                        </select></div>
                    <div class="form-group"><label>Exchange Rate <span style="color:var(--gray-500); font-weight:normal;">(→ ${escapeHtml(homeCurrency)})</span></label>
                        <input name="exchange_rate" id="payment-exchange-rate" type="number" step="0.00000001" value="1" disabled></div>
                    <div class="form-group"><label>Check #</label>
                        <input name="check_number"></div>
                    <div class="form-group"><label>Reference</label>
                        <input name="reference"></div>
                    <div class="form-group"><label>Deposit To</label>
                        <select name="deposit_to_account_id">
                            <option value="">--</option>${bankOpts}</select></div>
                    <div class="form-group full-width"><label>Notes</label>
                        <textarea name="notes"></textarea></div>
                </div>
                <div id="payment-invoices" style="margin-top:16px;"></div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Record Payment</button>
                </div>
            </form>`);
    },

    async currencyChanged() {
        const ccy = $('#payment-currency').value;
        const rateField = $('#payment-exchange-rate');
        PaymentsPage._formCurrency = ccy;
        if (ccy === PaymentsPage._homeCurrency) {
            rateField.value = '1';
            rateField.disabled = true;
            return;
        }
        rateField.disabled = false;
        try {
            const res = await API.get(`/fx/rate?from=${encodeURIComponent(ccy)}&to=${encodeURIComponent(PaymentsPage._homeCurrency)}`);
            if (res.rate) {
                rateField.value = parseFloat(res.rate);
                if (res.source === 'bankofcanada-cross') {
                    toast(`FX rate ${ccy}→${PaymentsPage._homeCurrency}: ${parseFloat(res.rate).toFixed(4)} (cross-rate via CAD)`);
                }
            } else {
                rateField.value = '1';
                toast(`FX rate ${ccy}→${PaymentsPage._homeCurrency} unavailable; using 1.0`, 'error');
            }
        } catch (err) {
            rateField.value = '1';
            toast('FX lookup failed; using 1.0', 'error');
        }
    },

    async loadInvoices(customerId) {
        if (!customerId) { $('#payment-invoices').innerHTML = ''; return; }
        const invoices = await API.get(`/invoices?customer_id=${customerId}&status=sent`);
        const partial = await API.get(`/invoices?customer_id=${customerId}&status=partial`);
        PaymentsPage._invoices = [...invoices, ...partial].filter(i => i.balance_due > 0);

        if (PaymentsPage._invoices.length === 0) {
            $('#payment-invoices').innerHTML = '<p style="color:var(--gray-400);">No outstanding invoices</p>';
            return;
        }

        let html = `<h4 style="margin-bottom:8px;">Apply to Invoices</h4>
            <div class="table-container"><table><thead><tr>
            <th>Invoice</th><th>Date</th><th>Ccy</th>
            <th class="amount">Balance</th><th class="amount">Apply</th>
            </tr></thead><tbody>`;
        for (const inv of PaymentsPage._invoices) {
            const ccy = (inv.currency || 'USD').toUpperCase();
            html += `<tr>
                <td>#${escapeHtml(inv.invoice_number)}</td>
                <td>${formatDate(inv.date)}</td>
                <td><span style="font-size:10px; padding:1px 6px; background:var(--gray-100); border-radius:4px;">${escapeHtml(ccy)}</span></td>
                <td class="amount">${formatCurrency(inv.balance_due, ccy)}</td>
                <td><input class="alloc-amount" data-invoice="${inv.id}" data-max="${inv.balance_due}"
                    data-currency="${ccy}"
                    type="number" step="0.01" min="0" max="${inv.balance_due}"
                    style="width:100px; padding:4px 8px; border:1px solid var(--gray-300); border-radius:4px;"></td>
            </tr>`;
        }
        html += `</tbody></table></div>`;
        $('#payment-invoices').innerHTML = html;
    },

    async save(e) {
        e.preventDefault();
        const form = e.target;
        const payCcy = (form.currency.value || 'USD').toUpperCase();
        const allocations = [];
        let mismatch = null;
        $$('.alloc-amount').forEach(input => {
            const amt = parseFloat(input.value);
            if (amt > 0) {
                const invCcy = (input.dataset.currency || 'USD').toUpperCase();
                if (invCcy !== payCcy && !mismatch) mismatch = invCcy;
                allocations.push({ invoice_id: parseInt(input.dataset.invoice), amount: amt });
            }
        });
        if (mismatch) {
            toast(`Selected invoice is in ${mismatch}, but payment is in ${payCcy}. Cross-currency reconciliation is not supported.`, 'error');
            return;
        }

        const data = {
            customer_id: parseInt(form.customer_id.value),
            date: form.date.value,
            amount: parseFloat(form.amount.value),
            method: form.method.value || null,
            check_number: form.check_number.value || null,
            reference: form.reference.value || null,
            deposit_to_account_id: form.deposit_to_account_id.value ? parseInt(form.deposit_to_account_id.value) : null,
            notes: form.notes.value || null,
            currency: payCcy,
            exchange_rate: parseFloat(form.exchange_rate.value) || 1,
            allocations,
        };

        try {
            await API.post('/payments', data);
            toast('Payment recorded');
            closeModal();
            App.navigate(location.hash);
        } catch (err) { toast(err.message, 'error'); }
    },
};
