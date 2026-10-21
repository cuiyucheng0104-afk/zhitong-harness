/**
 * 能力小动画构建工具 `ArtKit`（04 章 §7.1）。
 *
 * 构建函数只调用这里的方法往同一条时间线上排补间；所有补间都是 `fromTo`（显式起点），
 * 每个元素每个属性第一次出现的补间 `immediateRender`，其余不立即渲染，循环回到 0 时由 GSAP 逐个回退到起点。
 * 元素用 `data-a="名"` 标注；`q('a, b')` 取多个名字。
 */
import { DUR, EASE } from '../../lib/motion-tokens';
import { formatInt, formatMoney } from '../../lib/format';
import { ART, textWidth } from './art-tokens';
import { ART_ANIM_SELECTOR } from './art/anim';

export type ArtLayout = 'split' | 'sequence';
export type CountFormat = 'money' | 'int' | 'pct2' | 'area';

export interface ArtKit {
  layout: ArtLayout;
  q(names: string): Element[];
  enter(names: string, at: number, o?: { stagger?: number; dx?: number; dy?: number }): void;
  pop(names: string, at: number, o?: { stagger?: number }): void;
  draw(names: string, at: number, dur: number, o?: { stagger?: number }): void;
  fill(
    names: string,
    at: number,
    dur: number,
    o?: { stagger?: number; origin?: 'left' | 'top' | 'center'; ease?: string },
  ): void;
  count(name: string, at: number, to: number, fmt: CountFormat, dur?: number): void;
  stream(name: string, at: number): number;
  tool(name: string, at: number, done: number, o?: { enter?: boolean }): void;
  swap(from: string, to: string, at: number): void;
  click(target: { x: number; y: number }, at: number): number;
  fade(names: string, at: number): void;
  handoff(at: number): void;
  end(at: number, hold?: number): void;
  /** 任意补充补间（构建函数里个别的 `opacity` 往返、字色变化等），同样遵守“首个补间立即渲染”。 */
  tween(names: string | Element[], from: gsap.TweenVars, to: gsap.TweenVars, at: number): void;
}

export interface ArtKitHandle {
  kit: ArtKit;
  /** `end` 打下的停留标签时刻与停留秒数。 */
  hold(): { at: number; dur: number };
  /** 撤销构建时加的遮罩（虚线描绘用），重建或卸载前调用。 */
  dispose(): void;
}

/** 构建函数。 */
export type ArtBuilder = (kit: ArtKit) => void;

const SHAPES = 'path, line, rect, polyline, polygon, circle, ellipse';

/**
 * 按格式写数字（`count` 用）。
 * @param value - 当前值。
 * @param fmt - 格式。
 * @returns 文本。
 */
export function formatArtNumber(value: number, fmt: CountFormat): string {
  if (fmt === 'int') return formatInt(value);
  if (fmt === 'pct2') return `${formatMoney(value, 2)}%`;
  return formatMoney(value, 2);
}

/**
 * 创建构建工具。
 * @param gsap - 已注册 DrawSVG 的 gsap。
 * @param tl - 目标时间线（暂停状态）。
 * @param stage - `.art-stage` 元素。
 * @param layout - 当前布局。
 * @returns 工具与停留信息。
 */
export function createArtKit(
  gsap: typeof import('gsap').gsap,
  tl: gsap.core.Timeline,
  stage: Element,
  layout: ArtLayout,
): ArtKitHandle {
  const claimed = new WeakMap<Element, Set<string>>();
  const undo: (() => void)[] = [];
  let maskSeq = 0;

  /**
   * 虚线（`data-dashed`）不能直接 DrawSVG（会覆盖 dasharray）：克隆一条实线放进遮罩，描绘遮罩里的线。
   * @returns 要描绘的元素。
   */
  const drawable = (el: Element): Element => {
    if (!el.hasAttribute('data-dashed')) return el;
    const svg = (el as SVGElement).ownerSVGElement;
    if (!svg) return el;
    const ns = 'http://www.w3.org/2000/svg';
    const mask = document.createElementNS(ns, 'mask');
    const id = `art-mask-${el.getAttribute('data-a') ?? 'x'}-${++maskSeq}`;
    mask.setAttribute('id', id);
    mask.setAttribute('maskUnits', 'userSpaceOnUse');
    for (const [k, v] of Object.entries({ x: '-40', y: '-40', width: '344', height: '280' }))
      mask.setAttribute(k, v);
    const clone = el.cloneNode(false) as SVGElement;
    for (const attr of ['data-a', 'data-dashed', 'class', 'style', 'mask'])
      clone.removeAttribute(attr);
    clone.setAttribute('fill', 'none');
    clone.setAttribute('stroke', '#fff');
    clone.setAttribute('stroke-width', '6');
    mask.append(clone);
    svg.append(mask);
    el.setAttribute('mask', `url(#${id})`);
    undo.push(() => {
      mask.remove();
      el.removeAttribute('mask');
    });
    return clone;
  };
  let holdAt = 0;
  let holdDur: number = ART.hold;

  const q = (names: string): Element[] =>
    names
      .split(',')
      .map((n) => n.trim())
      .filter(Boolean)
      .flatMap((n) => [...stage.querySelectorAll(`[data-a="${n}"]`)]);

  /** 任一目标第一次出现这些属性时为 true，并登记。 */
  const first = (targets: Element[], ...props: string[]) => {
    let fresh = false;
    for (const t of targets) {
      let set = claimed.get(t);
      if (!set) claimed.set(t, (set = new Set()));
      for (const p of props)
        if (!set.has(p)) {
          set.add(p);
          fresh = true;
        }
    }
    return fresh;
  };

  const resolve = (names: string | Element[]) => (typeof names === 'string' ? q(names) : names);

  function tween(names: string | Element[], from: gsap.TweenVars, to: gsap.TweenVars, at: number) {
    const targets = resolve(names);
    if (!targets.length) return;
    const props = Object.keys(from).filter((k) => k !== 'transformOrigin' && k !== 'svgOrigin');
    tl.fromTo(targets, from, { ...to, immediateRender: first(targets, ...props) }, at);
  }

  const shapesOf = (targets: Element[]) =>
    targets.flatMap((t) => (t.matches(SHAPES) ? [t] : [...t.querySelectorAll(SHAPES)]));

  const kit: ArtKit = {
    layout,
    q,
    tween,
    enter(names, at, o = {}) {
      tween(
        names,
        { opacity: 0, x: o.dx ?? 0, y: o.dy ?? 6 },
        { opacity: 1, x: 0, y: 0, duration: DUR.short, ease: EASE.out, stagger: o.stagger ?? 0 },
        at,
      );
    },
    pop(names, at, o = {}) {
      tween(
        names,
        { opacity: 0, scale: 0.7, transformOrigin: '50% 50%' },
        { opacity: 1, scale: 1, duration: DUR.micro, ease: EASE.out, stagger: o.stagger ?? 0 },
        at,
      );
    },
    draw(names, at, dur, o = {}) {
      const targets = shapesOf(q(names)).map(drawable);
      tween(
        targets,
        { drawSVG: '0%' },
        { drawSVG: '100%', duration: dur, ease: EASE.inOut, stagger: o.stagger ?? 0 },
        at,
      );
    },
    fill(names, at, dur, o = {}) {
      const origin = o.origin ?? 'left';
      const prop = origin === 'top' ? 'scaleY' : 'scaleX';
      const transformOrigin =
        origin === 'left' ? '0% 50%' : origin === 'top' ? '50% 0%' : '50% 50%';
      tween(
        names,
        { [prop]: 0, transformOrigin },
        { [prop]: 1, duration: dur, ease: o.ease ?? EASE.out, stagger: o.stagger ?? 0 },
        at,
      );
    },
    count(name, at, to, fmt, dur = DUR.long) {
      const el = q(name)[0];
      if (!el) return;
      const prefix = (el as HTMLElement).dataset?.prefix ?? '';
      const suffix = (el as HTMLElement).dataset?.suffix ?? '';
      const proxy = { v: 0 };
      const write = () => {
        el.textContent = `${prefix}${formatArtNumber(proxy.v, fmt)}${suffix}`;
      };
      tl.fromTo(
        proxy,
        { v: 0 },
        { v: to, duration: dur, ease: EASE.expo, onUpdate: write, immediateRender: false },
        at,
      );
    },
    stream(name, at) {
      const el = q(name)[0] as SVGTextContentElement | undefined;
      const rect = stage.querySelector(`[data-clip="${name}"]`);
      if (!el || !rect) return at;
      const text = el.textContent ?? '';
      const dur = [...text].length / ART.cps;
      let w = 0;
      try {
        w = el.getComputedTextLength?.() ?? 0;
      } catch {
        // jsdom 与未布局的 SVG 不支持测量，退回估算宽度。
        w = 0;
      }
      if (!w) w = textWidth(text);
      tween(
        [rect],
        { attr: { width: 0 } },
        { attr: { width: w + 4 }, duration: dur, ease: EASE.linear },
        at,
      );
      return at + dur;
    },
    tool(name, at, done, o = {}) {
      if (o.enter !== false) kit.enter(name, at, { dx: -8, dy: 0 });
      const spin = q(`${name}-spin`);
      tween(
        spin,
        { rotation: 0, opacity: 1, transformOrigin: '50% 50%' },
        { rotation: ((done - at) / 0.8) * 360, duration: done - at, ease: EASE.linear },
        at,
      );
      tween(spin, { opacity: 1 }, { opacity: 0, duration: DUR.micro, ease: EASE.out }, done);
      kit.draw(`${name}-ok`, done, 0.2);
    },
    swap(from, to, at) {
      tween(from, { opacity: 1 }, { opacity: 0, duration: DUR.micro, ease: EASE.inOut }, at);
      tween(
        to,
        { opacity: 0, y: 4 },
        { opacity: 1, y: 0, duration: DUR.short, ease: EASE.out },
        at + 0.08,
      );
    },
    click(target, at) {
      const ptr = q('ptr')[0] as SVGGElement | undefined;
      const arrive = at + 0.5;
      if (!ptr) return arrive;
      const sx = Number(ptr.dataset.x ?? target.x + 48);
      const sy = Number(ptr.dataset.y ?? target.y + 40);
      tween([ptr], { opacity: 0 }, { opacity: 1, duration: DUR.micro, ease: EASE.out }, at);
      tween(
        [ptr],
        { x: sx, y: sy },
        { x: target.x, y: target.y, duration: 0.5, ease: EASE.inOut },
        at,
      );
      tween(
        [ptr],
        { scale: 1, transformOrigin: '0% 0%' },
        { scale: 0.86, duration: 0.08, ease: EASE.out },
        arrive,
      );
      tween([ptr], { scale: 0.86 }, { scale: 1, duration: 0.08, ease: EASE.out }, arrive + 0.08);
      tween(
        q('ptr-ring'),
        { attr: { r: 4 }, opacity: 0.5 },
        { attr: { r: 14 }, opacity: 0, duration: 0.4, ease: EASE.out },
        arrive,
      );
      return arrive;
    },
    fade(names, at) {
      tween(names, { opacity: 1 }, { opacity: 0, duration: DUR.micro, ease: EASE.inOut }, at);
    },
    handoff(at) {
      tl.addLabel('handoff', at);
      if (layout === 'split') {
        kit.draw('link', at, 0.36);
        tween(q('link-dot'), { x: 0, opacity: 1 }, { x: 22, duration: 0.36, ease: EASE.inOut }, at);
        tween(
          q('link-dot'),
          { opacity: 1 },
          { opacity: 0, duration: DUR.micro, ease: EASE.out },
          at + 0.36,
        );
        return;
      }
      const inSvg = stage.querySelector('.art-in');
      const outSvg = stage.querySelector('.art-out');
      if (!inSvg || !outSvg) return;
      tl.fromTo(
        inSvg,
        { opacity: 1, x: 0 },
        { opacity: 1, x: 0, duration: 0, immediateRender: true },
        0,
      );
      tl.fromTo(
        outSvg,
        { opacity: 0, x: 16 },
        { opacity: 0, x: 16, duration: 0, immediateRender: true },
        0,
      );
      tl.fromTo(
        inSvg,
        { opacity: 1, x: 0 },
        { opacity: 0, x: -16, duration: DUR.short, ease: EASE.inOut, immediateRender: false },
        at,
      );
      tl.fromTo(
        outSvg,
        { opacity: 0, x: 16 },
        { opacity: 1, x: 0, duration: DUR.short, ease: EASE.out, immediateRender: false },
        at + 0.12,
      );
    },
    end(at, hold = ART.hold) {
      tl.addLabel('hold', at);
      holdAt = at;
      holdDur = hold;
    },
  };

  return {
    kit,
    hold: () => ({ at: holdAt, dur: holdDur }),
    dispose: () => {
      for (const fn of undo.splice(0)) fn();
    },
  };
}

/**
 * 在构建函数之后追加停留与复位段（全部动画元素（`[data-a]`）淡出），使循环总长 = 构建 + 停留 + 复位。
 * @param gsap - gsap。
 * @param tl - 时间线。
 * @param stage - `.art-stage`。
 * @param hold - `end` 记下的停留。
 */
export function finishArtLoop(
  gsap: typeof import('gsap').gsap,
  tl: gsap.core.Timeline,
  stage: Element,
  hold: { at: number; dur: number },
) {
  void gsap;
  const start = hold.at + hold.dur;
  tl.to({}, { duration: hold.dur }, hold.at);
  const anim = stage.querySelectorAll(ART_ANIM_SELECTOR);
  if (anim.length) tl.to(anim, { opacity: 0, duration: ART.reset, ease: EASE.inOut }, start);
  else tl.to({}, { duration: ART.reset }, start);
}
