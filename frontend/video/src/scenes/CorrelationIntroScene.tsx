import React from 'react';
import { CorrelationAIPane } from '../../../src/components/nlp/CorrelationAIPane';
import { FramedScene } from '../components/FramedScene';
import { NavDrawer } from '../components/NavDrawer';

/**
 * Framed intro for the hero: presents the Correlation AI engine like the
 * other featured pages, then the sidebar slides in and the cursor clicks
 * "Correlation AI" — cutting into the full-bleed interactive session.
 */
const HIDE_MESSAGES_CSS = `
  .og-video-stage div.space-y-4.overflow-x-hidden > div { visibility: hidden; }
`;

export const CorrelationIntroScene: React.FC = () => (
  <FramedScene
    overline="AI · The Engine"
    title="Correlation AI"
    bullets={[
      'Ask questions in plain language',
      'Spreadsheets, PDFs, photos, audio & live sensor feeds — one context',
      'Risk-scored answers with recommended actions',
    ]}
    chipText="⚡ Every pane on the grid feeds it"
    route="/nlp"
    page={<CorrelationAIPane />}
    fitHeight
    extraCss={HIDE_MESSAGES_CSS}
    moves={[
      { at: 0, scale: 1.0, focusX: 960, focusY: 515 },
      { at: 70, scale: 1.06, focusX: 900, focusY: 540 },
      { at: 118, scale: 1.0, focusX: 960, focusY: 515 },
    ]}
    stageOverlay={<NavDrawer activePath="" targetPath="/nlp" inAt={120} clickAt={142} />}
  />
);
