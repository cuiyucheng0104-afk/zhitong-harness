/** 05 章 §1 使用流程：文案、示例数据、节拍排期、钉住与吸附规则、降级。 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import { render } from '../src/entry-server';
import {
  CASE_INDEX,
  INVENTORY,
  INVENTORY_MAX,
  INVENTORY_RATE,
  KEY_METRICS,
  RECONCILE_CARD,
  UNIT_COST,
  WORKFLOW_STEPS,
} from '../src/data/workflow';
import { RECONCILE } from '../src/data/demo';
import { DOC_ROUTES } from '../src/docs/routes';
import {
  beatDuration,
  formatMs,
  planScene,
} from '../src/components/sections05/workflow/scene-plan';
import {
  labelPositions,
  nearestLabelIndex,
  snapDuration,
  snapTarget,
  WF_LABELS,
  WF_PIN_RATIO,
  WF_TOTAL,
} from '../src/components/sections05/workflow/useWorkflowPin';
import WorkflowSection from '../src/components/WorkflowSection.vue';
import { mountAt } from './helpers';

const ZHITONG = resolve(__dirname, '../../..');

async function workflowDom() {
  const { html } = await render('/');
  const doc = new DOMParser().parseFromString(html, 'text/html');
  return doc.getElementById('workflow')!;
}

/** 载入 config-import 的 `parsePackage`（去掉 node:fs 与 fflate 依赖后转译执行；只用其纯 JSON 校验部分）。 */
function loadParsePackage(): (text: string) => {
  company: { name: string };
  tos: { endpoint: string; region: string; bucket: string; prefix: string };
} {
  const src = readFileSync(resolve(ZHITONG, 'plugins/config-import/src/package.ts'), 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export async function readPackageText[\s\S]*?^}\n/m, '');
  const js = ts.transpileModule(src, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const mod: { exports: Record<string, unknown> } = { exports: {} };
  // 测试环境内执行仓库源码；站点本身不使用 eval。
  new Function('module', 'exports', js)(mod, mod.exports);
  return mod.exports.parsePackage as ReturnType<typeof loadParsePackage>;
}

describe('05 §1 使用流程', () => {
  it('AC-05-01：预渲染 HTML 内有四步的标签、标题、正文、写入芯片、文档链接与四个场景的全部终态文字', async () => {
    const root = await workflowDom();
    const text = root.textContent ?? '';
    expect(root.querySelector('h2#workflow-title')?.textContent).toBe('四步，从安装到归档');
    expect(text).toContain('从连接公司的桶开始，到归档回桶结束。');
    for (const step of WORKFLOW_STEPS) {
      for (const s of [step.label, step.title, step.body, step.doc.text]) expect(text).toContain(s);
      for (const w of step.writes) expect(text).toContain(w.text.trim());
      expect(root.querySelector(`a[href="${step.doc.href}"]`)).not.toBeNull();
      for (const beat of step.scene) {
        if (beat.kind === 'stream' || beat.kind === 'user') expect(text).toContain(beat.text);
        if (beat.kind === 'tool') {
          expect(text).toContain(beat.label);
          expect(text).toContain(beat.command);
          if (beat.result) expect(text).toContain(beat.result);
        }
        if (beat.kind === 'outcome') expect(text).toContain(beat.text);
        if (beat.kind === 'ask') for (const l of beat.lines) expect(text).toContain(l);
        if (beat.kind === 'push') for (const r of beat.rows) expect(text).toContain(r.path);
      }
    }
    expect(root.querySelectorAll('.wf-window')).toHaveLength(4);
    expect(root.querySelector('.wf-steps')?.tagName).toBe('OL');
    expect(root.querySelector('.wf-markers')?.getAttribute('aria-label')).toBe('使用流程四步');
  });

  it('文案：窗口标题栏、徽标、占位文字、场景容器的 aria', async () => {
    const root = await workflowDom();
    const wins = [...root.querySelectorAll('.wf-window')];
    expect(wins[0]!.textContent).toContain('智通数工AI · 示例会话');
    expect(wins[0]!.querySelector('.wf-badge')?.textContent).toBe('示例');
    expect(wins[0]!.querySelector('.wf-input')?.textContent?.trim()).toBe(
      '把配置包拖到这里，或告诉我它的路径',
    );
    expect(wins[2]!.querySelector('.wf-input')?.textContent?.trim()).toBe('说说要做什么');
    wins.forEach((w, i) => {
      expect(w.getAttribute('role')).toBe('group');
      expect(w.getAttribute('aria-roledescription')).toBe('示例');
      expect(w.getAttribute('aria-label')).toBe(`第 ${i + 1} 步示例：${WORKFLOW_STEPS[i]!.title}`);
      expect(w.querySelector('.wf-msgs')?.getAttribute('aria-live')).toBe('off');
    });
    const markers = [...root.querySelectorAll('.wf-marker')];
    expect(markers.map((m) => m.getAttribute('aria-label'))).toEqual([
      '第 1 步：导入配置包',
      '第 2 步：开项目',
      '第 3 步：对话完成任务',
      '第 4 步：归档回桶',
    ]);
  });

  it('AC-05-11：场景一第 3 拍 result 与 config-import 的 renderImport 对示例包的输出逐字相同', () => {
    const parsePackage = loadParsePackage();
    const pkg = parsePackage(
      JSON.stringify({
        format: 'zhitong.config/1',
        company: { name: '某某工程造价咨询有限公司' },
        tos: {
          endpoint: 'tos-cn-beijing.volces.com',
          region: 'cn-beijing',
          bucket: 'zt-demo',
          prefix: '示例咨询',
          accessKeyId: 'example-id',
          secretAccessKey: 'example-secret',
        },
      }),
    );
    // renderImport 的模板（applied: true、无 ssh / volc 段），与 config-import/src/index.ts 对照。
    const index = readFileSync(resolve(ZHITONG, 'plugins/config-import/src/index.ts'), 'utf8');
    expect(index).toContain(
      "const target = `tos://${value.tos.bucket}/${value.tos.prefix === '' ? '' : `${value.tos.prefix}/`}（${value.tos.endpoint}，${value.tos.region}）`",
    );
    expect(index).toContain(
      "`已导入「${value.company}」的配置包：${target}。密钥已存入本机凭据存储（${value.storedCredentials.join('、')}），TOS 工具已按新设置重新加载。`",
    );
    expect(index).toContain("config.accessKeyIdRef ?? 'ZT_TOS_ACCESS_KEY_ID'");
    expect(index).toContain("config.secretAccessKeyRef ?? 'ZT_TOS_SECRET_ACCESS_KEY'");
    const stored = ['ZT_TOS_ACCESS_KEY_ID', 'ZT_TOS_SECRET_ACCESS_KEY'];
    const target = `tos://${pkg.tos.bucket}/${pkg.tos.prefix === '' ? '' : `${pkg.tos.prefix}/`}（${pkg.tos.endpoint}，${pkg.tos.region}）`;
    const expected = `已导入「${pkg.company.name}」的配置包：${target}。密钥已存入本机凭据存储（${stored.join('、')}），TOS 工具已按新设置重新加载。`;
    const beat = WORKFLOW_STEPS[0]!.scene[2]!;
    expect(beat.kind === 'tool' && beat.result).toBe(expected);
  });

  it('AC-05-12：场景 DOM 不含 AKLT 或密钥样式的值；出现两个引用名与 ●', async () => {
    const root = await workflowDom();
    const html = root.innerHTML;
    expect(html).not.toMatch(/AKLT/);
    expect(html).not.toMatch(/[A-Za-z0-9+/]{32,}/);
    expect(html).toContain('ZT_TOS_ACCESS_KEY_ID');
    expect(html).toContain('ZT_TOS_SECRET_ACCESS_KEY');
    expect(html).toContain('●');
  });

  it('AC-05-13：场景二盘点数字 7 / 3 / 1 / 3，42.86% 与 57.14%', async () => {
    expect(INVENTORY).toEqual({ required: 7, ready: 3, pending: 1, missing: 3 });
    expect(INVENTORY_RATE).toBe(`${(Math.round((3 / 7) * 10000) / 100).toFixed(2)}%`);
    expect(INVENTORY_RATE).toBe('42.86%');
    expect(INVENTORY_MAX).toBe('57.14%');
    const text = (await workflowDom()).textContent ?? '';
    expect(text).toContain('必备 7 · 已备 3 · 待确认 1 · 缺失 3 ｜ 齐备率 42.86%（上限 57.14%）');
    expect(text).toContain('必备 7 项 · 已备 3 · 待确认 1 · 缺失 3');
  });

  it('AC-05-14：场景三的金额、比例、行数来自 demo.ts 的 RECONCILE，workflow.ts 不含这些数的字面量', () => {
    const src = readFileSync(resolve(__dirname, '../src/data/workflow.ts'), 'utf8');
    for (const lit of [
      '30,530,406.80',
      '30530406.8',
      '29,623,713.84',
      '29623713.84',
      '906,692.96',
      '906692.96',
      '2.97%',
      '0.0297',
      '546,666.34',
      '239,531.25',
      '81,533.65',
      '32,612.74',
      '612,418.27',
      '147,749.55',
      '1,284',
      '1,031',
    ])
      expect(src).not.toContain(lit);
    const task = WORKFLOW_STEPS[2]!;
    const stream = task.scene.find((b) => b.kind === 'stream');
    expect(stream?.kind === 'stream' && stream.text).toBe(
      '送审合计 30,530,406.80 元，审定合计 29,623,713.84 元，核减额 906,692.96 元，核减率 2.97%，均为脚本取数，需人工复核。核减最多的是混凝土及钢筋混凝土工程 546,666.34 元；门窗工程核增 32,612.74 元。量差 612,418.27 元，价差 147,749.55 元。另有 7 行待核实，已写进待确认清单。',
    );
    expect(RECONCILE_CARD.figures.map((f) => f.value)).toEqual([
      RECONCILE.summary.a_total,
      RECONCILE.summary.b_total,
      RECONCILE.summary.adjust_amount,
      RECONCILE.summary.adjust_rate,
    ]);
    expect(
      RECONCILE_CARD.bars.map((b) => [b.name, b.kind, b.amount, (b.ratio * 100).toFixed(1)]),
    ).toEqual([
      ['混凝土及钢筋混凝土工程', '核减', '546,666.34', '100.0'],
      ['措施项目', '核减', '239,531.25', '43.8'],
      ['土石方工程', '核减', '81,533.65', '14.9'],
      ['门窗工程', '核增', '32,612.74', '6.0'],
    ]);
    expect(RECONCILE_CARD.rows).toBe(
      '逐行 1,284：一致 1,031 · 调整 214 · 仅送审 23 · 仅审定 9 · 待核实 7',
    );
    expect(task.outcome).toBe('核减 906,692.96 元 · 2.97% · 需人工确认');
  });

  it('AC-05-15：案例索引新行 8 列、列序同模板；成果链接与单方造价', () => {
    const tpl = readFileSync(resolve(ZHITONG, 'skills/zt-project/templates/案例索引.md'), 'utf8');
    const header = tpl
      .split('\n')
      .find((l) => l.startsWith('| 编号'))!
      .split('|')
      .map((s) => s.trim())
      .filter(Boolean);
    expect(CASE_INDEX.columns).toEqual(header);
    expect(CASE_INDEX.after).toHaveLength(8);
    expect(CASE_INDEX.after[6]).toBe('项目/2026-007-某综合办公楼/成果/');
    expect(UNIT_COST).toBe(
      (Math.round((29623713.84 / 18600) * 100) / 100).toLocaleString('en-US', {
        minimumFractionDigits: 2,
      }),
    );
    expect(UNIT_COST).toBe('1,592.67');
    expect(KEY_METRICS).toBe(
      '审定 29,623,713.84 元；核减率 2.97%；土建单方 1,592.67 元/m²（按建筑面积）',
    );
  });

  it('AC-05-21：四个文档链接都在 06 章路由表内', () => {
    const paths = DOC_ROUTES.map((d) => d.path);
    for (const step of WORKFLOW_STEPS) expect(paths).toContain(step.doc.href);
  });

  it('AC-05-24：场景窗口内除两个按钮外没有可聚焦元素；样式里窗口文字不小于 12px', async () => {
    const root = await workflowDom();
    for (const w of root.querySelectorAll('.wf-window'))
      expect(
        w.querySelectorAll('a, input, select, textarea, [tabindex]:not([tabindex="-1"]), summary')
          .length,
      ).toBe(0);
    const css = readFileSync(resolve(__dirname, '../src/styles/sections/workflow.css'), 'utf8');
    const sizes = [...css.matchAll(/font-size:\s*(\d+(?:\.\d+)?)px/g)].map((m) => Number(m[1]));
    expect(sizes.length).toBeGreaterThan(5);
    expect(Math.min(...sizes)).toBeGreaterThanOrEqual(12);
  });

  it('节拍排期：起点 = 上一拍结束 + gap；各类型时长按 §1.2.1（按规则算出 10.5 / 18.2 / 14.9 / 14.8 s）', () => {
    const totals = WORKFLOW_STEPS.map((s) => planScene(s.scene).total);
    const { slots } = planScene(WORKFLOW_STEPS[0]!.scene);
    expect(slots[0]!.start).toBeCloseTo(0.4);
    expect(slots[1]!.start).toBeCloseTo(0.4 + beatDuration(WORKFLOW_STEPS[0]!.scene[0]!) + 0.1);
    expect(totals.map((t) => Number(t.toFixed(1)))).toEqual([10.5, 18.2, 14.9, 14.8]);
    expect(formatMs(3840)).toBe('3,840 ms');
  });

  it('钉住：区间 3.2 × innerHeight；标签 0 / 1.2 / 2.4 / 3.6（共 3.9）；最近标签', () => {
    expect(WF_PIN_RATIO).toBe(3.2);
    expect(WF_LABELS).toEqual([0, 1.2, 2.4, 3.6]);
    expect(WF_TOTAL).toBe(3.9);
    expect([0, 0.59, 0.61, 1.9, 3.1, 3.9].map(nearestLabelIndex)).toEqual([0, 0, 1, 2, 3, 3]);
    const pos = labelPositions(1000, 1000 + 3.9 * 100);
    expect(pos).toEqual([1000, 1120, 1240, 1360]);
  });

  it('AC-05-03 规则：向下 p ≥ 0.12 吸到 b、否则回 a；向上 p ≤ 0.88 吸到 a、否则回 b；吸附时长 0.35–0.8 s', () => {
    const pos = [0, 100, 200, 300];
    expect(snapTarget(11, pos, 390, 1)).toBe(0);
    expect(snapTarget(12, pos, 390, 1)).toBe(100);
    expect(snapTarget(188, pos, 390, -1)).toBe(100);
    expect(snapTarget(189, pos, 390, -1)).toBe(200);
    expect(snapTarget(350, pos, 390, 1)).toBe(390);
    expect(snapDuration(10, 900)).toBe(0.35);
    expect(snapDuration(900, 900)).toBe(0.8);
    expect(snapDuration(500, 900)).toBeCloseTo(0.5);
  });

  it('AC-05-18：减少动效（测试环境）下为纵向时间线、场景终态、无暂停与重播按钮', async () => {
    const { wrapper } = await mountAt('/', WorkflowSection);
    expect(wrapper.get('#workflow').classes()).not.toContain('wf--pinned');
    expect(wrapper.findAll('.wf-control')).toHaveLength(0);
    expect(wrapper.findAll('.wf-window[data-state="static"]')).toHaveLength(4);
    expect(wrapper.text()).toContain('已归档 2026-007：推送 58 个文件，回读校验全部通过。');
  });

  it('AC-05-23：打印样式隐藏场景按钮、强制终态', () => {
    const css = readFileSync(resolve(__dirname, '../src/styles/sections/workflow.css'), 'utf8');
    const print = css.slice(css.indexOf('@media print'));
    expect(print).toContain('.wf-controls');
    expect(print).toContain('display: none');
    expect(print).toContain('opacity: 1 !important');
  });
});
