/** 7.12 企业知识库（4.85 + 2.4 + 0.4 = 7.65s）。 */
import { DUR, EASE } from '../../../../lib/motion-tokens';
import type { ArtBuilder } from '../../art-kit';

const MUTED = '#5c6d82';
const BLUE = '#0666f5';

const build: ArtBuilder = (k) => {
  k.enter('hdr', 0);
  k.enter('src-bg, src-file, src-cl', 0.15, { stagger: 0.08 });
  k.stream('q1', 0.55);
  k.stream('q2', 1.11);
  k.enter('ask-bg, ask-t, ask-f, ask-y, ask-n', 1.55, { stagger: 0.06 });
  k.click({ x: 174, y: 147 }, 1.75);
  k.swap('ask-y, ask-n', 'ask-ok', 2.45);
  k.fade('ptr', 2.55);
  k.handoff(2.65);
  k.enter('o-hdr, o-dirs', 2.8, { stagger: 0.08 });
  k.tween('o-dirs-hl', { fill: MUTED }, { fill: BLUE, duration: DUR.short, ease: EASE.out }, 3.05);
  k.enter('o-new', 3.15, { dx: -12 });
  k.enter('e1, e2, e3, e4, e5', 3.45, { stagger: 0.08 });
  k.tool('chk-t', 4.1, 4.6);
  k.swap('chk-t', 'chk', 4.6);
  k.end(4.85);
};
export default build;
