/**
 * Light-mode brand tokens, copied from the `:root` block of src/index.css.
 * The video renders the app in light theme, so title/outro/captions and the
 * browser-chrome frame draw from the same palette as the product itself.
 */
export const theme = {
  bg: '#fafafa',
  panel: '#ffffff',
  border: '#e5e5e5',
  borderEmphasis: '#d4d4d4',
  text: '#171717',
  textSecondary: '#525252',
  primary: '#171717',
  accent: '#404040',
  hover: '#f5f5f5',
  // Video-only accent for caption keywords / underlines (matches the app's
  // blue used for chat bubbles + focus rings)
  highlight: '#3b82f6',
  highlightSoft: '#93c5fd',
  // Brand-moment (dark) tokens — the app's own charcoal dark colorway
  darkBg: '#0a0a0a',
  darkPanel: '#171717',
  darkBorder: '#2e2e2e',
  darkText: '#fafafa',
  darkTextSecondary: '#a3a3a3',
  fontFamily:
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue', sans-serif",
};

/** Composition geometry */
export const VIDEO_W = 3840;
export const VIDEO_H = 2160;
export const FPS = 30;

/**
 * Pages are laid out on a 1920x1080 stage and scaled 2x so Chromium
 * rasterizes text at the final 4K resolution without stretching layouts
 * designed for ~1080p-class viewports.
 */
export const STAGE_W = 1920;
export const STAGE_H = 1080;
export const STAGE_SCALE = 2;
export const CHROME_H = 44; // browser-chrome bar height in stage px
