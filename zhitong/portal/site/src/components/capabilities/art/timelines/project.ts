/** 7.2 开项目与资料盘点（构建 4.8 + 停留 2.4 + 复位 0.4 = 7.6s）。 */
import { DUR, EASE } from '../../../../lib/motion-tokens';
import type { ArtBuilder } from '../../art-kit';

const build: ArtBuilder = (k) => {
  k.enter('hdr', 0);
  k.enter('r1, r2, r3, r4, r5, r6, r7', 0.1, { stagger: 0.05 });
  k.tween('scan', { opacity: 0, y: 0 }, { opacity: 1, duration: DUR.micro, ease: EASE.out }, 0.7);
  k.pop('m1', 0.78);
  for (let row = 2; row <= 7; row++) {
    const t = 0.78 + 0.26 * (row - 1);
    k.tween(
      'scan',
      { y: 22 * (row - 2) },
      { y: 22 * (row - 1), duration: 0.2, ease: EASE.inOut },
      t - 0.2,
    );
    k.pop(`m${row}`, t);
  }
  k.fade('scan', 2.5);
  k.handoff(2.5);
  k.enter('o-hdr', 2.66);
  k.fill('bar1, bar2, bar3, bar4, bar5, bar6, bar7', 2.8, 0.2, { stagger: 0.06 });
  k.enter('o-sum', 3.1);
  k.enter('o-rate', 3.3);
  k.count('o-rate-v', 3.3, 42.86, 'pct2');
  k.enter('o-miss, c1, c2, c3', 3.8, { stagger: 0.08 });
  k.enter('o-pend', 4.3);
  k.enter('o-foot', 4.5);
  k.end(4.8);
};
export default build;
