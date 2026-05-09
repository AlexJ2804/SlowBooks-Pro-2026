/**
 * Airline Miles — household loyalty-programme tracker.
 *
 * Design: "Cabin Pass" (boarding-pass card geometry — perforated stub + body
 * with monospace member numbers — rendered in the Cabin palette: cool light
 * gray shell, white cards, navy ink, per-airline accent tint on each stub).
 *
 * Visual marks here are the airlines' real logos served from
 * /static/airline_logos/. Brand colours come from each programme's published
 * palette and only appear as a soft tint on the stub plus a uppercase mono
 * "AIRLINE NAME" label.
 */
const AirlineMilesPage = {
    PEOPLE: [
        { id: 'alex',     name: 'Alex',     role: 'Primary' },
        { id: 'alexa',    name: 'Alexa',    role: 'Spouse'  },
        { id: 'theodore', name: 'Theodore', role: 'Child'   },
    ],

    PROGRAMS: [
        {
            id: 'aa',
            airline: 'American Airlines',
            program: 'AAdvantage',
            logo: '/static/airline_logos/aadvantage.jpeg',
            accent: '#c8102e',
            accentSoft: '#FBE5E8',
            balances: {
                alex:     { member: '1TU70K8',  balance: 18730, asOf: 'May 8, 2026' },
                alexa:    { member: null,       balance: null,  asOf: null },
                theodore: { member: null,       balance: null,  asOf: null },
            },
        },
        {
            id: 'dl',
            airline: 'Delta Air Lines',
            program: 'SkyMiles',
            logo: '/static/airline_logos/skymiles.png',
            accent: '#003366',
            accentSoft: '#DDE5EE',
            balances: {
                alex:     { member: '9283122365', balance: 57670, asOf: 'May 8, 2026' },
                alexa:    { member: null,         balance: null,  asOf: null },
                theodore: { member: null,         balance: null,  asOf: null },
            },
        },
        {
            id: 'ua',
            airline: 'United Airlines',
            program: 'MileagePlus',
            logo: '/static/airline_logos/mileageplus.png',
            accent: '#002244',
            accentSoft: '#DCE2EC',
            balances: {
                alex:     { member: 'UF461456', balance: 10304, asOf: 'May 8, 2026' },
                alexa:    { member: null,       balance: null,  asOf: null },
                theodore: { member: null,       balance: null,  asOf: null },
            },
        },
        {
            id: 'ei',
            airline: 'Aer Lingus',
            program: 'AerClub',
            logo: '/static/airline_logos/aerclub.jpg',
            accent: '#00754a',
            accentSoft: '#DCEBE2',
            balances: {
                alex:     { member: 'alexj2804', balance: 5446, asOf: 'May 8, 2026' },
                alexa:    { member: null,        balance: null, asOf: null },
                theodore: { member: null,        balance: null, asOf: null },
            },
        },
        {
            id: 'ac',
            airline: 'Air Canada',
            program: 'Aeroplan',
            logo: '/static/airline_logos/aeroplan.png',
            accent: '#d22630',
            accentSoft: '#FBE2E4',
            balances: {
                alex:     { member: '370845117', balance: 4, asOf: 'May 8, 2026' },
                alexa:    { member: null,        balance: null, asOf: null },
                theodore: { member: null,        balance: null, asOf: null },
            },
        },
    ],

    state: { view: 'program' },

    fmt(n) { return n == null ? '&mdash;' : n.toLocaleString('en-US'); },

    setView(view) {
        AirlineMilesPage.state.view = view;
        const root = document.getElementById('hx-root');
        if (root) root.outerHTML = AirlineMilesPage.shell();
    },

    programCard(p) {
        const total = Object.values(p.balances).reduce((s, b) => s + (b.balance || 0), 0);
        const rows = AirlineMilesPage.PEOPLE.map(person => {
            const b = p.balances[person.id];
            const empty = b.balance == null;
            return `
                <div class="hx-row">
                    <span class="who">${escapeHtml(person.name)}<small>${escapeHtml(person.role)}</small></span>
                    <span class="num">${b.member ? escapeHtml(b.member) : '&mdash;'}</span>
                    <span class="bal${empty ? ' empty' : ''}">${AirlineMilesPage.fmt(b.balance)}</span>
                    <button type="button">Update</button>
                </div>`;
        }).join('');

        return `
            <article class="hx-card" style="--accent:${p.accent};--accentSoft:${p.accentSoft};">
                <span class="hx-notch-top"></span>
                <span class="hx-notch-bot"></span>
                <div class="hx-stub">
                    <div class="hx-logo">
                        <img src="${p.logo}" alt="${escapeHtml(p.airline)} ${escapeHtml(p.program)}">
                    </div>
                    <div>
                        <div class="airline">${escapeHtml(p.airline)}</div>
                        <div class="program">${escapeHtml(p.program)}</div>
                    </div>
                    <div class="meta">
                        <div class="lbl">Programme balance</div>
                        <div class="val">${AirlineMilesPage.fmt(total)}<span>PTS</span></div>
                    </div>
                </div>
                <div class="hx-body">${rows}</div>
            </article>`;
    },

    personCard(person) {
        const total = AirlineMilesPage.PROGRAMS.reduce(
            (s, p) => s + (p.balances[person.id].balance || 0), 0
        );
        const programsWith    = AirlineMilesPage.PROGRAMS.filter(p => p.balances[person.id].balance != null);
        const programsWithout = AirlineMilesPage.PROGRAMS.filter(p => p.balances[person.id].balance == null);
        const ordered = [...programsWith, ...programsWithout];

        const rows = ordered.map(p => {
            const b = p.balances[person.id];
            const empty = b.balance == null;
            return `
                <div class="hx-prow">
                    <div class="pmono"><img src="${p.logo}" alt=""></div>
                    <div class="pname">${escapeHtml(p.program)}<small>${escapeHtml(p.airline)}</small></div>
                    <div class="pmember">${b.member ? escapeHtml(b.member) : '&mdash;'}</div>
                    <div class="pbal${empty ? ' empty' : ''}">${AirlineMilesPage.fmt(b.balance)}</div>
                    <button type="button">Update</button>
                </div>`;
        }).join('');

        return `
            <article class="hx-pcard">
                <div class="hx-pstub">
                    <div>
                        <div class="role">${escapeHtml(person.role)}</div>
                        <div class="name">${escapeHtml(person.name)}</div>
                    </div>
                    <div class="meta">
                        <div class="lbl">Total across programmes</div>
                        <div class="val">${AirlineMilesPage.fmt(total)}<span>PTS</span></div>
                    </div>
                </div>
                <div class="hx-pbody">${rows}</div>
            </article>`;
    },

    shell() {
        const view = AirlineMilesPage.state.view;
        const cards = view === 'program'
            ? AirlineMilesPage.PROGRAMS.map(AirlineMilesPage.programCard).join('')
            : AirlineMilesPage.PEOPLE.map(AirlineMilesPage.personCard).join('');
        const gridStyle = view === 'person' ? 'grid-template-columns:1fr;' : '';

        return `
            <div id="hx-root" class="hx-page">
                <header class="hx-head">
                    <div class="crumb">Travel &middot; Loyalty</div>
                    <h1>Airline Miles</h1>
                    <div class="sub">${AirlineMilesPage.PROGRAMS.length} programmes &middot; ${AirlineMilesPage.PEOPLE.length} members</div>
                </header>
                <div class="hx-segs">
                    <button type="button" class="hx-pill${view === 'program' ? ' on' : ''}"
                        onclick="AirlineMilesPage.setView('program')">By programme</button>
                    <button type="button" class="hx-pill${view === 'person' ? ' on' : ''}"
                        onclick="AirlineMilesPage.setView('person')">By person</button>
                    <button type="button" class="hx-pill" style="margin-left:auto;">Sort: Balance &darr;</button>
                    <button type="button" class="hx-pill">+ Add programme</button>
                </div>
                <div class="hx-grid" style="${gridStyle}">${cards}</div>
            </div>`;
    },

    render() {
        return AirlineMilesPage.styles() + AirlineMilesPage.shell();
    },

    styles() {
        // Scoped under .hx-page so the design fonts and palette don't leak into
        // the rest of the QB2003 chrome. Inter Tight + JetBrains Mono come from
        // the existing Google Fonts CDN connection (Tahoma already loaded once).
        return `
            <style id="hx-styles">
            @import url('https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

            /* Let the cabin shell fill #content edge-to-edge — the rest of the
             * app keeps its 1100px reading width. */
            #page-content:has(.hx-page) { max-width: none; }

            .hx-page {
                --hx-bg: #F4F5F7;
                --hx-card: #FFFFFF;
                --hx-ink: #0E1726;
                --hx-ink2: #5A6478;
                --hx-ink3: #8A93A6;
                --hx-rule: #E6E9EF;
                --hx-rule-soft: #EEF0F4;

                background: var(--hx-bg);
                color: var(--hx-ink);
                font-family: 'Inter Tight', system-ui, -apple-system, sans-serif;
                font-size: 14px;
                /* Neutralise #content's 16px/20px padding so the cabin shell
                 * bleeds edge-to-edge inside the QB2003 chrome. */
                margin: -16px -20px;
                min-height: calc(100% + 32px);
                -webkit-font-smoothing: antialiased;
            }

            .hx-page * { box-sizing: border-box; }
            .hx-page button { font-family: inherit; }

            .hx-head { padding: 26px 32px 18px; }
            .hx-head .crumb { font-size: 12px; letter-spacing: 0.04em; color: var(--hx-ink3); text-transform: uppercase; }
            .hx-head h1 { margin: 4px 0 0; font-size: 32px; font-weight: 600; letter-spacing: -0.02em; color: var(--hx-ink); }
            .hx-head .sub { font-size: 13px; color: var(--hx-ink2); margin-top: 4px; }

            .hx-segs { display: flex; gap: 8px; padding: 0 32px 16px; align-items: center; flex-wrap: wrap; }
            .hx-pill {
                padding: 6px 14px;
                border: 1px solid var(--hx-rule);
                border-radius: 999px;
                background: var(--hx-card);
                color: var(--hx-ink2);
                font-size: 12.5px;
                cursor: pointer;
                transition: border-color .12s, color .12s, background .12s;
            }
            .hx-pill:hover { border-color: var(--hx-ink); color: var(--hx-ink); }
            .hx-pill.on { background: var(--hx-ink); color: var(--hx-card); border-color: var(--hx-ink); font-weight: 500; }
            .hx-pill.on:hover { color: var(--hx-card); }

            .hx-grid {
                padding: 0 32px 32px;
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 18px;
                align-content: start;
            }
            @media (max-width: 1100px) {
                .hx-grid { grid-template-columns: 1fr; }
            }

            /* === Per-programme card: boarding-pass stub + body === */
            .hx-card {
                background: var(--hx-card);
                border: 1px solid var(--hx-rule);
                border-radius: 14px;
                display: grid;
                grid-template-columns: 184px 1fr;
                min-height: 220px;
                position: relative;
                overflow: hidden;
                box-shadow: 0 1px 2px rgba(15, 23, 38, 0.04);
            }
            .hx-stub {
                background: var(--accentSoft);
                padding: 18px 16px 16px;
                display: flex;
                flex-direction: column;
                gap: 12px;
                position: relative;
            }
            /* perforation between stub and body */
            .hx-stub::before {
                content: "";
                position: absolute;
                right: -5px;
                top: 16px;
                bottom: 16px;
                width: 10px;
                border-left: 1px dashed color-mix(in oklab, var(--accent) 35%, var(--hx-rule));
            }
            /* notches at top and bottom of perforation, reading as the page bg */
            .hx-card .hx-notch-top,
            .hx-card .hx-notch-bot {
                position: absolute;
                left: 179px;
                width: 14px;
                height: 14px;
                border-radius: 50%;
                background: var(--hx-bg);
            }
            .hx-card .hx-notch-top { top: -7px; }
            .hx-card .hx-notch-bot { bottom: -7px; }

            .hx-logo {
                width: 56px;
                height: 56px;
                border-radius: 12px;
                background: var(--hx-card);
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 6px;
                box-shadow: 0 2px 8px rgba(15, 23, 38, 0.10), inset 0 0 0 1px rgba(15, 23, 38, 0.04);
            }
            .hx-logo img { max-width: 100%; max-height: 100%; object-fit: contain; }

            .hx-stub .airline {
                font-family: 'JetBrains Mono', ui-monospace, monospace;
                font-size: 10px;
                letter-spacing: 0.18em;
                color: var(--accent);
                text-transform: uppercase;
                font-weight: 600;
            }
            .hx-stub .program {
                font-size: 19px;
                font-weight: 600;
                letter-spacing: -0.01em;
                line-height: 1.15;
                color: var(--hx-ink);
                margin-top: 2px;
            }

            .hx-stub .meta { margin-top: auto; }
            .hx-stub .meta .lbl {
                font-family: 'JetBrains Mono', ui-monospace, monospace;
                font-size: 10px;
                letter-spacing: 0.18em;
                color: var(--hx-ink2);
                text-transform: uppercase;
            }
            .hx-stub .meta .val {
                font-family: 'JetBrains Mono', ui-monospace, monospace;
                font-size: 22px;
                font-weight: 600;
                color: var(--hx-ink);
                letter-spacing: -0.01em;
                margin-top: 1px;
            }
            .hx-stub .meta .val span {
                font-family: 'JetBrains Mono', ui-monospace, monospace;
                font-size: 10px;
                letter-spacing: 0.16em;
                color: var(--hx-ink2);
                margin-left: 5px;
                font-weight: 500;
            }

            /* Body (per-person rows) */
            .hx-body { padding: 14px 18px; display: flex; flex-direction: column; }
            .hx-row {
                display: grid;
                grid-template-columns: 80px 1fr 100px 80px;
                gap: 12px;
                align-items: center;
                padding: 11px 0;
                border-top: 1px dotted var(--hx-rule);
                font-size: 13.5px;
            }
            .hx-row:first-child { border-top: none; padding-top: 4px; }
            .hx-row .who { font-weight: 500; color: var(--hx-ink); }
            .hx-row .who small {
                display: block;
                font-size: 11px;
                color: var(--hx-ink3);
                font-weight: 400;
                margin-top: 1px;
            }
            .hx-row .num {
                font-family: 'JetBrains Mono', ui-monospace, monospace;
                font-size: 11.5px;
                color: var(--hx-ink2);
                letter-spacing: 0.02em;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .hx-row .bal {
                font-family: 'JetBrains Mono', ui-monospace, monospace;
                font-weight: 600;
                text-align: right;
                font-size: 14px;
                color: var(--hx-ink);
            }
            .hx-row .bal.empty { color: var(--hx-ink3); font-weight: 400; }
            .hx-row button {
                font-size: 11.5px;
                font-weight: 500;
                padding: 6px 10px;
                border: 1px solid var(--hx-rule);
                border-radius: 7px;
                background: var(--hx-card);
                color: var(--hx-ink2);
                cursor: pointer;
                transition: border-color .12s, color .12s;
            }
            .hx-row button:hover { border-color: var(--hx-ink); color: var(--hx-ink); }

            /* === Per-person card === */
            .hx-pcard {
                background: var(--hx-card);
                border: 1px solid var(--hx-rule);
                border-radius: 14px;
                display: grid;
                grid-template-columns: 220px 1fr;
                overflow: hidden;
                box-shadow: 0 1px 2px rgba(15, 23, 38, 0.04);
                position: relative;
            }
            .hx-pstub {
                background: linear-gradient(160deg, #EAF1FB, #F4F5F7);
                padding: 22px 20px;
                display: flex;
                flex-direction: column;
                gap: 10px;
                position: relative;
            }
            .hx-pstub::before {
                content: "";
                position: absolute;
                right: -5px;
                top: 16px;
                bottom: 16px;
                width: 10px;
                border-left: 1px dashed var(--hx-rule);
            }
            .hx-pstub .name { font-size: 26px; font-weight: 600; letter-spacing: -0.02em; color: var(--hx-ink); }
            .hx-pstub .role {
                font-family: 'JetBrains Mono', ui-monospace, monospace;
                font-size: 10px;
                letter-spacing: 0.2em;
                color: var(--hx-ink2);
                text-transform: uppercase;
            }
            .hx-pstub .meta { margin-top: auto; }
            .hx-pstub .meta .lbl {
                font-family: 'JetBrains Mono', ui-monospace, monospace;
                font-size: 10px;
                letter-spacing: 0.18em;
                color: var(--hx-ink2);
                text-transform: uppercase;
            }
            .hx-pstub .meta .val {
                font-family: 'JetBrains Mono', ui-monospace, monospace;
                font-size: 22px;
                font-weight: 600;
                color: var(--hx-ink);
                letter-spacing: -0.01em;
                margin-top: 2px;
            }
            .hx-pstub .meta .val span {
                font-family: 'JetBrains Mono', ui-monospace, monospace;
                font-size: 10px;
                color: var(--hx-ink2);
                margin-left: 5px;
                letter-spacing: 0.16em;
                font-weight: 500;
            }

            .hx-pbody { padding: 12px 18px; }
            .hx-prow {
                display: grid;
                grid-template-columns: 36px 1fr 110px 110px 80px;
                gap: 12px;
                align-items: center;
                padding: 11px 0;
                border-top: 1px dotted var(--hx-rule);
            }
            .hx-prow:first-child { border-top: none; }
            .hx-prow .pmono {
                width: 30px;
                height: 30px;
                border-radius: 7px;
                background: var(--hx-card);
                padding: 3px;
                display: flex;
                align-items: center;
                justify-content: center;
                box-shadow: inset 0 0 0 1px var(--hx-rule);
            }
            .hx-prow .pmono img { max-width: 100%; max-height: 100%; object-fit: contain; }
            .hx-prow .pname { font-size: 13.5px; font-weight: 500; color: var(--hx-ink); }
            .hx-prow .pname small {
                display: block;
                font-family: 'JetBrains Mono', ui-monospace, monospace;
                font-size: 10px;
                letter-spacing: 0.12em;
                color: var(--hx-ink3);
                font-weight: 400;
                text-transform: uppercase;
                margin-top: 1px;
            }
            .hx-prow .pmember {
                font-family: 'JetBrains Mono', ui-monospace, monospace;
                font-size: 11.5px;
                color: var(--hx-ink2);
            }
            .hx-prow .pbal {
                font-family: 'JetBrains Mono', ui-monospace, monospace;
                font-weight: 600;
                text-align: right;
                font-size: 14px;
                color: var(--hx-ink);
            }
            .hx-prow .pbal.empty { color: var(--hx-ink3); font-weight: 400; }
            .hx-prow button {
                font-size: 11.5px;
                font-weight: 500;
                padding: 6px 10px;
                border: 1px solid var(--hx-rule);
                border-radius: 7px;
                background: var(--hx-card);
                color: var(--hx-ink2);
                cursor: pointer;
                transition: border-color .12s, color .12s;
            }
            .hx-prow button:hover { border-color: var(--hx-ink); color: var(--hx-ink); }

            /* Dark-mode parity — keep the cabin palette but invert ink/bg so it
             * doesn't fight the existing dark theme. */
            [data-theme="dark"] .hx-page {
                --hx-bg: #14161c;
                --hx-card: #1e2028;
                --hx-ink: #e0e4ec;
                --hx-ink2: #a0a8b8;
                --hx-ink3: #7a8498;
                --hx-rule: #2e3240;
                --hx-rule-soft: #242830;
            }
            [data-theme="dark"] .hx-pstub {
                background: linear-gradient(160deg, #1e2838, #14161c);
            }
            [data-theme="dark"] .hx-stub { background: color-mix(in oklab, var(--accent) 22%, var(--hx-card)); }
            </style>`;
    },
};
