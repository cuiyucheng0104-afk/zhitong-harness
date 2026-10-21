/** 05 章 §2 数据与复核：几何、文案、读屏结构、聚焦模式、静止位置。 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { flushPromises } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import { render } from '../src/entry-server';
import { FOCUS, NARROW, WIDE, isLit } from '../src/components/sections05/trust/trust-geometry';
import { TRUST_COPY, TRUST_FLOWS, TRUST_NODES, TRUST_PRINCIPLES } from '../src/data/trust';
import TrustSection from '../src/components/TrustSection.vue';
import { mountAt } from './helpers';

async function trustDom() {
  const { html } = await render('/');
  return new DOMParser().parseFromString(html, 'text/html').getElementById('trust')!;
}

/** 把只含 M / H / V / Q 的路径拆成采样点（Q 用二次贝塞尔采样）。 */
function samplePath(d: string, steps = 20): [number, number][] {
  const tokens = d.match(/[MHVQ]|-?\d+(?:\.\d+)?/g)!;
  const pts: [number, number][] = [];
  let x = 0;
  let y = 0;
  let i = 0;
  while (i < tokens.length) {
    const cmd = tokens[i++]!;
    const n = () => Number(tokens[i++]);
    if (cmd === 'M') {
      x = n();
      y = n();
      pts.push([x, y]);
    } else if (cmd === 'H' || cmd === 'V') {
      const to = n();
      const [x0, y0] = [x, y];
      if (cmd === 'H') x = to;
      else y = to;
      for (let k = 1; k <= steps; k++)
        pts.push([x0 + ((x - x0) * k) / steps, y0 + ((y - y0) * k) / steps]);
    } else if (cmd === 'Q') {
      const [cx, cy, ex, ey] = [n(), n(), n(), n()];
      const [x0, y0] = [x, y];
      for (let k = 1; k <= steps; k++) {
        const t = k / steps;
        pts.push([
          (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * ex,
          (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * ey,
        ]);
      }
      x = ex;
      y = ey;
    }
  }
  return pts;
}
const inside = (p: [number, number], r: { x: number; y: number; w: number; h: number }) =>
  p[0] > r.x && p[0] < r.x + r.w && p[1] > r.y && p[1] < r.y + r.h;

describe('05 §2 数据与复核', () => {
  it('AC-05-25：宽几何 0 0 1040 576、窄几何 0 0 360 656 都预渲染，CSS 按断点只显示其一', async () => {
    const root = await trustDom();
    const boxes = [...root.querySelectorAll('svg.trust-svg')].map((s) => s.getAttribute('viewBox'));
    expect(boxes).toEqual(['0 0 1040 576', '0 0 360 656']);
    const css = readFileSync(resolve(__dirname, '../src/styles/sections/trust.css'), 'utf8');
    expect(css).toMatch(/\.trust-geo\.is-narrow \{\s*display: none;/);
    expect(css).toMatch(
      /@media \(max-width: 1023px\)[\s\S]*\.trust-geo\.is-wide \{\s*display: none;/,
    );
  });

  it('AC-05-26：1024、768、390 宽下图内最小文字渲染高度 ≥ 12px', () => {
    const gutter = { 1024: 96, 768: 48, 390: 20 } as const;
    const wideScale = Math.min(1120, 1024 - 2 * gutter[1024]) / WIDE.viewBox[2];
    expect(WIDE.font.body * wideScale).toBeGreaterThanOrEqual(12);
    const tablet = Math.min(480, 768 - 2 * gutter[768]) / NARROW.viewBox[2];
    expect(NARROW.font.body * tablet).toBeGreaterThanOrEqual(12);
    const phone = (390 - 2 * gutter[390]) / NARROW.viewBox[2];
    expect(NARROW.font.body * phone).toBeGreaterThanOrEqual(12);
  });

  it('AC-05-28：凭据只走 credStub，终点 x 不超过锁的左缘（宽 640，窄 276）', () => {
    for (const [g, edge] of [
      [WIDE, 640],
      [NARROW, 276],
    ] as const) {
      const pts = samplePath(g.paths.credStub!.d);
      expect(Math.max(...pts.map((p) => p[0]))).toBeLessThanOrEqual(edge);
      expect(g.lock[0] - 8).toBe(edge);
      expect(g.rest.credential[0]).toBeLessThanOrEqual(edge);
    }
  });

  it('AC-05-29：实心金额只走 reviewPath，从不进入 model 节点；进入 model 的只有 file 与 amountEcho 的路径', () => {
    for (const g of [WIDE, NARROW]) {
      const m = g.nodes.model;
      expect(samplePath(g.paths.reviewPath!.d).some((p) => inside(p, m))).toBe(false);
      const into = (d: string) => {
        const pts = samplePath(d);
        const last = pts.at(-1)!;
        return last[0] >= m.x && last[0] <= m.x + m.w && last[1] >= m.y && last[1] <= m.y + m.h;
      };
      expect(into(g.paths.ctxFile!.d)).toBe(true);
      expect(into(g.paths.ctxSum!.d)).toBe(true);
      expect(into(g.paths.reviewPath!.d)).toBe(false);
      expect(inside(g.rest.amount, m)).toBe(false);
    }
    const timeline = readFileSync(
      resolve(__dirname, '../src/components/sections05/trust/trust-timeline.ts'),
      'utf8',
    );
    expect(timeline).toMatch(/along\(amount, path\('reviewPath'\)/);
    expect(timeline).not.toMatch(/along\(amount, path\('(ctxFile|ctxSum)'\)/);
    expect(timeline).toMatch(/along\(cred, path\('credStub'\)/);
    expect(timeline).toContain('repeat: -1, repeatDelay: FLOW_REPEAT_DELAY');
  });

  it('AC-05-31 / AC-05-32：6 个节点按钮用 popovertarget 指向各自说明卡，说明卡文字与 §2.2 一致', async () => {
    const root = await trustDom();
    const wideHits = [...root.querySelectorAll('.trust-geo.is-wide .trust-hit')];
    expect(wideHits.map((b) => b.getAttribute('popovertarget'))).toEqual(
      ['tos', 'cache', 'script', 'cred', 'model', 'review'].map((n) => `trust-pop-${n}`),
    );
    expect(wideHits[0]!.getAttribute('aria-label')).toBe('公司存储桶（TOS）：查看说明');
    for (const card of TRUST_NODES) {
      const pop = root.querySelector(`#trust-pop-${card.node}`)!;
      expect(pop.getAttribute('popover')).toBe('auto');
      expect(pop.querySelector('.zt-popover-title')?.textContent).toBe(card.title);
      const text = pop.textContent ?? '';
      expect(text).toContain(card.lead);
      for (const row of card.rows) {
        expect(text).toContain(row.label);
        expect(text).toContain(row.text.replaceAll('`', ''));
      }
      expect(pop.querySelector('a[href="/docs/security/"]')?.textContent).toContain('读文档');
    }
    expect(TRUST_NODES.find((c) => c.node === 'review')!.rows[0]!.text).toBe(
      '金额与数量标“需人工确认”；报告中未核实的程序性陈述标“待核”；导出的 Word 页眉写明“AI 初稿，金额未经人工核对，不得直接出具”。',
    );
  });

  it('AC-05-38 / AC-05-39（图例与模型说明已按用户意见删除）：SVG 结构、读屏流向列表、四张原则卡逐字一致', async () => {
    const root = await trustDom();
    expect(root.querySelector('h2#trust-title')?.textContent).toBe(
      '数据在您自己的桶里，数字有出处',
    );
    expect(root.querySelector('figcaption, .trust-legend, .trust-disclosure')).toBeNull();
    for (const svg of root.querySelectorAll('svg.trust-svg')) {
      expect(svg.getAttribute('role')).toBe('img');
      expect(svg.querySelector('title')?.textContent).toBe('数据流向示意');
      expect(svg.querySelector('desc')?.textContent).toBe(
        '公司存储桶、工程师电脑、模型服务与人工复核之间，五类内容的去向。',
      );
      const [t, d] = svg.getAttribute('aria-labelledby')!.split(' ');
      expect(svg.querySelector(`#${t}`)?.tagName.toLowerCase()).toBe('title');
      expect(svg.querySelector(`#${d}`)?.tagName.toLowerCase()).toBe('desc');
    }
    const flows = [...root.querySelectorAll('figure > ol.sr-only > li')].map((l) => l.textContent);
    expect(flows).toEqual([...TRUST_FLOWS]);
    expect(flows).toHaveLength(5);
    const cards = [...root.querySelectorAll('.trust-principle')];
    expect(cards).toHaveLength(4);
    cards.forEach((c, i) => {
      const p = TRUST_PRINCIPLES[i]!;
      expect(c.tagName).toBe('BUTTON');
      expect(c.getAttribute('aria-pressed')).toBe('false');
      expect(c.querySelector('.trust-principle-no')?.textContent).toBe(p.no);
      expect(c.querySelector('.trust-principle-title')?.textContent).toBe(p.title);
      expect(c.querySelector('.trust-principle-body')?.textContent).toBe(p.body);
    });
    expect(TRUST_PRINCIPLES.map((p) => p.title)).toEqual([
      '数据归客户所有',
      '凭据不离开本机',
      '每个数字有出处',
      'AI 结果需人工确认',
    ]);
  });

  it('AC-05-37：无 JS / 减少动效时数据包位于 rest 坐标', async () => {
    const root = await trustDom();
    for (const [g, cls] of [
      [WIDE, 'is-wide'],
      [NARROW, 'is-narrow'],
    ] as const)
      for (const [kind, [x, y]] of Object.entries(g.rest))
        expect(
          root
            .querySelector(`.trust-geo.${cls} [data-packet="${kind}"]`)
            ?.getAttribute('transform'),
        ).toBe(`translate(${x} ${y})`);
  });

  it('聚焦集合：FOCUS 与图元归属（锁与“不进对话”归 credential）', () => {
    expect(FOCUS.credential).toEqual({
      nodes: ['cred'],
      paths: ['credStub', 'credTos'],
      packets: ['credential'],
    });
    expect(isLit('credential', { key: 'lock' })).toBe(true);
    expect(isLit('owned', { key: 'lock' })).toBe(false);
    expect(isLit(null, { node: 'model' })).toBe(true);
  });

  async function mountTrust() {
    const { wrapper } = await mountAt('/', TrustSection);
    return wrapper;
  }
  const pointer = (type: string, pointerType: string) => {
    const e = new Event(type, { bubbles: type !== 'pointerenter' && type !== 'pointerleave' });
    Object.defineProperty(e, 'pointerType', { value: pointerType });
    return e;
  };

  it('AC-05-33：悬停原则卡 02：锁、cred 车道、credStub、credTos 保持高亮，其余变暗；移开后恢复', async () => {
    const w = await mountTrust();
    const card = w.findAll('.trust-principle')[1]!;
    card.element.dispatchEvent(pointer('pointerenter', 'mouse'));
    await flushPromises();
    const wide = w.get('.trust-geo.is-wide');
    expect(card.attributes('aria-pressed')).toBe('true');
    expect(wide.get('.trust-lock').classes()).not.toContain('is-dim');
    expect(wide.get('[data-node="cred"]').classes()).not.toContain('is-dim');
    expect(wide.get('[data-path="credStub"]').classes()).not.toContain('is-dim');
    expect(wide.get('[data-path="credTos"]').classes()).not.toContain('is-dim');
    for (const sel of [
      '[data-node="tos"]',
      '[data-node="model"]',
      '[data-path="pull"]',
      '[data-path="reviewPath"]',
    ])
      expect(wide.get(sel).classes()).toContain('is-dim');
    const css = readFileSync(resolve(__dirname, '../src/styles/sections/trust.css'), 'utf8');
    expect(css).toMatch(/\.trust-svg \.is-dim \{\s*opacity: 0\.28;/);
    expect(css).toContain('transition: opacity var(--dur-short) var(--ease-out)');
    card.element.dispatchEvent(pointer('pointerleave', 'mouse'));
    await flushPromises();
    expect(w.findAll('.trust-geo.is-wide .is-dim')).toHaveLength(0);
  });

});
