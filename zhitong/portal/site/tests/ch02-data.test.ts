/**
 * 02 章 §9 数字验算（AC-02-14）、时刻表（AC-02-24）、复核记录格式（AC-02-15）、文字版（AC-02-25）、文案禁词（AC-02-29 数据部分）。
 * 金额用“分”为单位的整数计算，避免浮点误差；四舍五入为 ROUND_HALF_UP。
 */
import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import {
  CAD,
  RECONCILE,
  SCENES,
  TK,
  buildTranscript,
  reviewRecordLine,
  streamDuration,
  type HitlState,
} from '../src/data/demo';
import { ROOMS, VIEW } from '../src/data/demo-drawing';
import { HERO, PRINCIPLES } from '../src/data/hero';
import { scheduleIssues, pick } from '../src/components/demo/engine';
import { formatMoney } from '../src/lib/format';

const cents = (v: number) => Math.round(v * 100);
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
/** 两位小数 ROUND_HALF_UP（输入为精确到 1e-6 的乘积）。 */
const round2 = (v: number) => Math.round((v + Number.EPSILON) * 100) / 100;

describe('§9 送审审定核对数字', () => {
  const ch = RECONCILE.chapters;
  const S = RECONCILE.summary;

  it('6 章送审、审定之和等于两侧合计；核减额 = 送审 − 审定', () => {
    expect(sum(ch.map((c) => cents(c.a_amount)))).toBe(cents(30530406.8));
    expect(sum(ch.map((c) => cents(c.b_amount)))).toBe(cents(29623713.84));
    expect(cents(S.a_total) - cents(S.b_total)).toBe(cents(906692.96));
    expect(cents(S.adjust_amount)).toBe(cents(906692.96));
    for (const c of ch) expect(cents(c.a_amount) - cents(c.b_amount)).toBe(cents(c.adjust));
  });

  it('核减率 0.029698… 四舍五入为 adjust_rate 0.0297，页面 2.97%', () => {
    const rate = S.adjust_amount / S.a_total;
    expect(rate).toBeCloseTo(0.029698, 6);
    expect(Math.round(rate * 10000) / 10000).toBe(S.adjust_rate);
    expect(`${(S.adjust_rate * 100).toFixed(2)}%`).toBe('2.97%');
  });

  it('核减合计 939,305.70、核增合计 32,612.74、净核减 906,692.96', () => {
    const pos = sum(ch.filter((c) => c.adjust > 0).map((c) => cents(c.adjust)));
    const neg = sum(ch.filter((c) => c.adjust < 0).map((c) => cents(-c.adjust)));
    expect(pos).toBe(cents(939305.7));
    expect(neg).toBe(cents(32612.74));
    expect(pos - neg).toBe(cents(906692.96));
  });

  it('逐行 1,284 行；清单行 1,275 / 1,261；章行数合计 1,284', () => {
    expect(S.count_same + S.count_changed + S.count_only_a + S.count_only_b + S.count_uncertain).toBe(1284);
    expect(S.count_total).toBe(1284);
    expect(S.count_total - S.count_only_b).toBe(S.count_a_items);
    expect(S.count_total - S.count_only_a).toBe(S.count_b_items);
    expect(S.count_a_items).toBe(1275);
    expect(S.count_b_items).toBe(1261);
    expect(sum(ch.map((c) => c.count))).toBe(1284);
  });

  it('单方造价 1,641.42 / 1,592.67 元/m²（建筑面积 18,600.00）', () => {
    expect(round2(S.a_total / 18600)).toBe(1641.42);
    expect(round2(S.b_total / 18600)).toBe(1592.67);
  });

  it('钢筋行、有梁板、构造柱的量价额与差额', () => {
    const [steel, scaffold, slab, col] = RECONCILE.rows;
    expect(round2(steel!.submitted_qty * steel!.submitted_price)).toBe(6084647.97);
    expect(round2(steel!.approved_qty * steel!.approved_price)).toBe(5781091.26);
    expect(round2((steel!.submitted_qty - steel!.approved_qty) * steel!.approved_price)).toBe(303556.71);
    expect(cents(steel!.submitted_amount) - cents(steel!.approved_amount)).toBe(cents(steel!.diff));
    expect(round2(slab!.submitted_qty * slab!.submitted_price)).toBe(1522640.74);
    expect(round2(slab!.approved_qty * slab!.approved_price)).toBe(1465951.96);
    expect(round2((slab!.submitted_price - slab!.approved_price) * slab!.submitted_qty)).toBe(56688.78);
    expect(round2(col!.submitted_qty * col!.submitted_price)).toBe(59025.72);
    expect(cents(col!.submitted_amount) - cents(59025.72)).toBe(cents(2000));
    const dev = Math.abs(col!.submitted_amount - 59025.72) / col!.submitted_amount;
    expect(Math.round(dev * 10000) / 100).toBe(3.28);
    expect(dev).toBeGreaterThan(0.02);
    expect(2000).toBeGreaterThan(Math.max(1, round2(0.005 * 61025.72)));
    expect(round2(0.005 * 61025.72)).toBe(305.13);
    expect(round2(scaffold!.submitted_qty * scaffold!.submitted_price)).toBe(125120);
    expect(scaffold!.diff).toBeLessThanOrEqual(239531.25);
  });

  it('混凝土章余量 184,420.85 ≥ 0', () => {
    expect(cents(546666.34) - cents(303556.71) - cents(56688.78) - cents(2000)).toBe(cents(184420.85));
  });

  it('核减额构成（00 章 §8.2）：量差 + 价差 + 仅送审 − 仅审定 + 计算错误差额；量差 + 价差 ≠ 核减额', () => {
    expect(S.diff_by_qty).toBe(612418.27);
    expect(S.diff_by_price).toBe(147749.55);
    expect(cents(612418.27) + cents(147749.55) + cents(186342.5) - cents(41817.36) + cents(2000)).toBe(cents(906692.96));
    expect(cents(S.diff_by_qty) + cents(S.diff_by_price)).not.toBe(cents(S.adjust_amount));
  });
});

describe('§9 投控与原表片段', () => {
  it('290 = 2 + 1 + 1 + 286，重点 4', () => {
    const r = TK.byRule;
    expect(r.duplicate + r.zangu + r.self_check + r.big_amount).toBe(TK.total);
    expect(TK.total).toBe(290);
    expect(r.duplicate + r.zangu + r.self_check).toBe(TK.focusCount);
  });

  it('防火门 58.80 × 1,180.00 = 69,384.00；暂估价 58.80 × 860.00 = 50,568.00', () => {
    expect(round2(58.8 * 1180)).toBe(69384);
    expect(round2(58.8 * 860)).toBe(50568);
  });

  it('原表片段每行 工程量 × 综合单价 = 合价（构造柱第 374 行即“行内自洽”异常本身，合价偏差 2,000.00）', () => {
    const num = (s: string) => Number(s.replace(/,/g, ''));
    for (const a of TK.focus)
      for (const row of a.source.rows) {
        const product = round2(num(row.qty) * num(row.price));
        if (a.type === 'self_check' && row.row === a.row) expect(cents(num(row.amount)) - cents(product)).toBe(cents(2000));
        else expect(product).toBe(num(row.amount));
      }
  });

  it('anomaly_id = uuid5(NAMESPACE_URL, "tk2|2026-007|资料/4 结算资料/送审计价表.xlsx|<表>|<行>")', () => {
    const ns = Buffer.from('6ba7b8109dad11d180b400c04fd430c8', 'hex');
    const uuid5 = (name: string) => {
      const h = createHash('sha1').update(Buffer.concat([ns, Buffer.from(name, 'utf8')])).digest();
      h[6] = (h[6]! & 0x0f) | 0x50;
      h[8] = (h[8]! & 0x3f) | 0x80;
      const x = h.subarray(0, 16).toString('hex');
      return `${x.slice(0, 8)}-${x.slice(8, 12)}-${x.slice(12, 16)}-${x.slice(16, 20)}-${x.slice(20)}`;
    };
    for (const a of TK.focus)
      expect(a.anomaly_id).toBe(uuid5(`tk2|2026-007|资料/4 结算资料/送审计价表.xlsx|${a.sheet}|${a.row}`));
  });
});

describe('§9 CAD 房间与出图', () => {
  it('房间几何面积 = 多段线矩形宽 × 高 × 0.01 m²，差异% 两位小数', () => {
    for (const r of CAD.rooms.rows) {
      const poly = ROOMS.find((x) => x.label === r.label)!;
      const [x1, y1, x2, y2] = poly.rect;
      expect(round2((x2 - x1) * (y2 - y1) * 0.01)).toBe(r.geom_m2);
      if (r.text_m2 !== null) expect(round2((Math.abs(r.geom_m2 - r.text_m2) / r.text_m2) * 100)).toBe(r.diff_pct);
    }
    expect(round2(84 * 87 * 0.01)).toBe(73.08);
    expect(round2(40 * 85.15 * 0.01)).toBe(34.06);
  });

  it('房间表按差异降序、无文字面积的排最后', () => {
    const diffs = CAD.rooms.rows.map((r) => r.diff_pct ?? -1);
    expect([...diffs].sort((a, b) => b - a)).toEqual(diffs);
    expect(CAD.rooms.rows.at(-1)!.text_m2).toBeNull();
    expect(CAD.rooms.rows.map((r) => r.label)).toEqual([
      '会议室201', '卫生间', '培训室', '资料室', '会议室202', '开放办公区', '楼梯间1', '设备间', '楼梯间2',
    ]);
  });

  it('总览图每单位像素 0.0181688，1600 × 1151；E4 0.138363，1600 × 1515，文字中位 48 px', () => {
    const s = (1600 - 72) / 84100;
    expect(Number(s.toFixed(7))).toBe(CAD.renders.S1.px_per_unit);
    expect(Math.round(84100 * s + 72)).toBe(1600);
    expect(Math.round(59400 * s + 72)).toBe(1151);
    const pad = 525.625;
    const w = 52562.5 - 42050 + 2 * pad;
    const h = 29700 - 19800 + 2 * pad;
    const e = 1600 / w;
    expect(w).toBe(11563.75);
    expect(Number(e.toFixed(6))).toBe(CAD.renders.E4.px_per_unit);
    expect(Math.round(h * e)).toBe(1515);
    expect(Math.round(350 * e)).toBe(48);
  });

  it('E4 viewBox 是 E 列第 4 行外扩 5%；总览留 36 px 网格边距', () => {
    const cw = 841 / 8;
    const rh = 594 / 6;
    const pad = cw * 0.05;
    expect(Number((4 * cw - pad).toFixed(2))).toBe(VIEW.E4.x);
    expect(Number((3 * rh - pad).toFixed(2))).toBe(VIEW.E4.y);
    expect(Number((cw + 2 * pad).toFixed(2))).toBe(VIEW.E4.w);
    expect(Number((rh + 2 * pad).toFixed(2))).toBeCloseTo(VIEW.E4.h, 1);
    expect(Number((36 / 0.0181688 / 100).toFixed(2))).toBe(-VIEW.S1.x);
  });
});

describe('AC-02-24 时刻表', () => {
  const decisions: HitlState[] = ['confirmed', 'dismissed', 'pending'];
  it.each(SCENES.map((s) => [s.id, s] as const))('%s：say 在下一个 say/ask/status 前结束，tool 在下一个 tool 前结束，最后一步 ≤ end', (_, scene) => {
    for (const d of decisions) expect(scheduleIssues(scene, d)).toEqual([]);
  });

  it('场景总长 17.80 / 21.35 / 21.05，一轮 60.20 s', () => {
    const totals = SCENES.map((s) => Number((s.end + s.hold).toFixed(2)));
    expect(totals).toEqual([17.8, 21.35, 21.05]);
    expect(Number(totals.reduce((a, b) => a + b, 0).toFixed(2))).toBe(60.2);
  });

  it('streamDuration：字数 ÷ 36 + 中文标点 × 0.12，mono 片段计 1 字', () => {
    expect(streamDuration(['疑似不是结论。先看第 1 条，请您判定：'])).toBeCloseTo(20 / 36 + 3 * 0.12, 6);
    expect(streamDuration([{ t: '906,692.96', mono: true }])).toBeCloseTo(1 / 36, 6);
  });
});

describe('AC-02-15 复核记录', () => {
  it('自动播放写入的一行与 §4.5 逐字一致', () => {
    const a = TK.focus[0]!;
    const line = reviewRecordLine(a, 'pending', 'confirmed', a.reasons.confirmed, TK.autoRecordTs);
    expect(line).toBe(
      '{"ts": "2026-10-19T06:42:18+00:00", "anomaly_id": "3eb1778e-6da3-574a-bbab-aa16b02411ff", "from_state": "pending", "hitl_state": "confirmed", "reason": "与第 28 行编码、名称、特征、工程量相同，重复列项", "reviewer": "张工", "anomaly": {"type": "duplicate", "anomaly_type": "重复计取", "item_code": "011701001001", "item_name": "综合脚手架", "source_file": "送审计价表.xlsx", "sheet": "施工技术措施项目清单与计价表", "row": 46, "line_amount": 125120.0, "excess_amount": null}}',
    );
  });

  it('非整数金额按 Python float 输出', () => {
    const a = TK.focus[3]!;
    expect(reviewRecordLine(a, 'pending', 'dismissed', 'x', 't')).toContain('"line_amount": 61025.72');
  });
});

describe('AC-02-25 文字版与 AC-02-29 文案', () => {
  const all = SCENES.map((s) => buildTranscript(s)).join('\n');

  it('文字版含三个用户原话、全部工具原名、全部回答段落', () => {
    for (const s of SCENES) {
      expect(all).toContain(s.prompt);
      for (const st of s.steps) {
        if (st.kind === 'tool') expect(all).toContain(pick(st.tool, 'confirmed').name);
        if (st.kind === 'say') expect(all).toContain(pick(st.segs, 'confirmed').map((x) => (typeof x === 'string' ? x : x.t)).join(''));
      }
    }
  });

  it('示例数据与首屏文案不含禁用说法与敏感字段', () => {
    const banned = ['自动算造价', 'AI 审定', '一键出报告', '行业标准阈值', '按客户确认', 'API Key', 'AK/SK'];
    const text = JSON.stringify({ SCENES, RECONCILE, TK, CAD, PRINCIPLES });
    for (const w of banned) expect(text).not.toContain(w);
    const noBubble = JSON.stringify({ ...SCENES.map((s) => ({ ...s, prompt: '', steps: s.steps.filter((x) => x.kind !== 'compose') })) });
    expect(noBubble).not.toContain('你');
    expect(JSON.stringify(HERO)).not.toContain('你');
  });

  it('formatMoney 负数用 U+2212', () => {
    expect(formatMoney(-32612.74)).toBe('−32,612.74');
  });
});
