/** 07 章 §5–§10：D1–D6 的几何、数值、模型与预渲染。 */
import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import { createSSRApp, h } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { flushPromises, mount } from '@vue/test-utils';
import { BRAND_RAW, accentColor, parseBrandMark } from '../src/components/deco/brandMark';
import {
  CLS,
  FIELD_CODES,
  INSTALL_FIELD,
  codeRow,
  composite,
  createFieldModel,
  decodeKey,
  encodeKey,
  fieldPlacement,
  relativeLuminance,
  roundRectSdf,
  type FieldPlacement,
} from '../src/components/deco/installField';
import { SKYLINE, skyline, towerGrid } from '../src/components/deco/skyline';
import DecoFooterMark from '../src/components/deco/DecoFooterMark.vue';
import { columnEdges, columnsFor, dimensionState, formatDimension } from '../src/components/deco/dimension';
import { countParts, missingSheetParts, revisionCloud, parkMiller } from '../src/components/deco/missingSheet';
import DecoMissingSheet from '../src/components/deco/DecoMissingSheet.vue';
import DecoDimension from '../src/components/deco/DecoDimension.vue';
import { relativeLuminance as lum } from '../src/components/deco/installField';
import { hexRgb } from '../src/components/deco/brandMark';

const decoCss = readFileSync('src/styles/deco.css', 'utf8');

describe('D1 首屏底稿网格（07 §5，按用户意见只保留静态网格）', () => {
it('只输出 CSS 网格，不挂载画布层、不监听指针', () => {
  const src = readFileSync('src/components/deco/DecoHeroGrid.vue', 'utf8');
  expect(src).toContain('bp-paper');
  expect(src).not.toMatch(/<canvas|defineAsyncComponent|pointermove/);
});
});

describe('D2 清单编码字符场（07 §6）', () => {
  it('AC-07-15 parseBrandMark 快照：rx 17、两个 stop、rotate(-43 32 32)、白与 #12D99F 两组描边', () => {
    const m = parseBrandMark(BRAND_RAW);
    expect(m.viewBox).toEqual([0, 0, 64, 64]);
    expect(m.rect).toEqual({ x: 0, y: 0, width: 64, height: 64, rx: 17 });
    expect(m.gradient?.stops).toEqual([
      { offset: 0, color: '#00b3ec' },
      { offset: 1, color: '#0666f5' },
    ]);
    expect(m.gradient).toMatchObject({ x1: 0, y1: 0, x2: 1, y2: 1, userSpace: false });
    expect(m.rotate).toEqual({ angle: -43, cx: 32, cy: 32 });
    expect(m.strokes.map((s) => [s.kind, s.stroke, s.width, s.cap])).toEqual([
      ['light', '#fff', 7.5, 'round'],
      ['accent', '#12d99f', 5, 'round'],
    ]);
    expect(accentColor(m)).toBe('#12d99f');
  });

  it('AC-07-15 把强调色改成 #ff0000 后，强调类格子的颜色随之改变', () => {
    const m = parseBrandMark(BRAND_RAW.replace('#12D99F', '#ff0000'));
    expect(accentColor(m)).toBe('#ff0000');
  });

  it('布局：桌面 S = min(0.82H, 0.5W)，格距 round(S/54) 夹在 6–14，格高 = round(格距 × 1.55)', () => {
    const P = fieldPlacement(1248, 760);
    expect(P.S).toBeCloseTo(Math.min(0.82 * 760, 0.5 * 1248), 6);
    expect(P.cw).toBe(12);
    expect(P.ch).toBe(19);
    expect(P.fs).toBe(16);
    expect(P.cx).toBeCloseTo(1248 - 0.22 * P.S, 6);
    const M = fieldPlacement(390, 1480);
    expect(M.S).toBeCloseTo(0.92 * 390, 6);
    expect(M.cw).toBe(7);
    expect(M.ch).toBe(11);
  });

  it('字符流：第 r 行从第 7r 项开始，行首错开 (5r) mod 13 格；编码 24 个、均为 12 位', () => {
    expect(FIELD_CODES).toHaveLength(24);
    for (const c of FIELD_CODES) expect(c).toMatch(/^01(01|04|05|08|09|17)\d{8}$/);
    expect(codeRow(0, 26)).toBe(`${FIELD_CODES[0]} ${FIELD_CODES[1]} `.slice(0, 26));
    expect(codeRow(1, 13)).toBe((FIELD_CODES[7] + ' ' + FIELD_CODES[8]).slice(5, 18));
  });

  it('绘制键可逆', () => {
    const k = encodeKey(7, 13, 0.5, 0.4, 0.3);
    const d = decodeKey(k);
    expect(d.glyph).toBe(7);
    expect(d.row).toBe(13);
    expect(d.alpha).toBeCloseTo(0.5, 1);
    expect(d.overlay).toBeCloseTo(0.4, 1);
    expect(d.tile).toBeCloseTo(0.3, 6);
  });

  /** 合成采样：圆角方块为主体，中心十字为白，四角短划为强调。 */
  function synth(P: FieldPlacement) {
    const sample = new Float32Array(P.cols * P.rows * 3);
    const half = P.S / 2;
    const rad = (17 / 64) * P.S;
    for (let r = 0; r < P.rows; r++)
      for (let c = 0; c < P.cols; c++) {
        const x = P.region.x + (c + 0.5) * P.cw;
        const y = P.region.y + (r + 0.5) * P.ch;
        const i = (r * P.cols + c) * 3;
        if (roundRectSdf(x, y, P.cx, P.cy, half, rad) > 0) continue;
        const dx = Math.abs(x - P.cx);
        const dy = Math.abs(y - P.cy);
        if ((dx < 0.06 * P.S && dy < 0.27 * P.S) || (dy < 0.06 * P.S && dx < 0.27 * P.S)) sample[i + 1] = 1;
        else if (dx > 0.3 * P.S && dy > 0.3 * P.S && dx < 0.38 * P.S) sample[i + 2] = 1;
        else sample[i] = 1;
      }
    return sample;
  }
  function makeModel(W = 1248, H = 760) {
    const P = fieldPlacement(W, H);
    const model = createFieldModel(P, synth(P), {
      S: P.S,
      cx: P.cx,
      cy: P.cy,
      radius: (17 / 64) * P.S,
      grad: { x1: 0, y1: 0, x2: 1, y2: 1 },
    });
    return { P, model };
  }

  it('分类：白、强调、主体、场四类都有', () => {
    const { model } = makeModel();
    const counts = [0, 0, 0, 0];
    for (const c of model.cls) counts[c]++;
    expect(counts[CLS.light]).toBeGreaterThan(0);
    expect(counts[CLS.acc]).toBeGreaterThan(0);
    expect(counts[CLS.body]).toBeGreaterThan(0);
    expect(counts[CLS.field]).toBeGreaterThan(0);
    expect(model.count).toBeGreaterThan(1000);
  });

  it('AC-07-17 面板可见后 2.1 s 内全部格子锁定，2.7 s 内叠白褪尽', () => {
    const { model } = makeModel();
    expect(model.lockEnd).toBeLessThanOrEqual(2.1);
    expect(model.entranceEnd).toBeLessThanOrEqual(2.7);
    for (let i = 0; i < model.count; i++) expect(decodeKey(model.key(i, 2.71, false)).overlay).toBe(0);
  });

  it('AC-07-17 稳态（闪烁 + 扫光）8 s 平均每帧重绘的格子 ≤ 5%', () => {
    const { model } = makeModel();
    const last = new Int32Array(model.count).fill(-1);
    let t = model.entranceEnd;
    for (let i = 0; i < model.count; i++) last[i] = model.key(i, t, true);
    let changed = 0;
    const frames = 8 * 60;
    for (let f = 0; f < frames; f++) {
      t += 1 / 60;
      model.update(t, 1 / 60, true);
      for (let i = 0; i < model.count; i++) {
        const k = model.key(i, t, true);
        if (k !== last[i]) {
          changed++;
          last[i] = k;
        }
      }
    }
    expect(changed / frames / model.count).toBeLessThanOrEqual(0.05);
  });

  it('AC-07-16 内容盒子外扩 8px 内：任何状态的格子合成亮度 L ≤ 0.183（白字对比 ≥ 4.5:1）', () => {
    const { P, model } = makeModel();
    // 整个区域都当作内容盒子
    model.applySafe([{ x: P.region.x, y: P.region.y, w: P.region.w, h: P.region.h }]);
    const navy = hexRgb('#082457');
    const white: [number, number, number] = [255, 255, 255];
    const accent = hexRgb('#12d99f');
    const cyan = hexRgb('#00b3ec');
    let maxL = 0;
    for (const t of [0.6, 1.0, 1.6, 2.2, model.entranceEnd + 0.8, model.entranceEnd + 5]) {
      model.update(t, 1 / 60, true);
      for (let i = 0; i < model.count; i++) {
        const d = decodeKey(model.key(i, t, true));
        // 最坏情况：字形颜色取最亮的白，叠在同色格底上再叠白
        const col = d.row === 13 ? accent : d.row < 12 ? cyan : white;
        const c = composite(navy, [
          [col, d.tile],
          [white, d.alpha],
          [white, d.overlay],
        ]);
        maxL = Math.max(maxL, relativeLuminance(c));
      }
    }
    expect(maxL).toBeLessThanOrEqual(0.183);
    // spec 的推导：白 α 0.18 合成在 #082457 上 L ≈ 0.071
    expect(lum(composite(navy, [[white, 0.18]]))).toBeCloseTo(0.071, 2);
  });

  it('AC-07-18 指针解码只改变非内容格子', () => {
    const { P, model } = makeModel();
    const box = { x: P.cx - 60, y: P.cy - 60, w: 120, h: 120 };
    model.applySafe([box]);
    const t = model.entranceEnd + 1;
    const before = Array.from({ length: model.count }, (_, i) => model.key(i, t, false));
    model.pointer(P.cx, P.cy, t);
    const t2 = t + 0.1;
    for (let i = 0; i < model.count; i++) {
      if (!model.safe[i]) continue;
      // 内容格子的字形不变（与无指针时的同一时刻比较）
      expect(decodeKey(model.key(i, t2, false)).glyph).toBe(decodeKey(before[i]).glyph);
    }
    model.pointer(P.cx - 200, P.cy, t);
    expect(model.busy(t + 0.05)).toBe(true);
    expect(model.busy(t + 0.6)).toBe(false);
  });

  it('safeSelector 与参数照 §6.4', () => {
    expect(INSTALL_FIELD.safeSelector).toBe('h2, h3, p, li, dt, dd, a, button, [data-deco-safe]');
    expect(INSTALL_FIELD.safeCap).toEqual({ field: 0.08, body: 0.22, light: 0.18, acc: 0.2, overlay: 0.05 });
    expect(INSTALL_FIELD.drawBudgetMs).toBe(2.2);
  });
});

describe('D3 页脚楼群（替代 07 §7：铺满一排，无轴号与标高）', () => {
  it('楼栋从 0 排到画布右缘，互不重叠，宽高为开间与层高的整数倍', () => {
    const t = skyline();
    expect(t[0]!.x).toBe(0);
    expect(t.at(-1)!.x + t.at(-1)!.w).toBe(SKYLINE.width);
    for (let i = 1; i < t.length; i++) expect(t[i]!.x).toBeGreaterThanOrEqual(t[i - 1]!.x + t[i - 1]!.w);
    for (const b of t) {
      expect(b.h % SKYLINE.floor).toBe(0);
      expect(b.h + b.roofH).toBeLessThanOrEqual(SKYLINE.height);
    }
    expect(skyline()).toEqual(t);
  });
  it('窗格线只在楼栋轮廓内', () => {
    for (const b of skyline()) {
      for (const [, x] of towerGrid(b).matchAll(/M([\d.]+) /g)) {
        expect(Number(x)).toBeGreaterThanOrEqual(b.x);
        expect(Number(x)).toBeLessThanOrEqual(b.x + b.w);
      }
    }
  });
  it('预渲染直接输出 SVG 楼群终态，没有画布、文字、轴号与标高', async () => {
    const html = await renderToString(createSSRApp(DecoFooterMark));
    expect(html).toContain('deco-skyline');
    expect(html).toContain('data-state="still"');
    expect(html).not.toMatch(/<canvas|<text/);
    expect((html.match(/class="sk-tower"/g) ?? []).length).toBe(skyline().length);
  });
});

describe('D4 尺寸线分隔（07 §8）', () => {
  it('AC-07-25 终态数字 = 容器实测宽（四舍五入、千位空格）', () => {
    expect(formatDimension(1248)).toBe('1 248');
    expect(formatDimension(350)).toBe('350');
    expect(formatDimension(12480.4)).toBe('12 480');
    expect(dimensionState(1, 1248).value).toBe(1248);
  });

  it('AC-07-26 线长随进度线性增加，反向回退', () => {
    const W = 1248;
    for (const p of [0, 0.1, 0.25, 0.5, 0.9, 1]) {
      const s = dimensionState(p, W);
      expect(s.x2 - s.x1).toBeCloseTo(W * p, 6);
      expect((s.x1 + s.x2) / 2).toBeCloseTo(W / 2, 6);
      expect(s.textOpacity).toBeCloseTo(Math.min(1, 4 * p), 6);
    }
    expect(dimensionState(0.8, W).ext).toBe(0);
    expect(dimensionState(0.95, W).ext).toBeCloseTo(0.5, 6);
    expect(dimensionState(0.95, W).bubble).toBe(0);
    expect(dimensionState(0.98, W).bubble).toBeCloseTo(0.5, 6);
  });

  it('AC-07-27 栏刻度与 12/8/4 栏网格栏间距两缘重合', () => {
    const W = 1248;
    const colW = (W - 11 * 24) / 12;
    const edges = columnEdges(W, 12);
    expect(edges).toHaveLength(22);
    for (let k = 1; k < 12; k++) {
      expect(edges[2 * (k - 1)]).toBeCloseTo(k * colW + (k - 1) * 24, 6);
      expect(edges[2 * (k - 1) + 1]).toBeCloseTo(k * (colW + 24), 6);
    }
    expect(columnsFor(1440)).toBe(12);
    expect(columnsFor(900)).toBe(8);
    expect(columnsFor(390)).toBe(4);
    expect(columnEdges(350, 4)).toHaveLength(6);
  });

  it('无 JS：预渲染输出 1248 宽的终态 SVG；水合无不匹配', async () => {
    const App = { render: () => h(DecoDimension, { from: '3', to: '4' }) };
    const html = await renderToString(createSSRApp(App));
    expect(html).toContain('viewBox="0 0 1248 56"');
    expect(html).toContain('1 248');
    expect(html).not.toMatch(/scaleX\(0\)/);
    document.body.innerHTML = `<div id="app">${html}</div>`;
    const warn = vi.spyOn(console, 'warn');
    const app = createSSRApp(App);
    app.mount('#app');
    await flushPromises();
    expect(warn.mock.calls.map((a) => String(a[0])).filter((m) => /hydrat/i.test(m))).toEqual([]);
    app.unmount();
  });

  it('减少动效：终态（满线、终值）', async () => {
    const w = mount(DecoDimension, { props: { from: '3', to: '4' }, attachTo: document.body });
    await flushPromises();
    const line = w.find('.dd-line').element as SVGLineElement;
    expect(line.style.transform).toBe('scaleX(1)');
    w.unmount();
  });

  it('inline 变体（04 章 .cap-dimline）：高 24、无轴号、可写标注', async () => {
    const html = await renderToString(createSSRApp({ render: () => h(DecoDimension, { variant: 'inline', label: '12 = 3 + 4 + 3 + 2' }) }));
    expect(html).toContain('viewBox="0 0 1248 24"');
    expect(html).toContain('12 = 3 + 4 + 3 + 2');
    expect(html).not.toContain('dd-bubbles');
  });
});

describe('D5 404 图纸缺页（07 §9）', () => {
  it('AC-07-33 固定种子：两次生成的 SVG 字节相同', async () => {
    expect(missingSheetParts()).toEqual(missingSheetParts());
    const a = await renderToString(createSSRApp(DecoMissingSheet));
    const b = await renderToString(createSSRApp(DecoMissingSheet));
    expect(a).toBe(b);
    expect(revisionCloud(parkMiller(404))).toBe(revisionCloud(parkMiller(404)));
  });

  it('AC-07-30 SSR 内联完整 SVG（约 190 个元素），没有 <canvas>', async () => {
    const html = await renderToString(createSSRApp(DecoMissingSheet));
    expect(html.startsWith('<svg')).toBe(true);
    expect(html).not.toContain('<canvas');
    expect(html).not.toContain('paused');
    const count = countParts(missingSheetParts());
    expect(count).toBeGreaterThan(150);
    expect(count).toBeLessThan(240);
    for (const s of ['智通数工AI 门户', '页面不存在', 'A-404', '1:100', '404 / —', '接 A-404', '缺页：本页不在图纸目录中', 'X ?  Y ?', '6 200']) {
      expect(html).toContain(s);
    }
  });

  it('时间线：22 段墙依次相隔 0.045 s，1.15–2.6 s；审核章 3.75 s 落下；十字 4.4 s 起循环', () => {
    const parts = missingSheetParts();
    const walls = parts.filter((p) => p.cls.includes('ms-wall-i'));
    expect(walls).toHaveLength(22);
    expect(walls[0].d).toBeCloseTo(1.15, 6);
    expect(walls[1].d! - walls[0].d!).toBeCloseTo(0.045, 6);
    expect(walls[21].d! + walls[21].t!).toBeCloseTo(2.595, 2);
    const stamp = parts.flatMap((p) => p.children ?? []).find((p) => p.cls === 'ms-stamp');
    expect(stamp?.d).toBe(3.75);
    expect(decoCss).toMatch(/ms-roam 15s var\(--ease-in-out\) 4\.4s infinite/);
    // 所有动画在 4.4 s 前结束（AC-07-31：4.4 s 后除十字外与终帧一致）
    const all = (ps: typeof parts): number[] => ps.flatMap((p) => [p.t !== undefined ? (p.d ?? 0) + p.t : 0, ...all(p.children ?? [])]);
    expect(Math.max(...all(parts))).toBeLessThanOrEqual(4.4);
  });

  it('修订云线：每段 A r r 0 0 1，r = 0.62 × 弦长（随机 ±25%）', () => {
    const d = revisionCloud(parkMiller(404));
    const arcs = [...d.matchAll(/A([\d.]+) ([\d.]+) 0 0 1/g)];
    expect(arcs.length).toBeGreaterThan(40);
    for (const [, r] of arcs) {
      // ±25% 随机权重归一到边长后，弦长落在 11 × [0.6, 1.4] 内
      expect(+r).toBeGreaterThanOrEqual(0.62 * 11 * 0.6);
      expect(+r).toBeLessThanOrEqual(0.62 * 11 * 1.4);
    }
  });

  it('AC-07-32 页面隐藏或离开视口时根元素加 .paused；水合一致', async () => {
    const html = await renderToString(createSSRApp(DecoMissingSheet));
    document.body.innerHTML = `<div id="app">${html}</div>`;
    const warn = vi.spyOn(console, 'warn');
    const app = createSSRApp(DecoMissingSheet);
    app.mount('#app');
    await flushPromises();
    expect(warn.mock.calls.map((a) => String(a[0])).filter((m) => /hydrat/i.test(m))).toEqual([]);
    // 测试环境 IntersectionObserver 为空桩（从未可见），挂载后为暂停
    expect(document.querySelector('svg.deco-missing')?.classList.contains('paused')).toBe(true);
    app.unmount();
  });

  it('手机裁切版：overflow hidden，SVG 宽 172%、左移 70%', () => {
    expect(decoCss).toMatch(/\.notfound-deco \.deco-missing \{\s*width: 172%;\s*margin-left: -70%;/);
  });
});

describe('D6 深色区底纹（07 §10）', () => {
  it('AC-07-34 小格 24px α 0.035、大格 120px α 0.075，大格竖线落在容器左缘（四个断点）', () => {
    expect(decoCss).toMatch(/rgba\(255, 255, 255, 0\.075\) 1px/);
    expect(decoCss).toMatch(/rgba\(255, 255, 255, 0\.035\) 1px/);
    expect(decoCss).toMatch(/--gx: 96px;/);
    expect(decoCss).toMatch(/max-width: 1023px\) \{\s*\.deco-navy-grid \{\s*--gx: 48px;/);
    expect(decoCss).toMatch(/max-width: 767px\) \{\s*\.deco-navy-grid \{\s*--gx: 20px;/);
    expect(decoCss).toMatch(/--gx: calc\(50% - 564px\);\s*--gx-s: calc\(50% - 612px\);/);
    // 1440 起：背景百分比相对于（元素宽 − 图块宽）：W=1600 时 0.5 × (1600 − 120) − 564 = 176 = (1600 − 1248) / 2
    expect(0.5 * (1600 - 120) - 564).toBe((1600 - 1248) / 2);
    expect(0.5 * (1600 - 24) - 612).toBe((1600 - 1248) / 2);
  });
});
