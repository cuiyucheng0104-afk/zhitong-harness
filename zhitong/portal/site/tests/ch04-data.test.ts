/** 04 章数据与小动画构建（AC-04-01 – 05、16）。 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, beforeAll } from 'vitest';
import { mount } from '@vue/test-utils';
import { defineComponent, h } from 'vue';
import { gsap } from 'gsap';
import { DrawSVGPlugin } from 'gsap/DrawSVGPlugin';
import {
  ART_FACTS,
  ART_TOKENS,
  DEFAULT_GROUP,
  DEFAULT_SELECTION,
  allFeatures,
  dimLabel,
  featureGroups,
  glossary,
  homeGroups,
} from '../src/data/capabilities';
import { DOC_ROUTES } from '../src/docs/routes';
import { formatInt, formatMoney } from '../src/lib/format';
import { builders } from '../src/components/capabilities/art/timelines';
import {
  createArtKit,
  finishArtLoop,
  type ArtLayout,
} from '../src/components/capabilities/art-kit';
import ProjectArt from '../src/components/capabilities/art/ProjectArt.vue';
import QaArt from '../src/components/capabilities/art/QaArt.vue';
import CadArt from '../src/components/capabilities/art/CadArt.vue';
import CheckArt from '../src/components/capabilities/art/CheckArt.vue';
import MetricsArt from '../src/components/capabilities/art/MetricsArt.vue';
import ControlArt from '../src/components/capabilities/art/ControlArt.vue';
import EstimateArt from '../src/components/capabilities/art/EstimateArt.vue';
import ReportArt from '../src/components/capabilities/art/ReportArt.vue';
import BillsArt from '../src/components/capabilities/art/BillsArt.vue';
import ArchiveArt from '../src/components/capabilities/art/ArchiveArt.vue';
import KnowledgeArt from '../src/components/capabilities/art/KnowledgeArt.vue';
import CloudArt from '../src/components/capabilities/art/CloudArt.vue';

const ARTS = {
  project: ProjectArt,
  qa: QaArt,
  cad: CadArt,
  check: CheckArt,
  metrics: MetricsArt,
  control: ControlArt,
  estimate: EstimateArt,
  report: ReportArt,
  bills: BillsArt,
  archive: ArchiveArt,
  knowledge: KnowledgeArt,
  cloud: CloudArt,
} as const;

const REPO = resolve(__dirname, '../../..');
const close = (a: number, b: number, eps = 0.005) => Math.abs(a - b) <= eps;
const round2 = (v: number) => Math.round(v * 100) / 100;

describe('AC-04-01 分组与顺序', () => {
  it('4 组 3/4/3/2 项，id 与顺序同 §5.3', () => {
    expect(featureGroups.map((g) => g.id)).toEqual(['project', 'calculate', 'output', 'knowledge']);
    expect(featureGroups.map((g) => g.features.length)).toEqual([3, 4, 3, 2]);
    expect(allFeatures.map((f) => f.id)).toEqual([
      'project',
      'qa',
      'cad',
      'check',
      'metrics',
      'control',
      'estimate',
      'report',
      'bills',
      'archive',
      'knowledge',
      'cloud',
    ]);
    expect(featureGroups.map((g) => g.label)).toEqual([
      '项目资料',
      '核对与测算',
      '成果与归档',
      '知识与协作',
    ]);
  });
});

describe('AC-04-02 每项字段', () => {
  const docPaths = new Set(DOC_ROUTES.map((d) => d.path));
  it.each(allFeatures.map((f) => [f.id, f] as const))(
    '%s 字段完整，文档路径在 06 章路由表中',
    (id, f) => {
      for (const key of [
        'name',
        'kicker',
        'title',
        'description',
        'input',
        'output',
        'caution',
      ] as const)
        expect(f[key].length).toBeGreaterThan(0);
      expect(f.art.caption.length).toBeGreaterThan(0);
      expect(f.say).toHaveLength(2);
      expect(f.outputs.length).toBeGreaterThanOrEqual(1);
      expect(f.docs).toBe(`/docs/features/${id}/`);
      expect(docPaths.has(f.docs)).toBe(true);
      expect(f.kicker).toBe(
        `${featureGroups.find((g) => g.features.some((x) => x.id === id))!.label} · ${f.skill}`,
      );
    },
  );
  it('06 章路由表标题与能力名称一致（00 章 §14 第 10 条）', () => {
    for (const f of allFeatures)
      expect(DOC_ROUTES.find((d) => d.path === f.docs)?.title).toBe(f.name);
    expect(allFeatures.find((f) => f.id === 'control')!.name).toBe('投控异常检测与复核');
  });
});

describe('AC-04-03 文案禁用词', () => {
  const strings = (f: (typeof allFeatures)[number]) => [
    f.name,
    f.kicker,
    f.title,
    f.description,
    f.input,
    f.output,
    f.caution,
    f.art.caption,
    ...f.say,
    ...f.outputs.flatMap((o) => [o.path, o.note ?? '']),
  ];
  it('不含 你 / 自动算 / AI 审定 / 一键 / 按客户确认 / 行业标准阈值', () => {
    const all = [
      ...allFeatures.flatMap(strings),
      ...Object.values(glossary),
      ...featureGroups.map((g) => g.intro),
    ].join('\n');
    expect(all).not.toMatch(/你|自动算|AI ?审定|一键|按客户确认|行业标准阈值/);
  });
  it('say 每句 ≤ 32 字', () => {
    for (const f of allFeatures)
      for (const s of f.say) expect([...s].length).toBeLessThanOrEqual(32);
  });
  it('默认选中项：核对与测算 / 送审审定核对，cloud 永不为默认项（AC-04-07 数据部分）', () => {
    expect(DEFAULT_GROUP).toBe('calculate');
    expect(DEFAULT_SELECTION.calculate).toBe('check');
    expect(Object.values(DEFAULT_SELECTION)).not.toContain('cloud');
    expect(allFeatures.find((f) => f.id === 'cloud')!.badge).toBe('管理员');
  });
});

describe('AC-04-04 源数据计数与仓库一致', () => {
  it('report_templates.yaml 24 套 172 章；gb50854_zj2025.yaml codes 490 条（Z 码 158）', () => {
    const tpl = readFileSync(
      resolve(REPO, 'skills/zt-report/data/report_templates.yaml'),
      'utf8',
    ).split('\n');
    expect(tpl.filter((l) => /^\s*- template_code:/.test(l))).toHaveLength(24);
    expect(tpl.filter((l) => /^\s*- code:/.test(l))).toHaveLength(172);
    const reg = readFileSync(
      resolve(REPO, 'python/zt/code_registry/data/gb50854_zj2025.yaml'),
      'utf8',
    ).split('\n');
    const start = reg.findIndex((l) => l.startsWith('codes:'));
    let end = reg.findIndex((l, i) => i > start && /^\S/.test(l));
    if (end < 0) end = reg.length;
    const keys = reg
      .slice(start + 1, end)
      .map((l) => /^ {2}'?([0-9A-Z]+)'?:/.exec(l)?.[1])
      .filter(Boolean) as string[];
    expect(keys).toHaveLength(490);
    expect(keys.filter((k) => k.startsWith('Z'))).toHaveLength(158);
    const report = allFeatures.find((f) => f.id === 'report')!.description;
    const bills = allFeatures.find((f) => f.id === 'bills')!.description;
    expect(report).toContain('24 套模板');
    expect(report).toContain('172 章');
    expect(bills).toContain('490 条受控码表');
  });
});

describe('AC-04-05 §5.5 验算', () => {
  const C = ART_FACTS.check;
  it('00 章 §8.2 合计与比率', () => {
    expect(round2(C.sent - C.approved)).toBe(C.reduce);
    expect(round2(C.reduceSum - C.increaseSum)).toBe(C.reduce);
    expect(round2((C.reduce / C.sent) * 100)).toBe(C.rate);
    const r = C.rows;
    expect(r.same + r.adjusted + r.sentOnly + r.approvedOnly + r.pending).toBe(r.total);
  });
  it('check 行：钢筋核减、窗核增', () => {
    const b = C.rebar;
    expect(round2(b.sentQty * b.price - b.approvedQty * b.price)).toBe(b.reduce);
    expect(round2(round2(b.sentQty * b.price) - round2(b.approvedQty * b.price))).toBe(b.reduce);
    const w = C.window;
    expect(round2(w.sentQty * w.sentPrice)).toBe(1_587_252.1);
    expect(round2(w.approvedQty * w.approvedPrice)).toBe(1_613_660.15);
    expect(round2(1_613_660.15 - 1_587_252.1)).toBe(w.increase);
    expect(C.increaseSum).toBeGreaterThanOrEqual(w.increase);
  });
  it('project：3/7、4/7', () => {
    const p = ART_FACTS.project;
    expect(p.ready + p.pending + p.missing).toBe(p.required);
    expect(round2((p.ready / p.required) * 100)).toBe(p.rate);
    expect(round2(((p.ready + p.pending) / p.required) * 100)).toBe(p.upper);
  });
  it('cad：差异% 与面积、坐标换算、网格行数', () => {
    const cad = ART_FACTS.cad;
    for (const r of cad.rooms)
      expect(round2((Math.abs(r.geom - r.text) / r.text) * 100)).toBe(r.diff);
    expect(round2(cad.axisRect.w * cad.axisRect.h)).toBe(73.08);
    expect(round2(cad.innerRect.w * cad.innerRect.h)).toBe(69.7);
    expect(Math.round((8 * 594) / 841)).toBe(cad.gridRows);
    const X = (x: number) => 36 + (x * 216) / 84_100;
    expect(X(84_100)).toBe(252);
    expect(36 + (59_400 * 0) / 59_400).toBe(36);
    expect(round2(159 - (59_400 * 153) / 59_400)).toBe(6);
    expect(round2(200 * 0.014244)).toBe(2.85);
  });
  it('metrics：单方、占比、均值、偏差、数轴', () => {
    const m = ART_FACTS.metrics;
    expect(round2(C.approved / m.area)).toBe(m.unit);
    expect(round2(m.mean)).toBe(round2((m.peers.a + m.peers.b) / 2));
    expect(round2(((m.unit - m.mean) / m.mean) * 100)).toBe(m.deviation);
    expect(round2((18_215_641.08 / C.approved) * 100)).toBe(m.shares.concrete);
    expect(round2((3_991_286.35 / C.approved) * 100)).toBe(m.shares.measures);
    expect(round2((2_948_226.54 / C.approved) * 100)).toBe(m.shares.windows);
    const x = (v: number) => 12 + ((v - m.axis.min) / (m.axis.max - m.axis.min)) * 240;
    expect(close(x(1600), 80.6, 0.05)).toBe(true);
    expect(close(x(m.peers.b), 31.2, 0.05)).toBe(true);
    expect(close(x(m.peers.a), 232.1, 0.05)).toBe(true);
    expect(close(x(m.mean), 131.7, 0.05)).toBe(true);
    expect(close(x(m.unit), 68.0, 0.05)).toBe(true);
    expect(round2(30_530_406.8 / m.area)).toBe(m.sentArea);
  });
  it('control：290 = 286 + 2 + 1 + 1', () => {
    const c = ART_FACTS.control;
    expect(c.large + c.duplicate + c.provisional + c.consistency).toBe(c.total);
    expect(c.confirmed + c.remaining).toBe(c.total);
    expect(c.duplicate + c.provisional + c.consistency).toBe(c.focus);
  });
  it('estimate、report、bills', () => {
    const e = ART_FACTS.estimate;
    expect(e.basement + e.tower).toBe(e.total);
    expect(e.ground + e.underground).toBe(e.parking);
    expect(e.found + e.rest).toBe(e.slots);
    const [s, a, rd, inc, net] = ART_FACTS.report.values;
    expect([s, a, rd, inc, net]).toEqual([
      C.sent,
      C.approved,
      C.reduceSum,
      C.increaseSum,
      C.reduce,
    ]);
    expect(round2(rd - inc)).toBe(net);
    const b = ART_FACTS.bills;
    expect(b.parts.reduce((x, y) => x + y, 0)).toBe(b.segments);
    expect(b.base + b.serial).toBe(b.item);
  });

  /** 动画文本中的每个数字都能在 ART_FACTS / 00 章 §8.2 中找到。 */
  const facts: number[] = [];
  const idents: string[] = [...ART_TOKENS];
  const walk = (v: unknown) => {
    if (typeof v === 'number') facts.push(v);
    else if (typeof v === 'string') idents.push(v);
    else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') Object.values(v).forEach(walk);
  };
  walk(ART_FACTS);
  const forms = new Set<string>();
  for (const v of facts) {
    for (const t of [formatMoney(v), formatInt(v), String(v), v.toFixed(2), formatMoney(v, 1)]) {
      forms.add(t);
      forms.add(`${t}%`);
    }
  }
  const composites = idents.filter((t) => !/^\d+$/.test(t)).sort((a, b) => b.length - a.length);
  for (const t of idents) if (/^\d+$/.test(t)) forms.add(t);

  it.each(Object.keys(ARTS) as (keyof typeof ARTS)[])('%s 动画文本中的数字都有出处', (id) => {
    const wrapper = mount(defineComponent({ render: () => h('div', [h(ARTS[id])]) }));
    const texts = wrapper.findAll('text').map((t) => t.element.textContent ?? '');
    const unknown: string[] = [];
    for (const raw of texts) {
      let s = raw;
      for (const c of composites) s = s.split(c).join(' ');
      for (const m of s.matchAll(/−?\d[\d,]*(?:\.\d+)?%?/g))
        if (!forms.has(m[0])) unknown.push(`${m[0]} ← ${raw}`);
    }
    expect(unknown).toEqual([]);
  });
});

describe('尺寸线标注与计数（AC-04-06 数据部分）', () => {
  it('home 全为 true 时 12 = 3 + 4 + 3 + 2；cloud.home = false 时 11 = 3 + 4 + 3 + 1', () => {
    expect(dimLabel(homeGroups())).toBe('12 = 3 + 4 + 3 + 2');
    const groups = featureGroups.map((g) => ({
      ...g,
      features: g.features.map((f) => (f.id === 'cloud' ? { ...f, home: false } : f)),
    }));
    expect(dimLabel(homeGroups(groups))).toBe('11 = 3 + 4 + 3 + 1');
  });
});

describe('AC-04-16 循环总时长与 art.loop 一致', () => {
  beforeAll(() => {
    gsap.registerPlugin(DrawSVGPlugin);
    const proto = SVGElement.prototype as unknown as Record<string, unknown>;
    proto.getTotalLength ??= () => 100;
    proto.getBBox ??= () => ({ x: 0, y: 0, width: 10, height: 10 });
    proto.getComputedTextLength ??= () => 0;
  });
  const cases = allFeatures.flatMap((f) =>
    (['split', 'sequence'] as ArtLayout[]).map((layout) => [f.id, layout, f.art.loop] as const),
  );
  it.each(cases)('%s（%s）循环 %ss', (id, layout, loop) => {
    const wrapper = mount(
      defineComponent({ render: () => h('div', { class: 'art-stage' }, [h(ARTS[id])]) }),
      { attachTo: document.body },
    );
    const stage = wrapper.element as HTMLElement;
    const tl = gsap.timeline({ paused: true, repeat: -1 });
    const handle = createArtKit(gsap, tl, stage, layout);
    builders[id](handle.kit);
    finishArtLoop(gsap, tl, stage, handle.hold());
    expect(Math.abs(tl.duration() - loop)).toBeLessThanOrEqual(0.05);
    expect(tl.labels.hold).toBeGreaterThan(0);
    expect(tl.labels.handoff).toBeGreaterThan(0);
    // 停留标签处：过程元素（data-transient）全部不可见
    tl.time(tl.labels.hold!);
    const visible = [...stage.querySelectorAll<SVGElement>('[data-transient]')].filter((el) => {
      const op = el.style.opacity;
      return op !== '' && Number(op) > 0.01;
    });
    expect(visible.map((el) => el.dataset.a)).toEqual([]);
    tl.kill();
    handle.dispose();
    wrapper.unmount();
  });
});
