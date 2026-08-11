/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Separate from vite.config.ts (prod build) so the test harness is self-contained.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // plotly needs canvas/WebGL at import time, which jsdom lacks — stub the
      // whole react wrapper under test (real builds use the actual library).
      'react-plotly.js': new URL('./src/test/plotlyStub.tsx', import.meta.url).pathname,
      'plotly.js': 'plotly.js-dist-min',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      // WIDENED in FS-240. This used to be three paths — two stores files, one
      // websocket client and one component — which made the reported percentage
      // decorative: it measured the code we happened to have tested, so it could
      // never fall no matter how much untested code was added.
      //
      // The scope below is the code a regression would actually be felt in.
      // WIDENED 2026-08-08 (FS-541) from `src/components/ui/**` to all of
      // `src/components/**`. The narrow form left NINE of the ten component
      // directories outside the measurement — assets, charts, commands, common,
      // fleet, kanban, layout, nlp and yard, **10,566 lines** — so the four
      // percentages below described a subset chosen years ago and the ratchet could
      // not fall no matter how much untested component code was added.
      //
      // That is the same failure the comment above this block describes for an even
      // narrower include, fixed once at a different depth and left half-done: the
      // scope was widened to five paths and one of them was itself a leaf.
      include: [
        'src/api/**',
        'src/stores/**',
        'src/hooks/**',
        'src/components/**',
        'src/pages/**',
        // FS-541, found by the guard after the components fix. `utils/` holds
        // `formatters.ts` — which wraps every date/number conversion in a try/catch — and
        // `statusColors.ts`, whose contrast values have a test protecting them. Both had
        // tests and neither counted toward the number. `i18n/` is the runtime setup.
        'src/utils/**',
        'src/i18n/*.{ts,tsx}',
      ],
      exclude: [
        '**/*.test.{ts,tsx}',
        '**/*.spec.{ts,tsx}',
        'src/test/**',
        // Mock datasets are fixtures, not product code; counting them would
        // inflate the number with data that has no behaviour to test.
        'src/api/mockApi.ts',
        'src/api/generated/**',
        // macOS writes these inside source directories and the coverage provider tries
        // to parse them, printing three RollupError stack traces on every run. Harmless
        // — they are gitignored and excluded automatically — but a gate whose output is
        // full of red stack traces is a gate people stop reading.
        '**/.DS_Store',
        // Type declarations have no runtime behaviour to cover; including them adds a
        // denominator with no possible numerator and drags every percentage down for a
        // reason unrelated to testing.
        'src/types/**',
        // Translation catalogues are data, on the same argument as `mockApi.ts` above.
        'src/i18n/locales/**',
      ],
      // RAISED 2026-07-31 (FS-260). Set from the MEASURED value, with ~1 point of
      // margin, so this is a ratchet rather than an aspiration: it cannot be met by
      // deleting tests, and it fails if new untested code dilutes the total.
      //
      //   set by FS-240   19.83 / 16.16 / 14.51 / 20.55   -> 19 / 15 / 14 / 19
      //   measured today  39.01 / 42.78 / 35.21 / 40.23   -> 38 / 41 / 34 / 39
      //
      // Coverage had roughly DOUBLED while the thresholds stood still, which made
      // them decorative in the direction nobody checks: the gate would have sat
      // through coverage falling by half and still passed. A ratchet that trails
      // reality by 20 points is not a ratchet, it is a number in a config file.
      //
      // FS-260 was written up as "no thresholds exist, and the coverage `include` is
      // narrowed to three paths". Neither reproduced — FS-240 had already widened the
      // include and set these. The real defect was the opposite one, and the sprint
      // entry has been corrected in place per that document's own instruction.
      //
      // Raise these as coverage improves. Do NOT lower them to make a build pass:
      // the point is that dropping below today's level is a regression.
      // RAISED 2026-08-08 (FS-541/542), and the include widened in the same commit so
      // the number moves for a stated reason rather than appearing to improve.
      //
      //   before, ui/ only        50.96 / 55.57 / 45.25 / 52.61   thresholds 38/41/34/39
      //   after, all components   45.60 / 46.30 / 41.39 / 47.02   thresholds 44/45/40/46
      //
      // (utils/ and i18n/ joined in the same commit — the guard found them after the
      // components fix, and utils/ holds two modules that HAD tests which did not count.)
      //
      // The measured figure FELL by widening — 10,566 lines of previously invisible
      // component code came into scope — and the threshold still rises by six points,
      // because the old one trailed even the narrow measurement by 13. A ratchet that
      // sits 13 points below reality would sit through coverage falling by a quarter.
      //
      // ~1 point of margin, as FS-260 set: enough that a single refactor does not fail
      // the build, not enough to absorb a real regression.
      //
      // Raise these as coverage improves. Do NOT lower them to make a build pass.
      //
      // LOWERED 2026-08-09 — and the enforcement went UP in the same edit, which is the
      // only reason lowering is defensible here. **No CI job has ever run `--coverage`.**
      // `ci-cd.yml` runs `npx vitest run` and `quality-gates.yml` runs `npm run test`,
      // both of which are `vitest run` WITHOUT it, so these numbers were checked by
      // nobody — exactly the "number in a config file" the comment above warns about,
      // and it had already gone false: the 2026-08-08 merge added ~700 lines of
      // untested pages and lines fell to 45.45 against a threshold of 46. Nothing
      // reported it, because nothing was looking.
      //
      // Set to the measured floor and wired into `quality-gates.yml` as a blocking step.
      // A lower number that a gate enforces is strictly tighter than a higher one that
      // no gate reads — but the direction is still down, and the way back up is
      // FS-654/655, not another edit here.
      //
      //   measured 2026-08-09: statements 44.14 · branches 44.65 · functions 37.90 · lines 45.45
      //
      // RAISED BACK 2026-08-11, and past where it started. FS-652 put tests on the five
      // `common/` components and the dialog primitives — all of which were stubbed out of
      // every page test that mounted them, so a stub and an exercised component looked
      // identical to the coverage tool. **Lines 45.45 -> 46.40**, above the 46 the merge
      // pushed them under. The lowering lasted two days and the way back up was tests,
      // which is what that note said it would be.
      //
      //   measured 2026-08-11: statements 45.05 · branches 45.69 · functions 38.40 · lines 46.40
      //
      // RAISED AGAIN, same day, after FS-651 put the first tests on `components/kanban/` —
      // 1,811 lines that had none. Every threshold is now above where it stood before the
      // merge, and branches (46) is the highest this ratchet has ever held.
      //
      //   measured 2026-08-11: statements 45.60 · branches 46.58 · functions 38.86 · lines 47.00
      //
      // AND AGAIN, after the kanban STORE — 367 lines that own board loading and every task
      // mutation, and which `pages/Kanban.test.tsx` mocks wholesale, so the page tests
      // proved the page renders whatever it returns and nothing about what it returns.
      //
      //   measured 2026-08-11: statements 46.53 · branches 46.84 · functions 39.36 · lines 47.96
      //
      // FOURTH RAISE, after the filter bar and the metrics bar. Lines have gone 45.45 ->
      // 48.21 in a day, entirely by testing components that were `() => null` stubs in
      // every page test that mounted them.
      //
      //   measured 2026-08-11: statements 46.76 · branches 47.30 · functions 39.61 · lines 48.21
      //
      // FIFTH RAISE, after KanbanBoard. Lines 45.45 -> 48.57 in a day.
      //
      //   measured 2026-08-11: statements 47.13 · branches 47.60 · functions 39.91 · lines 48.57
      //
      // SIXTH RAISE, closing FS-651 and FS-652b: the last two kanban stubs (`CreateTaskModal`,
      // `TaskDetailModal` — 820 lines between them) and the five `ui/` primitives that had no
      // test of their own. The primitives moved the number barely at all, which is the point
      // of having tested them: they already reported high line coverage from the pages that
      // mount them, exactly as `ui/Select.tsx` did at 100% while rendering an unlabelled
      // combobox. Coverage counts a line that executed, not a behaviour anybody asserted.
      //
      // Lines have gone 45.45 -> 50.24 in a day, entirely by replacing `() => null` stubs
      // with tests. Functions clears 40 for the first time.
      //
      //   measured 2026-08-11: statements 48.69 · branches 48.63 · functions 41.23 · lines 50.24
      //
      // SEVENTH RAISE, after FS-655 — the sweep that asked what a POLLED value shows when its
      // poll starts failing. Statements only; branches, functions and lines each moved by less
      // than a point and their floors already sit inside that. Raising a threshold the
      // measurement does not clear by a margin is how a ratchet starts failing on variance
      // rather than on regressions.
      //
      //   measured 2026-08-11: statements 49.01 · branches 48.97 · functions 41.44 · lines 50.57
      thresholds: {
        statements: 49,
        branches: 48,
        functions: 41,
        lines: 50,
      },
    },
  },
})
