/**
 * 数据流图的入场与循环时间线（05 章 §2.5）。只为当前显示的那套几何创建（AC-05-25）。
 * 数据包用 MotionPathPlugin 沿连线走（`align` 到路径、`alignOrigin: [0.5, 0.5]`、`autoRotate: false`）。
 * `amount` 只走 `reviewPath`；去往模型的只有虚线 `amountEcho`；`credential` 只走 `credStub`，止于锁前。
 */
import type { Motion } from '../../../lib/motion';
import { DUR, EASE, STAGGER } from '../../../lib/motion-tokens';
import type { PacketKind, TrustNodeId, TrustPathId } from './trust-geometry';

/** 循环参数：`repeat: -1`、`repeatDelay: 1.5`。 */
export const FLOW_REPEAT_DELAY = 1.5;

export interface TrustTimelines {
  entrance: gsap.core.Timeline;
  flow: gsap.core.Timeline;
}

/**
 * 为一套已渲染的 SVG 建入场与循环时间线（都处于暂停）。
 * @param motion - 动效句柄。
 * @param svg - 该几何的 `<svg>`。
 * @returns 入场与循环时间线。
 */
export function buildTrustTimelines(motion: Motion, svg: SVGSVGElement): TrustTimelines {
  const { gsap } = motion;
  const q = <T extends Element>(sel: string) => svg.querySelector<T>(sel);
  const node = (n: TrustNodeId) => q<SVGRectElement>(`[data-node="${n}"] .trust-node-box`);
  const path = (p: TrustPathId) => q<SVGPathElement>(`[data-path="${p}"] path`);
  const packet = (k: PacketKind) => q<SVGGElement>(`[data-packet="${k}"]`);

  // 入场：节点 opacity 0→1、y 8→0（tos、电脑外框、三车道、model、review）；连线 DrawSVG，与节点同起点后 0.2 s。
  const entrance = gsap.timeline({ paused: true });
  const order = [
    node('tos'),
    q('.trust-frame rect'),
    node('cache'),
    node('script'),
    node('cred'),
    node('model'),
    node('review'),
  ].filter(Boolean);
  entrance.fromTo(
    order,
    { opacity: 0, y: 8 },
    { opacity: 1, y: 0, duration: DUR.base, ease: EASE.out, stagger: STAGGER.base },
    0,
  );
  entrance.fromTo(
    svg.querySelectorAll('.trust-label text, .trust-lock-inner, .trust-keys'),
    { opacity: 0 },
    { opacity: 1, duration: DUR.base, ease: EASE.out },
    0.1,
  );
  entrance.fromTo(
    svg.querySelectorAll('.trust-path path'),
    { drawSVG: '0% 0%' },
    {
      drawSVG: '0% 100%',
      duration: DUR.long,
      ease: EASE.out,
      stagger: STAGGER.base,
      clearProps: 'strokeDasharray,strokeDashoffset',
    },
    0.2,
  );

  // 循环。
  const flow = gsap.timeline({ paused: true, repeat: -1, repeatDelay: FLOW_REPEAT_DELAY });
  const all = (['file', 'amount', 'amountEcho', 'credential', 'reply', 'result'] as PacketKind[])
    .map(packet)
    .filter(Boolean);
  const lockLabel = q('[data-lock-label] text');
  const check = q('.trust-tos-check');
  flow.set(all, { opacity: 0 }, 0);
  if (lockLabel) flow.set(lockLabel, { opacity: 0 }, 0);
  if (check) flow.set(check, { opacity: 0, scale: 0, transformOrigin: '50% 50%' }, 0);

  const along = (
    el: Element | null,
    p: SVGPathElement | null,
    at: number,
    duration: number,
    ease = 'power1.inOut',
  ) => {
    if (!el || !p) return;
    flow.to(
      el,
      {
        motionPath: { path: p, align: p, alignOrigin: [0.5, 0.5], autoRotate: false },
        duration,
        ease,
      },
      at,
    );
  };
  const placeAt = (el: Element | null, p: SVGPathElement | null, at: number) => {
    if (!el || !p) return;
    flow.set(
      el,
      { motionPath: { path: p, align: p, alignOrigin: [0.5, 0.5], start: 0, end: 0 } },
      at,
    );
  };
  const pulse = (n: TrustNodeId, at: number, peak = 3) => {
    const box = node(n);
    if (box)
      flow.to(
        box,
        { keyframes: { strokeWidth: [1.5, peak, 1.5] }, duration: DUR.base, ease: 'none' },
        at,
      );
  };
  const flash = (n: TrustNodeId, color: string, at: number) => {
    const box = node(n);
    if (box)
      flow.to(
        box,
        { fill: color, duration: 0.25, yoyo: true, repeat: 1, ease: 'power1.inOut' },
        at,
      );
  };

  // 0.00 文件：出现在 pull 起点，沿 pull；0.90 缓存车道闪；1.25 沿 ctxFile；2.55 模型脉冲，文件淡出。
  const file = packet('file');
  placeAt(file, path('pull'), 0);
  flow.to(file, { opacity: 1, duration: DUR.micro }, 0);
  along(file, path('pull'), 0, 0.9);
  flash('cache', '#f2f7ff', 0.9);
  along(file, path('ctxFile'), 1.25, 1.3);
  pulse('model', 2.55);
  flow.to(file, { opacity: 0, duration: 0.2 }, 2.55);

  // 1.00 凭据：在 credStub 起点出现；1.28 沿 credStub；1.73 锁抖动并闪红，凭据左移淡出，“不进对话”出现到 3.60。
  const cred = packet('credential');
  placeAt(cred, path('credStub'), 0);
  flow.fromTo(
    cred,
    { opacity: 0, scale: 0.6 },
    { opacity: 1, scale: 1, duration: DUR.short, ease: 'back.out(2)', immediateRender: false },
    1.0,
  );
  along(cred, path('credStub'), 1.28, 0.45, 'power2.in');
  const lock = q('.trust-lock-inner');
  const lockBody = q('.trust-lock-body');
  if (lock)
    flow.to(lock, { keyframes: { x: [0, -3, 3, -2, 2, 0] }, duration: 0.36, ease: 'none' }, 1.73);
  if (lockBody) flow.to(lockBody, { fill: '#b4400f', duration: 0.18, yoyo: true, repeat: 1 }, 1.73);
  if (cred) flow.to(cred, { x: '-=6', opacity: 0, duration: 0.3 }, 1.73);
  if (lockLabel) {
    flow.to(lockLabel, { opacity: 1, duration: 0.2 }, 1.73);
    flow.to(lockLabel, { opacity: 0, duration: 0.2 }, 3.6);
  }

  // 3.00 脚本车道闪绿，金额出现在车道左缘；3.20 沿 reviewPath；4.30 复核脉冲。
  const amount = packet('amount');
  flash('script', '#e6f8f0', 3.0);
  placeAt(amount, path('reviewPath'), 0);
  flow.to(amount, { opacity: 1, duration: 0.2 }, 3.0);
  along(amount, path('reviewPath'), 3.2, 1.1);
  pulse('review', 4.3);
  flow.to(amount, { opacity: 0, duration: 0.2 }, 4.5);

  // 3.30 金额回声（虚线圆）沿 ctxSum；4.60 模型小脉冲。
  const echo = packet('amountEcho');
  placeAt(echo, path('ctxSum'), 0);
  flow.to(echo, { opacity: 0.9, duration: 0.2 }, 3.3);
  along(echo, path('ctxSum'), 3.3, 1.3);
  pulse('model', 4.6, 2.2);
  flow.to(echo, { opacity: 0, duration: 0.2 }, 4.6);

  // 5.00 回复沿 reply；6.40 复核脉冲。
  const reply = packet('reply');
  placeAt(reply, path('reply'), 0);
  flow.to(reply, { opacity: 1, duration: DUR.micro }, 5.0);
  along(reply, path('reply'), 5.0, 1.4);
  pulse('review', 6.4);
  flow.to(reply, { opacity: 0, duration: 0.2 }, 6.4);

  // 6.80 成果在缓存车道左缘出现，沿 push；7.70 tos 脉冲与对勾，停留 0.8 s 后淡出。
  const result = packet('result');
  placeAt(result, path('push'), 0);
  flow.to(result, { opacity: 1, duration: DUR.micro }, 6.8);
  along(result, path('push'), 6.8, 0.9);
  pulse('tos', 7.7);
  flow.to(result, { opacity: 0, duration: 0.2 }, 7.7);
  if (check) {
    flow.to(check, { opacity: 1, scale: 1, duration: DUR.short, ease: EASE.out }, 7.7);
    flow.to(check, { opacity: 0, duration: 0.2 }, 7.7 + DUR.short + 0.8);
  }

  return { entrance, flow };
}
