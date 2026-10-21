/** 7.11 归档与案例索引（4.8 + 2.4 + 0.4 = 7.6s）。 */
import { DUR, EASE } from '../../../../lib/motion-tokens';
import type { ArtBuilder } from '../../art-kit';

const build: ArtBuilder = (k) => {
  k.enter('hdr', 0);
  k.enter('g1, a1, a2, a3, g2, w1, w2, w3, w4, w5', 0.15, { stagger: 0.05 });
  k.pop('ck1, ck2, ck3, ck4, ck5, ck6, ck7, ck8', 0.6, { stagger: 0.05 });
  k.pop('warn1', 1.05);
  k.enter('ask', 1.4);
  k.click({ x: 60, y: 109 }, 1.6);
  k.fade('ask', 2.3);
  k.swap('warn1', 'push', 2.35);
  k.fill('pbar', 2.35, 0.6, { ease: EASE.linear });
  k.handoff(3.05);
  k.fade('ptr', 3.05);
  k.enter('o-hdr, o-note', 3.2, { stagger: 0.08 });
  k.fill('o-bg', 3.4, DUR.short, { origin: 'top' });
  k.enter('fd', 3.55, { stagger: 0.05 });
  k.draw('o-link', 4.45, 0.3);
  k.end(4.8);
};
export default build;
