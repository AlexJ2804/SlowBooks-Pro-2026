/**
 * Credit scores tracker — phase 1.5 task 3.
 *
 * Page layout:
 *   1. Latest scores grid: rows = parents, columns = bureaus.
 *   2. Per-parent history line chart (hand-rolled inline SVG; no
 *      chart library exists in this codebase).
 *   3. Full history table (most recent first) with delete buttons.
 *   4. Modal "Add scores" form: enters all 3 bureaus at once via
 *      POST /api/credit-scores/batch. The score_model field uses an
 *      HTML <datalist> so common values (FICO 8 / FICO 9 /
 *      VantageScore 3.0) suggest themselves while the input stays
 *      freeform.
 *
 * Theodore is excluded from the person dropdown client-side because
 * the route layer rejects him with 422 (children can't have scores
 * recorded). Doing it in both places means the user never gets the
 * 422 in the happy path while raw API callers still get the guard.
 */
const BUREAUS = ['Equifax', 'Experian', 'TransUnion'];

// One color per bureau, used in both the grid badge and the SVG chart.
// Picked for distinguishability against the off-white panel background.
const BUREAU_COLORS = {
    Equifax:    '#1f5fa8',  // blue
    Experian:   '#c2410c',  // orange
    TransUnion: '#16793b',  // green
};

const CreditScoresPage = {
    _scores: [],
    _people: [],

    async render() {
        const [scores, people] = await Promise.all([
            API.get('/credit-scores'),
            API.get('/people'),
        ]);
        CreditScoresPage._scores = scores;
        CreditScoresPage._people = people;
        const parents = people.filter(p => p.role === 'parent');

        return `
            <div class="page-header">
                <h2>Credit Scores</h2>
                <div>
                    <button class="btn btn-primary" onclick="CreditScoresPage.openAddModal()">
                        Add scores
                    </button>
                </div>
            </div>
            ${CreditScoresPage._renderLatestGrid(parents, scores)}
            ${parents.map(p => CreditScoresPage._renderHistoryChart(p, scores)).join('')}
            ${CreditScoresPage._renderHistoryTable(scores)}
        `;
    },

    // ----------------------------------------------------------------
    // Latest scores grid
    // ----------------------------------------------------------------
    _renderLatestGrid(parents, scores) {
        const latestByPersonBureau = CreditScoresPage._latestMap(scores);

        const headerCells = BUREAUS.map(b =>
            `<th><span class="bureau-tag" style="background:${BUREAU_COLORS[b]}">${b}</span></th>`
        ).join('');

        const rows = parents.map(p => {
            const cells = BUREAUS.map(b => {
                const r = latestByPersonBureau.get(`${p.id}|${b}`);
                if (!r) {
                    return `<td class="cs-cell empty"><span class="muted">—</span></td>`;
                }
                return `<td class="cs-cell">
                    <div class="cs-score">${r.score}</div>
                    <div class="cs-meta">
                        ${escapeHtml(r.score_model)} &middot; ${formatDate(r.as_of_date)}
                    </div>
                </td>`;
            }).join('');
            return `<tr><th class="cs-person">${escapeHtml(p.name)}</th>${cells}</tr>`;
        }).join('');

        return `
            <div class="dashboard-section">
                <h3>Latest scores</h3>
                <table class="cs-grid">
                    <thead><tr><th></th>${headerCells}</tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    },

    _latestMap(scores) {
        // Pick most-recent reading per (person_id, bureau) regardless of
        // score_model. If two models were recorded on the same day we
        // surface the FICO 8 row preferentially (matches what the user
        // most commonly sees quoted).
        const sorted = [...scores].sort((a, b) => {
            // Newer date first; ties broken by FICO-8 preference.
            const d = b.as_of_date.localeCompare(a.as_of_date);
            if (d !== 0) return d;
            const aFico = a.score_model === 'FICO 8' ? 0 : 1;
            const bFico = b.score_model === 'FICO 8' ? 0 : 1;
            return aFico - bFico;
        });
        const map = new Map();
        for (const r of sorted) {
            const k = `${r.person_id}|${r.bureau}`;
            if (!map.has(k)) map.set(k, r);
        }
        return map;
    },

    // ----------------------------------------------------------------
    // Per-person history chart — hand-rolled inline SVG.
    // ----------------------------------------------------------------
    _renderHistoryChart(person, scores) {
        const personScores = scores.filter(s => s.person_id === person.id);
        if (personScores.length === 0) {
            return `
                <div class="dashboard-section">
                    <h3>${escapeHtml(person.name)} — history</h3>
                    <div class="empty-state"><p>No readings yet.</p></div>
                </div>
            `;
        }

        // Group by bureau, sorted ascending by date for the polyline.
        const byBureau = {};
        for (const b of BUREAUS) byBureau[b] = [];
        for (const s of personScores) {
            if (byBureau[s.bureau]) byBureau[s.bureau].push(s);
        }
        for (const b of BUREAUS) {
            byBureau[b].sort((a, b) => a.as_of_date.localeCompare(b.as_of_date));
        }

        // Determine date range; if only one date, pad it left so the
        // polyline doesn't render as a degenerate point.
        const allDates = [...new Set(personScores.map(s => s.as_of_date))].sort();
        const minDate = new Date(allDates[0]);
        const maxDate = new Date(allDates[allDates.length - 1]);
        if (minDate.getTime() === maxDate.getTime()) {
            minDate.setDate(minDate.getDate() - 30);
        }

        // SVG geometry — fixed band 300 to 850 on Y, dates on X.
        const W = 640, H = 180;
        const PAD = { l: 40, r: 12, t: 14, b: 28 };
        const innerW = W - PAD.l - PAD.r;
        const innerH = H - PAD.t - PAD.b;
        const Y_MIN = 300, Y_MAX = 850;

        const xOf = (dStr) => {
            const t = new Date(dStr).getTime();
            const span = maxDate.getTime() - minDate.getTime();
            const f = span === 0 ? 0.5 : (t - minDate.getTime()) / span;
            return PAD.l + f * innerW;
        };
        const yOf = (score) => {
            const f = (score - Y_MIN) / (Y_MAX - Y_MIN);
            return PAD.t + (1 - f) * innerH;
        };

        // Y-axis gridlines at 600 / 700 / 800 — the bands most users care about.
        const grid = [600, 700, 800].map(y => `
            <line x1="${PAD.l}" x2="${W - PAD.r}" y1="${yOf(y)}" y2="${yOf(y)}"
                  stroke="#e5e7eb" stroke-dasharray="3 3"/>
            <text x="${PAD.l - 6}" y="${yOf(y) + 4}" text-anchor="end"
                  font-size="9" fill="#9ca3af">${y}</text>
        `).join('');

        // One polyline per bureau plus circles at each data point.
        const lines = BUREAUS.map(b => {
            const rows = byBureau[b];
            if (rows.length === 0) return '';
            const points = rows.map(r => `${xOf(r.as_of_date)},${yOf(r.score)}`).join(' ');
            const circles = rows.map(r =>
                `<circle cx="${xOf(r.as_of_date)}" cy="${yOf(r.score)}" r="3"
                         fill="${BUREAU_COLORS[b]}">
                    <title>${b} ${r.score} (${r.score_model}) on ${r.as_of_date}</title>
                </circle>`
            ).join('');
            return `<polyline points="${points}" fill="none"
                              stroke="${BUREAU_COLORS[b]}" stroke-width="2"/>${circles}`;
        }).join('');

        // Date labels: first, middle, last.
        const dateLabels = [
            { date: minDate, anchor: 'start' },
            { date: new Date((minDate.getTime() + maxDate.getTime()) / 2), anchor: 'middle' },
            { date: maxDate, anchor: 'end' },
        ];
        const dateLabelsHtml = dateLabels.map(d => {
            const x = d.anchor === 'start' ? PAD.l :
                      d.anchor === 'end'   ? W - PAD.r : PAD.l + innerW / 2;
            const label = d.date.toISOString().slice(0, 10);
            return `<text x="${x}" y="${H - 8}" text-anchor="${d.anchor}"
                          font-size="9" fill="#6b7280">${label}</text>`;
        }).join('');

        const legend = BUREAUS.map(b => `
            <span style="display:inline-flex; align-items:center; gap:4px; margin-right:12px; font-size:10px;">
                <span style="display:inline-block; width:10px; height:10px; background:${BUREAU_COLORS[b]}; border-radius:50%;"></span>
                ${b}
            </span>
        `).join('');

        return `
            <div class="dashboard-section">
                <h3>${escapeHtml(person.name)} — history</h3>
                <div style="margin-bottom:6px;">${legend}</div>
                <svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px;">
                    <rect x="${PAD.l}" y="${PAD.t}" width="${innerW}" height="${innerH}"
                          fill="#fff" stroke="#d8dce4"/>
                    ${grid}
                    ${lines}
                    ${dateLabelsHtml}
                </svg>
            </div>
        `;
    },

    // ----------------------------------------------------------------
    // Full history table
    // ----------------------------------------------------------------
    _renderHistoryTable(scores) {
        if (scores.length === 0) {
            return `
                <div class="dashboard-section">
                    <h3>All readings</h3>
                    <div class="empty-state"><p>No credit scores recorded yet.</p></div>
                </div>
            `;
        }
        // API already returns sorted DESC by as_of_date, but resort to
        // be safe against future changes there.
        const rows = [...scores].sort((a, b) =>
            b.as_of_date.localeCompare(a.as_of_date)
            || b.created_at.localeCompare(a.created_at)
        );
        const trs = rows.map(r => `
            <tr>
                <td>${formatDate(r.as_of_date)}</td>
                <td>${escapeHtml(r.person_name || '')}</td>
                <td><span class="bureau-tag" style="background:${BUREAU_COLORS[r.bureau] || '#555'}">${escapeHtml(r.bureau)}</span></td>
                <td class="amount">${r.score}</td>
                <td>${escapeHtml(r.score_model)}</td>
                <td>${escapeHtml(r.source || '')}</td>
                <td style="font-size:10px; color:var(--text-muted);">${escapeHtml(r.notes || '')}</td>
                <td class="actions">
                    <button class="btn btn-sm btn-danger"
                            onclick="CreditScoresPage.deleteScore(${r.id})">Delete</button>
                </td>
            </tr>
        `).join('');
        return `
            <div class="dashboard-section">
                <h3>All readings</h3>
                <div class="table-container">
                    <table>
                        <thead><tr>
                            <th>Date</th>
                            <th>Person</th>
                            <th>Bureau</th>
                            <th class="amount">Score</th>
                            <th>Model</th>
                            <th>Source</th>
                            <th>Notes</th>
                            <th style="width:80px;"></th>
                        </tr></thead>
                        <tbody>${trs}</tbody>
                    </table>
                </div>
            </div>
        `;
    },

    // ----------------------------------------------------------------
    // Add-scores modal
    // ----------------------------------------------------------------
    openAddModal() {
        const parents = CreditScoresPage._people.filter(p => p.role === 'parent');
        if (parents.length === 0) {
            toast('No adult parents in the household yet', 'error');
            return;
        }
        const today = todayISO();
        const personOptions = parents.map(p =>
            `<option value="${p.id}">${escapeHtml(p.name)}</option>`
        ).join('');

        // One row per bureau. The model field is shared via a single
        // <datalist> below; users typically enter the same model for
        // all 3 bureaus on a given pull.
        const bureauRows = BUREAUS.map(b => `
            <tr>
                <td>
                    <span class="bureau-tag" style="background:${BUREAU_COLORS[b]}">${b}</span>
                </td>
                <td><input name="score_${b}" type="number" min="300" max="850"
                           inputmode="numeric" placeholder="—"></td>
                <td><input name="model_${b}" type="text" list="cs-model-list"
                           value="FICO 8" maxlength="64"></td>
            </tr>
        `).join('');

        const html = `
            <form id="cs-add-form" onsubmit="CreditScoresPage.saveBatch(event)">
                <div class="form-group">
                    <label>Person *</label>
                    <select name="person_id" required>${personOptions}</select>
                </div>
                <div class="form-group">
                    <label>As-of date *</label>
                    <input name="as_of_date" type="date" required value="${today}">
                </div>
                <div class="form-group">
                    <label>Source</label>
                    <input name="source" type="text" maxlength="128"
                           placeholder="e.g. Credit Karma, Experian.com">
                </div>
                <table class="cs-batch-table">
                    <thead><tr><th>Bureau</th><th>Score</th><th>Model</th></tr></thead>
                    <tbody>${bureauRows}</tbody>
                </table>
                <div class="form-group">
                    <label>Notes</label>
                    <input name="notes" type="text" maxlength="500">
                </div>
                <datalist id="cs-model-list">
                    <option value="FICO 8">
                    <option value="FICO 9">
                    <option value="VantageScore 3.0">
                    <option value="VantageScore 4.0">
                </datalist>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save</button>
                </div>
                <div style="font-size:10px; color:var(--text-muted); margin-top:6px;">
                    Empty score rows are skipped. Re-entering the same
                    bureau / model / date overwrites the previous reading.
                </div>
            </form>
        `;
        openModal('Add credit scores', html);
    },

    async saveBatch(e) {
        e.preventDefault();
        const form = e.target;
        const data = Object.fromEntries(new FormData(form).entries());
        const entries = [];
        for (const b of BUREAUS) {
            const raw = data[`score_${b}`];
            if (!raw) continue;  // skip empty rows
            const score = parseInt(raw, 10);
            if (Number.isNaN(score)) continue;
            entries.push({
                bureau: b,
                score,
                score_model: (data[`model_${b}`] || 'FICO 8').trim() || 'FICO 8',
            });
        }
        if (entries.length === 0) {
            toast('Enter at least one score', 'error');
            return;
        }
        const payload = {
            person_id: parseInt(data.person_id, 10),
            as_of_date: data.as_of_date,
            entries,
        };
        if (data.source) payload.source = data.source;
        if (data.notes) payload.notes = data.notes;
        try {
            await API.post('/credit-scores/batch', payload);
            toast(`Saved ${entries.length} score${entries.length === 1 ? '' : 's'}`);
            closeModal();
            const html = await CreditScoresPage.render();
            document.getElementById('page-content').innerHTML = html;
        } catch (err) {
            toast(err.message || 'Save failed', 'error');
        }
    },

    async deleteScore(id) {
        if (!confirm('Delete this credit score reading?')) return;
        try {
            await API.del(`/credit-scores/${id}`);
            toast('Reading deleted');
            const html = await CreditScoresPage.render();
            document.getElementById('page-content').innerHTML = html;
        } catch (err) {
            toast(err.message || 'Delete failed', 'error');
        }
    },
};
