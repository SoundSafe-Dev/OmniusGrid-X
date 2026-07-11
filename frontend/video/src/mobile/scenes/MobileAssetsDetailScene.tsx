import React from 'react';
import { AbsoluteFill, Sequence, useCurrentFrame } from 'remotion';
import { Route, Routes } from 'react-router-dom';
import Assets from '../../../../src/pages/Assets';
import AssetDetail from '../../../../src/pages/AssetDetail';
import { MobileAppFrame } from '../MobileAppFrame';
import { MobilePanZoom } from '../MobilePanZoom';
import { MobileCaption } from '../MobileCaption';
import { MobileNavDrawer } from '../MobileNavDrawer';
import { Cursor } from '../../components/Interactions';
import { LiftFocus } from '../components/LiftFocus';
import { M_FULL } from '../theme';

/** Portrait assets → asset-detail click-through. */

const CLICK_AT = 96;
const DETAIL_AT = 104;

export const MobileAssetsDetailScene: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill>
      {frame < DETAIL_AT ? (
        <MobileAppFrame route="/assets">
          <MobilePanZoom
            moves={[
              { at: 0, ...M_FULL },
              { at: 50, ...M_FULL },
              { at: 72, scale: 1.55, focusX: 961, focusY: 560 },
              { at: 103, scale: 1.55, focusX: 961, focusY: 565 },
            ]}
          >
            <Assets />
            <LiftFocus x={646} y={462} w={630} h={196} inAt={60} outAt={CLICK_AT + 6} />
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
          </MobilePanZoom>
        </MobileAppFrame>
      ) : (
        <Sequence from={DETAIL_AT} layout="none">
          <MobileAppFrame route="/assets/asset-8">
            <MobilePanZoom
              moves={[
                { at: 0, ...M_FULL },
                { at: 48, ...M_FULL },
                // Latest Telemetry value cards, lifted with a pan across
                { at: 60, scale: 1.35, focusX: 420, focusY: 303 },
                { at: 88, scale: 1.35, focusX: 1060, focusY: 306 },
                { at: 104, ...M_FULL },
                { at: 130, ...M_FULL },
              ]}
            >
              <Routes>
                <Route path="/assets/:id" element={<AssetDetail />} />
              </Routes>
              <LiftFocus
                x={20}
                y={250}
                w={1430}
                h={106}
                inAt={58}
                outAt={98}
                radius={10}
              />
            </MobilePanZoom>
            <MobileNavDrawer activePath="/assets" targetPath="/" inAt={116} clickAt={132} />
          </MobileAppFrame>
        </Sequence>
      )}
      <MobileCaption
        text="Cameras, acoustic and vibration sensors — every asset drills down to its live feed."
        accent="drills down"
        inAt={12}
        outAt={190}
      />
    </AbsoluteFill>
  );
};
