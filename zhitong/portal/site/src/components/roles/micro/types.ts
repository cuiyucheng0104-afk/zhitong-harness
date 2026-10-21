/** 十二个说明卡小动画的共用类型（03 章 §1.5.7）。 */
import type { Component } from 'vue';

/** GSAP 主对象类型（只用类型，不在运行时引入 gsap）。 */
export type Gsap = typeof import('gsap').gsap;

/**
 * 构建小动画时间线：返回暂停的时间线，`from` 段在构建时即把画面置为起始态；
 * `revert()` 后回到组件的静态 SVG（即末帧）。
 */
export type MicroBuild = (svg: SVGSVGElement, gsap: Gsap) => gsap.core.Timeline;

/** 小动画模块：默认导出组件（静态 SVG = 末帧），具名导出 `build`。 */
export interface MicroModule {
  default: Component;
  build: MicroBuild;
}

/** 在 svg 内按 `data-m` 取元素。 */
export function pick(svg: SVGSVGElement, name: string): SVGElement[] {
  return [...svg.querySelectorAll<SVGElement>(`[data-m="${name}"]`)];
}

/**
 * 在时间线起点把目标立即置为给定状态（构建时即生效，播放越过起点后保持）。
 * @param tl - 时间线。
 * @param targets - 目标。
 * @param vars - 状态。
 */
export function hold(tl: gsap.core.Timeline, targets: gsap.TweenTarget, vars: gsap.TweenVars) {
  tl.fromTo(targets, { ...vars }, { ...vars, duration: 0.001, immediateRender: true }, 0);
}
