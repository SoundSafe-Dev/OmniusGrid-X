import React from 'react';
import { AbsoluteFill } from 'remotion';
import { CorrelationAIPane } from '../../../src/components/nlp/CorrelationAIPane';
import { AppFrame } from '../AppFrame';
import { PanZoom } from '../components/PanZoom';
import { Caption } from '../components/Caption';
import { Cursor, Highlight, RealClick } from '../components/Interactions';

/** Post-click settle: Kanban tab styled active + its task list rendered. */
const kanbanTabSettled = () => {
  const btn = document.querySelector('.og-video-stage button[title="Kanban"]');
  if (!btn || !btn.className.includes('bg-white')) return false;
  const panel = btn.closest('.flex.flex-col.h-full');
  if (!panel) return true;
  if (panel.querySelector('.animate-spin')) return false;
  return (panel.textContent || '').includes('WO-4482');
};

/**
 * Return beat: full session view → punch on Recommended Actions → pan to the
 * right rail where the Real-Time Data toggles (Live / Alarms / Kanban /
 * Registries) get emphasized with a cursor click on the Kanban tab.
 */
export const CorrelationReturnScene: React.FC = () => (
  <AbsoluteFill>
    <AppFrame route="/nlp" fitHeight>
      <PanZoom
        entrance={false}
        moves={[
          { at: 0, scale: 1.0, focusX: 960, focusY: 515 },
          { at: 26, scale: 1.0, focusX: 960, focusY: 515 },
          { at: 40, scale: 1.8, focusX: 500, focusY: 600 },
          { at: 70, scale: 1.8, focusX: 510, focusY: 615 },
          { at: 86, scale: 1.75, focusX: 1500, focusY: 720 },
          { at: 116, scale: 1.75, focusX: 1500, focusY: 720 },
          { at: 130, scale: 1.85, focusX: 1550, focusY: 750 },
          { at: 150, scale: 1.85, focusX: 1550, focusY: 750 },
        ]}
      >
        <CorrelationAIPane />
        {/* the real Kanban tab is clicked — it flips to its selected style
            and the panel content swaps to the live task list */}
        <RealClick
          at={107}
          selector='.og-video-stage button[title="Kanban"]'
          settledWhen={kanbanTabSettled}
        />
        {/* Recommended Actions */}
        <Highlight x={326} y={540} w={480} h={136} inAt={44} outAt={74} />
        {/* Real-Time Data panel + its source toggles */}
        <Highlight x={1652} y={730} w={256} h={292} inAt={94} outAt={146} radius={14} />
        <Cursor
          path={[
            { at: 84, x: 1300, y: 620 },
            { at: 100, x: 1818, y: 798 },
            { at: 116, x: 1818, y: 798 },
            { at: 132, x: 1795, y: 825 },
          ]}
          clicks={[106]}
          inAt={82}
          outAt={144}
        />
      </PanZoom>
    </AppFrame>
    <Caption
      text="Rapid insight on disparate data. End to end."
      accent="End to end"
      inAt={8}
      outAt={68}
    />
    <Caption
      text="Live telemetry, alarms, Kanban and registries — toggled right inside the session."
      accent="Kanban"
      inAt={94}
      outAt={142}
    />
  </AbsoluteFill>
);
