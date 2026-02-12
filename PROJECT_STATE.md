# 📊 Dolomite veDOLO + oDOLO Dashboard — PROJECT STATE

> **Live URL**: https://twojekrypto.github.io/vedolo-dashboard/
> **Repo**: https://github.com/twojekrypto/vedolo-dashboard.git (branch: `main`)
> **Hosting**: GitHub Pages (auto-deploy on push to `main`)
> **Last updated**: 2026-02-12

---

## 🏗️ Architecture

Single-page app in one HTML file (`index_draft.html`) with **two tabs** — veDOLO Holders and oDOLO Stats. All CSS, HTML, and JS are inline. No frameworks, no bundler.

### File Structure
```
vedolo-dashboard/
├── index_draft.html          ← MAIN SOURCE (edit this)
├── index.html                ← PRODUCTION (copy of draft, deployed)
├── vedolo_holders.json       ← veDOLO holder data
├── vedolo_holders.csv        ← CSV version
├── exercisers_by_address.json ← oDOLO exerciser data
├── exercised_volume_results.json ← oDOLO transaction history
├── avg_lock_data.json        ← Lock duration averages
├── exercised_usd.json        ← USD volume summary
├── dolomite-logo.svg         ← Main logo
├── vedolo-logo.svg           ← veDOLO tab icon
├── odolo-logo-official.svg   ← oDOLO tab icon
├── update_data.py            ← Data refresh script
├── generate_exercisers.py    ← Exerciser data generator
├── calculate_avg_lock.py     ← Avg lock calculator
├── calculate_exercised_usd.py ← USD calc
└── update_exercised_usd.py   ← USD volume updater
```

### Deploy Workflow
```bash
cp index_draft.html index.html
git add index.html
git commit -m "description"
git push origin main
```
GitHub Pages auto-deploys. **Always edit `index_draft.html`**, then copy to `index.html`.

---

## 🎨 Design System — Dolomite-Inspired

### CSS Variables (Design Tokens)
```css
/* Backgrounds */
--bg-base: #090910         /* Page background */
--bg-surface: #111119      /* Surface/elevated */
--bg-card: #15151f         /* Card backgrounds */
--bg-card-alt: #1a1a26     /* Alternate cards */
--bg-hover: #1e1e2c        /* Hover state */

/* Borders */
--border-subtle: rgba(255, 255, 255, 0.06)
--border-default: rgba(255, 255, 255, 0.08)

/* Text */
--text-primary: #f0f0f6    /* White — headings, important data */
--text-secondary: #8b8fa3  /* Gray — default table data, body text */
--text-muted: #555770      /* Dim — labels, captions */

/* Accents */
--accent-indigo: #6366f1   /* Buttons, active states */
--accent-cyan: #22d3ee     /* Links, Tx hashes */
--accent-green: #34d399    /* Price/veDOLO, positive values */
--accent-amber: #fbbf24    /* Warnings, DOLO locked values, whale badges */
--accent-orange: #fb923c   /* oDOLO specific */
--accent-rose: #fb7185     /* Negative, burned */
```

### Color Rules for Data
| Element | Color | CSS |
|---|---|---|
| Table data (default) | Gray | `var(--text-secondary)` / `#8b8fa3` |
| Total/summary rows | White | `#fff` (inline style on each `td`) |
| Price/veDOLO | Green | `#34d399` |
| Tx links | Cyan | `var(--accent-cyan)` via `.tx-link` class |
| USDC.e Spent | Orange | `#f59e0b` via `.orange` class |
| Exercises, Avg Lock | White | `#fff` (inline style) |
| DOLO Locked | Amber/Orange | `var(--accent-amber)` |

### Typography
- **Inter** — primary (`300-800` weights)
- **JetBrains Mono** — monospace (addresses, numbers, tx hashes)

### Important CSS Specificity Notes
- `.detail-table td { color: var(--text-secondary) }` applies to ALL td cells
- To override, use **inline `style="color:#fff"`** on each `<td>` (not on `<tr>`)
- `<tr>` color gets overridden by `td` selector specificity

---

## 📐 File Layout (Line Ranges in index_draft.html)

### CSS Sections (~lines 12-2140)
| Section | Lines | Description |
|---|---|---|
| Design Tokens | 12-51 | CSS variables |
| Reset | 53-70 | Box-sizing, body |
| Header | 79-262 | Logo, nav tabs, actions |
| Metric Strip | 278-416 | Top stats grid |
| Tooltips | 417-492 | Metric hover tooltips |
| Analytics Grid | 493-684 | Charts layout, donut, bars |
| Table Section | 685-1078 | Main data table, search, pagination |
| Profile Modal | 1138-1455 | veDOLO holder detail modal |
| Exercise History Table | 822-855 | `.detail-table` styles |
| Whale Rows | 1482-1530 | Top 10 gradient backgrounds |
| Expiry Timeline | 1596-1615 | Canvas chart styles |
| Responsive | 1746-1870 | Media queries (768px, 480px) |
| oDOLO Styles | 1888-2139 | oDOLO-specific components |
| Animations | 2140-2165 | fadeUp keyframes |

### HTML Sections (~lines 2167-2740)
| Section | Description |
|---|---|
| Header | Logo + tab navigation (veDOLO / oDOLO) |
| veDOLO view | Metrics + analytics grid + expiry chart + table |
| oDOLO view | Metrics + flow diagram + charts + exerciser table |
| Profile Modal | veDOLO holder detail (locks, vote weight) |
| Exerciser Modal | oDOLO exercise history |

### JavaScript Sections (~lines 2742-4289)
| Section | Lines | Description |
|---|---|---|
| Data & Load | 2744-2828 | JSON fetch, data initialization |
| Charts | 2848-3040 | Donut chart (SVG path arcs), bar chart |
| Expiry Timeline | 3041-3250 | Canvas-based bar chart |
| Table Render | 3255-3323 | veDOLO holders table |
| Pagination | 3326-3360 | Page navigation |
| Sort & Filter | 3362-3420 | Column sorting, search |
| Profile Modal | 3448-3580 | veDOLO holder detail modal |
| Tab Switching | 3673-3708 | veDOLO ↔ oDOLO tab logic |
| oDOLO Namespace | 3709-3915 | oDOLO data loading, RPC calls |
| oDOLO Donut | 3916-4100 | oDOLO distribution chart |
| Exercisers Table | 4101-4230 | oDOLO exerciser table + modal |

---

## 🍩 Donut Chart Technical Notes

**Implementation**: SVG `<path>` arcs (NOT circle + stroke-dasharray)

The chart was rewritten from `circle` + `stroke-dasharray` to proper SVG path arcs because small segments (like the pink 100+ NFTs segment at 3.1%) had visual distortion with the dasharray approach.

### Key function: `describeArc(cx, cy, r, startAngle, endAngle)`
- Uses trigonometry to compute exact arc coordinates
- Starts at 12 o'clock (subtracts 90° from angles)
- No CSS `transform: rotate(-90deg)` needed on the SVG
- Full circles (single segment ≥359.99°) fall back to `<circle>` element

### Hover system
- `donutSegments()` queries both `path[data-idx]` and `circle[data-idx]`
- Hover highlights segment + legend row, dims others
- Tooltip follows mouse via `donutMove(e)`

---

## 📱 Responsive Breakpoints

| Breakpoint | Key Changes |
|---|---|
| `1024px` | Metrics grid: 3 columns |
| `768px` | Metrics: 2 columns, analytics: 1 column, donut: stacked, expiry canvas: 240px height + 500px min-width |
| `600px` | Modal: compact stats (16px values), Exercise History: horizontal scroll (`#em-txs` overflow-x), address: `word-break: break-all` |
| `480px` | Smaller fonts, tighter spacing |

---

## 🧩 Modal Patterns

### veDOLO Profile Modal (`#profile-modal`)
- **Trigger**: Click address in table → `showProfile(address)`
- **Shows**: Rank, address, Vote Weight, DOLO Locked, Supply %, Active Locks (sortable by DOLO/Vote/Expiry), Berascan link
- **Close**: `closeProfile()`, Escape key, click overlay

### oDOLO Exerciser Modal (`#exerciser-modal`)
- **Trigger**: Click row in exerciser table → `openExerciserModal(addr, rank)`
- **Stats**: USDC.e Spent (orange), Exercises (white), Avg Lock (white), Avg Price (green)
- **Exercise History table**: Shows Date, USDC.e Paid, veDOLO Received, Price/veDOLO (green), Lock, Tx (cyan link)
- **Total row**: White text, Price stays green, inline `color:#fff` on each `td`
- **Close**: `closeExerciserModal()`, Escape key, click overlay

---

## 🐋 Whale Rows

- **Top 3**: Medal icons 🥇🥈🥉 (CSS classes `rank-1`, `rank-2`, `rank-3`)
- **Top 10**: Gradient background `linear-gradient(90deg, rgba(251,191,36,0.06) 0%, transparent 60%)`
- Applied to both veDOLO and oDOLO tables via `.whale-row` class

---

## 📡 Data Sources

### veDOLO
- `vedolo_holders.json` — fetched from GitHub raw URL
- Contains: address, rank, nft_count, total_dolo, total_vote_weight, token_ids, token_details (individual locks with amounts, vote weights, expiry dates)

### oDOLO
- `exercisers_by_address.json` — fetched from GitHub raw URL
- `exercised_volume_results.json` — transaction-level exercise data
- RPC calls to Berachain for: oDOLO total supply, exercise volume, pricing data
- `avg_lock_data.json` — pre-calculated average lock durations

---

## 🔧 Known Issues & Decisions

1. **CSS Specificity**: `.detail-table td` overrides `<tr>` color — always use inline `style="color:#fff"` on `<td>` elements
2. **Donut chart**: Must use SVG path arcs, NOT circle+dasharray (causes artifacts on small segments)
3. **Text rotation**: SVG text elements do NOT need `transform="rotate(90)"` since path arcs start at 12 o'clock
4. **Cache busting**: Append `?cachebust=xxx` to URL when testing GitHub Pages changes
5. **Expiry chart**: Canvas-based (`<canvas>`), needs `min-width` for proper rendering on mobile
6. **Mobile scroll**: Exercise History table wrapped in `#em-txs` with `overflow-x: auto` for horizontal scrolling

---

## 🚀 Future Ideas / TODO

- [ ] More detailed oDOLO analytics
- [ ] Historical charts for veDOLO metrics
- [ ] Export functionality (CSV/PDF)
- [ ] Address label system expansion
- [ ] Performance optimization for large datasets
