/** 07 章 §3–4：装饰共享运行时、同屏调度、启动闸、无障碍、减少动效、打印与依赖约束。 */
import { readFileSync, readdirSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { ref, nextTick } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { createSSRApp } from 'vue';
import { cappedDpr, createDecoLoop, resolveDecoMode, sizeCanvas, type DecoLoopOptions } from '../src/components/deco/decoLoop';
import { registerDeco, schedulerSnapshot } from '../src/components/deco/decoScheduler';
import { DECO_START_FLOOR_MS, resetDecoGate, whenDecoReady } from '../src/components/deco/decoStart';
import DecoHeroGrid from '../src/components/deco/DecoHeroGrid.vue';
import DecoInstallField from '../src/components/deco/DecoInstallField.vue';
import DecoFooterMark from '../src/components/deco/DecoFooterMark.vue';
import DecoDimension from '../src/components/deco/DecoDimension.vue';
import DecoMissingSheet from '../src/components/deco/DecoMissingSheet.vue';

const decoCss = readFileSync('src/styles/deco.css', 'utf8');

let frames: FrameRequestCallback[] = [];
let now = 0;
function stepFrames(count: number, ms = 16.67) {
  for (let i = 0; i < count; i++) {
    const q = frames;
    frames = [];
    now += ms;
    for (const cb of q) cb(now);
  }
}

function host(w = 400, h = 200) {
  const el = document.createElement('div');
  el.getBoundingClientRect = () => ({ width: w, height: h, left: 0, top: 0, right: w, bottom: h, x: 0, y: 0, toJSON() {} }) as DOMRect;
  document.body.appendChild(el);
  return el;
}

beforeEach(() => {
  frames = [];
  now = 0;
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    frames.push(cb);
    return frames.length;
  });
  vi.stubGlobal('cancelAnimationFrame', () => {
    frames = [];
  });
});
afterEach(() => vi.unstubAllGlobals());

function options(over: Partial<DecoLoopOptions> = {}) {
  const calls = { tick: 0, still: 0, resize: [] as number[][] };
  const opts: DecoLoopOptions = {
    tick: () => {
      calls.tick++;
      return true;
    },
    resize: (w, h, d) => calls.resize.push([w, h, d]),
    still: () => calls.still++,
    view: { active: ref(true), ratio: ref(1) },
    resolveMode: () => 'live',
    ...over,
  };
  return { opts, calls };
}

describe('07 §3.1–3.2 createDecoLoop', () => {
  it('AC-07-02 减少动效：模式 still，不请求帧，只画静态终帧', () => {
    // tests/setup.ts 的 matchMedia 对 prefers-reduced-motion 返回 true
    expect(resolveDecoMode()).toBe('still');
    const { opts, calls } = options({ resolveMode: undefined });
    const loop = createDecoLoop(host(), null, opts);
    expect(loop.mode).toBe('still');
    stepFrames(180);
    expect(calls.tick).toBe(0);
    expect(calls.still).toBeGreaterThan(0);
    expect(loop.running).toBe(false);
    loop.destroy();
  });

  it('AC-07-03 离开视口后帧数增量为 0；回来后时钟从原处继续，不重播', () => {
    const active = ref(true);
    const ratio = ref(1);
    let lastT = 0;
    const { opts, calls } = options({
      view: { active, ratio },
      tick: (t) => {
        calls.tick++;
        lastT = t;
        return true;
      },
    });
    const loop = createDecoLoop(host(), null, opts);
    stepFrames(30);
    const t1 = lastT;
    expect(t1).toBeGreaterThan(0.4);
    active.value = false;
    ratio.value = 0;
    return nextTick().then(() => {
      const before = calls.tick;
      stepFrames(60);
      expect(calls.tick).toBe(before);
      expect(loop.running).toBe(false);
      active.value = true;
      ratio.value = 1;
      return nextTick().then(() => {
        stepFrames(2);
        expect(lastT).toBeGreaterThan(t1);
        expect(lastT).toBeLessThan(t1 + 0.1);
        loop.destroy();
      });
    });
  });

  it('dt 截到 ≤ 0.05 s；tick 返回 false 后休眠，wake() 唤醒', () => {
    const dts: number[] = [];
    let more = true;
    const { opts } = options({
      tick: (_t, dt) => {
        dts.push(dt);
        return more;
      },
    });
    const loop = createDecoLoop(host(), null, opts);
    stepFrames(1);
    stepFrames(1, 500);
    expect(Math.max(...dts)).toBeLessThanOrEqual(0.05);
    more = false;
    stepFrames(1);
    expect(loop.running).toBe(false);
    const n = dts.length;
    stepFrames(30);
    expect(dts.length).toBe(n);
    more = true;
    loop.wake();
    stepFrames(3);
    expect(dts.length).toBe(n + 3);
    loop.destroy();
  });

  it('once 模式：入场结束后停在终帧，不再请求帧', () => {
    let k = 0;
    const { opts, calls } = options({ resolveMode: () => 'once', tick: () => ++k < 10 });
    const loop = createDecoLoop(host(), null, opts);
    stepFrames(40);
    expect(k).toBe(10);
    expect(calls.still).toBe(1);
    loop.wake();
    stepFrames(10);
    expect(k).toBe(10);
    loop.destroy();
  });

  it('预算守卫：连续 90 帧超过 budgetMs 时 dprCap 降为 1 并重建一次', () => {
    Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 2 });
    let t = 0;
    vi.spyOn(performance, 'now').mockImplementation(() => (t += 2));
    const { opts, calls } = options({ budgetMs: 1 });
    const loop = createDecoLoop(host(), null, opts);
    expect(calls.resize.at(-1)?.[2]).toBe(2);
    stepFrames(95);
    expect(calls.resize.at(-1)?.[2]).toBe(1);
    loop.destroy();
    Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 1 });
  });

  it('destroy 取消 rAF 并移除监听', () => {
    const remove = vi.spyOn(document, 'removeEventListener');
    const { opts, calls } = options();
    const loop = createDecoLoop(host(), null, opts);
    loop.destroy();
    const n = calls.tick;
    stepFrames(10);
    expect(calls.tick).toBe(n);
    expect(remove).toHaveBeenCalledWith('visibilitychange', expect.any(Function));
  });

  it('AC-07-06 DPR 3 时画布像素宽 = CSS 宽 × 2', () => {
    Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 3 });
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    expect(cappedDpr()).toBe(2);
    const c = document.createElement('canvas');
    sizeCanvas(c, 390, 120, cappedDpr());
    expect(c.width).toBe(780);
    expect(c.height).toBe(240);
    Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 1 });
  });
});

describe('07 §3.3 同屏调度', () => {
  it('AC-07-08 两个 live 装饰同时可见时，任一时刻最多一个持有待机运行权', () => {
    const a = registerDeco(() => {});
    const b = registerDeco(() => {});
    const seq = [
      [0.4, 0.6],
      [0.8, 0.6],
      [0.8, 0.9],
      [0, 0.9],
      [0.3, 0],
      [0.5, 0.5],
    ];
    for (const [ra, rb] of seq) {
      a.setRatio(ra);
      b.setRatio(rb);
      expect(schedulerSnapshot().granted).toBeLessThanOrEqual(1);
      if (ra > rb) expect(a.granted).toBe(true);
      if (rb > ra) expect(b.granted).toBe(true);
    }
    a.setRatio(0);
    b.setRatio(0);
    expect(schedulerSnapshot().granted).toBe(0);
    a.release();
    b.release();
    expect(schedulerSnapshot().size).toBe(0);
  });

  it('运行权变化时通知（被挂起的一方据此画静态终帧并休眠）', () => {
    const log: string[] = [];
    const a = registerDeco((g) => log.push(`a${g ? '+' : '-'}`));
    const b = registerDeco((g) => log.push(`b${g ? '+' : '-'}`));
    a.setRatio(0.5);
    b.setRatio(0.7);
    expect(log).toEqual(['a+', 'a-', 'b+']);
    a.release();
    b.release();
  });
});

describe('07 §3.2 第 1 步 启动闸（AC-07-07）', () => {
  it('首屏可交互前（idle 或 1.5 s 之前）不启动', async () => {
    vi.useFakeTimers();
    resetDecoGate();
    vi.spyOn(performance, 'now').mockReturnValue(200);
    let ready = false;
    void whenDecoReady().then(() => (ready = true));
    await vi.advanceTimersByTimeAsync(1000);
    expect(ready).toBe(false);
    await vi.advanceTimersByTimeAsync(DECO_START_FLOOR_MS);
    expect(ready).toBe(true);
    vi.useRealTimers();
    resetDecoGate();
  });
});

describe('AC-07-01 装饰根元素 aria-hidden，内部无可聚焦元素', () => {
  it.each([
    ['D1', DecoHeroGrid, {}],
    ['D2', DecoInstallField, {}],
    ['D3', DecoFooterMark, {}],
    ['D4', DecoDimension, { from: '3', to: '4' }],
    ['D5', DecoMissingSheet, {}],
  ])('%s', async (_id, comp, props) => {
    const w = mount(comp as never, { props: props as never, attachTo: document.body });
    await flushPromises();
    const el = w.element as Element;
    expect(el.getAttribute('aria-hidden')).toBe('true');
    expect(el.querySelectorAll('a, button, input, select, textarea, [tabindex]').length).toBe(0);
    w.unmount();
  });

  it('D5 根元素 focusable="false"', () => {
    const w = mount(DecoMissingSheet);
    expect(w.element.getAttribute('focusable')).toBe('false');
  });
});

describe('AC-07-07 / AC-07-14 预渲染只输出静态底', () => {
  it('D1：.bp-paper 有 CSS 细网格，没有画布', async () => {
    const html = await renderToString(createSSRApp(DecoHeroGrid));
    expect(html).toContain('bp-paper');
    expect(html).not.toContain('<canvas');
    expect(decoCss).toMatch(/\.bp-paper \{[^}]*linear-gradient\(to right, rgba\(220, 232, 244, 0\.72\) 1px/);
    expect(decoCss).toMatch(/mask-image: linear-gradient\(to bottom, #000 62%, transparent\)/);
  });
  it('D2：预渲染为空；D3：预渲染为静态 SVG（都无画布）', async () => {
    for (const comp of [DecoInstallField, DecoFooterMark]) {
      const html = await renderToString(createSSRApp(comp));
      expect(html).not.toContain('<canvas');
    }
  });
  it('装饰都是绝对定位或固定尺寸，挂载画布不产生布局位移', () => {
    expect(decoCss).toMatch(/\.deco-hero \{\s*position: absolute;\s*inset: 0;\s*z-index: 0;/);
    expect(decoCss).toMatch(/\.deco-install \{\s*position: absolute;\s*inset: 0;\s*z-index: 0;/);
    expect(decoCss).toMatch(/\.deco-skyline \{[^}]*height: auto;/);
  });
});

describe('AC-07-02 / AC-07-09 / AC-07-32 减少动效与打印', () => {
  it('D5 的 CSS 动画只写在 prefers-reduced-motion: no-preference 之下（减少动效时动画数为 0）', () => {
    const outside = decoCss.replace(/@media \(prefers-reduced-motion: no-preference\) \{[\s\S]*?\n\}\n/, '');
    expect(outside).not.toMatch(/animation:\s*ms-/);
    expect(decoCss).toMatch(/\.deco-missing\.paused \*[\s\S]*animation-play-state: paused/);
  });
  it('打印：画布装饰隐藏，SVG 装饰为终帧', () => {
    const print = decoCss.slice(decoCss.lastIndexOf('@media print'));
    expect(print).toMatch(/\.deco-hero canvas,\s*\.deco-install,\s*\.deco-footer \{\s*display: none !important;/);
    expect(print).toMatch(/\.deco-missing \*[\s\S]*animation: none !important/);
    expect(print).toMatch(/\.dd-line \{\s*transform: none !important;/);
  });
});

describe('AC-07-04 依赖与体积', () => {
  const dir = 'src/components/deco';
  const files = [
    ...readdirSync(dir).filter((f) => /\.(ts|vue)$/.test(f)).map((f) => `${dir}/${f}`),
    ...readdirSync(`${dir}/live`).map((f) => `${dir}/live/${f}`),
  ];
  it('没有 three 或其它 WebGL 依赖，没有外部请求', () => {
    const pkg = JSON.parse(readFileSync('package.json', 'utf8'));
    const deps = { ...pkg.dependencies, ...pkg.devDependencies };
    expect(Object.keys(deps).some((d) => /three|webgl|pixi|babylon/i.test(d))).toBe(false);
    for (const f of files) {
      const src = readFileSync(f, 'utf8');
      expect(src, f).not.toMatch(/getContext\(\s*['"]webgl|from ['"]three|https?:\/\/(?!www\.w3\.org)/);
    }
  });
  it.each([
    ['D2', ['live/InstallFieldCanvas.vue', 'installField.ts', 'brandMark.ts']],
    ['D3', ['DecoFooterMark.vue', 'skyline.ts']],
    ['D4', ['DecoDimension.vue', 'dimension.ts']],
    ['共享运行时', ['decoLoop.ts', 'decoScheduler.ts']],
  ])('%s 去注释源码 gzip ≤ 12 KB（未压缩、未摇树，生产块只会更小）', (_id, parts) => {
    const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    const src = parts.map((p) => strip(readFileSync(`${dir}/${p}`, 'utf8'))).join('\n');
    expect(gzipSync(src).length).toBeLessThanOrEqual(12 * 1024);
  });
  it('D5 只引用 useInView 与纯函数，不加载 GSAP 或画布组件', () => {
    const src = readFileSync(`${dir}/DecoMissingSheet.vue`, 'utf8') + readFileSync(`${dir}/missingSheet.ts`, 'utf8');
    const imports = src.match(/^import .*$/gm) ?? [];
    expect(imports.join('\n')).not.toMatch(/motion|gsap|live\/|decoLoop|defineAsyncComponent/);
    expect(src).not.toMatch(/<canvas|getContext/);
  });
  it('装饰外壳用 defineAsyncComponent 懒加载画布层（D4、D5 的静态 SVG 在 SSR 输出）', () => {
    for (const f of ['DecoInstallField.vue']) {
      expect(readFileSync(`${dir}/${f}`, 'utf8')).toMatch(/defineAsyncComponent\(\(\) => import\('\.\/live\//);
    }
  });
});
