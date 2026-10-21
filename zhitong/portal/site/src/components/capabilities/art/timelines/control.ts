/** 7.7 投控异常检测与复核（4.4 + 2.4 + 0.4 = 7.2s）。 */
import { DUR, EASE } from '../../../../lib/motion-tokens';
import { ART_FACTS } from '../../../../data/capabilities';
import type { ArtBuilder } from '../../art-kit';

const C = ART_FACTS.control;
const counts = [C.duplicate, C.provisional, C.consistency, C.large];

const build: ArtBuilder = (k) => {
  k.enter('hdr, src', 0, { stagger: 0.08 });
  k.enter('rw1, rw2, rw3, rw4', 0.4, { stagger: 0.12 });
  counts.forEach((v, i) => {
    k.count(`rn${i + 1}`, 0.4 + 0.12 * i, v, 'int', 0.5);
    k.pop(`rc${i + 1}`, 0.52 + 0.12 * i);
  });
  k.enter('total, skip, skip2', 1.3, { stagger: 0.08 });
  k.handoff(1.7);
  k.tween(
    'card',
    { opacity: 0, y: 6, scale: 0.98, transformOrigin: '50% 50%' },
    { opacity: 1, y: 0, scale: 1, duration: DUR.short, ease: EASE.out },
    1.85,
  );
  k.enter('c-h, c-code, c-l1, c-l2, c-l3, c-loc', 2.0, { stagger: 0.06 });
  k.enter('b1, b2', 2.65);
  k.click({ x: 56, y: 159 }, 2.85);
  k.fade('b1, b2', 3.65);
  k.enter('done, reason', 3.75, { stagger: 0.08 });
  k.swap('c-h', 'c-h2', 4.0);
  k.fade('ptr', 4.2);
  k.end(4.4);
};
export default build;
