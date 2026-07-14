import React from 'react';
import { AbsoluteFill, useCurrentFrame } from 'remotion';
import { CorrelationAIPane } from '../../../src/components/nlp/CorrelationAIPane';
import { AppFrame } from '../AppFrame';
import { PanZoom } from '../components/PanZoom';
import { Caption } from '../components/Caption';
import { Cursor, Highlight, TypeText, ThinkingCard } from '../components/Interactions';
import { NavDrawer } from '../components/NavDrawer';

/**
 * Interactive hero (four beats over one mounted pane, frame-driven):
 *   Sources:  camera on the session rail — spreadsheets, PDFs, the whiteboard
 *             photo and live platform feeds pop into the analysis session
 *   Ask:      cursor to input → question types → Send click
 *   Thinking: user bubble appears, analysis-progress card animates
 *   Answer:   answer appears → punch on risk badge → pull back → sidebar nav
 *
 * The pane always loads the full mock session; which messages / data sources
 * are visible is switched with frame-driven CSS. No remounts, no timers.
 */

const QUESTION =
  "Why did Line 3's scrap rate jump 3.4% last week? I've added the production log, compressor report and whiteboard photo.";

// Beat boundaries (scene-local frames)
const SEND_CLICK = 280;
const ACT2_AT = 286; // user bubble appears
const ACT3_AT = 380; // assistant answer appears

const MSG_LIST = '.og-video-stage div.space-y-4.overflow-x-hidden';
const SOURCES = '.og-video-stage .w-72 .space-y-2';

const sourcesShown = (frame: number) =>
  Math.max(0, Math.min(6, Math.floor((frame - 36) / 14)));

const ActCss: React.FC = () => {
  const frame = useCurrentFrame();
  let css = '#correlation-chat-input::placeholder { color: transparent !important; }\n';
  // data sources pop into the session one by one
  const k = sourcesShown(frame);
  if (k < 6) {
    css += `${SOURCES} > div:nth-child(n+${k + 1}) { visibility: hidden; }\n`;
  }
  if (frame < ACT2_AT) {
    css += `${MSG_LIST} > div:nth-child(1), ${MSG_LIST} > div:nth-child(2) { visibility: hidden; }`;
  } else if (frame < ACT3_AT) {
    css += `${MSG_LIST} > div:nth-child(2) { visibility: hidden; }`;
  }
  return <style>{css}</style>;
};

export const CorrelationScene: React.FC = () => (
  <AbsoluteFill>
    <AppFrame route="/nlp" fitHeight>
      <ActCss />
      <PanZoom
        moves={[
          { at: 0, scale: 1.0, focusX: 960, focusY: 515 },
          { at: 32, scale: 1.0, focusX: 960, focusY: 515 },
          { at: 48, scale: 1.5, focusX: 240, focusY: 640 },
          { at: 124, scale: 1.5, focusX: 250, focusY: 700 },
          // hold on the input until the Send click has fully landed
          { at: 142, scale: 1.16, focusX: 880, focusY: 780 },
          { at: 282, scale: 1.16, focusX: 880, focusY: 800 },
          { at: ACT2_AT + 4, scale: 1.3, focusX: 860, focusY: 330 },
          { at: ACT3_AT - 8, scale: 1.3, focusX: 860, focusY: 330 },
          { at: ACT3_AT + 12, scale: 1.55, focusX: 760, focusY: 400 },
          { at: 500, scale: 1.55, focusX: 760, focusY: 430 },
          { at: 545, scale: 1.0, focusX: 960, focusY: 515 },
          { at: 598, scale: 1.0, focusX: 960, focusY: 515 },
        ]}
      >
        <CorrelationAIPane />
        {/* typed question overlaid on the real (empty) chat input */}
        <TypeText x={337} y={964} text={QUESTION} startAt={158} cpf={1.15} outAt={ACT2_AT} />
        {/* Send button highlight + cursor choreography */}
        <Highlight
          x={1583}
          y={938}
          w={54}
          h={50}
          inAt={SEND_CLICK - 14}
          outAt={SEND_CLICK + 12}
          spotlight={false}
        />
        <Cursor
          path={[
            { at: 24, x: 1250, y: 700 },
            { at: 44, x: 150, y: 560 },
            { at: 62, x: 170, y: 645 },
            { at: 88, x: 180, y: 765 },
            { at: 116, x: 190, y: 880 },
            { at: 142, x: 500, y: 955 },
            // park below the input while the question types — never over text
            { at: 158, x: 820, y: 1014 },
            { at: 256, x: 860, y: 1016 },
            { at: 272, x: 1610, y: 962 },
            { at: 294, x: 1610, y: 962 },
            { at: 330, x: 1500, y: 640 },
            { at: 420, x: 1720, y: 520 },
          ]}
          clicks={[148, SEND_CLICK]}
          inAt={20}
          outAt={460}
        />
        {/* analysis-progress card while "thinking" */}
        <ThinkingCard x={333} y={196} inAt={ACT2_AT + 6} outAt={ACT3_AT - 4} stepEvery={15} />
        {/* risk-badge highlight when the answer lands */}
        <Highlight x={330} y={192} w={155} h={38} inAt={ACT3_AT + 16} outAt={ACT3_AT + 80} />
      </PanZoom>
      <NavDrawer activePath="/nlp" targetPath="/intake" inAt={552} clickAt={578} />
    </AppFrame>
    <Caption
      text="Excel tabs, PDFs, a whiteboard photo, live feeds — one session, one question."
      accent="one session"
      inAt={52}
      outAt={132}
    />
    <Caption
      text="No dashboards to build. No data to wrangle. Just ask — and get the correlated answer."
      accent="Just ask"
      inAt={ACT3_AT + 10}
      outAt={540}
    /></AbsoluteFill>
);
