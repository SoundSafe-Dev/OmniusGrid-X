/**
 * Mobile (9:16) composition geometry. Colors and typography come from the
 * shared desktop theme — only the canvas/stage dimensions differ.
 *
 * Pages still render as the SAME 1920-wide desktop layouts (so every ring,
 * cursor path and typing overlay keeps its desktop-calibrated coordinates);
 * the portrait camera simply shows a 1080x1876 window over them, letterboxed
 * on theme.bg when zoomed out.
 */
export { theme } from '../theme';
export { CHROME_H, FPS } from '../theme';

export const MOBILE_W = 2160;
export const MOBILE_H = 3840;

/** Portrait stage (scaled 2x to the 2160x3840 canvas) */
export const M_STAGE_W = 1080;
export const M_STAGE_H = 1920;
export const M_STAGE_SCALE = 2;

/** Camera viewport below the browser-chrome bar */
export const M_VIEW_W = 1080;
export const M_VIEW_H = 1876; // M_STAGE_H - CHROME_H

/** Page space is unchanged: 1920-wide desktop layouts */
export const PAGE_W = 1920;
export const PAGE_H = 1036; // standard page box height (fitHeight pages)

/**
 * The "full page" camera pose: whole 1920x1036 page fits the portrait width
 * and sits vertically centered (scale 1080/1920, focusY solves centering).
 */
export const M_FULL = { scale: 0.5625, focusX: 960, focusY: 540 };
