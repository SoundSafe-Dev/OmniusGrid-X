import React from 'react';
import {
  Easing,
  continueRender,
  delayRender,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import { CheckCircle, Loader2 } from 'lucide-react';
import { theme } from '../theme';

/**
 * Screen-recording style interaction overlays. All of these are meant to be
 * rendered INSIDE <PanZoom> (they live in page/content coordinates and zoom
 * with the camera, exactly like a real recorded cursor would).
 */

const EASE = Easing.bezier(0.35, 0, 0.15, 1);

// ---------------------------------------------------------------- Cursor

export interface CursorStop {
  at: number;
  x: number;
  y: number;
}

interface CursorProps {
  path: CursorStop[];
  /** Scene-local frames at which a click happens (ripple + press) */
  clicks?: number[];
  inAt?: number;
  outAt?: number;
}

export const Cursor: React.FC<CursorProps> = ({ path, clicks = [], inAt = 0, outAt }) => {
  const frame = useCurrentFrame();
  const times = path.map((p) => p.at);
  const opts = { easing: EASE, extrapolateLeft: 'clamp' as const, extrapolateRight: 'clamp' as const };
  const x = path.length > 1 ? interpolate(frame, times, path.map((p) => p.x), opts) : path[0].x;
  const y = path.length > 1 ? interpolate(frame, times, path.map((p) => p.y), opts) : path[0].y;

  const fadeIn = interpolate(frame, [inAt, inAt + 8], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const fadeOut =
    outAt === undefined
      ? 1
      : interpolate(frame, [outAt, outAt + 8], [1, 0], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });

  // Press: brief scale-down around each click frame
  let press = 1;
  for (const c of clicks) {
    if (frame >= c - 3 && frame <= c + 5) {
      const t = interpolate(frame, [c - 3, c, c + 5], [1, 0.82, 1], opts);
      press = Math.min(press, t);
    }
  }

  return (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 40 }}>
      {/* click ripples */}
      {clicks.map((c, i) => {
        if (frame < c || frame > c + 22) return null;
        const t = (frame - c) / 22;
        const clickX = interpolate(c, times, path.map((p) => p.x), opts);
        const clickY = interpolate(c, times, path.map((p) => p.y), opts);
        const r = 8 + t * 34;
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: clickX - r,
              top: clickY - r,
              width: r * 2,
              height: r * 2,
              borderRadius: '50%',
              border: `3px solid ${theme.highlight}`,
              opacity: (1 - t) * 0.8,
            }}
          />
        );
      })}
      {/* pointer */}
      <svg
        width={26}
        height={30}
        viewBox="0 0 26 30"
        style={{
          position: 'absolute',
          left: x,
          top: y,
          opacity: fadeIn * fadeOut,
          transform: `scale(${press})`,
          transformOrigin: '4px 4px',
          filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.35))',
        }}
      >
        <path
          d="M4 2 L4 24 L9.5 19 L13 27 L16.5 25.4 L13 17.5 L21 17.5 Z"
          fill="#111"
          stroke="#fff"
          strokeWidth={1.6}
        />
      </svg>
    </div>
  );
};

// ---------------------------------------------------------------- RealClick

interface RealClickProps {
  /** Scene-local frame at which the real DOM element is clicked */
  at: number;
  /** querySelector for the element to click (first match) */
  selector: string;
  /** Optional settle predicate polled after the click; render is gated until it passes */
  settledWhen?: () => boolean;
}

/**
 * Dispatches a REAL click on a live app element at a given frame, so the
 * component's own state visibly changes (e.g. a tab flips to its selected
 * style and swaps its content). The render is gated (delayRender) until the
 * post-click UI settles, which keeps chunked renders deterministic: chunks
 * that start after `at` click on mount and settle before their first capture.
 */
export const RealClick: React.FC<RealClickProps> = ({ at, selector, settledWhen }) => {
  const frame = useCurrentFrame();
  const fired = React.useRef(false);
  const active = frame >= at;

  React.useEffect(() => {
    if (!active || fired.current) return;
    fired.current = true;
    // Gate from the start: the target may not exist yet (the page is still
    // bootstrapping when a render chunk begins past `at`) — poll for it,
    // click, then keep polling until the post-click UI settles.
    const handle = delayRender(`real click: ${selector}`);
    const t0 = performance.now();
    let clicked = false;
    const iv = setInterval(() => {
      if (!clicked) {
        const el = document.querySelector(selector) as HTMLElement | null;
        if (el) {
          el.click();
          clicked = true;
        }
      }
      const settled = clicked && (settledWhen ? settledWhen() : true);
      if (settled || performance.now() - t0 > 4000) {
        clearInterval(iv);
        continueRender(handle);
      }
    }, 50);
  }, [active, selector, settledWhen]);

  return null;
};

// ---------------------------------------------------------------- Highlight

interface HighlightProps {
  x: number;
  y: number;
  w: number;
  h: number;
  inAt: number;
  outAt: number;
  radius?: number;
  /** Dim everything except the target (default true — pronounced spotlight) */
  spotlight?: boolean;
}

/**
 * Spotlight ring around a UI element (button, card, row, badge): a bold
 * accent ring + glow, plus a scrim that dims the rest of the page so the
 * feature unmistakably pops.
 */
export const Highlight: React.FC<HighlightProps> = ({
  x,
  y,
  w,
  h,
  inAt,
  outAt,
  radius = 12,
  spotlight = true,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (frame < inAt || frame > outAt + 10) return null;

  const enter = spring({
    frame: frame - inAt,
    fps,
    config: { damping: 14, stiffness: 160 },
    durationInFrames: 14,
  });
  const exit = interpolate(frame, [outAt, outAt + 10], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  // gentle frame-driven pulse (CSS animations are disabled in the stage)
  const pulse = 1 + 0.02 * Math.sin(((frame - inAt) / fps) * Math.PI * 2.2);
  const pad = interpolate(enter, [0, 1], [30, 9]) * pulse;
  const opacity = Math.min(enter * 1.4, 1) * (1 - exit);
  const scrim = spotlight ? 0.26 * opacity : 0;

  return (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 30 }}>
      <div
        style={{
          position: 'absolute',
          left: x - pad,
          top: y - pad,
          width: w + pad * 2,
          height: h + pad * 2,
          borderRadius: radius + pad / 2,
          border: `5px solid ${theme.highlight}`,
          // the huge outer shadow doubles as the dimming scrim around the target
          boxShadow: `0 0 0 8px rgba(59,130,246,0.22), 0 0 42px rgba(59,130,246,0.55), 0 0 0 9999px rgba(10,10,10,${scrim})`,
          opacity,
        }}
      />
    </div>
  );
};

// ---------------------------------------------------------------- TypeText

interface TypeTextProps {
  x: number;
  y: number;
  text: string;
  startAt: number;
  /** characters per frame (1 ≈ fast demo typing) */
  cpf?: number;
  outAt?: number;
  fontSize?: number;
  width?: number;
}

/** Frame-driven "typing" with a blinking caret, overlaid on a real input. */
export const TypeText: React.FC<TypeTextProps> = ({
  x,
  y,
  text,
  startAt,
  cpf = 1.1,
  outAt,
  fontSize = 14,
  width = 900,
}) => {
  const frame = useCurrentFrame();
  if (frame < startAt - 12 || (outAt !== undefined && frame >= outAt)) return null;

  const chars = Math.max(0, Math.min(text.length, Math.floor((frame - startAt) * cpf)));
  const shown = text.slice(0, chars);
  const doneTyping = chars >= text.length;
  // caret: solid while typing, frame-driven blink when idle
  const caretVisible = !doneTyping || Math.floor(frame / 16) % 2 === 0;

  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        width,
        zIndex: 35,
        pointerEvents: 'none',
        fontFamily: theme.fontFamily,
        fontSize,
        lineHeight: 1.2,
        color: theme.text,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        // no backdrop — the real input's placeholder is hidden via CSS, so
        // the glyphs sit directly in the (empty) input like real typing
        background: 'transparent',
      }}
    >
      {shown}
      <span
        style={{
          display: 'inline-block',
          width: 2,
          height: fontSize + 2,
          verticalAlign: 'text-bottom',
          background: theme.text,
          opacity: caretVisible ? 1 : 0,
          marginLeft: 1,
        }}
      />
    </div>
  );
};

// ---------------------------------------------------------------- ThinkingCard

const THINKING_STEPS = [
  'Reading the uploaded spreadsheet',
  'Identifying the important columns and totals',
  'Looking for rows with high cost, delays, defects, or downtime',
  'Connecting delay reasons to assets, shifts, and maintenance status',
  'Generating response',
];

interface ThinkingCardProps {
  x: number;
  y: number;
  inAt: number;
  outAt: number;
  /** frames per step */
  stepEvery?: number;
  width?: number;
}

/**
 * Frame-driven replica of CorrelationAIPane's analysis-progress card (same
 * Tailwind classes/steps as the real component, but deterministic — the real
 * one is driven by a wall-clock interval).
 */
export const ThinkingCard: React.FC<ThinkingCardProps> = ({
  x,
  y,
  inAt,
  outAt,
  stepEvery = 13,
  width = 620,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (frame < inAt || frame > outAt + 8) return null;

  const enter = spring({
    frame: frame - inAt,
    fps,
    config: { damping: 15, stiffness: 150 },
    durationInFrames: 14,
  });
  const exit = interpolate(frame, [outAt, outAt + 8], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const activeStep = Math.min(
    THINKING_STEPS.length - 1,
    Math.floor((frame - inAt - 6) / stepEvery)
  );
  const spin = ((frame - inAt) * 16) % 360;

  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y + interpolate(enter, [0, 1], [16, 0]),
        width,
        opacity: Math.min(enter * 1.4, 1) * (1 - exit),
        zIndex: 20,
      }}
    >
      <div className="bg-white border border-gray-200 shadow-sm rounded-lg p-4">
        <div className="flex items-center gap-2 mb-3">
          <Loader2 className="w-4 h-4 text-blue-500" style={{ transform: `rotate(${spin}deg)` }} />
          <span className="text-sm font-medium text-gray-900">Working through the analysis</span>
        </div>
        <div className="space-y-2">
          {THINKING_STEPS.map((step, stepIndex) => {
            const isComplete = stepIndex < activeStep;
            const isActive = stepIndex === activeStep;
            return (
              <div
                key={step}
                className={`flex items-center gap-2 text-xs ${
                  isActive ? 'text-gray-900' : 'text-gray-500'
                }`}
              >
                {isComplete ? (
                  <CheckCircle className="w-3.5 h-3.5 text-green-500" />
                ) : isActive ? (
                  <Loader2
                    className="w-3.5 h-3.5 text-blue-500"
                    style={{ transform: `rotate(${spin}deg)` }}
                  />
                ) : (
                  <span className="w-3.5 h-3.5 rounded-full border border-gray-300" />
                )}
                <span>{step}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
