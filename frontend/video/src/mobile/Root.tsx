import React from 'react';
import { Composition, Sequence, Still } from 'remotion';
import { TransitionSeries, linearTiming } from '@remotion/transitions';
import { fade } from '@remotion/transitions/fade';
import { slide } from '@remotion/transitions/slide';
import { wipe } from '@remotion/transitions/wipe';
import { FPS } from '../theme';
import { MOBILE_W, MOBILE_H } from './theme';
import { TitleCard } from '../components/TitleCard';
import { ProblemLine } from '../components/ProblemLine';
import { Outro } from '../components/Outro';
import { MobileCorrelationScene } from './scenes/MobileCorrelationScene';
import { MobileCorrelationIntroScene } from './scenes/MobileCorrelationIntroScene';
import { MobileIntakeScene } from './scenes/MobileIntakeScene';
import { MobileAssetsDetailScene } from './scenes/MobileAssetsDetailScene';
import { MobileLogisticsScene } from './scenes/MobileLogisticsScene';
import { MobileYardScene } from './scenes/MobileYardScene';
import { MobileStackScene } from './MobileStackScene';
import { MobileDashboardScene } from './scenes/MobileDashboardScene';
import { MobileOEEScene } from './scenes/MobileOEEScene';
import { MobileERPScene } from './scenes/MobileERPScene';
import { MobileKanbanScene } from './scenes/MobileKanbanScene';
import { MobileCorrelationReturnScene } from './scenes/MobileCorrelationReturnScene';

const T = 12;

/** Identical order, durations and transitions to the desktop DemoVideo. */
const SCENES: {
  id: string;
  comp: React.FC;
  duration: number;
  transition: 'fade' | 'slide-l' | 'slide-r' | 'wipe';
}[] = [
  { id: 'Problem', comp: ProblemLine, duration: 100, transition: 'fade' },
  { id: 'Title', comp: TitleCard, duration: 110, transition: 'fade' },
  { id: 'CorrelationIntro', comp: MobileCorrelationIntroScene, duration: 180, transition: 'slide-l' },
  { id: 'Correlation', comp: MobileCorrelationScene, duration: 600, transition: 'fade' },
  { id: 'Intake', comp: MobileIntakeScene, duration: 175, transition: 'slide-l' },
  { id: 'AssetsDetail', comp: MobileAssetsDetailScene, duration: 270, transition: 'slide-l' },
  { id: 'Dashboard', comp: MobileDashboardScene, duration: 185, transition: 'slide-l' },
  { id: 'OEE', comp: MobileOEEScene, duration: 205, transition: 'slide-l' },
  { id: 'Logistics', comp: MobileLogisticsScene, duration: 260, transition: 'fade' },
  { id: 'Yard', comp: MobileYardScene, duration: 210, transition: 'slide-l' },
  { id: 'ERP', comp: MobileERPScene, duration: 210, transition: 'fade' },
  { id: 'Kanban', comp: MobileKanbanScene, duration: 250, transition: 'slide-l' },
  { id: 'CorrelationReturn', comp: MobileCorrelationReturnScene, duration: 185, transition: 'wipe' },
  { id: 'Stack', comp: MobileStackScene, duration: 240, transition: 'fade' },
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

const DemoVideoMobile: React.FC = () => (
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

const AtFrame: React.FC<{ Comp: React.FC; frame: number }> = ({ Comp, frame }) => (
  <Sequence from={-frame} layout="none">
    <Comp />
  </Sequence>
);

const STILLS = SCENES.filter((s) => !['Title', 'Outro'].includes(s.id)).map((scene) => {
  const Comp = scene.comp;
  const midFrame = Math.floor(scene.duration / 2);
  const StillComp: React.FC = () => <AtFrame Comp={Comp} frame={midFrame} />;
  return { id: `${scene.id}-MStill`, StillComp };
});

export const RemotionMobileRoot: React.FC = () => (
  <>
    <Composition
      id="DemoVideoMobile"
      component={DemoVideoMobile}
      durationInFrames={TOTAL_FRAMES}
      fps={FPS}
      width={MOBILE_W}
      height={MOBILE_H}
    />
    {STILLS.map(({ id, StillComp }) => (
      <Still key={id} id={id} component={StillComp} width={MOBILE_W} height={MOBILE_H} />
    ))}
  </>
);
