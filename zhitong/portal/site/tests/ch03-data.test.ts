/**
 * 03 章数据：岗位、任务入口、说明卡文案（与 spec 表格逐字对照）、示例数字、它解决什么的数据与对照列表。
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { ROLES, ROLE_FIGURES, ROLE_TASKS, primaryLabel, type CapabilityId } from '../src/data/roles';
import {
  buildClickMarkers,
  CLICK_MARKERS,
  LEGACY_PANELS,
  mulberry32,
  PROBLEM_COPY,
  THREAD_ROWS,
} from '../src/data/problem';
import { DOC_ROUTES } from '../src/docs/routes';
import { formatMoney, formatPercent } from '../src/lib/format';
import { nearestPoint, snapDuration, stepOf } from '../src/composables/usePinnedSteps';
import { AMOUNT, RATE } from '../src/components/roles/micro/MicroReconcile.vue';
import { TOTAL } from '../src/components/roles/micro/MicroDraft.vue';
import { UNIT } from '../src/components/roles/micro/MicroBenchmark.vue';
import { AREA } from '../src/components/roles/micro/MicroExtract.vue';

const spec = readFileSync('../spec-v1.1/03-岗位与痛点.md', 'utf8');
const copy = readFileSync('../门户文案.txt', 'utf8');

/** 取 spec 里以 header 开头的表格的数据行。 */
function table(header: string): string[][] {
  const lines = spec.split('\n');
  const start = lines.findIndex((l) => l.startsWith(header));
  expect(start, header).toBeGreaterThanOrEqual(0);
  const rows: string[][] = [];
  for (const line of lines.slice(start + 2)) {
    if (!line.startsWith('|')) break;
    rows.push(
      line
        .split('|')
        .slice(1, -1)
        .map((c) => c.trim().replace(/^`|`$/g, '')),
    );
  }
  return rows;
}

const ALL: CapabilityId[] = ['project', 'qa', 'cad', 'check', 'metrics', 'control', 'estimate', 'report', 'bills', 'archive', 'knowledge', 'cloud'];

describe('03 §1.4 岗位与任务数据', () => {
  it('12 个任务的 capability 互不相同且覆盖全部 12 个 id；docs 都在 06 章路由表；label ≤ 8 字', () => {
    expect(ROLE_TASKS).toHaveLength(12);
    expect(new Set(ROLE_TASKS.map((t) => t.capability)).size).toBe(12);
    expect([...ROLE_TASKS.map((t) => t.capability)].sort()).toEqual([...ALL].sort());
    const paths = new Set(DOC_ROUTES.map((r) => r.path));
    for (const t of ROLE_TASKS) {
      expect(paths.has(t.docs), t.docs).toBe(true);
      expect([...t.label].length).toBeLessThanOrEqual(8);
      expect(t.id).toBe(`${ROLES.find((r) => r.tasks.includes(t))!.id}-${t.capability}`);
    }
  });

  it('primary 为场景的恰为 check、control、cad，场景 id 分别为 check / review / cad（AC-03-09 按钮文字）', () => {
    const scenes = ROLE_TASKS.filter((t) => t.primary.kind === 'scene');
    expect(scenes.map((t) => t.capability)).toEqual(['check', 'control', 'cad']);
    expect(scenes.map((t) => (t.primary.kind === 'scene' ? t.primary.scene : null))).toEqual(['check', 'review', 'cad']);
    for (const t of ROLE_TASKS) expect(primaryLabel(t)).toBe(t.primary.kind === 'scene' ? '看示例' : '看能力介绍');
  });

  it('任务入口表（岗位、序号、文字、能力、文档）与 spec §1.2 一致', () => {
    const rows = table('| 岗位 | 序 | 入口文字 |');
    expect(rows).toHaveLength(12);
    rows.forEach(([role, no, label, cap, primary, docs], i) => {
      const t = ROLE_TASKS[i]!;
      expect(ROLES.find((r) => r.tasks.includes(t))!.name).toBe(role);
      expect([t.no, t.label, t.capability, t.docs]).toEqual([no, label, cap, docs]);
      expect(primary!.startsWith(primaryLabel(t))).toBe(true);
    });
  });

  it('岗位面板文案与 spec §1.2 逐字一致', () => {
    const rows = table('| 岗位 | 页签 | h3 | 正文 |');
    expect(rows.map(([id, name, title, body]) => ({ id, name, title, body }))).toEqual(
      ROLES.map((r) => ({ id: r.id, name: r.name, title: r.title, body: r.description })),
    );
  });

  it('AC-03-09：12 张说明卡（眉题、一句话、需要什么、得到什么、限定）与 spec §1.2 逐字一致', () => {
    const rows = table('| 入口 | 眉题 | 一句话 |');
    expect(rows).toHaveLength(12);
    // 00 §14 第 10 条（优先级高于 03 章表格）：control 的能力名以 04 章 featureGroups 为准，眉题“分组 / 能力名”随之改名。
    const OVERRIDE: Record<string, string> = { '核对与测算 / 全过程投控检查': '核对与测算 / 投控异常检测与复核' };
    for (const [label, rawEyebrow, summary, needs, yields, note] of rows) {
      const eyebrow = OVERRIDE[rawEyebrow!] ?? rawEyebrow;
      const t = ROLE_TASKS.find((x) => x.label === label)!;
      expect(t, label).toBeTruthy();
      expect({ eyebrow: t.eyebrow, summary: t.summary, needs: t.needs, yields: t.yields, note: t.note ?? '—' }).toEqual({
        eyebrow,
        summary,
        needs,
        yields,
        note,
      });
    }
  });

  it('小动画与入口一一对应（§1.4）', () => {
    expect(ROLE_TASKS.map((t) => t.micro)).toEqual([
      'inventory', 'reconcile', 'extract', 'draft',
      'review', 'benchmark', 'codes', 'plan',
      'archive', 'entry', 'answer', 'ops',
    ]);
  });
});

describe('AC-03-18 示例数字（00 章 §8.2）', () => {
  it('核减额、核减率、审定单方与 00 章互相验算', () => {
    const F = ROLE_FIGURES;
    expect(+(F.submittedTotal - F.approvedTotal).toFixed(2)).toBe(F.reduction);
    expect(formatPercent(F.reduction / F.submittedTotal)).toBe('2.97%');
    expect(formatMoney(F.approvedTotal / F.floorArea)).toBe('1,592.67');
    expect(F.approvedUnit).toBe(1592.67);
  });
  it('小动画里的金额与比例引用同一常量', () => {
    expect([AMOUNT, RATE, TOTAL, UNIT, AREA]).toEqual(['906,692.96', '2.97%', '30,530,406.80', '1,592.67', '15,200.00']);
  });
});

describe('03 §3 usePinnedSteps 的步骤与吸附', () => {
  it('三步：阈值在 0.25 / 0.75；吸附到最近点（AC-03-02）', () => {
    expect([0, 0.24, 0.26, 0.74, 0.76, 1].map((p) => stepOf(p, 3))).toEqual([0, 0, 1, 1, 2, 2]);
    expect([0.24, 0.3, 0.8].map((p) => nearestPoint(p, [0, 0.5, 1]))).toEqual([0, 0.5, 1]);
  });
  it('五点吸附（AC-03-21）与时长 clamp(|Δ|/1000, 0.2, 0.6)', () => {
    const pts = [0, 0.25, 0.5, 0.75, 1];
    expect(nearestPoint(0.1, pts)).toBe(0);
    expect(nearestPoint(0.2, pts)).toBe(0.25);
    expect([50, 400, 2000].map(snapDuration)).toEqual([0.2, 0.4, 0.6]);
  });
});

describe('03 §2.4 它解决什么的数据', () => {
  it('九个面板顺序与门户文案一致，点击标记合计 100，待确认 8，上次结果 2，扇形线 3', () => {
    expect(LEGACY_PANELS.map((p) => p.label).join('、')).toBe('标注、齐套、抽取、核对、指标、投控、报告、清单、概算');
    expect(copy).toContain('标注、齐套、抽取、核对、指标、投控、报告、清单、概算');
    expect(LEGACY_PANELS.reduce((a, p) => a + p.clicks, 0)).toBe(100);
    expect(LEGACY_PANELS.reduce((a, p) => a + p.pending, 0)).toBe(8);
    expect(LEGACY_PANELS.filter((p) => p.lastResult).map((p) => p.id)).toEqual(['check', 'metrics']);
    expect(LEGACY_PANELS.filter((p) => p.fan).map((p) => p.id)).toEqual(['check', 'metrics', 'control']);
    expect(LEGACY_PANELS.filter((p) => p.fate === 'retired').map((p) => p.id)).toEqual(['tag', 'extract']);
  });

  it('AC-03-27：CLICK_MARKERS 由固定种子生成，重复生成逐项相等，坐标在面板内', () => {
    expect(CLICK_MARKERS).toHaveLength(100);
    expect(buildClickMarkers()).toEqual(CLICK_MARKERS);
    expect(buildClickMarkers()).toEqual(buildClickMarkers());
    for (const m of CLICK_MARKERS) {
      expect(m.x).toBeGreaterThan(0);
      expect(m.x).toBeLessThan(100);
      expect(m.y).toBeGreaterThan(20);
      expect(m.y).toBeLessThan(100);
    }
    const a = mulberry32(1);
    const b = mulberry32(1);
    expect([a(), a(), a()]).toEqual([b(), b(), b()]);
  });

  it('线程 8 行与 spec §2.2 线程表逐字一致', () => {
    const rows = table('| 行 | 中文标签 | 等宽原名 | 结果行 |');
    expect(rows.map(([id, label, cmd, result]) => ({ id, label, cmd: cmd === '—' ? null : cmd, result }))).toEqual(
      THREAD_ROWS.map((r) => ({
        id: r.id,
        label: r.label,
        cmd: r.command,
        result: r.muted ? `${r.result}（灰色）` : r.result,
      })),
    );
    expect(THREAD_ROWS.find((r) => r.id === 'check')!.result).toBe('核减 906,692.96 元 · 核减率 2.97% · 需人工确认');
  });



  it('标题与副标题取自门户文案', () => {
    expect(copy).toContain(`副标题：${PROBLEM_COPY.subtitle}`);
    expect(PROBLEM_COPY.counterOld.note).toContain('估算值，非实测');
  });
});
