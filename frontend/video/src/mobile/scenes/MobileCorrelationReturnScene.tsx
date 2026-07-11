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
 * Portrait return beat: Recommended Actions punch, then the Real-Time Data
 * rail where the REAL Kanban tab is clicked (RealClick) and flips selected.
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
          { at: 26, ...M_FULL },
          // Recommended Actions lifted, then the Real-Time Data panel — big
          { at: 40, scale: 1.85, focusX: 566, focusY: 608 },
          { at: 70, scale: 1.85, focusX: 576, focusY: 612 },
          { at: 86, scale: 2.2, focusX: 1780, focusY: 855 },
          { at: 116, scale: 2.2, focusX: 1780, focusY: 855 },
          { at: 130, scale: 2.2, focusX: 1790, focusY: 860 },
          { at: 150, scale: 2.2, focusX: 1790, focusY: 860 },
        ]}
      >
        <CorrelationAIPane />
        <RealClick
          at={107}
          selector='.og-video-stage button[title="Kanban"]'
          settledWhen={kanbanTabSettled}
        />
        <LiftFocus x={326} y={540} w={480} h={136} inAt={44} outAt={76} />
        <LiftFocus x={1652} y={730} w={256} h={300} inAt={90} outAt={148} />
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
      </MobilePanZoom>
    </MobileAppFrame>
    <MobileCaption
      text="Rapid insight on disparate data. End to end."
      accent="End to end"
      inAt={8}
      outAt={68}
    />
    <MobileCaption
      text="Live telemetry, alarms, Kanban and registries — toggled right inside the session."
      accent="Kanban"
      inAt={94}
      outAt={142}
    />
  </AbsoluteFill>
);
