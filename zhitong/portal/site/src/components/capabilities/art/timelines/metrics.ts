/** 7.6 造价指标（5.1 + 2.5 + 0.4 = 8.0s）。 */
import { DUR, EASE } from '../../../../lib/motion-tokens';
import { ART_FACTS } from '../../../../data/capabilities';
import type { ArtBuilder } from '../../art-kit';

const M = ART_FACTS.metrics;
const shares = [M.shares.concrete, M.shares.measures, M.shares.windows];

const build: ArtBuilder = (k) => {
  k.enter('hdr', 0);
  k.enter('i-t', 0.2);
  k.count('i-t-v', 0.2, ART_FACTS.check.approved, 'money', 0.6);
  k.enter('i-a', 0.4);
  k.count('i-a-v', 0.4, M.area, 'area', 0.6);
  k.draw('rule', 0.9, 0.3);
  k.enter('i-u', 1.1);
  k.count('i-u-v', 1.1, M.unit, 'money', DUR.long);
  k.enter('i-ul', 1.7);
  k.enter('sl1, sl2, sl3', 1.9, { stagger: 0.1 });
  k.fill('sb1, sb2, sb3', 1.9, 0.45, { stagger: 0.1 });
  k.enter('sv1, sv2, sv3', 1.9, { stagger: 0.1 });
  shares.forEach((v, i) => k.count(`sv${i + 1}`, 1.9 + 0.1 * i, v, 'pct2', 0.45));
  k.handoff(2.6);
  k.enter('o-hdr', 2.75);
  k.enter('p1, p2', 2.9, { stagger: 0.12 });
  k.draw('ax', 3.3, 0.4);
  k.enter('tk', 3.5, { stagger: 0.04 });
  k.tween(
    'd1, d2',
    { opacity: 0, scale: 0.7, y: -8, transformOrigin: '50% 50%' },
    { opacity: 1, scale: 1, y: 0, duration: DUR.micro, ease: EASE.out, stagger: 0.08 },
    3.8,
  );
  k.draw('avg', 4.1, 0.3);
  k.enter('avg-l', 4.1);
  k.tween(
    'me',
    { scale: 0, transformOrigin: '50% 50%' },
    { scale: 1, duration: DUR.short, ease: EASE.out },
    4.4,
  );
  k.enter('me-l', 4.4);
  k.enter('dev', 4.7);
  k.count('dev-v', 4.7, M.deviation, 'pct2', 0.4);
  k.end(5.1, 2.5);
};
export default build;
