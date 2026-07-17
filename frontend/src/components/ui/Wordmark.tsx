import React from 'react';

/**
 * Brand wordmark — split weight, one color: "Omnius" extrabold, "Grid"
 * regular (see frontend/video/BRAND.md). Inherits size/color from parent.
 */
export const Wordmark: React.FC<{ className?: string }> = ({ className }) => (
  <span className={`tracking-tight ${className ?? ''}`}>
    <span className="font-extrabold">Omnius</span>
    <span className="font-normal">Grid</span>
  </span>
);
