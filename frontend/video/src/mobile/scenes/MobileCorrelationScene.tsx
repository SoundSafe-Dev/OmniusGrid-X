import React from 'react';
import { AbsoluteFill, useCurrentFrame } from 'remotion';
import { CorrelationAIPane } from '../../../../src/components/nlp/CorrelationAIPane';
import { MobileAppFrame } from '../MobileAppFrame';
import { MobilePanZoom } from '../MobilePanZoom';
import { MobileCaption } from '../MobileCaption';
import { MobileNavDrawer } from '../MobileNavDrawer';
import { Cursor, Highlight, TypeText, ThinkingCard } from '../../components/Interactions';
import { LiftFocus } from '../components/LiftFocus';
import { M_FULL } from '../theme';

/**
 * Portrait hero — identical beats, acts and overlay coordinates to the
 * desktop CorrelationScene; only the camera poses are portrait-framed.
 */

const QUESTION =
  "Why did Line 3's scrap rate jump 3.4% last week? I've added the production log, compressor report and whiteboard photo.";

const SEND_CLICK = 262;
const ACT2_AT = 268;
const ACT3_AT = 352;

const MSG_LIST = '.og-video-stage div.space-y-4.overflow-x-hidden';
const SOURCES = '.og-video-stage .w-72 .space-y-2';

const sourcesShown = (frame: number) =>
  Math.max(0, Math.min(6, Math.floor((frame - 32) / 12)));

const ActCss: React.FC = () => {
  const frame = useCurrentFrame();
  let css = '#correlation-chat-input::placeholder { color: transparent !important; }\n';
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

export const MobileCorrelationScene: React.FC = () => (
  <AbsoluteFill>
    <MobileAppFrame route="/nlp" fitHeight>
      <ActCss />
      <MobilePanZoom
        moves={[
          { at: 0, ...M_FULL },
          { at: 28, ...M_FULL },
          // sources rail, lifted tall
          { at: 44, scale: 1.9, focusX: 270, focusY: 530 },
          { at: 108, scale: 1.9, focusX: 270, focusY: 545 },
          // tight on the input while typing, then pan right to the Send button
          { at: 126, scale: 1.35, focusX: 730, focusY: 970 },
          { at: 234, scale: 1.35, focusX: 730, focusY: 970 },
          { at: 250, scale: 1.35, focusX: 1270, focusY: 970 },
          { at: 264, scale: 1.35, focusX: 1270, focusY: 970 },
          // thinking card lift
          { at: ACT2_AT + 4, scale: 1.4, focusX: 650, focusY: 298 },
          { at: ACT3_AT - 8, scale: 1.4, focusX: 650, focusY: 298 },
          // answer lift (badge + domains + chain)
          { at: ACT3_AT + 12, scale: 1.2, focusX: 741, focusY: 432 },
          { at: 452, scale: 1.2, focusX: 745, focusY: 436 },
          { at: 492, ...M_FULL },
          { at: 540, ...M_FULL },
        ]}
      >
        <CorrelationAIPane />
        {/* ghost-context lifts per beat */}
        <LiftFocus x={0} y={60} w={300} h={940} inAt={46} outAt={112} radius={10} />
        <LiftFocus x={320} y={935} w={1340} h={70} inAt={130} outAt={266} radius={10} />
        <LiftFocus x={322} y={184} w={650} h={225} inAt={ACT2_AT + 8} outAt={ACT3_AT - 6} />
        <LiftFocus
          x={326}
          y={186}
          w={830}
          h={492}
          inAt={ACT3_AT + 14}
          outAt={470}
          fadeEdge="right"
        />
        <TypeText x={337} y={964} text={QUESTION} startAt={140} cpf={1.15} outAt={ACT2_AT} />
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
            { at: 40, x: 150, y: 560 },
            { at: 56, x: 170, y: 645 },
            { at: 80, x: 180, y: 765 },
            { at: 104, x: 190, y: 880 },
            { at: 126, x: 500, y: 955 },
            { at: 240, x: 520, y: 960 },
            { at: 256, x: 1610, y: 962 },
            { at: 276, x: 1610, y: 962 },
            { at: 310, x: 1500, y: 640 },
            { at: 390, x: 1720, y: 520 },
          ]}
          clicks={[132, SEND_CLICK]}
          inAt={20}
          outAt={420}
        />
        <ThinkingCard x={333} y={196} inAt={ACT2_AT + 6} outAt={ACT3_AT - 4} stepEvery={13} />
        <Highlight x={330} y={192} w={155} h={38} inAt={ACT3_AT + 16} outAt={ACT3_AT + 70} />
      </MobilePanZoom>
      <MobileNavDrawer activePath="/nlp" targetPath="/intake" inAt={500} clickAt={524} />
    </MobileAppFrame>
    <MobileCaption
      text="Excel tabs, PDFs, a whiteboard photo, live feeds — one session, one question."
      accent="one session"
      inAt={48}
      outAt={116}
    />
    <MobileCaption
      text="No dashboards to build. No data to wrangle. Just ask — and get the correlated answer."
      accent="Just ask"
      inAt={ACT3_AT + 10}
      outAt={488}
    />
  </AbsoluteFill>
);
