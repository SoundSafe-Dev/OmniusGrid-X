import React from 'react';
import { Composition, Sequence, Still } from 'remotion';
import { Route, Routes } from 'react-router-dom';
import AssetDetail from '../../src/pages/AssetDetail';
import { AppFrame } from './AppFrame';
import { PanZoom } from './components/PanZoom';
import { TransitionSeries, linearTiming } from '@remotion/transitions';
import { fade } from '@remotion/transitions/fade';
import { slide } from '@remotion/transitions/slide';
import { wipe } from '@remotion/transitions/wipe';
import { VIDEO_W, VIDEO_H, FPS } from './theme';
import { TitleCard } from './components/TitleCard';
import { ProblemLine } from './components/ProblemLine';
import { Outro } from './components/Outro';
import { CorrelationScene } from './scenes/CorrelationScene';
import { CorrelationIntroScene } from './scenes/CorrelationIntroScene';
import { IntakeScene } from './scenes/IntakeScene';
import { AssetsDetailScene } from './scenes/AssetsDetailScene';
import { LogisticsScene } from './scenes/LogisticsScene';
import { YardScene } from './scenes/YardScene';
import { StackScene } from './scenes/StackScene';
import { DashboardScene } from './scenes/DashboardScene';
import { OEEScene } from './scenes/OEEScene';
import { ERPScene } from './scenes/ERPScene';
import { KanbanScene } from './scenes/KanbanScene';
import { CorrelationReturnScene } from './scenes/CorrelationReturnScene';
import { WordmarkCard } from './components/WordmarkCard';
import { PromoLogo, PromoTagline, PromoIndustry } from './promo/PromoCards';
import {
  ClientSlide1,
  ClientSlide2,
  ClientSlide3,
  InvestorSlide1,
  InvestorSlide2,
  InvestorSlide3,
} from './promo/DeckCards';
import {
  BrandPage1,
  BrandPage2,
  BrandPage3,
  BrandPage4,
  BrandPage5,
  BrandPage6,
  BrandPage7,
  BrandPage8,
  BrandPage9,
  BrandPage10,
} from './promo/BrandBook';
import { OnePager, BannerLinkedIn } from './promo/Collateral';
import * as RS from './promo/RealScreens';
import * as CAR from './promo/Carousel';
import {
  ClipAsk,
  ClipDetention,
  ClipTherapy,
  CLIP_ASK_DURATION,
  CLIP_DETENTION_DURATION,
  CLIP_THERAPY_DURATION,
} from './promo/Clips';
import {
  ClipAskLight,
  ClipDetentionLight,
  ClipTherapyLight,
  CLIP_ASK_LIGHT_DURATION,
  CLIP_DETENTION_LIGHT_DURATION,
  CLIP_THERAPY_LIGHT_DURATION,
} from './promo/ClipsLight';
import {
  Marketing1,
  Marketing2,
  Marketing3,
  Marketing4,
  Marketing5,
  Marketing6,
  Marketing7,
  Marketing8,
  Marketing9,
  Marketing10,
  Marketing1Tall,
  Marketing2Tall,
  Marketing3Tall,
  Marketing4Tall,
  Marketing5Tall,
  Marketing6Tall,
  Marketing7Tall,
  Marketing8Tall,
  Marketing9Tall,
  Marketing10Tall,
} from './promo/MarketingCards';
import {
  Marketing1Light,
  Marketing2Light,
  Marketing3Light,
  Marketing4Light,
  Marketing5Light,
  Marketing6Light,
  Marketing7Light,
  Marketing8Light,
  Marketing9Light,
  Marketing10Light,
  Marketing1TallLight,
  Marketing2TallLight,
  Marketing3TallLight,
  Marketing4TallLight,
  Marketing5TallLight,
  Marketing6TallLight,
  Marketing7TallLight,
  Marketing8TallLight,
  Marketing9TallLight,
  Marketing10TallLight,
} from './promo/MarketingCardsLight';
import {
  ClientSlide1Light,
  ClientSlide2Light,
  ClientSlide3Light,
  InvestorSlide1Light,
  InvestorSlide2Light,
  InvestorSlide3Light,
} from './promo/DeckCardsLight';

const T = 12; // transition overlap frames

// Scene order: hero first, then sources trail in, then the end-to-end chain
// (logistics → shop floor → insight → financials), action, return beat, outro.
const SCENES: {
  id: string;
  comp: React.FC;
  duration: number;
  transition: 'fade' | 'slide-l' | 'slide-r' | 'wipe';
}[] = [
  { id: 'Problem', comp: ProblemLine, duration: 100, transition: 'fade' },
  { id: 'Title', comp: TitleCard, duration: 110, transition: 'fade' },
  { id: 'CorrelationIntro', comp: CorrelationIntroScene, duration: 180, transition: 'slide-l' },
  { id: 'Correlation', comp: CorrelationScene, duration: 600, transition: 'fade' },
  { id: 'Intake', comp: IntakeScene, duration: 175, transition: 'slide-l' },
  { id: 'AssetsDetail', comp: AssetsDetailScene, duration: 270, transition: 'slide-l' },
  { id: 'Dashboard', comp: DashboardScene, duration: 185, transition: 'slide-l' },
  { id: 'OEE', comp: OEEScene, duration: 205, transition: 'slide-l' },
  { id: 'Logistics', comp: LogisticsScene, duration: 260, transition: 'fade' },
  { id: 'Yard', comp: YardScene, duration: 210, transition: 'slide-l' },
  { id: 'ERP', comp: ERPScene, duration: 210, transition: 'fade' },
  { id: 'Kanban', comp: KanbanScene, duration: 250, transition: 'slide-l' },
  { id: 'CorrelationReturn', comp: CorrelationReturnScene, duration: 185, transition: 'wipe' },
  { id: 'Stack', comp: StackScene, duration: 240, transition: 'fade' },
  { id: 'Outro', comp: Outro, duration: 105, transition: 'fade' },
];

const TOTAL_FRAMES =
  SCENES.reduce((sum, s) => sum + s.duration, 0) - (SCENES.length - 1) * T;

const presentationFor = (kind: (typeof SCENES)[number]['transition']) => {
  switch (kind) {
    case 'slide-l':
      return slide({ direction: 'from-right' });
    case 'slide-r':
      return slide({ direction: 'from-left' });
    case 'wipe':
      return wipe({ direction: 'from-left' });
    default:
      return fade();
  }
};

const DemoVideo: React.FC = () => (
  <TransitionSeries>
    {SCENES.flatMap((scene, i) => {
      const Comp = scene.comp;
      const parts: React.ReactNode[] = [
        <TransitionSeries.Sequence key={scene.id} durationInFrames={scene.duration}>
          <Comp />
        </TransitionSeries.Sequence>,
      ];
      if (i < SCENES.length - 1) {
        parts.push(
          <TransitionSeries.Transition
            key={`${scene.id}-t`}
            presentation={presentationFor(SCENES[i + 1].transition)}
            timing={linearTiming({ durationInFrames: T })}
          />
        );
      }
      return parts;
    })}
  </TransitionSeries>
);

/** Renders a scene as it appears at a given scene-local frame (for Still QA). */
const AtFrame: React.FC<{ Comp: React.FC; frame: number }> = ({ Comp, frame }) => (
  <Sequence from={-frame} layout="none">
    <Comp />
  </Sequence>
);

// Stable component refs for the Still compositions (defined once at module scope)
const STILLS = SCENES.filter((s) => !['Title', 'Outro'].includes(s.id)).map((scene) => {
  const Comp = scene.comp;
  const midFrame = Math.floor(scene.duration / 2);
  const StillComp: React.FC = () => <AtFrame Comp={Comp} frame={midFrame} />;
  return { id: `${scene.id}-Still`, StillComp };
});

// Brand-QA mounts: real Login page and Sidebar (for verifying app branding)
const ShotLogin: React.FC = () => {
  const Login = require('../../src/pages/auth/Login').default ?? require('../../src/pages/auth/Login').Login;
  return (
    <AppFrame route="/login">
      <PanZoom moves={[{ at: 0, scale: 1.0, focusX: 960, focusY: 500 }]}>
        <Routes>
          <Route path="/login" element={<Login />} />
        </Routes>
      </PanZoom>
    </AppFrame>
  );
};
const ShotSidebar: React.FC = () => {
  const { Sidebar } = require('../../src/components/layout/Sidebar');
  return (
    <AppFrame route="/">
      <PanZoom moves={[{ at: 0, scale: 1.0, focusX: 960, focusY: 500 }]}>
        <div style={{ display: 'flex' }}>
          <Sidebar />
        </div>
      </PanZoom>
    </AppFrame>
  );
};

// Bare asset-detail mount (no scene overlays) for chart/telemetry crops
const ShotDetailClean: React.FC = () => (
  <AppFrame route="/assets/asset-8">
    <PanZoom moves={[{ at: 0, scale: 1.0, focusX: 960, focusY: 500 }]}>
      <Routes>
        <Route path="/assets/:id" element={<AssetDetail />} />
      </Routes>
    </PanZoom>
  </AppFrame>
);

// Clean real-UI frames for marketing crops (early frames = no overlays yet)
const SHOTS: { id: string; Comp: React.FC; frame: number }[] = [
  { id: 'ShotDashboard', Comp: DashboardScene, frame: 8 },
  { id: 'ShotOEE', Comp: OEEScene, frame: 8 },
  { id: 'ShotKanban', Comp: KanbanScene, frame: 8 },
  { id: 'ShotIntake', Comp: IntakeScene, frame: 8 },
  { id: 'ShotAnswer', Comp: CorrelationReturnScene, frame: 8 },
  { id: 'ShotERP', Comp: ERPScene, frame: 8 },
  { id: 'ShotAssets', Comp: AssetsDetailScene, frame: 8 },
  { id: 'ShotTMS', Comp: LogisticsScene, frame: 70 },
  { id: 'ShotYard', Comp: YardScene, frame: 30 },
  { id: 'ShotAssetDetail', Comp: ShotDetailClean, frame: 180 },
  { id: 'ShotLogin', Comp: ShotLogin, frame: 30 },
  { id: 'ShotSidebar', Comp: ShotSidebar, frame: 30 },
];
const SHOT_STILLS = SHOTS.map(({ id, Comp, frame }) => {
  const StillComp: React.FC = () => <AtFrame Comp={Comp} frame={frame} />;
  return { id, StillComp };
});

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="DemoVideo"
      component={DemoVideo}
      durationInFrames={TOTAL_FRAMES}
      fps={FPS}
      width={VIDEO_W}
      height={VIDEO_H}
    />
    {STILLS.map(({ id, StillComp }) => (
      <Still key={id} id={id} component={StillComp} width={VIDEO_W} height={VIDEO_H} />
    ))}
    {SHOT_STILLS.map(({ id, StillComp }) => (
      <Still key={id} id={id} component={StillComp} width={VIDEO_W} height={VIDEO_H} />
    ))}
    {/* brand asset: wordmark white-on-black */}
    <Still id="WordmarkPng" component={WordmarkCard} width={3840} height={1400} />
    {/* Instagram 4:5 promo cards (render 2x, deliver 1080x1350) */}
    <Still id="PromoLogo" component={PromoLogo} width={2160} height={2700} />
    <Still id="PromoTagline" component={PromoTagline} width={2160} height={2700} />
    <Still id="PromoIndustry" component={PromoIndustry} width={2160} height={2700} />
    {/* 16:9 deck slides (render 2x, deliver 1920x1080) */}
    <Still id="DeckClient1" component={ClientSlide1} width={3840} height={2160} />
    <Still id="DeckClient2" component={ClientSlide2} width={3840} height={2160} />
    <Still id="DeckClient3" component={ClientSlide3} width={3840} height={2160} />
    <Still id="DeckInvestor1" component={InvestorSlide1} width={3840} height={2160} />
    <Still id="DeckInvestor2" component={InvestorSlide2} width={3840} height={2160} />
    <Still id="DeckInvestor3" component={InvestorSlide3} width={3840} height={2160} />
    {/* light-theme deck variants */}
    <Still id="DeckClient1Light" component={ClientSlide1Light} width={3840} height={2160} />
    <Still id="DeckClient2Light" component={ClientSlide2Light} width={3840} height={2160} />
    <Still id="DeckClient3Light" component={ClientSlide3Light} width={3840} height={2160} />
    <Still id="DeckInvestor1Light" component={InvestorSlide1Light} width={3840} height={2160} />
    <Still id="DeckInvestor2Light" component={InvestorSlide2Light} width={3840} height={2160} />
    <Still id="DeckInvestor3Light" component={InvestorSlide3Light} width={3840} height={2160} />
    {/* brand guidelines book (16:9 pages, bound to PDF) */}
    {[
      BrandPage1,
      BrandPage2,
      BrandPage3,
      BrandPage4,
      BrandPage5,
      BrandPage6,
      BrandPage7,
      BrandPage8,
      BrandPage10, // layout & formatting spec — page 9 of the bound book
      BrandPage9, // applications & sign-off — final page
    ].map((C, i) => (
      <Still key={`brand-${i + 1}`} id={`BrandBook${i + 1}`} component={C} width={3840} height={2160} />
    ))}
    {/* collateral */}
    <Still id="OnePager" component={OnePager} width={2550} height={3300} />
    <Still id="BannerLinkedIn" component={BannerLinkedIn} width={3168} height={792} />
    {/* witty social cards (square, delivered 1080x1080, dark + light) */}
    {[
      Marketing1,
      Marketing2,
      Marketing3,
      Marketing4,
      Marketing5,
      Marketing6,
      Marketing7,
      Marketing8,
      Marketing9,
      Marketing10,
    ].map((C, i) => (
      <Still key={`mkt-${i + 1}`} id={`Marketing${i + 1}`} component={C} width={2160} height={2160} />
    ))}
    {[
      Marketing1Light,
      Marketing2Light,
      Marketing3Light,
      Marketing4Light,
      Marketing5Light,
      Marketing6Light,
      Marketing7Light,
      Marketing8Light,
      Marketing9Light,
      Marketing10Light,
    ].map((C, i) => (
      <Still
        key={`mkt-light-${i + 1}`}
        id={`Marketing${i + 1}Light`}
        component={C}
        width={2160}
        height={2160}
      />
    ))}
    {/* 9:16 story variants */}
    {[
      Marketing1Tall,
      Marketing2Tall,
      Marketing3Tall,
      Marketing4Tall,
      Marketing5Tall,
      Marketing6Tall,
      Marketing7Tall,
      Marketing8Tall,
      Marketing9Tall,
      Marketing10Tall,
    ].map((C, i) => (
      <Still
        key={`mkt-tall-${i + 1}`}
        id={`Marketing${i + 1}Tall`}
        component={C}
        width={2160}
        height={3840}
      />
    ))}
    {/* real-screens series: 7 cards × dark/light × square/story */}
    {[1, 2, 3, 4, 5, 6, 7, 8].flatMap((i) => {
      const comps = RS as Record<string, React.FC>;
      return [
        ['', 2160, 2160],
        ['Light', 2160, 2160],
        ['Tall', 2160, 3840],
        ['TallLight', 2160, 3840],
      ].map(([suffix, w, h]) => (
        <Still
          key={`rs-${i}${suffix}`}
          id={`RealScreen${i}${suffix}`}
          component={comps[`RealScreen${i}${suffix}`]}
          width={w as number}
          height={h as number}
        />
      ));
    })}
    {/* carousel: 6 slides × dark/light */}
    {[1, 2, 3, 4, 5, 6].flatMap((i) => {
      const comps = CAR as Record<string, React.FC>;
      return ['', 'Light'].map((suffix) => (
        <Still
          key={`car-${i}${suffix}`}
          id={`CarouselS${i}${suffix}`}
          component={comps[`CarouselS${i}${suffix}`]}
          width={2160}
          height={2160}
        />
      ));
    })}
    {/* micro-demo clips (9:16 video) */}
    <Composition id="ClipAsk" component={ClipAsk} durationInFrames={CLIP_ASK_DURATION} fps={FPS} width={2160} height={3840} />
    <Composition id="ClipDetention" component={ClipDetention} durationInFrames={CLIP_DETENTION_DURATION} fps={FPS} width={2160} height={3840} />
    <Composition id="ClipTherapy" component={ClipTherapy} durationInFrames={CLIP_THERAPY_DURATION} fps={FPS} width={2160} height={3840} />
    <Composition id="ClipAskLight" component={ClipAskLight} durationInFrames={CLIP_ASK_LIGHT_DURATION} fps={FPS} width={2160} height={3840} />
    <Composition id="ClipDetentionLight" component={ClipDetentionLight} durationInFrames={CLIP_DETENTION_LIGHT_DURATION} fps={FPS} width={2160} height={3840} />
    <Composition id="ClipTherapyLight" component={ClipTherapyLight} durationInFrames={CLIP_THERAPY_LIGHT_DURATION} fps={FPS} width={2160} height={3840} />
    {[
      Marketing1TallLight,
      Marketing2TallLight,
      Marketing3TallLight,
      Marketing4TallLight,
      Marketing5TallLight,
      Marketing6TallLight,
      Marketing7TallLight,
      Marketing8TallLight,
      Marketing9TallLight,
      Marketing10TallLight,
    ].map((C, i) => (
      <Still
        key={`mkt-tall-light-${i + 1}`}
        id={`Marketing${i + 1}TallLight`}
        component={C}
        width={2160}
        height={3840}
      />
    ))}
  </>
);
