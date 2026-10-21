/** 7.5 送审审定核对（4.95 + 2.4 + 0.4 = 7.75s）。 */
import { EASE } from '../../../../lib/motion-tokens';
import { ART_FACTS } from '../../../../data/capabilities';
import type { ArtBuilder } from '../../art-kit';

const F = ART_FACTS.check;
const amounts = [F.rebar.reduce, F.scaffold.amount, F.slab.reduce, F.window.increase];

const build: ArtBuilder = (k) => {
  k.enter('fa, fb', 0, { stagger: 0.08 });
  k.enter('th', 0.3);
  for (let row = 1; row <= 5; row++) {
    const t = 0.4 + 0.34 * (row - 1);
    k.tween(
      `ga${row}`,
      { x: -30, opacity: 0 },
      { x: 0, opacity: 0.6, duration: 0.32, ease: EASE.inOut },
      t,
    );
    k.tween(
      `gb${row}`,
      { x: 30, opacity: 0 },
      { x: 0, opacity: 0.6, duration: 0.32, ease: EASE.inOut },
      t,
    );
    k.tween(
      `ga${row}, gb${row}`,
      { opacity: 0.6 },
      { opacity: 0, duration: 0.08, ease: EASE.out },
      t + 0.32,
    );
    k.enter(`s${row}, c${row}, v${row}`, t + 0.24);
    const value = amounts[row - 1];
    if (value !== undefined) k.count(`v${row}`, t + 0.24, value, 'money', 0.4);
  }
  k.enter('foot', 2.4);
  k.handoff(2.6);
  k.enter('o-hdr, o-tag', 2.75, { stagger: 0.08 });
  k.enter('o-a', 2.9);
  k.count('o-a-v', 2.9, F.sent, 'money');
  k.enter('o-b', 3.0);
  k.count('o-b-v', 3.0, F.approved, 'money');
  k.enter('o-d', 3.1);
  k.count('o-d-v', 3.1, F.reduce, 'money');
  k.enter('o-r', 3.3);
  k.count('o-r-v', 3.3, F.rate, 'pct2', 0.6);
  k.enter('k1, k2, k3, k4, k5, k6', 3.95, { stagger: 0.06 });
  k.enter('o-file, o-file-n', 4.6);
  k.draw('o-ok', 4.8, 0.2);
  k.end(4.95);
};
export default build;
