/**
 * Payroll — pay runs and pay stubs
 * Feature 17: Process payroll with withholding calculations
 */
const PayrollPage = {
    async render() {
        const runs = await API.get('/payroll');
        let html = `
            <div class="page-header">
                <h2>Payroll</h2>
                <button class="btn btn-primary" onclick="PayrollPage.showRunForm()">+ New Pay Run</button>
            </div>
            <div style="background:#fef3c7;border:1px solid #fbbf24;padding:6px 10px;margin-bottom:12px;font-size:10px;color:#92400e;">
                <strong>Disclaimer:</strong> Tax calculations are approximate. Verify with a tax professional before filing.
            </div>`;

        if (runs.length === 0) {
            html += '<div class="empty-state"><p>No payroll runs yet</p></div>';
        } else {
            html += `<div class="table-container"><table>
                <thead><tr><th>Period</th><th>Pay Date</th><th>Status</th>
                <th class="amount">Gross</th><th class="amount">Taxes</th><th class="amount">Net</th><th>Actions</th></tr></thead><tbody>`;
            for (const r of runs) {
                html += `<tr>
                    <td>${formatDate(r.period_start)} - ${formatDate(r.period_end)}</td>
                    <td>${formatDate(r.pay_date)}</td>
                    <td>${statusBadge(r.status)}</td>
                    <td class="amount">${formatCurrency(r.total_gross)}</td>
                    <td class="amount">${formatCurrency(r.total_taxes)}</td>
                    <td class="amount">${formatCurrency(r.total_net)}</td>
                    <td class="actions">
                        <button class="btn btn-sm btn-secondary" onclick="PayrollPage.view(${r.id})">View</button>
                        ${r.status === 'draft' ? `<button class="btn btn-sm btn-primary" onclick="PayrollPage.process(${r.id})">Process</button>` : ''}
                    </td>
                </tr>`;
            }
            html += '</tbody></table></div>';
        }
        return html;
    },

    async showRunForm() {
        const emps = await API.get('/employees?active_only=true');
        if (emps.length === 0) {
            toast('Add employees first', 'error');
            return;
        }

        let empRows = emps.map(e => `
            <tr>
                <td><input type="checkbox" class="pr-check" data-emp="${e.id}" checked></td>
                <td>${escapeHtml(e.first_name)} ${escapeHtml(e.last_name)}</td>
                <td>${e.pay_type}</td>
                <td class="amount">${formatCurrency(e.pay_rate)}${e.pay_type==='hourly'?'/hr':'/yr'}</td>
                <td><input type="number" step="0.5" class="pr-hours" data-emp="${e.id}" value="${e.pay_type==='hourly'?'80':'0'}" style="width:60px;"></td>
            </tr>`).join('');

        openModal('New Pay Run', `
            <form onsubmit="PayrollPage.createRun(event)">
                <div class="form-grid">
                    <div class="form-group"><label>Period Start *</label>
                        <input name="period_start" type="date" required value="${todayISO()}"></div>
                    <div class="form-group"><label>Period End *</label>
                        <input name="period_end" type="date" required></div>
                    <div class="form-group"><label>Pay Date *</label>
                        <input name="pay_date" type="date" required></div>
                </div>
                <h3 style="margin:12px 0 8px;font-size:14px;">Employee Hours</h3>
                <div class="table-container"><table>
                    <thead><tr><th style="width:30px;"></th><th>Employee</th><th>Type</th><th class="amount">Rate</th><th>Hours</th></tr></thead>
                    <tbody>${empRows}</tbody>
                </table></div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Calculate Payroll</button>
                </div>
            </form>`);
    },

    async createRun(e) {
        e.preventDefault();
        const form = e.target;
        const stubs = [];
        $$('.pr-check:checked').forEach(cb => {
            const empId = parseInt(cb.dataset.emp);
            const hours = parseFloat($(`.pr-hours[data-emp="${empId}"]`).value) || 0;
            stubs.push({ employee_id: empId, hours });
        });
        if (stubs.length === 0) { toast('Select employees', 'error'); return; }

        try {
            await API.post('/payroll', {
                period_start: form.period_start.value,
                period_end: form.period_end.value,
                pay_date: form.pay_date.value,
                stubs,
            });
            toast('Pay run created');
            closeModal();
            App.navigate('#/payroll');
        } catch (err) { toast(err.message, 'error'); }
    },

    async view(id) {
        const run = await API.get(`/payroll/${id}`);
        let rows = run.stubs.map(s => `
            <tr>
                <td>${escapeHtml(s.employee_name || `Employee ${s.employee_id}`)}</td>
                <td class="amount">${s.hours}</td>
                <td class="amount">${formatCurrency(s.gross_pay)}</td>
                <td class="amount">${formatCurrency(s.federal_tax)}</td>
                <td class="amount">${formatCurrency(s.state_tax)}</td>
                <td class="amount">${formatCurrency(s.ss_tax)}</td>
                <td class="amount">${formatCurrency(s.medicare_tax)}</td>
                <td class="amount" style="font-weight:700;">${formatCurrency(s.net_pay)}</td>
            </tr>`).join('');

        openModal(`Pay Run: ${run.period_start} to ${run.period_end}`, `
            <div class="table-container"><table>
                <thead><tr><th>Employee</th><th class="amount">Hours</th><th class="amount">Gross</th>
                <th class="amount">Fed</th><th class="amount">State</th><th class="amount">SS</th>
                <th class="amount">Med</th><th class="amount">Net</th></tr></thead>
                <tbody>${rows}</tbody>
            </table></div>
            <div class="invoice-totals">
                <div class="total-row"><span class="label">Total Gross</span><span class="value">${formatCurrency(run.total_gross)}</span></div>
                <div class="total-row"><span class="label">Total Taxes</span><span class="value">${formatCurrency(run.total_taxes)}</span></div>
                <div class="total-row grand-total"><span class="label">Total Net</span><span class="value">${formatCurrency(run.total_net)}</span></div>
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Close</button>
            </div>`);
    },

    async process(id) {
        if (!confirm('Process this pay run? This will create journal entries.')) return;
        try {
            await API.post(`/payroll/${id}/process`);
            toast('Payroll processed');
            App.navigate('#/payroll');
        } catch (err) { toast(err.message, 'error'); }
    },
};
