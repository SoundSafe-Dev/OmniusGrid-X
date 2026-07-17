import React from 'react';
import { useCurrentFrame } from 'remotion';

/**
 * Frame-driven simulation of the app's real tab hover state. The pages'
 * inactive tabs use `text-opsgrid-text-secondary hover:text-opsgrid-text`;
 * headless rendering can't produce CSS :hover, so this injects the hover
 * text color onto the tab under the cursor, synced to the cursor keyframes.
 */
interface TabHoverProps {
  /** Cursor arrival frames + 1-based child index of the hovered tab button */
  steps: { at: number; index: number }[];
  /** Frame after which no tab is hovered */
  until: number;
  /** Selector matching the tab buttons (nth-child applied per step) */
  selector?: string;
}

export const TabHover: React.FC<TabHoverProps> = ({
  steps,
  until,
  selector = '.og-video-stage button.border-b-2',
}) => {
  const frame = useCurrentFrame();
  let index: number | null = null;
  for (const s of steps) {
    if (frame >= s.at) index = s.index;
  }
  if (frame > until || index === null) return null;
  return (
    <style>{`${selector}:nth-child(${index}) { color: #171717 !important; border-bottom-color: #d4d4d4 !important; }`}</style>
  );
};
