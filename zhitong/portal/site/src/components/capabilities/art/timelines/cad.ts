/** 7.4 CAD 看图（5.5 + 2.1 + 0.4 = 8.0s）。 */
import { DUR, EASE } from '../../../../lib/motion-tokens';
import type { ArtBuilder } from '../../art-kit';

const build: ArtBuilder = (k) => {
  k.tool('tl-a', 0, 0.5);
  k.draw('frame', 0.15, 0.7);
  k.draw('plan', 0.45, 0.6);
  k.enter('title', 0.85);
  k.swap('tl-a', 'tl-b', 1.0);
  k.tool('tl-b', 1.0, 1.5, { enter: false });
  k.tween('r201', { opacity: 0 }, { opacity: 1, duration: DUR.short, ease: EASE.out }, 1.3);
  k.swap('tl-b', 'tl-c', 1.55);
  k.tool('tl-c', 1.55, 2.05, { enter: false });
  k.tween('grid', { opacity: 0 }, { opacity: 0.35, duration: DUR.short, ease: EASE.out }, 1.65);
  k.enter('grid-l', 1.65, { stagger: 0.02 });
  k.pop('e4', 2.0);
  k.tween('e4', { opacity: 0.8 }, { opacity: 0.4, duration: 0.15, ease: EASE.inOut }, 2.16);
  k.tween('e4', { opacity: 0.4 }, { opacity: 0.8, duration: 0.15, ease: EASE.inOut }, 2.31);
  k.swap('tl-c', 'tl-d', 2.1);
  k.tool('tl-d', 2.1, 2.8, { enter: false });
  k.tween(
    'ov',
    { scale: 1, opacity: 1, svgOrigin: '157.5 95.25' },
    { scale: 3.2, opacity: 0, duration: 0.6, ease: EASE.inOut },
    2.2,
  );
  k.tween(
    'zm',
    { scale: 0.55, opacity: 0, svgOrigin: '127.6 87.7' },
    { scale: 1, opacity: 1, duration: 0.6, ease: EASE.out },
    2.35,
  );
  k.draw('zm-wall, zm-stair', 2.9, 0.4, { stagger: 0.1 });
  k.enter('zm-room, zm-area, zm-hall', 3.1, { stagger: 0.06 });
  k.draw('axisline, innerline', 3.3, 0.45, { stagger: 0.15 });
  k.enter('zlabel', 3.7);
  k.handoff(3.9);
  k.enter('o-hdr, o-unit', 4.05, { stagger: 0.08 });
  k.enter('o-th', 4.25);
  k.enter('o-r1, o-r2, o-r3, o-r4', 4.35, { stagger: 0.12 });
  k.tween('o-r1bg', { opacity: 0 }, { opacity: 1, duration: DUR.short, ease: EASE.out }, 5.0);
  k.enter('o-more', 5.1);
  k.pop('o-warn', 5.3);
  k.end(5.5, 2.1);
};
export default build;
