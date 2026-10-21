/** 7.3 项目与知识库问答（4.8 + 2.4 + 0.4 = 7.6s）。 */
import { DUR, EASE } from '../../../../lib/motion-tokens';
import type { ArtBuilder } from '../../art-kit';

const build: ArtBuilder = (k) => {
  k.tween(
    'bubble',
    { opacity: 0, y: 6, scale: 0.96, transformOrigin: '100% 100%' },
    { opacity: 1, y: 0, scale: 1, duration: DUR.short, ease: EASE.out },
    0,
  );
  k.tool('t1', 0.4, 0.85);
  k.tool('t2', 0.9, 1.35);
  k.enter('t2-res', 1.4);
  k.tool('t3', 1.45, 1.9);
  k.enter('inj', 1.95);
  k.tool('t4', 2.15, 2.6);
  k.enter('t4-res', 2.65);
  k.handoff(2.7);
  k.enter('o-hdr', 2.85);
  k.stream('l1', 2.95);
  k.stream('l2', 3.51);
  k.enter('cite', 3.95);
  k.enter('uncov-l, uncov', 4.2, { stagger: 0.08 });
  k.pop('ok', 4.5);
  k.end(4.8);
};
export default build;
