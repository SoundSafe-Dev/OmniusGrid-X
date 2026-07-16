# OmniusGrid — Brand Guidelines (v1.0 · July 2026)

Text source of truth for the rendered book at
`frontend/out/brand/OmniusGrid-Brand-Guidelines.pdf` (pages generated from
`frontend/video/src/promo/BrandBook.tsx`). If copy changes here, change it
there and re-render. Brand owner & final sign-off: `hamad@soundsafe.ai`.

---

## 1 · Brand narrative

**Positioning.** OmniusGrid is the correlation engine for Industry 4.0. It
takes the files a factory already has — ERP orders, invoices, shipments,
quality records — and the machine data it already streams, and makes them
answer questions together.

**Elevator pitch (30 s).** Factories already produce everything they need to
know: enterprise records in ERP, spreadsheets and PDFs, and live telemetry
from the floor. OmniusGrid ingests every format, streams machine data
alongside, and answers plain-language questions with visible reasoning, a
score and a one-click action. The gains come when the two halves meet —
transparency, flexibility, better decisions.

**The rule that never breaks.** Enterprise data first, machine data second —
always in that order, always with examples ("ERP orders, invoices,
shipments, quality records" before "sensors and cameras").

**Boilerplate (copy verbatim).** OmniusGrid, by SoundSafe.ai, correlates
enterprise data — ERP orders, invoices, shipments, quality records — with
live machine data from the factory floor. Teams drop in the files they
already have, ask questions in plain language, and get answers that show
their reasoning, carry a score, and ship with a one-click action — across
OEE, Kanban, TMS, YMS and seven live ERP integrations.

## 2 · Messaging architecture

| Level | Line |
|---|---|
| Master tagline | Unleash the power of **data correlation** |
| Category line | The correlation engine for Industry 4.0. |
| Product line | Just ask. It correlates. |
| Problem hook | Industry 4.0 runs on data. The data doesn't talk. |
| Payoff line | The answers existed. They just never met. |

**Three pillars — fixed names, never reworded:**
- **Optimized Operations.** — ingested files × live telemetry, OEE, headroom
- **Actionable Insights.** — GO / risk scores, action approval, Kanban dispatch
- **Maximum Efficiency.** — TMS, YMS, detention alerts, OTIF

**Canonical example — use everywhere until replaced:** "What happens if we
raise Line 3 output by 20%?" → `material-forecast_q3.xlsx` (Purchasing) ×
`carrier-agreement_2026.pdf` (Logistics) × `Lines 1–3 stream` (Machines) →
**GO · 91** → green-light, material orders dispatched. Growth-positive
scenarios lead; risk examples support.

## 3 · Voice & tone — six principles

1. **Concrete over abstract.** Name the file, the line, the number.
   ✓ "Line 3 at 63% load — green-light +20%." ✗ "AI-driven insights optimize productivity."
2. **Short declaratives.** One idea per sentence; the em-dash makes the turn.
   ✓ "Capacity found, not bought." ✗ forty-word feature sentences.
3. **Growth-positive.** Lead with what teams green-light; leaks are evidence.
   ✓ "Commit to more volume knowing OTIF holds." ✗ fear-first pitches.
4. **Show the product.** Every capability claim is a real pane, button or chip.
   ✓ GO · 91 badge, the load bar. ✗ stock photos, 3D cubes, robot handshakes.
5. **No AI mysticism.** The reasoning is always shown — say so.
   ✓ "Every answer shows its reasoning." ✗ "magic black-box intelligence."
6. **Enterprise data first.** ERP orders, invoices, shipments, quality
   records — then machines. Never lead with sensors.

## 4 · Logo & wordmark

- **Split weight, always:** "Omnius" at 800, "Grid" at 400, one color.
  Never all-bold, never two colors, never "OMNIUSGRID" in running copy.
- **The white tile:** the gear never touches charcoal directly; it lives on
  a white rounded tile (hairline `#e2e2e6` border on light backgrounds).
- **SoundSafe attribution:** every outward asset carries "by" + the
  SoundSafe logo on a white pill, bottom-right (the SoundSafe logotype is
  dark — never place it on dark ground).
- **Clearspace:** half the tile height on all sides. Min tile height 32 px
  screen / 10 mm print.
- **Don'ts:** no recoloring, stretching, or drop shadows on the wordmark.

## 5 · Color

Dark (default): bg `#0a0a0a` · panel `#171717` · border `#2e2e2e` · text
`#fafafa` · secondary `#a3a3a3`.
Light (print & email): bg `#f7f7f8` · card `#ffffff` · border `#e2e2e6` ·
text `#141414` · secondary `#5c5c62`.
Accents: brand blue `#3b82f6` (soft `#93c5fd` on dark, deep `#2563eb` on
light) · live/GO green `#4ade80` dark / `#16a34a` light · risk red `#ef4444`.

**The accent law:** one blue accent. If a layout needs a second accent
color, the layout is wrong. Green is reserved for live streams and GO
scores; red is reserved for risk; neither is ever decoration.

## 6 · Typography & data language

- System stack (`-apple-system … sans-serif`) — no licensed display faces.
- Scale: display 800/−3 tracking · headline 800/−2.5 · body 500/1.45 line
  height · overline 700/+8 tracking/uppercase.
- **Data speaks monospace** (`ui-monospace`): file names, IDs, line names —
  `material-forecast_q3.xlsx`, `SHP-2214`, `Line 3`.
- **Chip system:** blue = ingested file formats (XLSX PDF JPG WAV) ·
  green = `● LIVE` streams and `GO · nn` scores · neutral = product modules
  (OEE, Kanban, TMS, YMS, ERP).

## 7 · Signature motifs

- **Grid texture** — 120 px grid, ~20% opacity, radial mask. Texture, never pattern-loud.
- **Product window** — three dots + session title + context chip; UI is always framed as a window, never a floating screenshot.
- **Question bubble** — right-aligned, one line where possible; white on dark, near-black on light.
- **Score badges** — GO leads in marketing; RISK appears as supporting evidence.
- **Power-up inset** — blue left bar + label + a real UI artifact + one-line payoff.
- **Payoff strip** — ⚡ + one sentence, blue-tinted bar; max one per asset.

## 8 · Sign-off checklist (every asset, before it ships)

- [ ] Split-weight wordmark — Omnius 800 / Grid 400
- [ ] One blue accent; green only for live & GO; red only for risk
- [ ] Enterprise data named before machine data
- [ ] Canonical Line 3 example (or an approved successor)
- [ ] Real product UI for every capability claim
- [ ] "by SoundSafe" pill, bottom-right
- [ ] Dark + light variants where the channel needs both
- [ ] No "app.omniusgrid.io" URLs until launch

## Asset library (all code, all re-renderable)

| Asset | Source | Output |
|---|---|---|
| Demo film 4K + 9:16 | `video/src`, `video/src/mobile` | `out/omniusgrid-demo-*.mp4` |
| Instagram cards ×3 | `promo/PromoCards.tsx` | `out/promo/` |
| Client & investor decks (dark) | `promo/DeckCards.tsx` | `out/decks/` + PDFs |
| Deck light variants | `promo/DeckCardsLight.tsx` | `out/decks/*Light*` + PDFs |
| Brand book ×9 pages | `promo/BrandBook.tsx` | `out/brand/` + PDF |
| One-pager, LinkedIn banner | `promo/Collateral.tsx` | `out/brand/` |
| Wordmark PNG | `components/WordmarkCard.tsx` | `out/` |

Render: `npx remotion still video/src/index.ts <StillId> <out.png>` from
`frontend/`; PDFs bound with PIL (`save_all`, quality 95) from 2x masters.
