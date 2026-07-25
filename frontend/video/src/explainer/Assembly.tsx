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
// slammed into the middle (w = 0.22 + 2.6*sin(pi*u)^4).
const BRIDGE_MAPS: Record<string, number[]> = {
  'bridge-a.mp4': [0.0, 0.162, 0.2305, 0.2782, 0.3174, 0.3505, 0.3806, 0.4102, 0.4393, 0.47, 0.503, 0.5379, 0.5755, 0.6122, 0.6502, 0.6904, 0.7308, 0.7727, 0.818, 0.8663, 0.9148, 0.9632, 1.0136, 1.0667, 1.1242, 1.1852, 1.2489, 1.3171, 1.3906, 1.4698, 1.552, 1.6395, 1.7306, 1.8231, 1.9184, 2.022, 2.1274, 2.2372, 2.3445, 2.452, 2.5587, 2.6644, 2.7725, 2.8825, 2.9944, 3.1096, 3.2256, 3.3425, 3.4591, 3.5724, 3.6795, 3.7826, 3.8826, 3.9809, 4.079, 4.181, 4.2856, 4.3955, 4.5185, 4.6587, 4.8173, 5.0],
  'bridge-b.mp4': [0.0, 0.1401, 0.2635, 0.3699, 0.478, 0.5927, 0.7232, 0.8623, 1.0118, 1.0931, 1.178, 1.2538, 1.3329, 1.4083, 1.4889, 1.5671, 1.6485, 1.7308, 1.8131, 1.8948, 1.9766, 2.0555, 2.1326, 2.2073, 2.2776, 2.3492, 2.4195, 2.49, 2.5596, 2.6313, 2.7049, 2.7757, 2.8468, 2.924, 3.0043, 3.0871, 3.1755, 3.2726, 3.3787, 3.4967, 3.6102, 3.7144, 3.8222, 3.9232, 4.0228, 4.1154, 4.1994, 4.2757, 4.3448, 4.4088, 4.4668, 4.5184, 4.5655, 4.6099, 4.6519, 4.6934, 4.7374, 4.7814, 4.8294, 4.8787, 4.9344, 5.0],
  'bridge-c.mp4': [0.0, 0.0748, 0.1493, 0.2222, 0.2934, 0.3572, 0.4184, 0.4795, 0.5371, 0.593, 0.6491, 0.7052, 0.763, 0.8249, 0.889, 0.9593, 1.0352, 1.1133, 1.1924, 1.2725, 1.3547, 1.44, 1.5306, 1.6205, 1.7107, 1.8011, 1.8916, 1.981, 2.0716, 2.1678, 2.263, 2.3567, 2.4461, 2.5314, 2.6117, 2.6918, 2.774, 2.859, 2.9432, 3.0253, 3.1075, 3.1907, 3.2747, 3.3636, 3.4611, 3.5515, 3.6346, 3.713, 3.7892, 3.8581, 3.9169, 3.9722, 4.0242, 4.0744, 4.1251, 4.1803, 4.2409, 4.318, 4.4144, 4.5708, 4.7823, 5.0],
  'bridge-d.mp4': [0.0, 0.1769, 0.3539, 0.5315, 0.7109, 0.8895, 1.0028, 1.0841, 1.1558, 1.2249, 1.2946, 1.3676, 1.4436, 1.5218, 1.6025, 1.6884, 1.7744, 1.8565, 1.9346, 2.0125, 2.0901, 2.1688, 2.2465, 2.3251, 2.404, 2.4829, 2.5596, 2.6363, 2.7138, 2.79, 2.8658, 2.9442, 3.0237, 3.1006, 3.1702, 3.2331, 3.2948, 3.3567, 3.4197, 3.4844, 3.5468, 3.606, 3.6618, 3.7126, 3.7643, 3.815, 3.8644, 3.9145, 3.9725, 4.0376, 4.1024, 4.1628, 4.2202, 4.2776, 4.3351, 4.3945, 4.4582, 4.5276, 4.6063, 4.7011, 4.8278, 5.0],
  'bridge-e.mp4': [0.0, 0.0362, 0.0734, 0.1093, 0.1453, 0.1819, 0.2204, 0.2624, 0.309, 0.3648, 0.443, 0.5584, 0.664, 0.7592, 0.8511, 0.9388, 1.0251, 1.1091, 1.1911, 1.2652, 1.3319, 1.3919, 1.448, 1.5037, 1.5621, 1.6229, 1.688, 1.7599, 1.8331, 1.9101, 1.9998, 2.1019, 2.1935, 2.2739, 2.3539, 2.4344, 2.5181, 2.6056, 2.6966, 2.788, 2.8779, 2.9669, 3.0569, 3.1493, 3.241, 3.3329, 3.4244, 3.5132, 3.5986, 3.6803, 3.7592, 3.8385, 3.9153, 3.9933, 4.0697, 4.1516, 4.2379, 4.3358, 4.4534, 4.6256, 4.8129, 5.0],
  'bridge-f.mp4': [0.0, 0.0288, 0.0561, 0.0824, 0.1047, 0.1269, 0.1461, 0.1665, 0.1849, 0.2054, 0.2273, 0.2523, 0.2794, 0.3105, 0.3454, 0.3838, 0.4282, 0.478, 0.5319, 0.5909, 0.6545, 0.7224, 0.7966, 0.8738, 0.9552, 1.0403, 1.1296, 1.2216, 1.3179, 1.4187, 1.5256, 1.6346, 1.7489, 1.8686, 1.9957, 2.1329, 2.2725, 2.4077, 2.5326, 2.6501, 2.7693, 2.883, 2.9987, 3.1175, 3.2409, 3.3778, 3.5214, 3.6506, 3.7585, 3.8337, 3.8905, 3.9385, 3.9957, 4.0587, 4.1384, 4.2405, 4.3576, 4.475, 4.5902, 4.7098, 4.845, 5.0],
  'bridge-g.mp4': [0.0, 0.0728, 0.1398, 0.2013, 0.2588, 0.3132, 0.3648, 0.4147, 0.4647, 0.5167, 0.571, 0.63, 0.6935, 0.7621, 0.8372, 0.9149, 0.9978, 1.0831, 1.1724, 1.2607, 1.352, 1.4436, 1.5327, 1.6189, 1.7065, 1.7958, 1.8853, 1.975, 2.0632, 2.1482, 2.2326, 2.3178, 2.4057, 2.4975, 2.6035, 2.7334, 2.8619, 2.9767, 3.086, 3.1948, 3.3032, 3.4109, 3.5176, 3.62, 3.7197, 3.8187, 3.9112, 3.9978, 4.079, 4.1564, 4.226, 4.2896, 4.3502, 4.4085, 4.4666, 4.5258, 4.5858, 4.6501, 4.7199, 4.7983, 4.8854, 5.0],
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
