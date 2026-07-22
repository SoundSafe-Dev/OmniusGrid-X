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
  /** playback rate; bridges run ~3x, footage 1x */
  rate?: number;
  /** treatment applied at the CUT INTO this piece */
  joint?: Joint;
};

// ---------------------------------------------------------------- timeline
// Source clips are ~5.04s. Bridges: trim tail (the settle), run fast, and
// the wipe on the joint into the NEXT piece hides the morphiest frames.
const TIMELINE: Piece[] = [
  { src: 'clip-01.mp4' },
  { src: 'bridge-a.mp4', in: 0.2, out: 0.7, rate: 3 },
  { src: 'clip-02.mp4', in: 0.25, joint: { wipe: 'up' } },
  { src: 'bridge-b.mp4', in: 0.2, out: 0.7, rate: 3 },
  { src: 'clip-03.mp4', in: 0.25, joint: { wipe: 'down' } },
  { src: 'clip-04.mp4' }, // hard cut on VO beat "opportunity shows up"
  { src: 'clip-05.mp4', joint: { dissolve: 12 } }, // time passing
  { src: 'bridge-c.mp4', in: 0.2, out: 0.7, rate: 3 },
  { src: 'clip-06.mp4', in: 0.25, joint: { wipe: 'up' } },
  { src: 'bridge-d.mp4', in: 0.2, out: 0.7, rate: 3 },
  { src: 'clip-07.mp4', in: 0.25, joint: { wipe: 'down' } },
  { src: 'clip-08a.mp4' }, // THE hard cut — masked by line motion
  { src: 'clip-08b.mp4', joint: { wipe: 'right' } },
  { src: 'clip-08c.mp4', joint: { wipe: 'right' } },
  { src: 'clip-09.mp4', joint: { wipe: 'right' } },
  { src: 'bridge-e.mp4', in: 0.2, out: 0.7, rate: 3 },
  { src: 'clip-10.mp4', in: 0.25, joint: { wipe: 'up' } },
  { src: 'bridge-f.mp4', in: 0.2, out: 0.7, rate: 3 },
  { src: 'clip-11.mp4', in: 0.25, joint: { wipe: 'up' } },
  { src: 'bridge-g.mp4', in: 0.2, out: 0.7, rate: 3 },
  { src: 'clip-12.mp4', in: 0.25, joint: { wipe: 'down' } },
];

const SRC_LEN = 5.04; // seconds per Higgsfield clip
const END_CARD_FRAMES = 6 * FPS;

/** VO file: drop the ElevenLabs render at public/explainer/vo.mp3 and set true. */
const HAS_VO = false;

const pieceFrames = (p: Piece) => {
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
};

const CAPTIONS: Caption[] = [
  { at: 1.2, dur: 3.2, text: 'ALL THIS DATA.' },
  { at: 7.4, dur: 3.4, text: 'THREE DEPARTMENTS. THREE VERSIONS OF THE TRUTH.', hi: 'THREE VERSIONS' },
  { at: 13.4, dur: 3.2, text: "THE LINE ISN'T BROKEN. IT'S BLIND.", hi: 'BLIND' },
  { at: 18.2, dur: 3.4, text: '12,000 UNITS. BY FRIDAY.', hi: 'BY FRIDAY' },
  // the film's thesis lands on its best image: the glowing order buried
  { at: 22.8, dur: 4.2, text: 'GROWTH HIDES IN YOUR DATA.', hi: 'IN YOUR DATA' },
  // question beat = ChatBar; receipts + verdict = AnswerPanel (below)
  { at: 61.8, dur: 3.4, text: 'NOW YOUR DATA TALKS BACK.', hi: 'TALKS BACK' },
  { at: 67.8, dur: 3.2, text: 'WHEREVER DATA PILES UP.' },
  { at: 74.2, dur: 3.2, text: 'SHIPPED FRIDAY.', hi: 'FRIDAY' },
];

/** The question beat: the dashboard's actual Correlation AI composer,
 *  typed live. Mirrors CorrelationAIPane's input + Send button. */
const CHAT = {
  at: 35.0,
  dur: 4.4,
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
  return (
    <AbsoluteFill style={{ opacity: fadeIn, background: '#0a0a0a' }}>
      <OffthreadVideo
        src={staticFile(`explainer/${piece.src}`)}
        trimBefore={Math.round((piece.in ?? 0) * FPS)}
        playbackRate={piece.rate ?? 1}
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
  at: 39.8,
  out: 61.2,
  rows: [
    { at: 40.4, chip: 'XLSX', tone: 'blue' as const, src: 'order-book_aug.xlsx', bold: '3,000 units/day', rest: " — Line 2's sweet spot" },
    { at: 45.2, chip: 'YMS', tone: 'neutral' as const, src: 'TR-2214', bold: 'materials for the full run', rest: ' — checked in Tue' },
    { at: 50.2, chip: '● LIVE', tone: 'green' as const, src: 'Lines 1–3', bold: '58% load', rest: ' · vibration clean · PM done' },
  ],
  verdictAt: 55.2,
  actionsAt: 57.4,
  kanbanAt: 58.6,
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
    </AbsoluteFill>
  );
};
