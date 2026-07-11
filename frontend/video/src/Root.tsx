import React from 'react';
import { Composition, Sequence, Still } from 'remotion';
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
  { id: 'CorrelationIntro', comp: CorrelationIntroScene, duration: 165, transition: 'slide-l' },
  { id: 'Correlation', comp: CorrelationScene, duration: 545, transition: 'fade' },
  { id: 'Intake', comp: IntakeScene, duration: 135, transition: 'slide-l' },
  { id: 'AssetsDetail', comp: AssetsDetailScene, duration: 240, transition: 'slide-l' },
  { id: 'Dashboard', comp: DashboardScene, duration: 150, transition: 'slide-l' },
  { id: 'OEE', comp: OEEScene, duration: 165, transition: 'slide-l' },
  { id: 'Logistics', comp: LogisticsScene, duration: 200, transition: 'fade' },
  { id: 'Yard', comp: YardScene, duration: 160, transition: 'slide-l' },
  { id: 'ERP', comp: ERPScene, duration: 150, transition: 'fade' },
  { id: 'Kanban', comp: KanbanScene, duration: 210, transition: 'slide-l' },
  { id: 'CorrelationReturn', comp: CorrelationReturnScene, duration: 155, transition: 'wipe' },
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
    {/* brand asset: wordmark white-on-black */}
    <Still id="WordmarkPng" component={WordmarkCard} width={3840} height={1400} />
  </>
);
