import React from 'react';
import { AbsoluteFill } from 'remotion';
import { CorrelationAIPane } from '../../../../src/components/nlp/CorrelationAIPane';
import { MobileAppFrame } from '../MobileAppFrame';
import { MobilePanZoom } from '../MobilePanZoom';
import { MobileCaption } from '../MobileCaption';
import { Cursor, RealClick } from '../../components/Interactions';
import { LiftFocus } from '../components/LiftFocus';
import { M_FULL } from '../theme';

/**
 * Portrait return beat: Recommended Actions lifted, then the Real-Time Data
 * panel — the REAL Kanban tab is clicked (RealClick) and flips selected.
 */
const kanbanTabSettled = () => {
  const btn = document.querySelector('.og-video-stage button[title="Kanban"]');
  if (!btn || !btn.className.includes('bg-white')) return false;
  const panel = btn.closest('.flex.flex-col.h-full');
  if (!panel) return true;
  if (panel.querySelector('.animate-spin')) return false;
  return (panel.textContent || '').includes('WO-4482');
};

export const MobileCorrelationReturnScene: React.FC = () => (
  <AbsoluteFill>
    <MobileAppFrame route="/nlp" fitHeight>
      <MobilePanZoom
        entrance={false}
        moves={[
          { at: 0, ...M_FULL },
          { at: 34, ...M_FULL },
          { at: 48, scale: 1.85, focusX: 566, focusY: 608 },
          { at: 88, scale: 1.85, focusX: 576, focusY: 612 },
          { at: 100, scale: 2.2, focusX: 1780, focusY: 855 },
          { at: 140, scale: 2.2, focusX: 1780, focusY: 855 },
          { at: 150, scale: 2.2, focusX: 1790, focusY: 860 },
          { at: 178, scale: 2.2, focusX: 1790, focusY: 860 },
        ]}
      >
        <CorrelationAIPane />
        <RealClick
          at={131}
          selector='.og-video-stage button[title="Kanban"]'
          settledWhen={kanbanTabSettled}
        />
        <LiftFocus x={326} y={540} w={480} h={136} inAt={50} outAt={92} />
        <LiftFocus x={1652} y={730} w={256} h={300} inAt={104} outAt={176} />
        <Cursor
          path={[
            { at: 98, x: 1300, y: 620 },
            { at: 116, x: 1818, y: 798 },
            { at: 144, x: 1818, y: 798 },
            { at: 160, x: 1795, y: 825 },
          ]}
          clicks={[130]}
          inAt={96}
          outAt={172}
        />
      </MobilePanZoom>
    </MobileAppFrame>
    <MobileCaption
      text="Rapid insight on disparate data. End to end."
      accent="End to end"
      inAt={8}
      outAt={84}
    />
    <MobileCaption
      text="Live telemetry, alarms, Kanban and registries — toggled right inside the session."
      accent="Kanban"
      inAt={108}
      outAt={170}
    />
  </AbsoluteFill>
);
