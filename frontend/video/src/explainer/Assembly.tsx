import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  OffthreadVideo,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import { theme } from '../theme';
import { Wordmark } from '../components/Wordmark';

/**
 * "The Gaps Are Expensive" — Vox-style explainer, assembled from the
 * Higgsfield footage in public/explainer/ (gitignored; see
 * out/marketing/explainer-higgsfield/PROMPTS.txt for the source kit).
 *
 * Everything an editor would keyframe lives in TIMELINE / CAPTIONS below:
 * per-piece trims (seconds of source), playback rate, joint treatment
 * (wipe direction / dissolve overlap), and caption copy + timing.
 * 1080x1920 @30fps master; footage is 24fps and resampled by Remotion.
 */

const FPS = 30;
const W = 1080;
const H = 1920;

const BLUE = theme.highlight; // #3b82f6
const GREEN = '#4ade80';
const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';

type Joint = { wipe?: 'left' | 'right' | 'up' | 'down'; dissolve?: number };

type Piece = {
  src: string;
  /** seconds trimmed off the source head/tail (at source speed) */
  in?: number;
  out?: number;
  /** playback rate; footage 1x */
  rate?: number;
  /** eased bridge: plays FULL source with a 1x->peak->1x speed curve so
   *  both joints match the neighbouring clips in speed and geometry */
  ease?: boolean;
  /** treatment applied at the CUT INTO this piece */
  joint?: Joint;
};

// ---------------------------------------------------------------- timeline
// Source clips are ~5.04s. Bridges: trim tail (the settle), run fast, and
// the wipe on the joint into the NEXT piece hides the morphiest frames.
const TIMELINE: Piece[] = [
  { src: 'clip-01.mp4' },
  { src: 'bridge-a.mp4', ease: true },
  { src: 'clip-02.mp4', joint: { wipe: 'up' } },
  { src: 'bridge-b.mp4', ease: true },
  { src: 'clip-03.mp4', joint: { wipe: 'down' } },
  { src: 'clip-04.mp4' }, // hard cut on VO beat "opportunity shows up"
  { src: 'clip-05.mp4', joint: { dissolve: 12 } }, // growth hides... buried
  { src: 'bridge-c.mp4', ease: true },
  { src: 'clip-06.mp4', joint: { wipe: 'up' } },
  { src: 'bridge-d.mp4', ease: true },
  { src: 'clip-07.mp4', joint: { wipe: 'down' } },
  { src: 'clip-08a.mp4' }, // THE hard cut - masked by line motion
  { src: 'clip-08b.mp4', joint: { wipe: 'right' } },
  { src: 'clip-08c.mp4', joint: { wipe: 'right' } },
  { src: 'clip-09.mp4', joint: { wipe: 'right' } },
  { src: 'bridge-e.mp4', ease: true },
  { src: 'clip-10.mp4', joint: { wipe: 'up' } },
  { src: 'bridge-f.mp4', ease: true },
  { src: 'clip-11.mp4', joint: { wipe: 'up' } },
  { src: 'bridge-g.mp4', ease: true },
  { src: 'clip-12.mp4', joint: { wipe: 'down' } },
];

const SRC_LEN = 5.04; // seconds per Higgsfield clip
const END_CARD_FRAMES = Math.round(5.05 * FPS);

/** VO file: drop the ElevenLabs render at public/explainer/vo.mp3 and set true. */
const HAS_VO = true;
/** Music bed: public/explainer/music.mp3 (Pixel Lift), ducked under the VO. */
const HAS_MUSIC = true;

// Constant-motion time maps per bridge (measured from per-frame pixel
// motion): comp frame -> source seconds. Playback sprints through each
// bridge's static head/tail (near-duplicates of the matched stills) and
// spends its time where the travel actually happens.
const BRIDGE_MAPS: Record<string, number[]> = {
  'bridge-a.mp4': [0.0, 0.3613, 0.4902, 0.5883, 0.6587, 0.7172, 0.7655, 0.8109, 0.8536, 0.8929, 0.9287, 0.9624, 0.9948, 1.0257, 1.0566, 1.0879, 1.1189, 1.1499, 1.1807, 1.2112, 1.2419, 1.2727, 1.304, 1.3359, 1.3683, 1.4021, 1.4362, 1.4706, 1.5054, 1.5404, 1.5766, 1.6137, 1.6519, 1.6904, 1.7296, 1.7693, 1.8094, 1.8504, 1.8926, 1.9371, 1.9843, 2.0334, 2.0831, 2.1354, 2.1907, 2.2468, 2.3049, 2.3631, 2.4258, 2.492, 2.5606, 2.6335, 2.7119, 2.8007, 2.8997, 3.0134, 3.1502, 3.3176, 3.5348, 3.8215, 4.2475, 5.0],
  'bridge-b.mp4': [0.0, 0.6411, 1.1475, 1.3575, 1.5061, 1.6198, 1.7173, 1.8006, 1.8742, 1.9399, 2.0008, 2.0541, 2.1038, 2.1509, 2.194, 2.2336, 2.2713, 2.3082, 2.3443, 2.3783, 2.4119, 2.4447, 2.4769, 2.5084, 2.5391, 2.57, 2.6009, 2.6321, 2.6642, 2.695, 2.7257, 2.756, 2.7851, 2.8152, 2.846, 2.8777, 2.9122, 2.9479, 2.9834, 3.0188, 3.0561, 3.0965, 3.138, 3.1824, 3.2304, 3.2816, 3.3378, 3.3993, 3.4663, 3.5413, 3.612, 3.6831, 3.7643, 3.8481, 3.9391, 4.0385, 4.1459, 4.2597, 4.3877, 4.5362, 4.7212, 5.0],
  'bridge-c.mp4': [0.0, 0.3785, 0.6278, 0.7833, 0.9032, 1.0088, 1.1001, 1.1805, 1.252, 1.318, 1.3788, 1.4385, 1.4973, 1.5521, 1.6042, 1.6547, 1.7027, 1.749, 1.7945, 1.8391, 1.8819, 1.9237, 1.9644, 2.0049, 2.0448, 2.0852, 2.1266, 2.1688, 2.2094, 2.25, 2.2902, 2.3307, 2.3689, 2.4074, 2.4452, 2.4825, 2.5192, 2.5552, 2.5907, 2.6263, 2.6627, 2.7006, 2.7394, 2.78, 2.8228, 2.8665, 2.9115, 2.9581, 3.0057, 3.0558, 3.109, 3.1661, 3.2281, 3.2966, 3.3774, 3.477, 3.5811, 3.6968, 3.836, 3.9924, 4.2185, 5.0],
  'bridge-d.mp4': [0.0, 0.9354, 1.2681, 1.47, 1.6204, 1.7451, 1.8434, 1.9231, 1.9926, 2.0554, 2.1129, 2.1675, 2.2175, 2.2649, 2.3106, 2.3545, 2.3968, 2.4378, 2.4772, 2.5151, 2.5514, 2.5871, 2.6221, 2.6569, 2.6912, 2.7251, 2.7584, 2.7908, 2.8232, 2.8554, 2.8881, 2.9215, 2.955, 2.989, 3.0229, 3.0566, 3.0898, 3.1218, 3.1524, 3.182, 3.2108, 3.2397, 3.2692, 3.2993, 3.3303, 3.3622, 3.3959, 3.4315, 3.469, 3.508, 3.5479, 3.589, 3.6312, 3.6753, 3.7207, 3.7729, 3.8318, 3.9041, 4.0157, 4.1848, 4.4353, 5.0],
  'bridge-e.mp4': [0.0, 0.1952, 0.4093, 0.6956, 0.8701, 0.9959, 1.0951, 1.1792, 1.2475, 1.3027, 1.3497, 1.3909, 1.4276, 1.4613, 1.4935, 1.5253, 1.5568, 1.588, 1.6185, 1.6494, 1.6807, 1.7126, 1.7465, 1.7788, 1.8113, 1.8439, 1.8761, 1.911, 1.9482, 1.9871, 2.0282, 2.0725, 2.1155, 2.1558, 2.1926, 2.2277, 2.2622, 2.2971, 2.3326, 2.3687, 2.4053, 2.4433, 2.4828, 2.5242, 2.5677, 2.6136, 2.6621, 2.7131, 2.7663, 2.8217, 2.8795, 2.9409, 3.0068, 3.0802, 3.1633, 3.2562, 3.365, 3.4945, 3.6532, 3.8675, 4.206, 5.0],
  'bridge-f.mp4': [0.0, 0.1336, 0.2188, 0.2896, 0.3531, 0.4121, 0.4694, 0.5235, 0.5754, 0.6254, 0.6741, 0.7212, 0.7683, 0.8148, 0.8597, 0.9039, 0.9477, 0.9917, 1.0341, 1.0768, 1.1197, 1.1625, 1.2042, 1.2468, 1.2892, 1.3324, 1.3754, 1.4198, 1.4658, 1.5113, 1.5563, 1.6027, 1.6501, 1.6983, 1.7478, 1.7993, 1.8514, 1.9046, 1.9606, 2.02, 2.0826, 2.1482, 2.214, 2.2824, 2.3518, 2.4194, 2.488, 2.5536, 2.6211, 2.6952, 2.7714, 2.8503, 2.9331, 3.0291, 3.1359, 3.2623, 3.4283, 3.6213, 3.8103, 3.9566, 4.3183, 5.0],
  'bridge-g.mp4': [0.0, 0.3327, 0.5501, 0.7161, 0.8531, 0.9682, 1.0684, 1.1588, 1.2377, 1.3111, 1.3788, 1.4419, 1.5008, 1.5532, 1.6032, 1.6516, 1.6986, 1.7444, 1.7894, 1.8332, 1.8756, 1.9175, 1.9585, 1.9988, 2.038, 2.0758, 2.1125, 2.149, 2.1852, 2.221, 2.2569, 2.2928, 2.3296, 2.3668, 2.4047, 2.4433, 2.4836, 2.5268, 2.5735, 2.6248, 2.6839, 2.7484, 2.8111, 2.8704, 2.9288, 2.9866, 3.0454, 3.1057, 3.1686, 3.2352, 3.3051, 3.3795, 3.459, 3.5445, 3.6354, 3.7362, 3.8517, 3.98, 4.1307, 4.313, 4.5642, 5.0],
};
const BRIDGE_COMP_SEC = 2.07; // eased bridges: full 5.04s source in 2.07s
const pieceFrames = (p: Piece) => {
  if (p.ease) return Math.round(BRIDGE_COMP_SEC * FPS);
  const usable = SRC_LEN - (p.in ?? 0) - (p.out ?? 0);
  return Math.round((usable / (p.rate ?? 1)) * FPS);
};

// absolute start frame of each piece (dissolves overlap backwards)
const starts: number[] = [];
{
  let t = 0;
  for (const p of TIMELINE) {
    const overlap = p.joint?.dissolve ?? 0;
    starts.push(Math.max(0, t - overlap));
    t = Math.max(0, t - overlap) + pieceFrames(p);
  }
}
export const EXPLAINER_DURATION =
  starts[starts.length - 1] + pieceFrames(TIMELINE[TIMELINE.length - 1]) + END_CARD_FRAMES;

// ---------------------------------------------------------------- captions
type Caption = {
  /** seconds on the master timeline */
  at: number;
  dur: number;
  text: string;
  /** substring rendered with the blue highlighter swipe */
  hi?: string;
  mono?: boolean;
  color?: string;
  /** render the split-weight brand wordmark instead of text */
  wordmark?: boolean;
};

const CAPTIONS: Caption[] = [
  { at: 1.6, dur: 3.4, text: 'MADE IN A DAY. READ IN A YEAR.', hi: 'READ IN A YEAR' },   // "data in a day" @1.2
  { at: 10.0, dur: 4.2, text: 'THREE DEPARTMENTS. THREE VERSIONS OF THE TRUTH.', hi: 'THREE VERSIONS' }, // spoken @10.1
  { at: 14.2, dur: 3.2, text: 'NOT BROKEN. JUST BLIND.', hi: 'BLIND' },                  // "isn't broken" @14.0
  { at: 18.0, dur: 4.6, text: '12,000 UNITS. BY FRIDAY. CAN YOU SAY YES?', hi: 'CAN YOU SAY YES?' }, // "12,000" @17.0, order clip @18.8
  { at: 23.2, dur: 4.6, text: 'GROWTH HIDES IN YOUR DATA.', hi: 'IN YOUR DATA' },        // "growth hides" @23.2, buried clip @23.4
  { at: 31.1, dur: 3.6, text: '', wordmark: true },                                      // floor plan lands @31.0
  { at: 66.3, dur: 4.4, text: 'MEETINGS, REPLACED BY A CONVERSATION WITH YOUR DATA.', hi: 'CONVERSATION' }, // @66.3
  { at: 74.2, dur: 3.8, text: 'WHEREVER DATA PILES UP, SO DOES OPPORTUNITY.', hi: 'OPPORTUNITY' }, // @74.3
  { at: 79.2, dur: 3.8, text: "SHIPPED FRIDAY. THE NEXT ONE'S ALREADY INBOUND.", hi: 'ALREADY INBOUND' }, // "shipped" @79.3
];

/** The question beat: the dashboard's actual Correlation AI composer,
 *  typed live. Mirrors CorrelationAIPane's input + Send button. */
const CHAT = {
  at: 38.2,
  dur: 4.2,
  text: 'Can we take the 12,000-unit rush order and still ship Friday?',
  typeSeconds: 2.6,
};

// ---------------------------------------------------------------- pieces
const ClipPiece: React.FC<{ piece: Piece }> = ({ piece }) => {
  const frame = useCurrentFrame();
  const fadeIn = piece.joint?.dissolve
    ? interpolate(frame, [0, piece.joint.dissolve], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      })
    : 1;
  // eased bridges: remap comp time -> source time along a smooth bell so the
  // joint speeds match the neighbouring 1x clips (no velocity snap) and the
  // full source plays (no geometry skip at either end).
  let trimBefore = Math.round((piece.in ?? 0) * FPS);
  let playbackRate = piece.rate ?? 1;
  if (piece.ease) {
    const map = BRIDGE_MAPS[piece.src];
    const srcSec = map[Math.min(map.length - 1, frame)];
    trimBefore = Math.max(0, Math.round(srcSec * FPS) - frame);
    playbackRate = 1;
  }
  return (
    <AbsoluteFill style={{ opacity: fadeIn, background: '#0a0a0a' }}>
      <OffthreadVideo
        src={staticFile(`explainer/${piece.src}`)}
        trimBefore={trimBefore}
        playbackRate={playbackRate}
        muted
        style={{ width: W, height: H, objectFit: 'cover' }}
      />
    </AbsoluteFill>
  );
};

/** Brand-blue light streak sweeping across the frame — the signal carrying
 *  us to the next place. Covers the joint (last frames of prev piece +
 *  first frames of this one). */
const SignalWipe: React.FC<{ dir: 'left' | 'right' | 'up' | 'down' }> = ({ dir }) => {
  const frame = useCurrentFrame();
  const DUR = 12;
  const t = interpolate(frame, [0, DUR], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  if (frame > DUR) return null;
  const vertical = dir === 'up' || dir === 'down';
  const sign = dir === 'right' || dir === 'down' ? 1 : -1;
  const travel = (vertical ? H : W) * 1.8;
  const pos = sign * (t * travel - travel / 2);
  const fade = Math.sin(Math.PI * t); // in and out
  return (
    <AbsoluteFill style={{ pointerEvents: 'none' }}>
      <div
        style={{
          position: 'absolute',
          left: vertical ? 0 : W / 2 + pos - 200,
          top: vertical ? H / 2 + pos - 200 : 0,
          width: vertical ? W : 400,
          height: vertical ? 400 : H,
          opacity: fade,
          background: `linear-gradient(${vertical ? '180deg' : '90deg'},
            transparent 0%, ${BLUE}22 30%, ${BLUE}ee 50%, ${BLUE}22 70%, transparent 100%)`,
          filter: 'blur(6px)',
        }}
      />
    </AbsoluteFill>
  );
};


const ChatBar: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const start = Math.round(CHAT.at * fps);
  const end = start + Math.round(CHAT.dur * fps);
  if (frame < start || frame >= end) return null;
  const local = frame - start;
  const pop = spring({ frame: local, fps, config: { damping: 15, stiffness: 160 }, durationInFrames: 22 });
  const outFade = interpolate(frame, [end - 8, end], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const typedChars = Math.round(
    interpolate(local, [8, 8 + CHAT.typeSeconds * fps], [0, CHAT.text.length], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    })
  );
  const typed = CHAT.text.slice(0, typedChars);
  const doneTyping = typedChars >= CHAT.text.length;
  const caretOn = Math.floor(local / 15) % 2 === 0 && !doneTyping;
  return (
    <AbsoluteFill style={{ pointerEvents: 'none' }}>
      <div
        style={{
          position: 'absolute',
          left: 60,
          right: 60,
          bottom: 560,
          opacity: outFade,
          transform: `translateY(${(1 - pop) * 50}px)`,
          background: '#171717',
          border: '2px solid #2e2e2e',
          borderRadius: 20,
          boxShadow: '0 0 70px rgba(59,130,246,0.14), 0 30px 80px rgba(0,0,0,0.55)',
          overflow: 'hidden',
          fontFamily: theme.fontFamily,
        }}
      >
        {/* window header — brand law: UI is always framed as a window */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '14px 22px',
            borderBottom: '2px solid #2e2e2e',
          }}
        >
          {['#f87171', '#fbbf24', '#4ade80'].map((c) => (
            <div key={c} style={{ width: 12, height: 12, borderRadius: 6, background: c, opacity: 0.85 }} />
          ))}
          <span style={{ marginLeft: 10, fontSize: 24, fontWeight: 600, color: '#a3a3a3' }}>
            Correlation AI
          </span>
        </div>
        {/* the composer row, mirroring CorrelationAIPane's Input + Send */}
        <div style={{ display: 'flex', gap: 14, padding: 20 }}>
          <div
            style={{
              flex: 1,
              minWidth: 0,
              border: '2px solid #2e2e2e',
              borderRadius: 12,
              background: '#0a0a0a',
              padding: '16px 20px',
              fontSize: 30,
              lineHeight: 1.35,
              color: typed ? '#fafafa' : '#525252',
              minHeight: 78,
            }}
          >
            {typed || 'Ask anything about your uploaded data...'}
            {caretOn && typed ? (
              <span style={{ borderLeft: `3px solid ${BLUE}`, marginLeft: 2 }} />
            ) : null}
          </div>
          <div
            style={{
              width: 78,
              borderRadius: 12,
              background: doneTyping ? BLUE : '#2e2e2e',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              alignSelf: 'stretch',
              flexShrink: 0,
            }}
          >
            {/* Send (paper plane), as in the app */}
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="m22 2-7 20-4-9-9-4Z" />
              <path d="M22 2 11 13" />
            </svg>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};


/** The correlation answer as it assembles in the dashboard: one
 *  Correlation AI window that accumulates receipt rows as each source
 *  answers, then lands the scored verdict + attached actions.
 *  Component metrics follow BRAND.md sec.6b (chips, score badge). */
const ANSWER = {
  at: 40.0,
  out: 65.6,
  rows: [
    { at: 40.3, chip: 'XLSX', tone: 'blue' as const, src: 'order-book_aug.xlsx', bold: '3,000 units/day', rest: " — Line 2's sweet spot" },
    { at: 44.5, chip: 'PDF', tone: 'blue' as const, src: 'pm-log_line2.pdf', bold: 'serviced last Tuesday', rest: ' — nothing due this week' },
    { at: 47.9, chip: 'YMS', tone: 'neutral' as const, src: 'TR-2214', bold: 'materials for the full run', rest: ' — checked in Tue' },
    { at: 52.1, chip: '● LIVE', tone: 'green' as const, src: 'Lines 1–3', bold: '58% load', rest: ' · vibration clean · headroom to spare' },
  ],
  verdictAt: 58.6,
  actionsAt: 62.4,
  kanbanAt: 64.8,
};

const CHIP_TONES = {
  blue: { border: 'rgba(59,130,246,0.45)', bg: 'rgba(59,130,246,0.10)', color: '#93c5fd' },
  green: { border: 'rgba(74,222,128,0.5)', bg: 'rgba(74,222,128,0.10)', color: GREEN },
  neutral: { border: '#2e2e2e', bg: 'rgba(255,255,255,0.05)', color: '#a3a3a3' },
};

const AnswerPanel: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const start = Math.round(ANSWER.at * fps);
  const end = Math.round(ANSWER.out * fps);
  if (frame < start || frame >= end) return null;
  const pop = spring({ frame: frame - start, fps, config: { damping: 15, stiffness: 160 }, durationInFrames: 22 });
  const outFade = interpolate(frame, [end - 10, end], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const verdictOn = frame >= Math.round(ANSWER.verdictAt * fps);
  const vPop = spring({ frame: frame - Math.round(ANSWER.verdictAt * fps), fps, config: { damping: 13, stiffness: 180 }, durationInFrames: 26 });
  return (
    <AbsoluteFill style={{ pointerEvents: 'none' }}>
      <div
        style={{
          position: 'absolute',
          left: 56,
          right: 56,
          bottom: 430,
          opacity: outFade,
          transform: `translateY(${(1 - pop) * 50}px)`,
          background: 'rgba(23,23,23,0.94)',
          border: `2px solid ${verdictOn ? 'rgba(74,222,128,0.5)' : '#2e2e2e'}`,
          borderRadius: 20,
          boxShadow: '0 0 90px rgba(59,130,246,0.16), 0 30px 80px rgba(0,0,0,0.55)',
          padding: '16px 22px 18px',
          fontFamily: theme.fontFamily,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          {['#f87171', '#fbbf24', '#4ade80'].map((c) => (
            <div key={c} style={{ width: 11, height: 11, borderRadius: 6, background: c, opacity: 0.85 }} />
          ))}
          <span style={{ marginLeft: 8, fontSize: 22, fontWeight: 600, color: '#a3a3a3' }}>Correlation AI</span>
          <span style={{ marginLeft: 'auto', fontSize: 19, fontFamily: MONO, color: '#525252' }}>
            {verdictOn ? 'answer · scored' : 'cross-referencing 4 sources…'}
          </span>
        </div>
        {ANSWER.rows.map((r, i) => {
          const rs = Math.round(r.at * fps);
          if (frame < rs) return null;
          const rp = spring({ frame: frame - rs, fps, config: { damping: 14, stiffness: 170 }, durationInFrames: 22 });
          const tone = CHIP_TONES[r.tone];
          return (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '9px 0',
                opacity: (verdictOn ? 0.62 : 1) * rp,
                transform: `translateX(${(1 - rp) * -34}px)`,
                whiteSpace: 'nowrap',
              }}
            >
              <span
                style={{
                  padding: '5px 14px',
                  borderRadius: 999,
                  border: `2.5px solid ${tone.border}`,
                  background: tone.bg,
                  color: tone.color,
                  fontSize: 19,
                  fontWeight: 700,
                  flexShrink: 0,
                }}
              >
                {r.chip}
              </span>
              <span style={{ fontFamily: MONO, fontSize: 20, color: '#a3a3a3', flexShrink: 0 }}>{r.src}</span>
              <span style={{ fontSize: 23, color: '#fafafa', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                <b>{r.bold}</b>
                {r.rest}
              </span>
            </div>
          );
        })}
        {verdictOn ? (
          <div style={{ opacity: vPop, transform: `translateY(${(1 - vPop) * 24}px)` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '14px 0 10px', borderTop: '2px solid #2e2e2e', marginTop: 8 }}>
              <span
                style={{
                  fontFamily: MONO,
                  fontSize: 30,
                  fontWeight: 800,
                  color: GREEN,
                  border: '3px solid rgba(74,222,128,0.5)',
                  background: 'rgba(74,222,128,0.10)',
                  borderRadius: 14,
                  padding: '8px 20px',
                  flexShrink: 0,
                }}
              >
                GO · 96
              </span>
              <span style={{ fontSize: 27, fontWeight: 700, color: '#fafafa' }}>
                Take the order — Line 2 covers it.
              </span>
            </div>
            {frame >= Math.round(ANSWER.actionsAt * fps) ? (
              <div style={{ display: 'flex', gap: 10, marginTop: 6, whiteSpace: 'nowrap' }}>
                {[
                  { t: 'Confirm — reply to Sales', filled: true },
                  { t: 'Kanban → Production ✓', filled: false },
                  { t: 'Dock 2 + carrier ✓', filled: false },
                ].map((a, i) => {
                  const as_ = Math.round(ANSWER.actionsAt * fps) + i * 7;
                  if (frame < as_) return null;
                  const ap = spring({ frame: frame - as_, fps, config: { damping: 14, stiffness: 190 }, durationInFrames: 18 });
                  return (
                    <span
                      key={i}
                      style={{
                        opacity: ap,
                        transform: `scale(${0.9 + 0.1 * ap})`,
                        fontSize: 20,
                        fontWeight: 700,
                        padding: '9px 18px',
                        borderRadius: 999,
                        background: a.filled ? BLUE : 'transparent',
                        border: a.filled ? `2.5px solid ${BLUE}` : '2.5px solid #2e2e2e',
                        color: a.filled ? '#ffffff' : '#a3a3a3',
                      }}
                    >
                      {a.t}
                    </span>
                  );
                })}
              </div>
            ) : null}
            {frame >= Math.round(ANSWER.kanbanAt * fps) ? (() => {
              const ks = Math.round(ANSWER.kanbanAt * fps);
              const kp = spring({ frame: frame - ks, fps, config: { damping: 15, stiffness: 150 }, durationInFrames: 30 });
              // card slides from QUEUED lane into PRODUCTION lane
              const slide = interpolate(kp, [0, 1], [0, 100]);
              return (
                <div style={{ display: 'flex', gap: 10, marginTop: 12, opacity: Math.min(1, kp * 2) }}>
                  {['QUEUED', 'PRODUCTION'].map((lane, li) => (
                    <div
                      key={lane}
                      style={{
                        flex: 1,
                        border: '2px solid #2e2e2e',
                        borderRadius: 12,
                        padding: '8px 10px',
                        minHeight: 74,
                        background: 'rgba(255,255,255,0.03)',
                        position: 'relative',
                        overflow: 'hidden',
                      }}
                    >
                      <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: 3, color: '#525252', marginBottom: 6 }}>
                        {lane}{' '}
                        <span style={{ fontFamily: MONO, color: li === 0 ? '#525252' : GREEN }}>
                          {li === 0 ? (slide > 55 ? '3' : '4') : slide > 55 ? '6' : '5'}
                        </span>
                      </div>
                      {/* the rush order's card, mid-flight between lanes */}
                      {li === 0 ? (
                        <div
                          style={{
                            position: 'absolute',
                            left: `${10 + slide * 1.15}%`,
                            right: 'auto',
                            width: '84%',
                            opacity: slide > 96 ? 0 : 1,
                            background: '#0a0a0a',
                            border: '2px solid #2e2e2e',
                            borderLeft: `6px solid ${slide > 55 ? GREEN : BLUE}`,
                            borderRadius: 8,
                            padding: '7px 10px',
                            fontFamily: MONO,
                            fontSize: 17,
                            color: '#fafafa',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          RUSH-12K · Line 2
                        </div>
                      ) : (
                        slide > 96 && (
                          <div
                            style={{
                              width: '84%',
                              background: '#0a0a0a',
                              border: '2px solid rgba(74,222,128,0.4)',
                              borderLeft: `6px solid ${GREEN}`,
                              borderRadius: 8,
                              padding: '7px 10px',
                              fontFamily: MONO,
                              fontSize: 17,
                              color: '#fafafa',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            RUSH-12K · Line 2 <span style={{ color: GREEN }}>✓ Fri</span>
                          </div>
                        )
                      )}
                    </div>
                  ))}
                </div>
              );
            })() : null}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

const CaptionLayer: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ pointerEvents: 'none' }}>
      {CAPTIONS.map((c, i) => {
        const start = Math.round(c.at * fps);
        const end = start + Math.round(c.dur * fps);
        if (frame < start || frame >= end) return null;
        const local = frame - start;
        const pop = spring({ frame: local, fps, config: { damping: 14, stiffness: 170 }, durationInFrames: 24 });
        const outFade = interpolate(frame, [end - 8, end], [1, 0], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });
        const swipe = interpolate(local, [10, 26], [0, 100], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });
        const parts = c.hi ? c.text.split(c.hi) : [c.text];
        if (c.wordmark) {
          const line = interpolate(local, [8, 26], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
          return (
            <div
              key={i}
              style={{
                position: 'absolute',
                left: 0,
                right: 0,
                bottom: 620,
                opacity: outFade,
                transform: `translateY(${(1 - pop) * 40}px)`,
                textAlign: 'center',
                fontFamily: theme.fontFamily,
              }}
            >
              <div style={{ fontSize: 100, color: '#fafafa', letterSpacing: -2, textShadow: '0 4px 40px rgba(0,0,0,0.85)' }}>
                <Wordmark />
              </div>
              <div
                style={{
                  height: 6,
                  width: `${line * 300}px`,
                  margin: '14px auto 0',
                  borderRadius: 3,
                  background: BLUE,
                }}
              />
            </div>
          );
        }
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: 70,
              right: 70,
              // captions live in the middle 4:5 zone so the feed crop is free
              bottom: 560,
              opacity: outFade,
              transform: `translateY(${(1 - pop) * 40}px)`,
              fontFamily: c.mono ? MONO : theme.fontFamily,
              fontSize: c.mono ? 44 : 76,
              fontWeight: c.mono ? 700 : 800,
              letterSpacing: c.mono ? 0 : -1.5,
              lineHeight: 1.18,
              color: c.color ?? '#ffffff',
              textShadow: '0 4px 40px rgba(0,0,0,0.85)',
            }}
          >
            {c.hi ? (
              <>
                {parts[0]}
                <span style={{ position: 'relative', whiteSpace: 'nowrap' }}>
                  <span
                    style={{
                      position: 'absolute',
                      left: -6,
                      right: `${100 - swipe}%`,
                      top: '8%',
                      bottom: '2%',
                      background: `${BLUE}55`,
                      borderRadius: 8,
                    }}
                  />
                  <span style={{ position: 'relative' }}>{c.hi}</span>
                </span>
                {parts[1]}
              </>
            ) : (
              c.text
            )}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

/** Brand outro — real logo files, never generated. */
const EndCard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const opacity = interpolate(frame, [0, 18], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const s = spring({ frame, fps, config: { damping: 16 }, durationInFrames: 40 });
  return (
    <AbsoluteFill
      style={{
        background: '#0a0a0a',
        opacity,
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: theme.fontFamily,
      }}
    >
      <AbsoluteFill
        style={{
          backgroundImage: `linear-gradient(${'#1b1b1f'} 1px, transparent 1px), linear-gradient(90deg, ${'#1b1b1f'} 1px, transparent 1px)`,
          backgroundSize: '60px 60px',
          opacity: 0.5,
          maskImage: 'radial-gradient(ellipse at center, black 20%, transparent 78%)',
          WebkitMaskImage: 'radial-gradient(ellipse at center, black 20%, transparent 78%)',
        }}
      />
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 40,
          transform: `scale(${0.92 + 0.08 * s})`,
          zIndex: 1,
        }}
      >
        <div style={{ width: 160, height: 160, borderRadius: 36, background: '#ffffff', overflow: 'hidden' }}>
          <Img src={staticFile('omniusgrid-logo.png')} style={{ width: 160, height: 160 }} />
        </div>
        <div style={{ fontSize: 84, color: '#fafafa', letterSpacing: -2, lineHeight: 1 }}>
          <Wordmark />
        </div>
        <div style={{ height: 6, width: 230, borderRadius: 3, background: BLUE }} />
        <div style={{ fontSize: 38, fontWeight: 700, color: '#fafafa', textAlign: 'center', lineHeight: 1.35 }}>
          Unleash the power of{' '}
          <span style={{ color: BLUE }}>data correlation</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 8 }}>
          <span style={{ fontSize: 22, fontWeight: 500, color: '#a3a3a3' }}>by</span>
          <div
            style={{
              background: '#ffffff',
              borderRadius: 999,
              padding: '10px 22px',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <Img src={staticFile('soundsafe-logo.png')} style={{ height: 40 }} />
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- master
export const ExplainerAssembly: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: '#0a0a0a' }}>
      {TIMELINE.map((p, i) => (
        <Sequence key={i} from={starts[i]} durationInFrames={pieceFrames(p)}>
          <ClipPiece piece={p} />
          {p.joint?.wipe ? <SignalWipe dir={p.joint.wipe} /> : null}
        </Sequence>
      ))}
      <Sequence from={EXPLAINER_DURATION - END_CARD_FRAMES} durationInFrames={END_CARD_FRAMES}>
        <EndCard />
      </Sequence>
      <CaptionLayer />
      <ChatBar />
      <AnswerPanel />
      {HAS_VO ? <Audio src={staticFile('explainer/vo.mp3')} /> : null}
      {HAS_MUSIC ? (
        <Audio
          src={staticFile('explainer/music.mp3')}
          volume={(f) =>
            interpolate(
              f,
              // ducked bed under speech; brief lift at the turn (28-29s
              // speech gap); swell after the sign-off; fade at the tail
              [0, 2660, 2688],
              [0.22, 0.22, 0],
              { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
            )
          }
        />
      ) : null}
    </AbsoluteFill>
  );
};
