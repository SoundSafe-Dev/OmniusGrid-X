import React from 'react';
import { AbsoluteFill } from 'remotion';
import { theme } from '../theme';
import { Wordmark } from './Wordmark';

/** Asset still: the brand wordmark, white on pure black (for export as PNG). */
export const WordmarkCard: React.FC = () => (
  <AbsoluteFill
    style={{
      background: '#000000',
      fontFamily: theme.fontFamily,
      alignItems: 'center',
      justifyContent: 'center',
    }}
  >
    <div style={{ fontSize: 560, color: '#ffffff', letterSpacing: '-0.016em', lineHeight: 1 }}>
      <Wordmark />
    </div>
  </AbsoluteFill>
);
