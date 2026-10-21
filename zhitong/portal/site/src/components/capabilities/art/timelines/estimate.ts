/** 7.8 概算编制辅助（5.3 + 2.3 + 0.4 = 8.0s）。 */
import { DUR, EASE } from '../../../../lib/motion-tokens';
import type { ArtBuilder } from '../../art-kit';

/** 用实际排版宽度改写引文高亮矩形（量不到时保留预渲染的估算值）。 */
function measureQuotes(k: Parameters<ArtBuilder>[0]) {
  for (const rect of k.q('hl-D4, hl-D15, hl-D19a, hl-D19b, hl-D20, hl-D10, hl-D7, hl-T')) {
    const q = (rect as SVGElement).dataset.hl;
    const span = (rect as SVGElement).ownerSVGElement?.querySelector<SVGTSpanElement>(
      `tspan[data-q="${q}"]`,
    );
    const text = span?.parentElement as unknown as SVGTextElement | null;
    if (!span || !text) continue;
    try {
      const spans = [...text.querySelectorAll('tspan')];
      const index = spans.indexOf(span);
      let offset = 0;
      for (let i = 0; i < index; i++) offset += spans[i]!.getComputedTextLength();
      const width = span.getComputedTextLength();
      if (!width) continue;
      rect.setAttribute('x', String(8 + offset - 2));
      rect.setAttribute('width', String(width + 4));
    } catch {
      // 未布局（不可见）或环境不支持测量：保留估算值。
    }
  }
}

const build: ArtBuilder = (k) => {
  measureQuotes(k);
  k.enter('hdr, page', 0);
  k.enter('ln1, ln2, ln3, ln4, ln5, ln6, ln7', 0.2, { stagger: 0.06 });
  const quotes = ['hl-D4', 'hl-D15', 'hl-D19a, hl-D19b', 'hl-D20', 'hl-D10', 'hl-D7'];
  quotes.forEach((q, i) => k.fill(q, 0.9 + 0.18 * i, 0.24));
  k.fill('hl-T', 2.04, 0.24);
  k.pop('chk', 2.3);
  k.handoff(2.5);
  k.enter('o-hdr', 2.65);
  k.enter('or1, or2, or3, or4, or5, or6', 2.8, { stagger: 0.08 });
  k.enter('o-rest-a', 3.4);
  k.tween(
    'ask',
    { opacity: 0, y: 6, scale: 0.96, transformOrigin: '50% 50%' },
    { opacity: 1, y: 0, scale: 1, duration: DUR.short, ease: EASE.out },
    3.6,
  );
  k.click({ x: 66, y: 113 }, 3.8);
  k.fade('ask', 4.45);
  k.tween(
    'ob1, ob2, ob3, ob4, ob5, ob6',
    { opacity: 1 },
    { opacity: 0, duration: DUR.short, ease: EASE.out, stagger: 0.05 },
    4.55,
  );
  k.swap('o-rest-a', 'o-rest', 4.6);
  k.enter('o-fx', 4.9);
  // §7.8 写的是“各 0.2s”，但 0.2 + 0.2 会越过 5.30 的停留标签；压到各 0.12s，使终帧不留高亮。
  k.tween('o-fx-hl', { opacity: 0 }, { opacity: 1, duration: 0.12, ease: EASE.out }, 5.05);
  k.tween('o-fx-hl', { opacity: 1 }, { opacity: 0, duration: 0.12, ease: EASE.out }, 5.17);
  // 指针 5.20 淡出，时长压到 0.1s 以在 5.30 前消失。
  k.tween('ptr', { opacity: 1 }, { opacity: 0, duration: 0.1, ease: EASE.inOut }, 5.2);
  k.end(5.3, 2.3);
};
export default build;
