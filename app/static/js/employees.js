/**
 * Employees — CRUD for employee records
 * Feature 17: Payroll basics
 */
const EmployeesPage = {
    async render() {
        const emps = await API.get('/employees');
        let html = `
            <div class="page-header">
                <h2>Employees</h2>
                <button class="btn btn-primary" onclick="EmployeesPage.showForm()">+ Add Employee</button>
            </div>`;

        if (emps.length === 0) {
            html += '<div class="empty-state"><p>No employees added yet</p></div>';
        } else {
            html += `<div class="table-container"><table>
                <thead><tr><th>Name</th><th>Pay Type</th><th class="amount">Rate</th><th>Status</th><th>Filing</th><th>Actions</th></tr></thead><tbody>`;
            for (const e of emps) {
                html += `<tr>
                    <td><strong>${escapeHtml(e.first_name)} ${escapeHtml(e.last_name)}</strong></td>
                    <td>${e.pay_type}</td>
                    <td class="amount">${formatCurrency(e.pay_rate)}${e.pay_type==='hourly'?'/hr':'/yr'}</td>
                    <td>${e.is_active ? '<span class="badge badge-paid">Active</span>' : '<span class="badge badge-draft">Inactive</span>'}</td>
                    <td>${e.filing_status}</td>
                    <td class="actions">
                        <button class="btn btn-sm btn-secondary" onclick="EmployeesPage.showForm(${e.id})">Edit</button>
                    </td>
                </tr>`;
            }
            html += '</tbody></table></div>';
        }
        return html;
    },

    async showForm(id = null) {
        let emp = { first_name: '', last_name: '', pay_type: 'hourly', pay_rate: 0, filing_status: 'single', allowances: 0, hire_date: todayISO() };
        if (id) emp = await API.get(`/employees/${id}`);

        openModal(id ? 'Edit Employee' : 'Add Employee', `
            <form onsubmit="EmployeesPage.save(event, ${id})">
                <div class="form-grid">
                    <div class="form-group"><label>First Name *</label>
                        <input name="first_name" required value="${escapeHtml(emp.first_name)}"></div>
                    <div class="form-group"><label>Last Name *</label>
                        <input name="last_name" required value="${escapeHtml(emp.last_name)}"></div>
                    <div class="form-group"><label>SSN Last 4</label>
                        <input name="ssn_last_four" maxlength="4" value="${escapeHtml(emp.ssn_last_four || '')}"></div>
                    <div class="form-group"><label>Pay Type</label>
                        <select name="pay_type">
                            <option value="hourly" ${emp.pay_type==='hourly'?'selected':''}>Hourly</option>
                            <option value="salary" ${emp.pay_type==='salary'?'selected':''}>Salary</option>
                        </select></div>
                    <div class="form-group"><label>Pay Rate</label>
                        <input name="pay_rate" type="number" step="0.01" value="${emp.pay_rate}"></div>
                    <div class="form-group"><label>Filing Status</label>
                        <select name="filing_status">
                            <option value="single" ${emp.filing_status==='single'?'selected':''}>Single</option>
                            <option value="married" ${emp.filing_status==='married'?'selected':''}>Married</option>
                            <option value="head_of_household" ${emp.filing_status==='head_of_household'?'selected':''}>Head of Household</option>
                        </select></div>
                    <div class="form-group"><label>Allowances</label>
                        <input name="allowances" type="number" value="${emp.allowances}"></div>
                    <div class="form-group"><label>Hire Date</label>
                        <input name="hire_date" type="date" value="${emp.hire_date || ''}"></div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">${id ? 'Update' : 'Add'} Employee</button>
                </div>
            </form>`);
    },

    async save(e, id) {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        data.pay_rate = parseFloat(data.pay_rate) || 0;
        data.allowances = parseInt(data.allowances) || 0;
        if (!data.hire_date) delete data.hire_date;
        try {
            if (id) { await API.put(`/employees/${id}`, data); toast('Employee updated'); }
            else { await API.post('/employees', data); toast('Employee added'); }
            closeModal();
            App.navigate('#/employees');
        } catch (err) { toast(err.message, 'error'); }
    },
};
