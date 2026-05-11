/**
 * Credit scores tracker — phase 1.5 task 3 (Cabin Pass design).
 *
 * Page sections (top to bottom):
 *   1. Header (.sb-head) with the "+ Add scores" pill in .sb-segs.
 *   2. Latest-scores grid: rows = parents, cols = bureaus. Each cell shows
 *      a big mono score with the model + as-of date underneath.
 *   3. Per-parent history line chart — hand-rolled inline SVG, one polyline
 *      per bureau, fixed Y-band 300..850 with gridlines at 600/700/800.
 *   4. Full history table (.table-container picks up the cabin .sb-table
 *      styling automatically).
 *   5. Modal "Add scores" form — POSTs all three bureaus in one
 *      /api/credit-scores/batch call. Score model uses an HTML <datalist>
 *      so common values (FICO 8 / FICO 9 / VantageScore 3.0 / 4.0)
 *      suggest themselves while the input stays freeform.
 *
 * Backend untouched: /api/credit-scores rejects non-parent person_id with
 * 422; the parent dropdown filters Theodore out client-side so the happy
 * path doesn't hit that error.
 */
const BUREAUS = ['Equifax', 'Experian', 'TransUnion'];

// One color per bureau, used as a small dot in the header cells and as
// the polyline color in the history chart. Picked for distinguishability
// against the cabin off-white panel background.
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
            <header class="sb-head">
                <div class="sb-crumb">Household &middot; Credit</div>
                <h1>Credit Scores</h1>
                <div class="sb-sub">
                    ${parents.length} parent${parents.length === 1 ? '' : 's'}
                    &middot;
                    ${scores.length} reading${scores.length === 1 ? '' : 's'}
                </div>
            </header>
            <div class="sb-segs">
                <span class="sb-grow"></span>
                <button type="button" class="sb-pill primary"
                        onclick="CreditScoresPage.openAddModal()">+ Add scores</button>
            </div>
            <div class="sb-section">
                ${CreditScoresPage._renderLatestGrid(parents, scores)}
            </div>
            ${parents.map(p => `
                <div class="sb-section">
                    ${CreditScoresPage._renderHistoryChart(p, scores)}
                </div>`).join('')}
            <div class="sb-section">
                ${CreditScoresPage._renderHistoryTable(scores)}
            </div>
        `;
    },

    // ----------------------------------------------------------------
    // Latest scores grid
    // ----------------------------------------------------------------
    _renderLatestGrid(parents, scores) {
        if (parents.length === 0) {
            return `<div class="empty-state"><p>No parents in the household yet.</p></div>`;
        }
        const latestByPersonBureau = CreditScoresPage._latestMap(scores);

        const headerCells = BUREAUS.map(b => `
            <th>
                <span class="cs-bureau-dot" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${BUREAU_COLORS[b]}; margin-right:6px;"></span>${b}
            </th>
        `).join('');

        const rows = parents.map(p => {
            const cells = BUREAUS.map(b => {
                const r = latestByPersonBureau.get(`${p.id}|${b}`);
                if (!r) {
                    return `<td style="text-align:center; color:var(--ink-3); font-style:italic;">&mdash;</td>`;
                }
                return `<td>
                    <div style="font-size:24px; font-weight:600; font-family:var(--font-mono-ds); color:var(--ink); line-height:1.05;">${r.score}</div>
                    <div style="font-size:10px; color:var(--ink-3); font-family:var(--font-mono-ds); letter-spacing:0.04em; margin-top:3px;">
                        ${escapeHtml(r.score_model)} &middot; ${formatDate(r.as_of_date)}
                    </div>
                </td>`;
            }).join('');
            return `<tr><th style="text-align:left; font-weight:600; color:var(--ink); font-size:14px;">${escapeHtml(p.name)}</th>${cells}</tr>`;
        }).join('');

        return `
            <h2 style="font-size:14px; font-weight:600; margin:0 0 12px;">Latest scores</h2>
            <div class="table-container">
                <table>
                    <thead><tr><th></th>${headerCells}</tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    },

    _latestMap(scores) {
        // Pick the most-recent reading per (person_id, bureau) regardless
        // of score model. If two models were recorded the same day we
        // surface the FICO 8 row preferentially since that's what most
        // lenders quote. Sorted in two passes so the second-tier sort
        // (model preference) only kicks in when dates tie.
        const sorted = [...scores].sort((a, b) => {
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
    // Per-parent history chart — hand-rolled inline SVG.
    // ----------------------------------------------------------------
    _renderHistoryChart(person, scores) {
        const personScores = scores.filter(s => s.person_id === person.id);
        if (personScores.length === 0) {
            return `
                <h2 style="font-size:14px; font-weight:600; margin:0 0 8px;">${escapeHtml(person.name)} &mdash; history</h2>
                <div class="empty-state"><p>No readings yet.</p></div>
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

        // Date range — pad left if there's only one reading so the
        // polyline doesn't render as a degenerate point.
        const allDates = [...new Set(personScores.map(s => s.as_of_date))].sort();
        const minDate = new Date(allDates[0]);
        const maxDate = new Date(allDates[allDates.length - 1]);
        if (minDate.getTime() === maxDate.getTime()) {
            minDate.setDate(minDate.getDate() - 30);
        }

        // SVG geometry — fixed band 300..850 on Y, dates on X.
        const W = 720, H = 200;
        const PAD = { l: 44, r: 14, t: 14, b: 28 };
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
                  stroke="var(--rule)" stroke-dasharray="3 3"/>
            <text x="${PAD.l - 6}" y="${yOf(y) + 4}" text-anchor="end"
                  font-size="9" fill="var(--ink-3)" font-family="var(--font-mono-ds)">${y}</text>
        `).join('');

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
                          font-size="9" fill="var(--ink-3)" font-family="var(--font-mono-ds)">${label}</text>`;
        }).join('');

        const legend = BUREAUS.map(b => `
            <span style="display:inline-flex; align-items:center; gap:6px; margin-right:14px; font-size:11px; color:var(--ink-2);">
                <span style="display:inline-block; width:10px; height:10px; background:${BUREAU_COLORS[b]}; border-radius:50%;"></span>
                ${b}
            </span>
        `).join('');

        return `
            <h2 style="font-size:14px; font-weight:600; margin:0 0 8px;">${escapeHtml(person.name)} &mdash; history</h2>
            <div style="margin-bottom:8px;">${legend}</div>
            <svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px; background:var(--card); border:1px solid var(--rule); border-radius:var(--radius-card);">
                ${grid}
                ${lines}
                ${dateLabelsHtml}
            </svg>
        `;
    },

    // ----------------------------------------------------------------
    // Full history table — picks up the cabin .sb-table look via
    // .table-container in components.css.
    // ----------------------------------------------------------------
    _renderHistoryTable(scores) {
        if (scores.length === 0) {
            return `
                <h2 style="font-size:14px; font-weight:600; margin:0 0 8px;">All readings</h2>
                <div class="empty-state"><p>No credit scores recorded yet.</p></div>
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
                <td>
                    <span style="display:inline-flex; align-items:center; gap:6px;">
                        <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${BUREAU_COLORS[r.bureau] || '#555'};"></span>
                        ${escapeHtml(r.bureau)}
                    </span>
                </td>
                <td class="amount" style="font-family:var(--font-mono-ds); font-weight:600;">${r.score}</td>
                <td>${escapeHtml(r.score_model)}</td>
                <td>${escapeHtml(r.source || '')}</td>
                <td style="font-size:11px; color:var(--ink-3);">${escapeHtml(r.notes || '')}</td>
                <td class="actions">
                    <button class="btn btn-sm btn-danger"
                            onclick="CreditScoresPage.deleteScore(${r.id})">Delete</button>
                </td>
            </tr>
        `).join('');
        return `
            <h2 style="font-size:14px; font-weight:600; margin:0 0 8px;">All readings</h2>
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

        // One row per bureau, model field shared via a single <datalist>
        // since users typically enter the same model for all 3 bureaus on
        // a given pull.
        const bureauRows = BUREAUS.map(b => `
            <tr>
                <td style="padding:6px 8px;">
                    <span style="display:inline-flex; align-items:center; gap:6px; font-size:12px;">
                        <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${BUREAU_COLORS[b]};"></span>
                        ${b}
                    </span>
                </td>
                <td style="padding:6px 8px;">
                    <input name="score_${b}" type="number" min="300" max="850"
                           inputmode="numeric" placeholder="&mdash;" style="width:90px;">
                </td>
                <td style="padding:6px 8px;">
                    <input name="model_${b}" type="text" list="cs-model-list"
                           value="FICO 8" maxlength="64" style="width:100%; box-sizing:border-box;">
                </td>
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
                <table style="width:100%; margin:8px 0; border-collapse:collapse;">
                    <thead>
                        <tr>
                            <th style="text-align:left; font-size:10px; text-transform:uppercase; letter-spacing:0.04em; color:var(--ink-3); padding:4px 8px; border-bottom:1px solid var(--rule);">Bureau</th>
                            <th style="text-align:left; font-size:10px; text-transform:uppercase; letter-spacing:0.04em; color:var(--ink-3); padding:4px 8px; border-bottom:1px solid var(--rule);">Score</th>
                            <th style="text-align:left; font-size:10px; text-transform:uppercase; letter-spacing:0.04em; color:var(--ink-3); padding:4px 8px; border-bottom:1px solid var(--rule);">Model</th>
                        </tr>
                    </thead>
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
                <div style="font-size:10px; color:var(--ink-3); margin-top:6px;">
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
            if (!raw) continue;
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
