import React from 'react';
import { AbsoluteFill, Sequence, useCurrentFrame } from 'remotion';
import { Route, Routes } from 'react-router-dom';
import Assets from '../../../src/pages/Assets';
import AssetDetail from '../../../src/pages/AssetDetail';
import { AppFrame } from '../AppFrame';
import { PanZoom } from '../components/PanZoom';
import { Caption } from '../components/Caption';
import { Cursor, Highlight } from '../components/Interactions';
import { NavDrawer } from '../components/NavDrawer';

/**
 * Source scene with a real click-through: the full assets grid (acoustic /
 * camera / vibration assets), cursor clicks "View Details" on the Vibration
 * Sensor card, and the Asset Detail page opens with live telemetry.
 */

const CLICK_AT = 96;
const DETAIL_AT = 104; // hard cut, like a real navigation

export const AssetsDetailScene: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill>
      {frame < DETAIL_AT ? (
        <AppFrame route="/assets">
          <PanZoom
            moves={[
              { at: 0, scale: 1.0, focusX: 960, focusY: 440 },
              { at: 50, scale: 1.0, focusX: 960, focusY: 440 },
              { at: 72, scale: 1.22, focusX: 900, focusY: 560 },
              { at: 103, scale: 1.24, focusX: 900, focusY: 580 },
            ]}
          >
            <Assets />
            {/* Vibration Sensor card + its View Details button */}
            <Highlight x={646} y={462} w={630} h={196} inAt={56} outAt={CLICK_AT + 6} radius={14} />
            <Cursor
              path={[
                { at: 14, x: 1500, y: 260 },
                { at: 52, x: 1120, y: 600 },
                { at: 80, x: 1210, y: 636 },
                { at: 103, x: 1210, y: 636 },
              ]}
              clicks={[CLICK_AT]}
              inAt={10}
            />
          </PanZoom>
        </AppFrame>
      ) : (
        <Sequence from={DETAIL_AT} layout="none">
          <AppFrame route="/assets/asset-8">
            <PanZoom
              moves={[
                { at: 0, scale: 1.0, focusX: 960, focusY: 500 },
                { at: 48, scale: 1.0, focusX: 960, focusY: 500 },
                { at: 66, scale: 1.25, focusX: 768, focusY: 620 },
                { at: 96, scale: 1.25, focusX: 800, focusY: 700 },
                { at: 114, scale: 1.0, focusX: 960, focusY: 500 },
                { at: 130, scale: 1.0, focusX: 960, focusY: 500 },
              ]}
            >
              {/* AssetDetail reads :id from the router, so mount it via a Route */}
              <Routes>
                <Route path="/assets/:id" element={<AssetDetail />} />
              </Routes>
            </PanZoom>
            <NavDrawer activePath="/assets" targetPath="/" inAt={116} clickAt={132} />
          </AppFrame>
        </Sequence>
      )}
      <Caption
        text="Cameras, acoustic and vibration sensors — every asset drills down to its live feed."
        accent="drills down"
        inAt={12}
        outAt={190}
      />
    </AbsoluteFill>
  );
};
