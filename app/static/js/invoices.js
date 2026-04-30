/**
 * Decompiled from QBW32.EXE!CCreateInvoicesView  Offset: 0x0015E400
 * This was the crown jewel of QB2003 — the "Create Invoices" form with
 * the yellow-tinted paper background texture (resource RT_BITMAP id=0x012C).
 * Line items were rendered in a custom owner-draw CListCtrl subclass called
 * CQBGridCtrl. We're using an HTML table instead. Less charming, more functional.
 * The original auto-fill from item selection was in CInvoiceForm::OnItemChanged()
 * at 0x0015E890 — same logic lives in itemSelected() below.
 */
const InvoicesPage = {
    async render() {
        const [invoices, settings] = await Promise.all([
            API.get('/invoices'),
            API.get('/settings'),
        ]);
        const homeCurrency = (settings.home_currency || 'USD').toUpperCase();

        // YTD total in home currency: include drafts, exclude void only.
        const yearStart = new Date().getFullYear() + '-01-01';
        const ytdTotal = invoices
            .filter(inv => inv.status !== 'void' && inv.date >= yearStart)
            .reduce((sum, inv) => sum + parseFloat(inv.home_currency_amount || 0), 0);

        let html = `
            <div class="page-header">
                <h2>Invoices</h2>
                <button class="btn btn-primary" onclick="InvoicesPage.showForm()">+ New Invoice</button>
            </div>
            <div class="toolbar" style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
                <select id="inv-status-filter" onchange="InvoicesPage.applyFilter()">
                    <option value="">All Statuses</option>
                    <option value="draft">Draft</option>
                    <option value="sent">Sent</option>
                    <option value="partial">Partial</option>
                    <option value="paid">Paid</option>
                    <option value="void">Void</option>
                </select>
                <div style="font-size:12px; color:var(--gray-700);">
                    <strong>YTD in ${escapeHtml(homeCurrency)}:</strong>
                    ${formatCurrency(ytdTotal, homeCurrency)}
                </div>
            </div>`;

        if (invoices.length === 0) {
            html += `<div class="empty-state"><p>No invoices yet</p></div>`;
        } else {
            html += `<div class="table-container"><table>
                <thead><tr>
                    <th>#</th><th>Customer</th><th>Date</th><th>Due Date</th>
                    <th>Status</th>
                    <th class="amount">Total</th>
                    <th class="amount">Total (${escapeHtml(homeCurrency)})</th>
                    <th class="amount">Balance</th><th>Actions</th>
                </tr></thead><tbody id="inv-tbody">`;
            for (const inv of invoices) {
                const invCcy = (inv.currency || 'USD').toUpperCase();
                html += `<tr class="inv-row" data-status="${inv.status}">
                    <td><strong>${escapeHtml(inv.invoice_number)}</strong></td>
                    <td>${escapeHtml(inv.customer_name || '')}</td>
                    <td>${formatDate(inv.date)}</td>
                    <td>${formatDate(inv.due_date)}</td>
                    <td>${statusBadge(inv.status)}</td>
                    <td class="amount">${formatCurrency(inv.total, invCcy)}</td>
                    <td class="amount">${formatCurrency(inv.home_currency_amount, homeCurrency)}</td>
                    <td class="amount">${formatCurrency(inv.balance_due, invCcy)}</td>
                    <td class="actions">
                        <button class="btn btn-sm btn-secondary" onclick="InvoicesPage.view(${inv.id})">View</button>
                        <button class="btn btn-sm btn-secondary" onclick="InvoicesPage.showForm(${inv.id})">Edit</button>
                    </td>
                </tr>`;
            }
            html += `</tbody></table></div>`;
        }
        return html;
    },

    applyFilter() {
        const status = $('#inv-status-filter').value;
        $$('.inv-row').forEach(row => {
            row.style.display = (!status || row.dataset.status === status) ? '' : 'none';
        });
    },

    async view(id) {
        const [inv, settings] = await Promise.all([
            API.get(`/invoices/${id}`),
            API.get('/settings'),
        ]);
        const invCcy = (inv.currency || 'USD').toUpperCase();
        const homeCcy = (settings.home_currency || 'USD').toUpperCase();
        const showHome = invCcy !== homeCcy;
        const totalLine = showHome
            ? `${formatCurrency(inv.total, invCcy)} <span style="color:var(--gray-500); font-weight:normal;">(≈ ${formatCurrency(inv.home_currency_amount, homeCcy)})</span>`
            : formatCurrency(inv.total, invCcy);

        let linesHtml = inv.lines.map(l =>
            `<tr><td>${escapeHtml(l.description || '')}</td><td class="amount">${l.quantity}</td>
             <td class="amount">${formatCurrency(l.rate, invCcy)}</td><td class="amount">${formatCurrency(l.amount, invCcy)}</td></tr>`
        ).join('');

        openModal(`Invoice #${inv.invoice_number}`, `
            <div style="margin-bottom:12px;">
                <strong>Customer:</strong> ${escapeHtml(inv.customer_name || '')}<br>
                <strong>Date:</strong> ${formatDate(inv.date)}<br>
                <strong>Due:</strong> ${formatDate(inv.due_date)}<br>
                <strong>Status:</strong> ${statusBadge(inv.status)}<br>
                <strong>Currency:</strong> ${escapeHtml(invCcy)}${showHome ? ` <span style="color:var(--gray-500);">(rate ${parseFloat(inv.exchange_rate).toFixed(4)} → ${escapeHtml(homeCcy)})</span>` : ''}<br>
                ${inv.po_number ? `<strong>PO#:</strong> ${escapeHtml(inv.po_number)}<br>` : ''}
            </div>
            <div class="table-container"><table>
                <thead><tr><th>Description</th><th class="amount">Qty</th><th class="amount">Rate</th><th class="amount">Amount</th></tr></thead>
                <tbody>${linesHtml}</tbody>
            </table></div>
            <div class="invoice-totals">
                <div class="total-row"><span class="label">Subtotal</span><span class="value">${formatCurrency(inv.subtotal, invCcy)}</span></div>
                <div class="total-row"><span class="label">Tax</span><span class="value">${formatCurrency(inv.tax_amount, invCcy)}</span></div>
                <div class="total-row grand-total"><span class="label">Total</span><span class="value">${totalLine}</span></div>
                <div class="total-row"><span class="label">Paid</span><span class="value">${formatCurrency(inv.amount_paid, invCcy)}</span></div>
                <div class="total-row grand-total"><span class="label">Balance Due</span><span class="value">${formatCurrency(inv.balance_due, invCcy)}</span></div>
            </div>
            ${inv.notes ? `<p style="margin-top:12px;color:var(--gray-500);">${escapeHtml(inv.notes)}</p>` : ''}
            <div style="margin-top:16px; border-top:1px solid var(--gray-200); padding-top:12px;">
                <h3 style="font-size:13px; margin-bottom:8px;">Attachments</h3>
                <div id="inv-attachments-list" style="margin-bottom:8px; font-size:11px;">Loading...</div>
                <input type="file" id="inv-attach-file" style="font-size:11px;">
                <button class="btn btn-sm btn-secondary" onclick="InvoicesPage.uploadAttachment(${inv.id})" style="margin-left:4px;">Upload</button>
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="window.open('/api/invoices/${inv.id}/pdf','_blank')">Save PDF</button>
                <button class="btn btn-secondary" onclick="window.open('/api/invoices/${inv.id}/print-preview','_blank')">Print</button>
                <button class="btn btn-secondary" onclick="InvoicesPage.duplicate(${inv.id})">Duplicate</button>
                <button class="btn btn-secondary" onclick="InvoicesPage.emailInvoice(${inv.id})">Email Invoice</button>
                <button class="btn btn-secondary" onclick="InvoicesPage.copyPaymentLink(${inv.id})">Copy Payment Link</button>
                ${inv.status === 'draft' ? `<button class="btn btn-primary" onclick="InvoicesPage.markSent(${inv.id})">Mark Sent</button>` : ''}
                ${inv.status !== 'void' ? `<button class="btn btn-danger" onclick="InvoicesPage.void(${inv.id})">Void Invoice</button>` : ''}
                <button class="btn btn-secondary" onclick="closeModal()">Close</button>
            </div>`);
        InvoicesPage.loadAttachments('invoice', inv.id);
    },

    async void(id) {
        if (!confirm('Void this invoice? This cannot be undone.')) return;
        try {
            await API.post(`/invoices/${id}/void`);
            toast('Invoice voided');
            closeModal();
            App.navigate(location.hash);
        } catch (err) { toast(err.message, 'error'); }
    },

    async markSent(id) {
        try {
            await API.post(`/invoices/${id}/send`);
            toast('Invoice marked as sent');
            closeModal();
            App.navigate(location.hash);
        } catch (err) { toast(err.message, 'error'); }
    },

    async duplicate(id) {
        try {
            const inv = await API.post(`/invoices/${id}/duplicate`);
            toast(`Duplicated as Invoice #${inv.invoice_number}`);
            closeModal();
            App.navigate('#/invoices');
        } catch (err) { toast(err.message, 'error'); }
    },

    async copyPaymentLink(id) {
        try {
            const data = await API.get(`/stripe/payment-link/${id}`);
            await navigator.clipboard.writeText(data.url);
            toast('Payment link copied to clipboard');
        } catch (err) { toast(err.message, 'error'); }
    },

    async emailInvoice(id) {
        const inv = await API.get(`/invoices/${id}`);
        const email = inv.customer_email || '';
        openModal('Email Invoice', `
            <form onsubmit="InvoicesPage.sendEmail(event, ${id})">
                <div class="form-grid">
                    <div class="form-group full-width"><label>Recipient Email *</label>
                        <input name="recipient" type="email" required value="${escapeHtml(email)}"></div>
                    <div class="form-group full-width"><label>Subject</label>
                        <input name="subject" value="Invoice #${escapeHtml(inv.invoice_number)} from ${escapeHtml(inv.customer_name || 'us')}"></div>
                    <div class="form-group full-width"><label>Message</label>
                        <textarea name="message">Please find attached Invoice #${escapeHtml(inv.invoice_number)}.</textarea></div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Send Email</button>
                </div>
            </form>`);
    },

    async sendEmail(e, id) {
        e.preventDefault();
        const form = e.target;
        try {
            await API.post(`/invoices/${id}/email`, {
                recipient: form.recipient.value,
                subject: form.subject.value,
                message: form.message.value,
            });
            toast('Invoice emailed');
            closeModal();
        } catch (err) { toast(err.message, 'error'); }
    },

    lineCount: 0,
    _customers: [],

    async showForm(id = null) {
        const [customers, items, settings, classes] = await Promise.all([
            API.get('/customers?active_only=true'),
            API.get('/items?active_only=true'),
            API.get('/settings'),
            API.get('/classes'),
        ]);
        InvoicesPage._classes = classes;

        const homeCurrency = (settings.home_currency || 'USD').toUpperCase();
        let inv = {
            customer_id: '',
            date: todayISO(),
            terms: settings.default_terms || 'Net 30',
            po_number: '',
            tax_rate: (parseFloat(settings.default_tax_rate || '0') || 0) / 100,
            notes: settings.invoice_notes || '',
            currency: homeCurrency,
            exchange_rate: 1,
            lines: [],
        };
        if (id) inv = await API.get(`/invoices/${id}`);
        if (inv.lines.length === 0) inv.lines = [{ item_id: '', description: '', quantity: 1, rate: 0 }];

        InvoicesPage.lineCount = inv.lines.length;
        InvoicesPage._items = items;
        InvoicesPage._customers = customers;
        InvoicesPage._homeCurrency = homeCurrency;
        InvoicesPage._invCurrency = (inv.currency || homeCurrency).toUpperCase();

        const custOpts = customers.map(c => `<option value="${c.id}" ${inv.customer_id==c.id?'selected':''}>${escapeHtml(c.name)}</option>`).join('');

        openModal(id ? 'Edit Invoice' : 'New Invoice', `
            <form id="invoice-form" onsubmit="InvoicesPage.save(event, ${id})">
                <div class="form-grid">
                    <div class="form-group"><label>Class *</label>
                        <select name="class_id" id="inv-class-select" required>${classOptions(classes, inv.class_id)}</select>
                        <a href="#" style="font-size:11px;" onclick="event.preventDefault(); InvoicesPage.newClass()">+ New class</a></div>
                    <div class="form-group"><label>Customer *</label>
                        <select name="customer_id" id="inv-customer-select" required onchange="InvoicesPage.customerSelected(this.value)"><option value="">Select...</option>${custOpts}</select>
                        <a href="#" style="font-size:11px;" onclick="event.preventDefault(); InvoicesPage.newCustomer()">+ New customer</a></div>
                    <div class="form-group"><label>Date *</label>
                        <input name="date" type="date" required value="${inv.date}"></div>
                    <div class="form-group"><label>Terms</label>
                        <select name="terms" id="invoice-terms">
                            ${['Net 15','Net 30','Net 45','Net 60','Due on Receipt'].map(t =>
                                `<option value="${t}" ${inv.terms===t?'selected':''}>${t}</option>`).join('')}
                        </select></div>
                    <div class="form-group"><label>PO #</label>
                        <input name="po_number" value="${escapeHtml(inv.po_number || '')}"></div>
                    <div class="form-group"><label>Tax Rate (%)</label>
                        <input name="tax_rate" type="number" step="0.01" value="${(inv.tax_rate * 100) || 0}"
                            oninput="InvoicesPage.recalc()"></div>
                    <div class="form-group"><label>Currency</label>
                        <select name="currency" id="invoice-currency" onchange="InvoicesPage.currencyChanged()">
                            ${currencyOptions((inv.currency || homeCurrency).toUpperCase())}
                        </select></div>
                    <div class="form-group"><label>Exchange Rate <span style="color:var(--gray-500); font-weight:normal;">(→ ${escapeHtml(homeCurrency)})</span></label>
                        <input name="exchange_rate" id="invoice-exchange-rate" type="number" step="0.00000001"
                            value="${parseFloat(inv.exchange_rate || 1)}"></div>
                </div>
                <h3 style="margin:16px 0 8px; font-size:14px; color:var(--gray-600);">Line Items</h3>
                <table class="line-items-table">
                    <thead><tr>
                        <th>Item</th><th>Description</th><th class="col-qty">Qty</th>
                        <th class="col-rate">Rate</th><th class="col-amount">Amount</th><th class="col-actions"></th>
                    </tr></thead>
                    <tbody id="inv-lines">
                        ${inv.lines.map((l, i) => InvoicesPage.lineRowHtml(i, l, items)).join('')}
                    </tbody>
                </table>
                <button type="button" class="btn btn-sm btn-secondary" style="margin-top:8px;" onclick="InvoicesPage.addLine()">+ Add Line</button>
                <a href="#" style="font-size:11px; margin-left:12px;" onclick="event.preventDefault(); InvoicesPage.newItem()">+ New item</a>
                <div class="invoice-totals" id="inv-totals">
                    <div class="total-row"><span class="label">Subtotal</span><span class="value" id="inv-subtotal">$0.00</span></div>
                    <div class="total-row"><span class="label">Tax</span><span class="value" id="inv-tax">$0.00</span></div>
                    <div class="total-row grand-total"><span class="label">Total</span><span class="value" id="inv-total">$0.00</span></div>
                </div>
                <div class="form-group" style="margin-top:12px;"><label>Notes</label>
                    <textarea name="notes">${escapeHtml(inv.notes || '')}</textarea></div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">${id ? 'Update' : 'Create'} Invoice</button>
                </div>
            </form>`);
        if (!id && inv.customer_id) InvoicesPage.customerSelected(inv.customer_id);
        InvoicesPage._syncRateField();
        InvoicesPage.recalc();
    },

    _syncRateField() {
        // Disable the rate field when invoice currency == home currency
        // (rate is always 1.0 in that case).
        const ccy = $('#invoice-currency')?.value;
        const rateField = $('#invoice-exchange-rate');
        if (!ccy || !rateField) return;
        if (ccy === InvoicesPage._homeCurrency) {
            rateField.value = '1';
            rateField.disabled = true;
        } else {
            rateField.disabled = false;
        }
    },

    async currencyChanged() {
        const ccy = $('#invoice-currency').value;
        const rateField = $('#invoice-exchange-rate');
        InvoicesPage._invCurrency = ccy;
        InvoicesPage.recalc();
        if (ccy === InvoicesPage._homeCurrency) {
            rateField.value = '1';
            rateField.disabled = true;
            return;
        }
        rateField.disabled = false;
        // Pre-populate from BoC; user can still edit. If unavailable, leave 1.0.
        try {
            const res = await API.get(`/fx/rate?from=${encodeURIComponent(ccy)}&to=${encodeURIComponent(InvoicesPage._homeCurrency)}`);
            if (res.rate) {
                rateField.value = parseFloat(res.rate);
                if (res.source === 'bankofcanada-cross') {
                    toast(`FX rate ${ccy}→${InvoicesPage._homeCurrency}: ${parseFloat(res.rate).toFixed(4)} (cross-rate via CAD)`);
                }
            } else {
                rateField.value = '1';
                toast(`FX rate ${ccy}→${InvoicesPage._homeCurrency} unavailable; using 1.0`, 'error');
            }
        } catch (err) {
            rateField.value = '1';
            toast(`FX lookup failed; using 1.0`, 'error');
        }
    },

    newClass() {
        InlineCreate.open('class', async (created) => {
            const fresh = await API.get('/classes');
            InvoicesPage._classes = fresh;
            const sel = $('#inv-class-select');
            if (sel) {
                sel.innerHTML = classOptions(fresh, created.id);
            }
        });
    },

    customerSelected(customerId) {
        const customer = InvoicesPage._customers.find(c => c.id == customerId);
        const termsField = $('#invoice-terms');
        if (customer && termsField && customer.terms) {
            termsField.value = customer.terms;
        }
    },

    newCustomer() {
        InlineCreate.open('customer', async (created) => {
            const fresh = await API.get('/customers?active_only=true');
            InvoicesPage._customers = fresh;
            const sel = $('#inv-customer-select');
            if (sel) {
                const opts = fresh.map(c =>
                    `<option value="${c.id}"${c.id == created.id ? ' selected' : ''}>${escapeHtml(c.name)}</option>`
                ).join('');
                sel.innerHTML = `<option value="">Select...</option>${opts}`;
                sel.value = String(created.id);
            }
        });
    },

    newItem() {
        InlineCreate.open('item', async (created) => {
            const fresh = await API.get('/items?active_only=true');
            InvoicesPage._items = fresh;
            // Refresh every line's item dropdown, preserving each row's
            // current selection. New rows added later already see the
            // updated _items list via lineRowHtml.
            $$('#inv-lines tr').forEach(row => {
                const sel = row.querySelector('.line-item');
                if (!sel) return;
                const current = sel.value;
                const opts = fresh.map(i =>
                    `<option value="${i.id}"${i.id == current ? ' selected' : ''}>${escapeHtml(i.name)}</option>`
                ).join('');
                sel.innerHTML = `<option value="">--</option>${opts}`;
            });
        });
    },

    lineRowHtml(idx, line, items) {
        const itemOpts = items.map(i => `<option value="${i.id}" ${line.item_id==i.id?'selected':''}>${escapeHtml(i.name)}</option>`).join('');
        const ccy = InvoicesPage._invCurrency || 'USD';
        return `<tr data-line="${idx}">
            <td><select class="line-item" onchange="InvoicesPage.itemSelected(${idx})">
                <option value="">--</option>${itemOpts}</select></td>
            <td><input class="line-desc" value="${escapeHtml(line.description || '')}"></td>
            <td><input class="line-qty" type="number" step="0.01" value="${line.quantity || 1}" oninput="InvoicesPage.recalc()"></td>
            <td><input class="line-rate" type="number" step="0.01" value="${line.rate || 0}" oninput="InvoicesPage.recalc()"></td>
            <td class="col-amount line-amount">${formatCurrency((line.quantity||1) * (line.rate||0), ccy)}</td>
            <td><button type="button" class="btn btn-sm btn-danger" onclick="InvoicesPage.removeLine(${idx})">X</button></td>
        </tr>`;
    },

    addLine() {
        const tbody = $('#inv-lines');
        const idx = InvoicesPage.lineCount++;
        tbody.insertAdjacentHTML('beforeend', InvoicesPage.lineRowHtml(idx, {}, InvoicesPage._items));
    },

    removeLine(idx) {
        const row = $(`[data-line="${idx}"]`);
        if (row) row.remove();
        InvoicesPage.recalc();
    },

    itemSelected(idx) {
        const row = $(`[data-line="${idx}"]`);
        const itemId = row.querySelector('.line-item').value;
        const item = InvoicesPage._items.find(i => i.id == itemId);
        if (item) {
            row.querySelector('.line-desc').value = item.description || item.name;
            row.querySelector('.line-rate').value = item.rate;
            InvoicesPage.recalc();
        }
    },

    recalc() {
        const ccy = InvoicesPage._invCurrency || 'USD';
        let subtotal = 0;
        $$('#inv-lines tr').forEach(row => {
            const qty = parseFloat(row.querySelector('.line-qty')?.value) || 0;
            const rate = parseFloat(row.querySelector('.line-rate')?.value) || 0;
            const amount = qty * rate;
            subtotal += amount;
            const amountCell = row.querySelector('.line-amount');
            if (amountCell) amountCell.textContent = formatCurrency(amount, ccy);
        });
        const taxPct = parseFloat($('[name="tax_rate"]')?.value) || 0;
        const tax = subtotal * (taxPct / 100);
        $('#inv-subtotal').textContent = formatCurrency(subtotal, ccy);
        $('#inv-tax').textContent = formatCurrency(tax, ccy);
        $('#inv-total').textContent = formatCurrency(subtotal + tax, ccy);
    },

    async save(e, id) {
        e.preventDefault();
        const form = e.target;
        const lines = [];
        $$('#inv-lines tr').forEach((row, i) => {
            const item_id = row.querySelector('.line-item')?.value;
            lines.push({
                item_id: item_id ? parseInt(item_id) : null,
                description: row.querySelector('.line-desc')?.value || '',
                quantity: parseFloat(row.querySelector('.line-qty')?.value) || 1,
                rate: parseFloat(row.querySelector('.line-rate')?.value) || 0,
                line_order: i,
            });
        });

        if (!requireClassPicked(form)) return;
        const data = {
            customer_id: parseInt(form.customer_id.value),
            date: form.date.value,
            terms: form.terms.value,
            po_number: form.po_number.value || null,
            tax_rate: (parseFloat(form.tax_rate.value) || 0) / 100,
            notes: form.notes.value || null,
            currency: (form.currency.value || 'USD').toUpperCase(),
            exchange_rate: parseFloat(form.exchange_rate.value) || 1,
            class_id: parseInt(form.class_id.value),
            lines,
        };

        try {
            if (id) { await API.put(`/invoices/${id}`, data); toast('Invoice updated'); }
            else { await API.post('/invoices', data); toast('Invoice created'); }
            closeModal();
            App.navigate(location.hash);
        } catch (err) { toast(err.message, 'error'); }
    },

    async loadAttachments(entityType, entityId) {
        const el = $('#inv-attachments-list');
        if (!el) return;
        try {
            const attachments = await API.get(`/attachments/${entityType}/${entityId}`);
            if (attachments.length === 0) {
                el.innerHTML = '<span style="color:var(--text-muted);">No attachments</span>';
            } else {
                el.innerHTML = attachments.map(a =>
                    `<div style="display:flex; align-items:center; gap:8px; padding:2px 0;">
                        <a href="/api/attachments/download/${a.id}" target="_blank">${escapeHtml(a.filename)}</a>
                        <span style="color:var(--gray-400);">(${(a.file_size/1024).toFixed(1)} KB)</span>
                        <button class="btn btn-sm btn-danger" onclick="InvoicesPage.deleteAttachment(${a.id},'${entityType}',${entityId})" style="padding:0 4px; font-size:10px;">X</button>
                    </div>`
                ).join('');
            }
        } catch (e) { el.innerHTML = ''; }
    },

    async uploadAttachment(entityId) {
        const fileInput = $('#inv-attach-file');
        if (!fileInput?.files[0]) { toast('Select a file first', 'error'); return; }
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        try {
            const resp = await fetch(`/api/attachments/invoice/${entityId}`, { method: 'POST', body: formData });
            if (!resp.ok) { const d = await resp.json(); throw new Error(d.detail || 'Upload failed'); }
            toast('Attachment uploaded');
            fileInput.value = '';
            InvoicesPage.loadAttachments('invoice', entityId);
        } catch (err) { toast(err.message, 'error'); }
    },

    async deleteAttachment(attachId, entityType, entityId) {
        if (!confirm('Delete this attachment?')) return;
        try {
            await API.del(`/attachments/${attachId}`);
            toast('Attachment deleted');
            InvoicesPage.loadAttachments(entityType, entityId);
        } catch (err) { toast(err.message, 'error'); }
    },
};
