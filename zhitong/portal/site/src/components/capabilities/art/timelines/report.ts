/** 7.9 报告撰写（5.45 + 2.15 + 0.4 = 8.0s）。 */
import { DUR, EASE } from '../../../../lib/motion-tokens';
import type { ArtBuilder } from '../../art-kit';

const build: ArtBuilder = (k) => {
  k.enter('hdr', 0);
  k.enter('s1, s2, s3, s4, s5, s6, s7, s8, s9', 0.15, { stagger: 0.04 });
  k.pop('mk1, mk2, mk3, mk4, mk5', 0.8, { stagger: 0.08 });
  k.fill('cur', 1.3, DUR.short);
  k.tween('s6-spin', { opacity: 0 }, { opacity: 1, duration: DUR.micro, ease: EASE.out }, 1.3);
  k.tween(
    's6-spin',
    { rotation: 0, transformOrigin: '50% 50%' },
    { rotation: 1440, duration: 3.15, ease: EASE.linear },
    1.3,
  );
  k.handoff(1.6);
  k.enter('o-hdr', 1.75);
  [1.85, 2.33, 2.73, 3.13, 3.5].forEach((t, i) => k.stream(`d${i + 1}`, t));
  k.stream('d6', 4.06);
  k.pop('d7', 4.27);
  k.swap('o-hdr', 'o-hdr2', 4.45);
  k.fade('s6-spin', 4.45);
  k.draw('mk6', 4.45, 0.2);
  for (let i = 1; i <= 5; i++) k.swap(`d${i}`, `f${i}`, 4.55 + 0.1 * (i - 1));
  k.enter('src', 5.25);
  k.end(5.45, 2.15);
};
export default build;
