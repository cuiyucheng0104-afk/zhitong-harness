/**
 * 03 章 §2 它解决什么 + 两个区块的预渲染终态（测试环境为减少动效：静态终态、无 ScrollTrigger）。
 */
import { describe, expect, it } from 'vitest';
import { flushPromises } from '@vue/test-utils';
import { createSSRApp, type Component } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { createMemoryHistory } from 'vue-router';
import ProblemSection from '../src/components/ProblemSection.vue';
import RolesSection from '../src/components/RolesSection.vue';
import { createAppRouter } from '../src/router';
import { vMagnetic } from '../src/composables/useMagnetic';
import { vSpotlight } from '../src/composables/useSpotlight';
import { CLICK_MARKERS, PROBLEM_COPY, THREAD_ROWS } from '../src/data/problem';
import { loadMotion } from '../src/lib/motion';
import { mountAt } from './helpers';

async function ssr(component: Component): Promise<Document> {
  const router = createAppRouter(createMemoryHistory());
  await router.push('/');
  await router.isReady();
  const app = createSSRApp(component);
  app.use(router);
  app.directive('magnetic', vMagnetic);
  app.directive('spotlight', vSpotlight);
  const html = await renderToString(app);
  return new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html');
}

const norm = (s: string | null | undefined) => (s ?? '').replace(/\s+/g, ' ').trim();

describe('03 §2 预渲染（静态终态）', () => {
  it('AC-03-27：预渲染 HTML 含 100 个 .click-dot，坐标与 CLICK_MARKERS 逐项相等', async () => {
    const doc = await ssr(ProblemSection);
    const dots = [...doc.querySelectorAll<HTMLElement>('.click-dot')];
    expect(dots).toHaveLength(100);
    const seen = dots.map((d) => ({
      panel: d.closest<HTMLElement>('.legacy-panel')!.dataset.panel,
      k: Number(d.dataset.k),
      x: parseFloat(d.style.left),
      y: parseFloat(d.style.top),
    }));
    expect(seen).toEqual(CLICK_MARKERS.map((m) => ({ panel: m.panel, k: m.k, x: m.x, y: m.y })));
  });

  it('标题区、9 个面板、8 个待确认菱形、2 个“上次结果”、2 个“不再单独做”', async () => {
    const doc = await ssr(ProblemSection);
    const section = doc.getElementById('problem')!;
    expect(section.getAttribute('aria-labelledby')).toBe('problem-title');
    expect(section.querySelector('.eyebrow')).toBeNull();
    expect(doc.getElementById('problem-title')!.innerHTML).toBe('它解决什么');
    expect(section.querySelector('.compare-list, .problem-after')).toBeNull();
    expect(norm(section.querySelector('.problem-heading > p:last-child')?.textContent)).toBe(PROBLEM_COPY.subtitle);
    expect([...doc.querySelectorAll('.lp-bar')].map((e) => e.textContent)).toEqual([
      '标注', '齐套', '抽取', '核对', '指标', '投控', '报告', '清单', '概算',
    ]);
    expect(doc.querySelectorAll('.pending-mark')).toHaveLength(8);
    expect([...doc.querySelectorAll('.lp-last')].map((e) => e.closest<HTMLElement>('.legacy-panel')!.dataset.panel)).toEqual(['check', 'metrics']);
    expect([...doc.querySelectorAll('.lp-retired')].map((e) => e.closest<HTMLElement>('.legacy-panel')!.dataset.panel)).toEqual(['tag', 'extract']);
    expect(doc.querySelectorAll('.lp-pick')[0]!.textContent).toBe('选择文件');
    expect(doc.querySelectorAll('.lp-start')[0]!.textContent).toBe('开始');
    expect(doc.querySelectorAll('.lp-export')[0]!.textContent).toBe('导出');
  });

  it('AC-03-23 顺序线序号 ①–⑨ 按九个面板顺序；扇形线端点为核对、指标、投控（AC-03-22）', async () => {
    const doc = await ssr(ProblemSection);
    expect([...doc.querySelectorAll('[data-o="no"]')].map((g) => `${g.textContent}${g.getAttribute('data-panel')}`)).toEqual([
      '1tag', '2kit', '3extract', '4check', '5metrics', '6control', '7report', '8bills', '9estimate',
    ]);
    expect([...doc.querySelectorAll('[data-o="fan"]')].map((p) => p.getAttribute('data-to'))).toEqual(['check', 'metrics', 'control']);
    expect([...doc.querySelectorAll('[data-o="strike"]')].map((p) => p.getAttribute('data-panel'))).toEqual(['tag', 'extract']);
    expect(doc.querySelector('[data-o="tag"]')?.textContent).toBe('送审计价表.xlsx');
  });

  it('AC-03-24：线程 8 行全部完成，idle 行为灰色行，check 行结果逐字', async () => {
    const doc = await ssr(ProblemSection);
    expect(norm(doc.querySelector('.conv__title')?.textContent)).toBe('对话 · 2026-007 某综合办公楼（示例）');
    expect(norm(doc.querySelector('.conv__bubble')?.textContent)).toBe(PROBLEM_COPY.userBubble);
    const rows = [...doc.querySelectorAll<HTMLElement>('.conv-row')];
    expect(rows.map((r) => r.dataset.row)).toEqual(THREAD_ROWS.map((r) => r.id));
    for (const r of rows) {
      const state = r.querySelector('.zt-tool')!.getAttribute('data-state');
      expect(state).toBe('done');
    }
    const idle = rows.find((r) => r.dataset.row === 'idle')!;
    expect(idle.classList.contains('is-idle')).toBe(true);
    expect(norm(idle.querySelector('.zt-tool-detail')?.textContent)).toBe('本项目未调用');
    const check = rows.find((r) => r.dataset.row === 'check')!;
    const text = norm(`${check.querySelector('.zt-tool-detail')?.textContent}${check.querySelector('.zt-status')?.textContent}`);
    expect(text.replace(/·需/, '· 需')).toBe('核减 906,692.96 元 · 核减率 2.97% · 需人工确认');
    expect(check.querySelector('.zt-tool-name')?.textContent).toBe('reconcile.py run');
  });

  it('§2.7：场景 role="img" + aria-describedby，内部 aria-hidden；计数器有读屏真实文本', async () => {
    const doc = await ssr(ProblemSection);
    const body = doc.querySelector('.scene-body')!;
    expect(body.getAttribute('role')).toBe('img');
    expect(body.getAttribute('aria-describedby')).toBe('problem-scene-desc');
    expect([...body.children].every((c) => c.getAttribute('aria-hidden') === 'true')).toBe(true);
    expect(doc.getElementById('problem-scene-desc')!.textContent).toBe(PROBLEM_COPY.sceneDesc);
    expect(doc.getElementById('problem-scene-desc')!.classList.contains('sr-only')).toBe(true);
    const counter = doc.querySelector('.problem-counter')!;
    expect(counter.querySelector('.sr-only')!.textContent).toBe('约 60 至 150 次点击（估算值，非实测）');
    expect(counter.querySelector('.counter-old')!.getAttribute('aria-hidden')).toBe('true');
    expect(norm(counter.querySelector('.counter-old .counter-main')?.textContent).replace(/ /g, '')).toBe('60–150次点击');
    expect(doc.querySelectorAll('.scene-body a, .scene-body button, .scene-body [tabindex]')).toHaveLength(0);
  });

});

describe('03 §1 预渲染（无 JS）', () => {
  it('选中工程师，其余两个面板 hidden；岗位图只显示工程师组；入口为普通链接', async () => {
    const doc = await ssr(RolesSection);
    const panels = [...doc.querySelectorAll('.role-panel')];
    expect(panels).toHaveLength(3);
    expect(panels.map((p) => p.hasAttribute('hidden'))).toEqual([false, true, true]);
    expect(panels.some((p) => p.hasAttribute('inert'))).toBe(false);
    expect(doc.getElementById('role-tab-engineer')!.getAttribute('aria-selected')).toBe('true');
    const groups = [...doc.querySelectorAll<SVGGElement>('[data-art]')];
    expect(groups.map((g) => g.getAttribute('style') ?? '')).toEqual(['', 'display:none;', 'display:none;']);
    expect(doc.querySelectorAll('a.task-chip[href^="/docs/features/"]')).toHaveLength(12);
    expect(doc.getElementById('role-task-popover')?.getAttribute('popover')).toBe('auto');
  });
});

describe('AC-03-29 减少动效', () => {
  it('不钉住，ScrollTrigger.getAll() 中没有本区块的触发器；计数器与线程直接为终态', async () => {
    const { wrapper } = await mountAt('/', ProblemSection);
    const motion = await loadMotion();
    await flushPromises();
    expect(wrapper.get('#problem').classes()).not.toContain('is-pinned');
    if (motion) expect(motion.ScrollTrigger.getAll()).toHaveLength(0);
    expect(wrapper.get('.problem-counter').attributes('data-mode')).toBe('count');
    expect(wrapper.findAll('.conv-row .zt-tool').every((t) => ['done', 'pending'].includes(t.attributes('data-state')!))).toBe(true);
  });
});
