/**
 * Household airline miles tracker — phase 1.5 task 2.
 *
 * One card per loyalty programme with logo and brand colour, a horizontal
 * stacked bar showing the per-person split of the current point total, and
 * a table of memberships underneath (member#, elite status, latest balance,
 * "as of" date).
 *
 * The "Update balance" inline form on each row POSTs to /airline-miles/snapshots
 * which is upsert by (membership_id, as_of_date) — re-entering today's value
 * overwrites instead of creating a duplicate.
 *
 * Brand colour is rendered as an inline CSS custom property
 * (`style="--program-color: #c8102e"`) on each card so styling stays
 * data-driven without requiring per-program CSS edits.
 */
const AirlineMilesPage = {
    _payload: [],
    _people: [],

    async render() {
        AirlineMilesPage._payload = await API.get('/airline-miles');
        AirlineMilesPage._people = await API.get('/people');

        const cardsHtml = AirlineMilesPage._payload
            .map(prog => AirlineMilesPage._renderCard(prog))
            .join('');

        const grandTotal = AirlineMilesPage._payload
            .reduce((sum, p) => sum + (p.total_balance || 0), 0);

        return `
            <div class="page-header">
                <h2>Airline Miles</h2>
                <div class="header-meta">
                    Household total
                    <strong style="margin-left:6px;">${AirlineMilesPage._fmtPoints(grandTotal)}</strong>
                    points across ${AirlineMilesPage._payload.length} programmes
                </div>
            </div>
            <div class="airline-miles-grid">
                ${cardsHtml || AirlineMilesPage._emptyState()}
            </div>
        `;
    },

    _emptyState() {
        return `<div class="empty-state">
            <p>No airline programmes yet.</p>
        </div>`;
    },

    _renderCard(prog) {
        const total = prog.total_balance || 0;

        // Logo: only render the <img> if the row has a logo_path. The
        // initial-circle fallback uses the brand colour and the first
        // letter of the programme name.
        const logoHtml = prog.logo_path
            ? `<img src="/static/${escapeHtml(prog.logo_path)}"
                    alt="${escapeHtml(prog.name)} logo"
                    class="airline-logo"
                    onerror="this.replaceWith(AirlineMilesPage._fallbackLogoEl(${JSON.stringify(prog.name).replace(/"/g, '&quot;')}))">`
            : AirlineMilesPage._fallbackLogoHtml(prog.name);

        // Person split bar: one segment per membership with a non-zero
        // latest balance, width proportional to share of the program total.
        const segments = prog.memberships
            .filter(m => (m.latest_balance || 0) > 0)
            .map(m => {
                const pct = total > 0 ? ((m.latest_balance / total) * 100) : 0;
                return `<div class="split-seg"
                    style="width:${pct.toFixed(2)}%;"
                    title="${escapeHtml(m.person_name)}: ${AirlineMilesPage._fmtPoints(m.latest_balance)}">
                    <span class="split-seg-label">${escapeHtml(m.person_name)}</span>
                </div>`;
            })
            .join('');

        const splitBarHtml = total > 0
            ? `<div class="split-bar">${segments}</div>`
            : `<div class="split-bar split-bar-empty">No balances entered yet</div>`;

        // Membership table — every (program, person) row, blanks shown as em-dashes.
        const rowsHtml = prog.memberships.map(m => `
            <tr data-membership-id="${m.id}">
                <td class="person-name">${escapeHtml(m.person_name)}</td>
                <td class="member-number">${m.member_number ? escapeHtml(m.member_number) : '<span class="muted">—</span>'}</td>
                <td class="elite-status">${m.elite_status ? escapeHtml(m.elite_status) : '<span class="muted">—</span>'}</td>
                <td class="balance">${m.latest_balance != null ? AirlineMilesPage._fmtPoints(m.latest_balance) : '<span class="muted">—</span>'}</td>
                <td class="as-of">${m.latest_as_of_date ? formatDate(m.latest_as_of_date) : '<span class="muted">—</span>'}</td>
                <td class="actions">
                    <button class="btn btn-sm btn-secondary"
                            onclick="AirlineMilesPage.openUpdate(${m.id})">
                        Update
                    </button>
                </td>
            </tr>
        `).join('');

        // Memberships missing a person from the household are rendered as
        // an "Add membership" link under the table. We compute which
        // people don't yet have a row for this program.
        const presentPersonIds = new Set(prog.memberships.map(m => m.person_id));
        const missingPeople = AirlineMilesPage._people.filter(p => !presentPersonIds.has(p.id));
        const addLinks = missingPeople.length > 0
            ? `<div class="add-membership">
                ${missingPeople.map(p =>
                    `<button class="btn btn-sm btn-link"
                             onclick="AirlineMilesPage.addMembership(${prog.id}, ${p.id}, ${JSON.stringify(p.name).replace(/"/g, '&quot;')})">
                        + Add ${escapeHtml(p.name)}
                    </button>`
                ).join(' ')}
            </div>`
            : '';

        return `
            <div class="program-card" style="--program-color: ${escapeHtml(prog.brand_color)};">
                <div class="program-card-header">
                    <div class="program-logo-wrap">${logoHtml}</div>
                    <div class="program-title">
                        <h3>${escapeHtml(prog.name)}</h3>
                        <div class="program-meta">
                            <span class="alliance-tag">${escapeHtml(prog.alliance)}</span>
                            <span class="program-total">${AirlineMilesPage._fmtPoints(total)} pts</span>
                        </div>
                    </div>
                </div>
                ${splitBarHtml}
                <table class="program-members">
                    <thead><tr>
                        <th>Person</th>
                        <th>Member #</th>
                        <th>Status</th>
                        <th class="amount">Balance</th>
                        <th>As of</th>
                        <th style="width:80px;"></th>
                    </tr></thead>
                    <tbody>${rowsHtml}</tbody>
                </table>
                ${addLinks}
            </div>
        `;
    },

    _fmtPoints(n) {
        if (n == null) return '—';
        return Number(n).toLocaleString('en-US');
    },

    _fallbackLogoHtml(name) {
        const initial = (name || '?').trim().charAt(0).toUpperCase();
        return `<div class="airline-logo airline-logo-fallback">${escapeHtml(initial)}</div>`;
    },

    _fallbackLogoEl(name) {
        // Used by <img onerror> to swap in a fallback when the file 404s.
        const div = document.createElement('div');
        div.className = 'airline-logo airline-logo-fallback';
        div.textContent = (name || '?').trim().charAt(0).toUpperCase();
        return div;
    },

    openUpdate(membershipId) {
        // Modal with three inputs: balance, as_of_date (default today),
        // optional notes. Submit POSTs to /airline-miles/snapshots
        // (upsert by membership_id + as_of_date).
        const today = todayISO();
        const html = `
            <form id="miles-update-form" onsubmit="AirlineMilesPage.saveSnapshot(event, ${membershipId})">
                <div class="form-group">
                    <label>Balance *</label>
                    <input name="balance" type="number" min="0" step="1" required autofocus>
                </div>
                <div class="form-group">
                    <label>As-of Date *</label>
                    <input name="as_of_date" type="date" required value="${today}">
                </div>
                <div class="form-group">
                    <label>Notes</label>
                    <input name="notes" type="text" maxlength="200">
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save</button>
                </div>
                <div style="font-size:10px; color:var(--text-muted); margin-top:6px;">
                    Re-entering the same date overwrites the previous balance.
                </div>
            </form>
        `;
        openModal('Update balance', html);
    },

    async saveSnapshot(e, membershipId) {
        e.preventDefault();
        const form = e.target;
        const data = Object.fromEntries(new FormData(form).entries());
        const payload = {
            membership_id: membershipId,
            as_of_date: data.as_of_date,
            balance: parseInt(data.balance, 10),
        };
        if (data.notes) payload.notes = data.notes;
        try {
            await API.post('/airline-miles/snapshots', payload);
            toast('Balance updated');
            closeModal();
            // Re-render the page so the new balance + split bar reflect immediately.
            const html = await AirlineMilesPage.render();
            document.getElementById('page-content').innerHTML = html;
        } catch (err) {
            toast(err.message || 'Save failed', 'error');
        }
    },

    async addMembership(programId, personId, personName) {
        // Single-click add — creates a placeholder membership with no
        // member# / status / balance. The user fills those in via Update.
        try {
            await API.post('/airline-miles/memberships', {
                program_id: programId,
                person_id: personId,
            });
            toast(`Added ${personName}`);
            const html = await AirlineMilesPage.render();
            document.getElementById('page-content').innerHTML = html;
        } catch (err) {
            toast(err.message || 'Add failed', 'error');
        }
    },
};
