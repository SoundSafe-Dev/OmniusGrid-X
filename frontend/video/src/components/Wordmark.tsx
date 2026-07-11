import React from 'react';

/**
 * Brand wordmark: "Omnius" bold, "Grid" regular weight. Inherits font size,
 * color and letter-spacing from the parent — only the weights are set here.
 */
export const Wordmark: React.FC<{ boldWeight?: number }> = ({ boldWeight = 800 }) => (
  <>
    <span style={{ fontWeight: boldWeight }}>Omnius</span>
    <span style={{ fontWeight: 400 }}>Grid</span>
  </>
);
