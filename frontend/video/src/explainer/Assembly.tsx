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
// shapes the rest as a Vox whip: clip-ambient pace at both joints, motion
// slammed into the middle (w = 0.28 + 1.6*sin(pi*u)^2.5).
const BRIDGE_MAPS: Record<string, number[]> = {
  'bridge-a.mp4': [0.0, 0.2016, 0.2791, 0.337, 0.3826, 0.426, 0.4676, 0.5095, 0.5514, 0.5925, 0.6305, 0.6685, 0.7069, 0.7424, 0.78, 0.8192, 0.8599, 0.9003, 0.9401, 0.9806, 1.0218, 1.065, 1.1108, 1.1587, 1.2081, 1.2595, 1.3137, 1.3708, 1.4323, 1.4957, 1.5611, 1.6298, 1.7012, 1.7738, 1.8473, 1.9232, 2.005, 2.0884, 2.1749, 2.262, 2.3476, 2.4342, 2.5216, 2.6084, 2.6957, 2.7866, 2.8798, 2.9761, 3.0763, 3.1813, 3.2894, 3.4034, 3.5214, 3.6406, 3.762, 3.8901, 4.0259, 4.1741, 4.3357, 4.5161, 4.7344, 5.0],
  'bridge-b.mp4': [0.0, 0.2052, 0.3719, 0.5392, 0.732, 0.956, 1.0865, 1.1929, 1.2831, 1.3667, 1.4467, 1.5242, 1.5978, 1.6724, 1.7444, 1.8151, 1.8844, 1.9527, 2.0191, 2.0826, 2.145, 2.205, 2.2616, 2.3187, 2.3749, 2.4308, 2.4866, 2.5414, 2.5974, 2.6552, 2.7126, 2.7684, 2.8237, 2.8816, 2.9452, 3.0081, 3.0732, 3.1424, 3.2164, 3.2956, 3.3822, 3.4761, 3.5725, 3.6582, 3.7476, 3.8353, 3.9207, 4.007, 4.0898, 4.1685, 4.2418, 4.3124, 4.3799, 4.446, 4.5086, 4.569, 4.6293, 4.6905, 4.7576, 4.8284, 4.9056, 5.0],
  'bridge-c.mp4': [0.0, 0.1122, 0.2237, 0.3302, 0.4226, 0.5115, 0.5889, 0.6609, 0.7262, 0.7909, 0.8552, 0.9197, 0.9883, 1.0571, 1.1265, 1.1943, 1.2621, 1.3311, 1.3989, 1.4718, 1.5453, 1.6177, 1.6903, 1.762, 1.8347, 1.906, 1.9767, 2.0479, 2.1219, 2.1981, 2.273, 2.3472, 2.4181, 2.4867, 2.5525, 2.6155, 2.6787, 2.7434, 2.8105, 2.8781, 2.9457, 3.012, 3.0787, 3.1464, 3.215, 3.2856, 3.3614, 3.4452, 3.5268, 3.6035, 3.6785, 3.7531, 3.8278, 3.8961, 3.9611, 4.0279, 4.0978, 4.1763, 4.2732, 4.4122, 4.674, 5.0],
  'bridge-d.mp4': [0.0, 0.2663, 0.5351, 0.8105, 1.0084, 1.1236, 1.2197, 1.3088, 1.3953, 1.4794, 1.5601, 1.6407, 1.7217, 1.7985, 1.8696, 1.9365, 2.0027, 2.0672, 2.1316, 2.1959, 2.259, 2.3226, 2.3858, 2.4492, 2.5113, 2.5719, 2.6326, 2.6939, 2.7547, 2.8141, 2.8739, 2.9358, 2.9985, 3.0604, 3.1194, 3.1732, 3.2231, 3.2722, 3.3215, 3.3706, 3.4217, 3.4739, 3.5254, 3.575, 3.6225, 3.6686, 3.7113, 3.7556, 3.8006, 3.8456, 3.892, 3.9438, 4.0076, 4.0785, 4.1513, 4.2246, 4.304, 4.3902, 4.4891, 4.6047, 4.7596, 5.0],
  'bridge-e.mp4': [0.0, 0.0549, 0.1101, 0.1653, 0.2232, 0.2859, 0.3604, 0.4629, 0.5993, 0.7071, 0.8044, 0.8908, 0.9722, 1.0491, 1.1231, 1.193, 1.2564, 1.3126, 1.3644, 1.4124, 1.4571, 1.502, 1.5486, 1.5966, 1.6462, 1.6989, 1.7564, 1.8139, 1.8724, 1.9377, 2.0103, 2.0913, 2.1669, 2.2316, 2.2943, 2.3577, 2.4212, 2.487, 2.555, 2.6259, 2.6994, 2.7733, 2.8467, 2.9196, 2.993, 3.0688, 3.147, 3.226, 3.3069, 3.3897, 3.4736, 3.5578, 3.6434, 3.7298, 3.8231, 3.9213, 4.028, 4.1458, 4.2804, 4.4508, 4.7184, 5.0],
  'bridge-f.mp4': [0.0, 0.0431, 0.083, 0.117, 0.1475, 0.1763, 0.2037, 0.232, 0.2619, 0.2934, 0.3271, 0.362, 0.4001, 0.4418, 0.4867, 0.5333, 0.5832, 0.6352, 0.69, 0.7477, 0.8089, 0.8714, 0.9363, 1.004, 1.0724, 1.1443, 1.217, 1.2925, 1.3705, 1.453, 1.5367, 1.6226, 1.7118, 1.8052, 1.9004, 2.0021, 2.1104, 2.2209, 2.3329, 2.4376, 2.5362, 2.6302, 2.7283, 2.8233, 2.9151, 3.0141, 3.1146, 3.2208, 3.3384, 3.4672, 3.5918, 3.7124, 3.8016, 3.8719, 3.9284, 4.0003, 4.0932, 4.2328, 4.4098, 4.5878, 4.7754, 5.0],
  'bridge-g.mp4': [0.0, 0.1074, 0.2025, 0.2888, 0.3683, 0.4414, 0.5128, 0.5825, 0.6532, 0.7242, 0.7976, 0.8715, 0.9458, 1.0214, 1.0973, 1.1745, 1.2492, 1.3254, 1.4005, 1.4755, 1.5467, 1.6163, 1.6864, 1.7572, 1.8288, 1.8997, 1.9707, 2.041, 2.1084, 2.1752, 2.2415, 2.3086, 2.3773, 2.4477, 2.5234, 2.609, 2.7109, 2.8172, 2.9124, 3.0019, 3.0894, 3.177, 3.2652, 3.3539, 3.4426, 3.5312, 3.6176, 3.7034, 3.791, 3.8764, 3.9593, 4.0406, 4.1214, 4.2009, 4.2775, 4.3547, 4.4352, 4.5217, 4.6144, 4.7184, 4.8403, 5.0],
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
  let whip = 0; // 0..1 intensity of the whip mid-bridge
  if (piece.ease) {
    const map = BRIDGE_MAPS[piece.src];
    const srcSec = map[Math.min(map.length - 1, frame)];
    trimBefore = Math.max(0, Math.round(srcSec * FPS) - frame);
    playbackRate = 1;
    whip = Math.pow(Math.sin(Math.PI * Math.min(1, frame / (map.length - 1))), 2.5);
  }
  return (
    <AbsoluteFill style={{ opacity: fadeIn, background: '#0a0a0a' }}>
      <OffthreadVideo
        src={staticFile(`explainer/${piece.src}`)}
        trimBefore={trimBefore}
        playbackRate={playbackRate}
        muted
        style={{
          width: W,
          height: H,
          objectFit: 'cover',
          filter: whip > 0.08 ? `blur(${(whip * 13).toFixed(1)}px)` : undefined,
          transform: whip > 0.08 ? `scale(${(1 + whip * 0.05).toFixed(3)})` : undefined,
        }}
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
