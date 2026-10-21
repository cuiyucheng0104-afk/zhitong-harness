/** 7.13 火山引擎运维（4.95 + 2.4 + 0.4 = 7.75s）。 */
import type { ArtBuilder } from '../../art-kit';

const build: ArtBuilder = (k) => {
  k.enter('bubble', 0);
  k.tool('t1', 0.4, 0.85);
  k.enter('t1-res', 0.9);
  k.tool('t2', 0.95, 1.45);
  k.enter('p0, p1, p2, p3', 1.5, { stagger: 0.1 });
  k.handoff(2.2);
  k.enter('card', 2.35);
  k.enter('c-t, c-1, c-2, c-3, c-4, c-cmd', 2.5, { stagger: 0.06 });
  k.enter('b1, b2', 3.15);
  k.click({ x: 44, y: 168 }, 3.35);
  k.fade('b1, b2', 4.05);
  k.tool('run', 4.1, 4.6);
  k.enter('res', 4.65);
  k.fade('ptr', 4.8);
  k.end(4.95);
};
export default build;
