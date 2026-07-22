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
  { at: 8.4, dur: 3.0, text: 'NOTHING CONNECTS.' },
  { at: 15.2, dur: 3.4, text: 'THE GAPS ARE EXPENSIVE.', hi: 'EXPENSIVE' },
  { at: 20.6, dur: 3.6, text: '12,000 UNITS. BY FRIDAY.', hi: 'BY FRIDAY' },
  { at: 26.4, dur: 3.4, text: "THE MOST EXPENSIVE WORD: 'NO.'", hi: "'NO.'" },
  { at: 37.8, dur: 4.2, text: 'Can we take the 12,000-unit rush order and still ship Friday?', mono: true },
  { at: 43.2, dur: 3.2, text: 'order-book_aug.xlsx -> 3,000 units/day', hi: '3,000 units/day', mono: true },
  { at: 46.8, dur: 3.2, text: 'TR-2214 · materials -> checked in Tue', hi: 'checked in Tue', mono: true },
  { at: 50.4, dur: 3.2, text: 'Line 2 -> PM done · 58% load · vib clean', hi: '58%', mono: true },
  { at: 54.4, dur: 2.6, text: 'GO · 96', mono: true, color: GREEN },
  { at: 57.0, dur: 3.4, text: 'reply to Sales ✓ · production ✓ · Dock 2 ✓', mono: true, color: GREEN },
  { at: 63.0, dur: 3.0, text: '9 SECONDS.', hi: '9' },
  { at: 70.0, dur: 3.4, text: 'WHEREVER DATA HIDES.' },
  { at: 76.5, dur: 3.6, text: 'GROWTH HIDES IN YOUR DATA TOO.', hi: 'IN YOUR DATA' },
];

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
      {HAS_VO ? <Audio src={staticFile('explainer/vo.mp3')} /> : null}
    </AbsoluteFill>
  );
};
