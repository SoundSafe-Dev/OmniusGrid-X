import React from 'react';
import { CorrelationAIPane } from '../../../../src/components/nlp/CorrelationAIPane';
import { MobileFramedScene } from '../MobileFramedScene';
import { NavDrawer } from '../../components/NavDrawer';

/** Portrait Correlation AI engine intro — stacked framed layout,
 *  identical copy and MiniStage internals to the desktop edition. */

const HIDE_MESSAGES_CSS = `
  .og-video-stage div.space-y-4.overflow-x-hidden > div { visibility: hidden; }
`;

export const MobileCorrelationIntroScene: React.FC = () => (
  <MobileFramedScene
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
    frameH={1290}
    frameTop={2020}
    fitHeight
    extraCss={HIDE_MESSAGES_CSS}
    moves={[
      // portrait-window cameras (viewport 1064x906, fit-width 0.554)
      { at: 0, scale: 0.554, focusX: 960, focusY: 518 },
      { at: 78, scale: 0.63, focusX: 920, focusY: 518 },
      { at: 130, scale: 0.554, focusX: 960, focusY: 518 },
    ]}
    stageOverlay={<NavDrawer activePath="" targetPath="/nlp" inAt={136} clickAt={158} />}
  />
);
