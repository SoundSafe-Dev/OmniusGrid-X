# OmniusGrid demo video (Remotion)

Renders the **actual app pages** (Correlation AI, Intake Inbox, Assets +
Asset Detail, Transportation TMS, Yard YMS, Dashboard, OEE, ERP, Kanban) into
a ~77s interactive-looking 4K product video, driven entirely by the in-browser
mock layer (`VITE_USE_MOCK=true`) — no backend needed. Structure: monochrome
problem-line cold open → logo title card → interactive hero (typed question →
thinking steps → answer) → full-bleed feature scenes with spotlight
highlights → framed side-explanation scenes (TMS/YMS) → sidebar-click
navigation between every page (NavDrawer) → 3D stack finale where all eight
live panes converge into the OmniusGrid mark → outro with the SoundSafe.ai
logo. Logo assets live in `public/` (staticFile).

## Commands (run from `frontend/`)

```bash
npm run video:studio        # interactive preview / scrubbing
npm run video:still -- Correlation-Still out/qa/correlation.png   # per-scene QA stills
npm run video:render        # full 4K h264 master → out/omniusgrid-demo-4k.mp4
npm run video:render:hevc   # smaller h265 deliverable
```

## Architecture notes

- **Do NOT split `video/` into its own package.** It must share
  `frontend/package.json` / `node_modules`, otherwise a second React copy gets
  bundled and hooks crash.
- Remotion bundles with **webpack, not Vite**. `remotion.config.ts` defines
  `import.meta.env` for the app code — both the whole object (for
  `import.meta.env?.X` optional-chain reads) and per-key entries (plain
  `import.meta.env.X` member chains get constant-folded by webpack's native
  import.meta handling before the object define applies). If you add a new
  env var read in app code that the video needs, add it in **both** places.
- `AppFrame.tsx` provides: QueryClient (no retries/polling), MemoryRouter,
  TooltipProvider, light-theme guard, a 1920x1080 stage scaled 2x (crisp 4K
  text), a browser-chrome bar, a `delayRender` settle gate (waits for
  react-query + mock fetchers to go quiet), CSS-animation kill, a
  `100vh`→stage-height remap, and a global `scrollIntoView` no-op —
  scrollIntoView scrolls `overflow:hidden` ancestors, which fights the
  PanZoom camera once content is scaled.
- Scene timing/order and transitions live in `Root.tsx` (`SCENES` table).
  Cameras are per-scene `PanZoom` keyframes in stage coordinates
  (1920x1036 content box below the 44px chrome bar).
- Interaction overlays (`components/Interactions.tsx`: `Cursor`, `Highlight`,
  `TypeText`, `ThinkingCard`) render INSIDE `PanZoom`, in page coordinates —
  they zoom with the camera like a real screen recording. All frame-driven.
  `Highlight` includes a spotlight scrim (dims everything but the target).
- `NavDrawer` (components/NavDrawer.tsx) is a pixel-faithful replica of the
  app sidebar (same classes/icons/order as `src/components/layout/Sidebar.tsx`)
  that slides in at scene ends for hover+click navigation moments. If the real
  sidebar's nav list changes, update the replica's NAV array.
- `MiniStage` renders a page at any width (framed scenes, stack cards);
  `FramedScene` is the dark side-explanation layout; `StackScene` mounts all
  eight pages live for the finale.
- The hero scene switches its three acts (ask → thinking → answer) with
  frame-driven CSS that hides message blocks (`nth-child` visibility on the
  message list) over ONE mounted pane — no remounts, no wall-clock timers.
  If the pane's DOM structure changes, re-check those selectors.
- Mock telemetry uses `deterministicNoise(i)`/`round1` in `mockApi.ts` —
  never reintroduce `Math.random()` there; it flickers at render-chunk seams.
- The demo dataset is one coherent incident across
  logistics → shop floor → financials → customer; fixtures live in
  `src/api/mocks/nlpMocks.ts` + `kanbanMocks.ts` and the legacy
  `src/api/mockApi.ts`.
