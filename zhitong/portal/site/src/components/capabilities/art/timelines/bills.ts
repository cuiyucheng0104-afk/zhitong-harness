/** 7.10 GB50854 清单框架（4.9 + 2.4 + 0.4 = 7.7s）。 */
import { ART_FACTS } from '../../../../data/capabilities';
import type { ArtBuilder } from '../../art-kit';

const BLUE = '#0666f5';
const INK = '#162943';

const build: ArtBuilder = (k) => {
  k.enter('hdr', 0);
  k.enter('y1, y2, y3, y4', 0.15, { stagger: 0.08 });
  [0.75, 0.97, 1.19, 1.41].forEach((t, i) => k.pop(`r${i + 1}`, t));
  k.draw('mg2', 0.97, 0.3);
  k.draw('mg3', 1.19, 0.3);
  k.enter('seg2, y5', 1.7, { stagger: 0.08 });
  k.pop('r5', 2.0);
  k.enter('reg', 2.2);
  k.handoff(2.4);
  k.enter('o-hdr', 2.55);
  k.enter('i1', 2.7, { dx: -6 });
  k.tween(
    'ser',
    { fill: BLUE },
    { fill: INK, duration: 0.2, repeat: 3, yoyo: true, ease: 'none' },
    2.95,
  );
  k.enter('f1, f2, f3', 3.05, { stagger: 0.08 });
  k.enter('q', 3.45);
  k.draw('q-box', 3.45, 0.4);
  k.enter('p, p2', 3.9, { stagger: 0.08 });
  k.enter('cov', 4.3);
  k.count('cov-a', 4.3, ART_FACTS.bills.segments, 'int', 0.6);
  k.count('cov-b', 4.3, ART_FACTS.bills.segments, 'int', 0.6);
  k.end(4.9);
};
export default build;
