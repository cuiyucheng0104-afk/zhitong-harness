/**
 * 把一个场景的终态 DOM 排成 GSAP 时间线（05 章 §1.2.1、§1.5）。
 *
 * - DOM 始终是终态全文；时间线只改 `opacity`、`transform`、SVG 描边（读屏读到完整对话）。
 * - 时间线是暂停的，由 `useAutoplay` 每帧 `time()` 定位，因此每个补间都可前后拖动。
 * - 钉住模式下消息列高度超过窗口正文时，在需要的那一拍把消息列整体 `y` 上移到底部对齐（`DUR.base`、`EASE.inOut`），不用 scrollTop。
 */
import type { Motion } from '../../../lib/motion';
import { DUR, EASE, STAGGER } from '../../../lib/motion-tokens';
import { formatMoney, formatPercent } from '../../../lib/format';
import type { SceneBeat } from '../../../data/workflow';
import { planScene } from './scene-plan';

export interface SceneTimelineOptions {
  /** 钉住模式：窗口高度固定，消息列需要上移。 */
  pinned: boolean;
}

/** 窗口内示意指针的目标点（相对舞台），考虑当时消息列的上移量。 */
function pointAt(stage: HTMLElement, target: HTMLElement, shift: number): { x: number; y: number } {
  const s = stage.getBoundingClientRect();
  const r = target.getBoundingClientRect();
  return {
    x: r.left - s.left + Math.min(48, r.width * 0.3),
    y: r.top - s.top + r.height / 2 - shift,
  };
}

/** 元素顶边相对消息列的距离（布局值，不含 transform）。 */
function offsetWithin(column: HTMLElement, el: HTMLElement): number {
  let top = 0;
  let node: HTMLElement | null = el;
  while (node && node !== column) {
    top += node.offsetTop;
    node = node.offsetParent as HTMLElement | null;
    if (node && !column.contains(node)) break;
  }
  return top;
}

/**
 * 构建场景时间线。
 * @param motion - 已加载的动效句柄。
 * @param stage - 场景舞台元素（`.wf-stage`）。
 * @param beats - 场景节拍。
 * @param opts - 模式。
 * @returns 暂停状态的时间线，时长 = 场景总时长。
 */
export function buildSceneTimeline(
  motion: Motion,
  stage: HTMLElement,
  beats: readonly SceneBeat[],
  opts: SceneTimelineOptions,
): gsap.core.Timeline {
  const { gsap } = motion;
  const { slots, total } = planScene(beats);
  const tl = gsap.timeline({ paused: true });
  const column = stage.querySelector<HTMLElement>('.wf-msgs');
  const pointer = stage.querySelector<HTMLElement>('.wf-pointer');
  const els = beats.map((_, i) => stage.querySelector<HTMLElement>(`[data-beat="${i}"]`));
  /** 初态：立即应用，并在 0 s 处记一次，保证拖回 0 s（重播）时回到同一初态。 */
  const init = (target: Element | ArrayLike<Element> | null | undefined, vars: gsap.TweenVars) => {
    if (!target || ('length' in target && target.length === 0)) return;
    gsap.set(target, vars);
    tl.set(target, vars, 0);
  };

  // 测量消息列：钉住模式下，每拍出现时消息列需要的上移量。
  const body = column?.parentElement;
  const pad = body
    ? parseFloat(getComputedStyle(body).paddingTop) +
      parseFloat(getComputedStyle(body).paddingBottom)
    : 0;
  const viewport = (body?.clientHeight ?? 0) - (pad || 0);
  let shift = 0;
  const shiftAt: number[] = [];
  init(column, { y: 0 });
  if (pointer) init(pointer, { opacity: 0, x: 0, y: 0 });

  beats.forEach((beat, i) => {
    const el = els[i];
    const t = slots[i]!.start;
    if (!el) return;
    if (opts.pinned && column && beat.kind !== 'drop') {
      const bottom = offsetWithin(column, el) + el.offsetHeight;
      const need = Math.max(0, bottom - viewport);
      if (need > shift + 1) {
        shift = need;
        tl.to(column, { y: -shift, duration: DUR.base, ease: EASE.inOut }, t);
      }
    }
    shiftAt[i] = shift;

    if (beat.kind === 'drop') {
      const card = el.querySelector<HTMLElement>('.wf-drop-card');
      init(el, { opacity: 1 });
      if (card) {
        init(card, { opacity: 0 });
        tl.fromTo(
          card,
          { x: 120, y: -80, rotate: 4, scale: 0.9, opacity: 0 },
          {
            x: 0,
            y: 0,
            rotate: 0,
            scale: 1,
            opacity: 1,
            duration: 0.8,
            ease: 'power3.inOut',
            immediateRender: false,
          },
          t,
        );
        tl.to(card, { opacity: 0, scale: 0.86, duration: DUR.short, ease: EASE.out }, t + 0.8);
      }
      return;
    }

    init(el, { opacity: 0 });
    tl.fromTo(
      el,
      { opacity: 0, y: 8 },
      { opacity: 1, y: 0, duration: DUR.short, ease: EASE.out, immediateRender: false },
      t,
    );

    switch (beat.kind) {
      case 'tool': {
        const done = el.querySelectorAll<HTMLElement>(
          '.zt-tool-check, .zt-tool-elapsed, .wf-tool-result',
        );
        const spin = el.querySelector<HTMLElement>('.wf-tool-spin');
        const end = t + DUR.short + beat.run;
        init(done, { opacity: 0 });
        if (spin) {
          init(spin, { opacity: 1 });
          tl.set(spin, { opacity: 0 }, end);
        }
        tl.to(done, { opacity: 1, duration: DUR.micro, ease: EASE.out }, end);
        break;
      }
      case 'card': {
        const rows = el.querySelectorAll<HTMLElement>('[data-row]');
        init(rows, { opacity: 0 });
        tl.fromTo(
          rows,
          { opacity: 0, y: 6 },
          {
            opacity: 1,
            y: 0,
            duration: DUR.short,
            ease: EASE.out,
            stagger: STAGGER.base,
            immediateRender: false,
          },
          t + 0.1,
        );
        if (beat.card === 'projects') {
          const last = el.querySelector<HTMLElement>('[data-pick]');
          if (last && pointer) {
            init(last, { backgroundColor: 'rgba(242, 247, 255, 0)' });
            const to = pointAt(stage, last, shiftAt[i]!);
            tl.fromTo(
              pointer,
              { opacity: 0, x: to.x + 60, y: to.y - 70 },
              {
                opacity: 1,
                x: to.x + 60,
                y: to.y - 70,
                duration: DUR.micro,
                immediateRender: false,
              },
              t + 0.1,
            );
            tl.to(pointer, { x: to.x, y: to.y, duration: 0.6, ease: EASE.inOut }, t + 0.2);
            tl.fromTo(
              last,
              { backgroundColor: 'rgba(242, 247, 255, 0)' },
              {
                backgroundColor: 'rgba(242, 247, 255, 1)',
                duration: DUR.micro,
                immediateRender: false,
              },
              t + 0.8,
            );
            tl.to(pointer, { opacity: 0, duration: DUR.short }, t + 1.3);
          }
        }
        if (beat.card === 'reconcile') {
          el.querySelectorAll<HTMLElement>('[data-count]').forEach((num) => {
            const live = num.parentElement?.querySelector<HTMLElement>('.wf-count-live');
            if (!live) return;
            const to = Number(num.dataset.count);
            const fmt =
              num.dataset.format === 'percent' ? formatPercent : (v: number) => formatMoney(v);
            const proxy = { v: 0 };
            init(num, { opacity: 1 });
            init(live, { opacity: 0 });
            tl.set(num, { opacity: 0 }, t).set(live, { opacity: 1 }, t);
            tl.fromTo(
              proxy,
              { v: 0 },
              {
                v: to,
                duration: DUR.long,
                ease: EASE.expo,
                immediateRender: false,
                onUpdate: () => {
                  live.textContent = fmt(proxy.v);
                },
              },
              t,
            );
            tl.set(num, { opacity: 1 }, t + DUR.long).set(live, { opacity: 0 }, t + DUR.long);
          });
          const fills = el.querySelectorAll<HTMLElement>('.wf-bar-fill');
          init(fills, { scaleX: 0 });
          tl.to(
            fills,
            { scaleX: 1, duration: DUR.long, ease: EASE.expo, stagger: STAGGER.base },
            t,
          );
        }
        break;
      }
      case 'ask': {
        const opt = el.querySelector<HTMLElement>('[data-picked]');
        const reach = t + DUR.base;
        if (opt) {
          init(opt, { attr: { 'data-picked': 'false' } });
          if (pointer) {
            const to = pointAt(stage, opt, shiftAt[i]!);
            tl.fromTo(
              pointer,
              { opacity: 0, x: to.x + 80, y: to.y + 40 },
              {
                opacity: 1,
                x: to.x + 80,
                y: to.y + 40,
                duration: DUR.micro,
                immediateRender: false,
              },
              reach - DUR.micro,
            );
            tl.to(pointer, { x: to.x, y: to.y, duration: 0.6, ease: EASE.inOut }, reach);
            tl.to(pointer, { opacity: 0, duration: DUR.short }, reach + 1);
          }
          tl.to(
            opt,
            { scale: 0.97, duration: 0.06, yoyo: true, repeat: 1, ease: 'power1.inOut' },
            reach + 0.6,
          );
          tl.set(opt, { attr: { 'data-picked': 'true' } }, reach + 0.72);
        }
        break;
      }
      case 'push': {
        const rows = el.querySelectorAll<HTMLElement>('[data-row]');
        rows.forEach((row, k) => {
          const ok = row.querySelector<HTMLElement>('.wf-push-ok');
          init(row, { opacity: 0 });
          tl.fromTo(
            row,
            { opacity: 0, y: 4 },
            { opacity: 1, y: 0, duration: DUR.micro, immediateRender: false },
            t + k * 0.14,
          );
          if (ok) {
            init(ok, { opacity: 0 });
            tl.fromTo(
              ok,
              { opacity: 0, scale: 0.6 },
              { opacity: 1, scale: 1, duration: DUR.micro, ease: EASE.out, immediateRender: false },
              t + k * 0.14 + 0.18,
            );
          }
        });
        break;
      }
      case 'diff': {
        const strikes = el.querySelectorAll<HTMLElement>('.wf-strike');
        const ins = el.querySelectorAll<HTMLElement>('.wf-ins-bg');
        // 有的 diff 卡没有删除线或逐格替换：空集合不建补间（否则 GSAP 报 target not found）。
        if (strikes.length) {
          init(strikes, { scaleX: 0 });
          tl.to(strikes, { scaleX: 1, duration: 0.3, ease: EASE.out }, t + DUR.base);
        }
        if (ins.length) {
          init(ins, { opacity: 1 });
          tl.to(ins, { opacity: 0.4, duration: 1.2, ease: 'none' }, t + DUR.base);
        }
        const olds = el.querySelectorAll<HTMLElement>('.wf-cell-old');
        const news = el.querySelectorAll<HTMLElement>('.wf-cell-new');
        if (olds.length) {
          init(olds, { yPercent: 0 });
          tl.to(
            olds,
            { yPercent: -100, duration: 0.36, ease: EASE.inOut, stagger: 0.08 },
            t + DUR.base,
          );
        }
        if (news.length) {
          init(news, { yPercent: 100 });
          tl.to(news, { yPercent: 0, duration: 0.36, ease: EASE.inOut, stagger: 0.08 }, t + DUR.base);
        }
        break;
      }
      case 'note': {
        const lead = el.querySelector<SVGPathElement>('.wf-note-lead path');
        const rows = el.querySelectorAll<HTMLElement>('[data-row]');
        if (lead) {
          init(lead, { drawSVG: '0% 0%' });
          tl.to(lead, { drawSVG: '0% 100%', duration: 0.3, ease: EASE.out }, t);
        }
        init(rows, { opacity: 0 });
        tl.fromTo(
          rows,
          { opacity: 0, x: -4 },
          { opacity: 1, x: 0, duration: DUR.micro, stagger: 0.09, immediateRender: false },
          t + 0.15,
        );
        break;
      }
      default:
        break;
    }
  });

  // 时间线总长 = 场景总时长（末拍之后不再有补间）。
  if (tl.duration() < total) tl.to({}, { duration: total - tl.duration() });
  return tl;
}
