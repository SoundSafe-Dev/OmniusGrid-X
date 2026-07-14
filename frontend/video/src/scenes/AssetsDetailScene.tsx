import React from 'react';
import { AbsoluteFill, Sequence, useCurrentFrame } from 'remotion';
import { Route, Routes } from 'react-router-dom';
import Assets from '../../../src/pages/Assets';
import AssetDetail from '../../../src/pages/AssetDetail';
import { AppFrame } from '../AppFrame';
import { PanZoom } from '../components/PanZoom';
import { Caption } from '../components/Caption';
import { Cursor } from '../components/Interactions';
import { LiftFocus } from '../mobile/components/LiftFocus';
import { NavDrawer } from '../components/NavDrawer';

/**
 * Source scene with a real click-through: the full assets grid, the
 * Vibration Sensor card lifts, the cursor clicks "View Details", and the
 * Asset Detail page opens — its Latest Telemetry values lifted and panned.
 */

const CLICK_AT = 112;
const DETAIL_AT = 120; // hard cut, like a real navigation

export const AssetsDetailScene: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill>
      {frame < DETAIL_AT ? (
        <AppFrame route="/assets">
          <PanZoom
            moves={[
              { at: 0, scale: 1.0, focusX: 960, focusY: 440 },
              { at: 56, scale: 1.0, focusX: 960, focusY: 440 },
              { at: 74, scale: 1.55, focusX: 961, focusY: 560 },
              { at: 119, scale: 1.55, focusX: 961, focusY: 565 },
            ]}
          >
            <Assets />
            <LiftFocus x={646} y={462} w={630} h={196} inAt={64} outAt={CLICK_AT + 6} />
            <Cursor
              path={[
                { at: 14, x: 1500, y: 260 },
                { at: 60, x: 1120, y: 600 },
                { at: 92, x: 1210, y: 636 },
                { at: 119, x: 1210, y: 636 },
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
                { at: 52, scale: 1.0, focusX: 960, focusY: 500 },
                // Latest Telemetry value cards, lifted with a pan across
                { at: 60, scale: 1.35, focusX: 420, focusY: 303 },
                { at: 96, scale: 1.35, focusX: 1060, focusY: 306 },
                { at: 114, scale: 1.0, focusX: 960, focusY: 500 },
                { at: 136, scale: 1.0, focusX: 960, focusY: 500 },
              ]}
            >
              {/* AssetDetail reads :id from the router, so mount it via a Route */}
              <Routes>
                <Route path="/assets/:id" element={<AssetDetail />} />
              </Routes>
              <LiftFocus x={20} y={250} w={1430} h={106} inAt={58} outAt={106} radius={10} />
            </PanZoom>
            <NavDrawer activePath="/assets" targetPath="/" inAt={118} clickAt={136} />
          </AppFrame>
        </Sequence>
      )}
      <Caption
        text="Cameras, acoustic and vibration sensors — every asset drills down to its live feed."
        accent="drills down"
        inAt={12}
        outAt={220}
      />
    </AbsoluteFill>
  );
};
