/**
 * 02 章组件：首屏（AC-02-01、AC-02-02 的预渲染部分）、工作示例终态与交互（AC-02-10、12、13、15、16、19、20、25、26、27、29）、
 * 提问卡分支（AC-02-17）、平面图（AC-02-18）、原则条。
 * 测试环境为“减少动效”（tests/setup.ts），示例不自动播放，三个场景均为终态。
 */
import { createSSRApp, nextTick } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import HeroSection from '../src/components/HeroSection.vue';
import WorkDemo from '../src/components/WorkDemo.vue';
import PrinciplesStrip from '../src/components/PrinciplesStrip.vue';
import CadDrawing from '../src/components/demo/CadDrawing.vue';
import DemoAskCard from '../src/components/demo/DemoAskCard.vue';
import { SCENES, TK, reviewRecordLine } from '../src/data/demo';
import { compileScene } from '../src/components/demo/engine';
import { currentPrinciple } from '../src/components/demo/bus';
import { vMagnetic } from '../src/composables/useMagnetic';
import { mountAt } from './helpers';

let status: HTMLElement;
beforeEach(() => {
  status = document.createElement('div');
  status.id = 'page-status';
  document.body.append(status);
});
afterEach(() => {
  status.remove();
  currentPrinciple.value = null;
});

const tick = async () => {
  await flushPromises();
  await nextTick();
};

describe('首屏文案区（§1）', () => {
  it('AC-02-01 预渲染 h1 去标签后为“造价咨询公司的对话式工作台”，每个字是 span.ch 且带 --i', async () => {
    const html = await renderToString(createSSRApp(HeroSection).directive('magnetic', vMagnetic));
    const doc = new DOMParser().parseFromString(`<div>${html}</div>`, 'text/html');
    const h1 = doc.querySelector('h1#hero-title')!;
    expect(h1.textContent!.replace(/\s/g, '')).toBe('造价咨询公司的对话式工作台');
    const chars = [...h1.querySelectorAll('span.ch')];
    expect(chars).toHaveLength(13);
    chars.forEach((c, i) => expect(c.getAttribute('style')).toContain(`--i:${i}`));
    expect(h1.querySelector('svg.hero-dimline path')?.getAttribute('pathLength')).toBe('100');
  });

  it('文案逐字、次按钮 aria、配置包说明卡', async () => {
    const { wrapper } = await mountAt('/', HeroSection);
    const text = wrapper.text();
    expect(text).toContain('为造价咨询团队而做');
    expect(text).toContain(
      '在工程师自己的电脑上，用对话完成开项目、核对、指标、投控、清单、概算、报告和看图。',
    );
    expect(text).not.toContain('资料留在公司自己的火山引擎对象存储');
    expect(wrapper.get('.hero-primary').text()).toBe('获取安装包');
    const watch = wrapper.get('.hero-watch');
    expect(watch.text()).toBe('看它怎么工作');
    expect(watch.attributes('aria-label')).toBe('看它怎么工作：从第 1 个场景播放工作示例');
    expect(watch.attributes('aria-controls')).toBe('demo');
    expect(text).toContain('支持 Mac 与 Windows');
    expect(text).toContain('配置包由服务方交付');
    const term = wrapper.get('button.term');
    expect(term.text()).toBe('配置包');
    await term.trigger('click');
    const pop = document.getElementById('hero-config-popover')!;
    expect(pop.textContent).toContain(
      '一个压缩文件，由服务方按贵司环境整理并交付，内含对象存储地址、区域、桶名、目录前缀、访问密钥和公司名；不随安装包分发。',
    );
    expect(pop.textContent).toContain('向服务方获取。');
    expect(pop.textContent).toContain('导入后即可列出公司桶里的项目。');
  });

  it('主按钮发出 acquire', async () => {
    const { wrapper } = await mountAt('/', HeroSection);
    await wrapper.get('.hero-primary').trigger('click');
    expect(wrapper.emitted('acquire')).toHaveLength(1);
  });
});

describe('工作示例（§2–§6）', () => {
  async function mountDemo() {
    const { wrapper } = await mountAt('/', WorkDemo);
    await tick();
    return wrapper;
  }

  it('AC-02-27 / 10 终态：场景 1 可见，含核减额与需人工确认；减少动效显示“播放演示”', async () => {
    const w = await mountDemo();
    const scene = w.get('#scene-check');
    expect(scene.attributes('hidden')).toBeUndefined();
    expect(w.get('#scene-review').attributes('hidden')).toBeDefined();
    expect(scene.text()).toContain('906,692.96');
    expect(scene.text()).toContain('需人工确认');
    expect(w.get('.demo-toggle').text()).toBe('播放演示');
    expect(w.get('.demo-toggle').attributes('aria-label')).toBe('播放演示');
    expect(w.get('.workbench').attributes('data-state')).toBe('reduced');
    expect(w.findAll('.demo-hotspot.is-pulsing')).toHaveLength(0);
  });

  it('窗口外壳文案（§2.2）', async () => {
    const w = await mountDemo();
    const text = w.text();
    for (const s of [
      '从一句话，到一份有出处的结果',
      '2026-007-某综合办公楼',
      '示例项目',
    ])
      expect(text).toContain(s);
    for (const s of ['交互示意 · 示例数据 · 已加速播放', '文字版：三个示例的完整过程']) expect(text).not.toContain(s);
    expect(w.find('.demo-footnote').exists()).toBe(false);
    expect(w.get('[role="tablist"]').attributes('aria-label')).toBe('工作示例场景');
    expect(w.findAll('.scenario-tab').map((t) => t.text())).toEqual(['计价表核对', '投控复核', 'CAD 看图']);
    expect(w.get('#demo').attributes('aria-roledescription')).toBe('轮播');
    expect(w.get('.replay-button').attributes('aria-label')).toBe('从头重播当前场景');
    expect(w.get('[data-hotspot-target="reduction"]').attributes('title')).toBe('点金额，看出处');
    expect(w.get('[data-hotspot-target="sheet-tabs"]').attributes('title')).toBe('切换工作表');
  });

  it('AC-02-12 场景一展开后工具条顺序、对勾与耗时、结果行逐字', async () => {
    const w = await mountDemo();
    const scene = w.get('#scene-check');
    await scene.get('.chat-collapsed').trigger('click');
    const tools = scene.findAll('.chat-tool');
    expect(tools.map((t) => t.attributes('data-tool'))).toEqual([
      'read', 'tos_pull', 'probe.py probe', 'reconcile.py run', 'python', 'write', 'tos_push',
    ]);
    const spec = compileScene(SCENES[0]!).tools;
    tools.forEach((t, i) => {
      expect(t.find('.zt-tool-check').exists()).toBe(true);
      expect(t.get('.zt-tool-elapsed').text()).toBe(spec[i]!.spec.elapsed);
      expect(t.get('.zt-tool-detail').text()).toBe(spec[i]!.spec.detail);
    });
    expect(tools[1]!.text()).toContain('×2');
    expect(tools[6]!.text()).toContain('×3');
  });

  it('AC-02-13 场景二、三工具原名；提问卡标注 ask_user_question；AC-02-25 手动切换朗读', async () => {
    const w = await mountDemo();
    await w.get('#tab-review').trigger('click');
    await tick();
    expect(w.get('#scene-review').attributes('hidden')).toBeUndefined();
    await new Promise((r) => queueMicrotask(() => r(null)));
    expect(status.textContent).toBe('已切换到：投控复核');
    const review = w.get('#scene-review');
    await review.get('.chat-collapsed').trigger('click');
    expect(review.findAll('.chat-tool').map((t) => t.attributes('data-tool'))).toEqual([
      'read', 'tos_pull', 'tk.py detect', 'tk.py review', 'write',
    ]);
    expect(review.get('.ask-card').text()).toContain('ask_user_question');
    await w.get('#tab-cad').trigger('click');
    await tick();
    const cad = w.get('#scene-cad');
    await cad.get('.chat-collapsed').trigger('click');
    expect(cad.findAll('.chat-tool').map((t) => t.attributes('data-tool'))).toEqual([
      'tos_pull', 'cad_open', 'cad_set_unit', 'cad_frames', 'cad_rooms', 'cad_render', 'read_image', 'cad_render', 'read_image', 'write',
    ]);
  });

  it('AC-02-15 场景二终态：复核记录 1 行逐字一致，A1 已确认', async () => {
    const w = await mountDemo();
    await w.get('#tab-review').trigger('click');
    await tick();
    const lines = w.findAll('#review-records li');
    expect(lines).toHaveLength(1);
    const a = TK.focus[0]!;
    expect(lines[0]!.text()).toBe(reviewRecordLine(a, 'pending', 'confirmed', a.reasons.confirmed, TK.autoRecordTs));
    expect(w.get('[data-anomaly-index="0"] .state-pill').text()).toBe('已确认');
    expect(w.get('.review-drawer').text()).toContain('复核.jsonl · 1 条');
    expect(w.text()).toContain('演示记录，仅当前页面有效 · 最终决定由您作出');
  });

  it('AC-02-16 A3 判为误报再重新选择：新增 2 行，已有行不变', async () => {
    const w = await mountDemo();
    await w.get('#tab-review').trigger('click');
    await tick();
    const before = w.get('#review-records li').text();
    await w.get('[data-decide="2-dismissed"]').trigger('click');
    await w.get('[data-decide="2-pending"]').trigger('click');
    const lines = w.findAll('#review-records li').map((l) => l.text());
    expect(lines).toHaveLength(3);
    expect(lines[0]).toBe(before);
    const r1 = JSON.parse(lines[1]!);
    const r2 = JSON.parse(lines[2]!);
    expect([r1.from_state, r1.hitl_state, r1.reason]).toEqual(['pending', 'dismissed', '已有认价单，暂估价列为原样保留']);
    expect([r2.from_state, r2.hitl_state, r2.reason]).toEqual(['dismissed', 'pending', '撤回，重新复核']);
    expect(r1.anomaly_id).toBe('a51f3df4-c86f-5e98-9711-3039efd1d0dd');
    expect(r1.reviewer).toBe('张工');
    expect(r1.ts).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$/);
  });

  it('AC-02-19 房间表顺序；点“开放办公区”切回总览并选中；放大时点“会议室201”保持 E4', async () => {
    const w = await mountDemo();
    await w.get('#tab-cad').trigger('click');
    await tick();
    const cad = w.get('#scene-cad');
    expect(cad.findAll('[data-room-row]').map((r) => r.attributes('data-room-row'))).toEqual([
      '会议室201', '卫生间', '培训室', '资料室', '会议室202', '开放办公区', '楼梯间1', '设备间', '楼梯间2',
    ]);
    expect(cad.get('.cad-preview').attributes('data-view')).toBe('E4');
    await cad.get('[data-room-row="会议室201"] .room-button').trigger('click');
    expect(cad.get('.cad-preview').attributes('data-view')).toBe('E4');
    await cad.get('[data-room-row="开放办公区"] .room-button').trigger('click');
    expect(cad.get('.cad-preview').attributes('data-view')).toBe('S1');
    expect(cad.get('rect[data-room="开放办公区"]').classes()).toContain('is-selected');
    expect(cad.get('.preview-path-aside').text()).toBe('开放办公区 · T15 · 多段线 2A4B');
    expect(cad.get('[data-room-row="会议室201"]').classes()).toContain('is-warn');
    expect(cad.get('[data-room-row="会议室201"]').text()).toContain('需核对');
  });

  it('AC-02-20 出处弹层：文案逐字，Esc 关闭后焦点回到核减额按钮', async () => {
    const w = await mountDemo();
    const amount = w.get('#scene-check [data-source-amount]');
    expect(amount.attributes('aria-label')).toBe('核减额 906,692.96 元，查看出处');
    await amount.trigger('click');
    await tick();
    const dialog = document.getElementById('source-dialog') as HTMLDialogElement;
    expect(dialog.open).toBe(true);
    const text = dialog.textContent!.replace(/\s+/g, ' ');
    for (const s of [
      '出处 · 示例数据',
      '核减额从哪里来',
      '906,692.96 元',
      '核减率 2.97%',
      '核减额 = 送审合计 − 审定合计',
      '30,530,406.80 − 29,623,713.84 = 906,692.96',
      '核减率 = 906,692.96 ÷ 30,530,406.80 ≈ 2.97%（脚本字段 adjust_rate = 0.0297）',
      '两份计价表',
      '送审计价表.xlsx · 资料/4 结算资料/ · 送审合计 30,530,406.80',
      '计入 2 张表：分部分项工程清单与计价表、施工技术措施项目清单与计价表 · 清单行 1,275 · 按标题跳过 7 张',
      '审定计价表.xlsx · 资料/4 结算资料/ · 审定合计 29,623,713.84',
      '清单行 1,261',
      '逐行对上 1,284 行',
      '一致 1,031 · 调整 214 · 仅送审 23 · 仅审定 9 · 待核实 7',
      '量差 612,418.27',
      '价差 147,749.55',
      '量差 =（送审量 − 审定量）× 审定单价；价差 =（送审单价 − 审定单价）× 送审量。只统计两侧量、价都取到的匹配行。',
      '核减最大的 3 行',
      '现浇构件钢筋 010515001002',
      '分部分项 · 第 768 行',
      '分部分项 · 第 761 行',
      '303,556.71',
      '技术措施 · 第 46 行',
      '—（仅送审）',
      '有梁板 010505001001',
      '56,688.78',
      '位置取自 rows[].submitted_sheet / submitted_row 与 approved_sheet / approved_row。',
      '金额由 zt.reconcile 脚本从两张表取数计算，模型不做加减。',
      '需人工确认',
      '看逐行核对',
      '关闭',
    ])
      expect(text).toContain(s);
    expect(dialog.querySelector('[aria-label="关闭出处"]')).not.toBeNull();
    expect(dialog.querySelector('caption')?.textContent).toBe('核减最大的 3 行，金额单位元');
    expect(document.activeElement?.id).toBe('source-title');
    dialog.dispatchEvent(new Event('cancel', { cancelable: true }));
    await tick();
    expect(dialog.open).toBe(false);
    expect(document.activeElement).toBe(amount.element);
  });


  it('AC-02-26 可聚焦：页签方向键切换；核减额、工作表页签、暂停按钮是按钮', async () => {
    const w = await mountDemo();
    const tabs = w.get('[role="tablist"]');
    await w.get('#tab-check').trigger('keydown', { key: 'ArrowRight' });
    await tick();
    expect(w.get('#tab-review').attributes('aria-selected')).toBe('true');
    void tabs;
    for (const sel of ['#scene-check [data-source-amount]', '#scene-check .sheet-tab', '.demo-toggle'])
      expect(w.get(sel).element.tagName).toBe('BUTTON');
    // DOM 顺序：暂停按钮紧跟页签之后。
    expect(w.get('.scenario-tabs').element.nextElementSibling?.classList.contains('demo-toggle')).toBe(true);
  });

  it('AC-02-29 示例窗口与出处弹层文案检查', async () => {
    const w = await mountDemo();
    await w.get('#scene-check [data-source-amount]').trigger('click');
    await tick();
    const bench = w.get('.workbench').element.cloneNode(true) as HTMLElement;
    bench.querySelectorAll('.chat-bubble').forEach((b) => b.remove());
    const text = bench.textContent! + document.getElementById('source-dialog')!.textContent!;
    expect(text).not.toContain('你');
    for (const bad of ['自动算造价', 'AI 审定', '一键出报告', '行业标准阈值', '按客户确认', 'API Key', 'AK/SK', '桶名'])
      expect(text).not.toContain(bad);
    expect(text).toContain('需人工确认');
    expect(w.get('.titlebar-tag').text()).toBe('示例项目');
  });
});

describe('AC-02-17 提问卡手动选择', () => {
  it('选项为单选组，未选时提交禁用；选“判为误报”后预填示例理由并提交该分支', async () => {
    const ask = compileScene(SCENES[1]!).ask!;
    const w = mount(DemoAskCard, { props: { ask, t: 13.0, decision: 'confirmed', choice: null, instant: false } });
    expect(w.find('[role="radiogroup"]').exists()).toBe(true);
    expect(w.get('[data-ask-submit]').attributes('disabled')).toBeDefined();
    await w.get('[data-ask-option="dismissed"]').trigger('click');
    expect(w.emitted('choose')![0]).toEqual(['dismissed']);
    await w.setProps({ choice: 'dismissed' });
    expect(w.get('[data-ask-reason]').text()).toBe('经核对为不同部位，非重复');
    expect(w.text()).toContain('示例理由');
    await w.get('[data-ask-submit]').trigger('click');
    expect(w.emitted('submit')![0]).toEqual(['dismissed']);
    await w.setProps({ t: 15.5, decision: 'dismissed', choice: null });
    expect(w.text()).toContain('您的回答：判为误报 · 经核对为不同部位，非重复');
  });

  it('自动播放：13.9 s 选中确认异常，14.4 s 理由写入一半，15.4 s 收起', async () => {
    const ask = compileScene(SCENES[1]!).ask!;
    const w = mount(DemoAskCard, { props: { ask, t: 13.95, decision: 'confirmed', choice: null, instant: false } });
    expect(w.get('[data-ask-option="confirmed"]').attributes('aria-checked')).toBe('true');
    await w.setProps({ t: 14.4 });
    const half = w.get('[data-ask-reason]').text();
    expect(half.length).toBeGreaterThan(5);
    expect(half.length).toBeLessThan(ask.type!.text.length);
    await w.setProps({ t: 15.4 });
    expect(w.text()).toContain('您的回答：确认异常 · 与第 28 行编码、名称、特征、工程量相同，重复列项');
  });
});

describe('AC-02-18 平面图', () => {
  it('总览：7 条内部竖线、5 条内部横线，A–H 与 1–6；TXTROOM 以 rect 呈现', () => {
    const w = mount(CadDrawing, { props: { cues: compileScene(SCENES[2]!).cues, z: 0, room: null, pulse: 0 } });
    expect(w.get('svg.cad-svg').attributes('viewBox')).toBe('-19.81 -19.81 880.62 633.62');
    expect(w.findAll('[data-grid="v"]')).toHaveLength(7);
    expect(w.findAll('[data-grid="h"]')).toHaveLength(5);
    const labels = [...new Set(w.findAll('.cad-grid-label').map((l) => l.text()))];
    expect(labels).toEqual(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', '1', '2', '3', '4', '5', '6']);
    expect(w.findAll('rect[data-layer="TXTROOM"]')).toHaveLength(10);
    expect(w.findAll('text[data-layer="TXTROOM"]')).toHaveLength(0);
  });

  it('放大结束：viewBox 为 E4，TXTROOM 以 text 呈现', () => {
    const w = mount(CadDrawing, { props: { cues: compileScene(SCENES[2]!).cues, z: 1, room: null, pulse: 0 } });
    const vb = w.get('svg.cad-svg').attributes('viewBox')!.split(' ').map(Number);
    [415.24, 291.74, 115.64, 109.52].forEach((v, i) => expect(Math.abs(vb[i]! - v)).toBeLessThanOrEqual(0.01));
    expect(w.findAll('text[data-layer="TXTROOM"]')).toHaveLength(10);
    expect(w.findAll('rect[data-layer="TXTROOM"]')).toHaveLength(0);
  });

  it('图元：35 段墙（WALLS 共 35 段）、20 根柱、9 个房间多段线 + 2 个电梯井', () => {
    const w = mount(CadDrawing, { props: { cues: compileScene(SCENES[2]!).cues, z: 0, room: null, pulse: 0 } });
    const el = w.element as HTMLElement;
    expect(el.querySelectorAll('.cad-wall line')).toHaveLength(35);
    expect(el.querySelectorAll('.cad-column rect')).toHaveLength(20);
    expect(el.querySelectorAll('rect.cad-room')).toHaveLength(9);
    expect(el.querySelectorAll('.cad-evtr rect')).toHaveLength(2);
  });
});

describe('原则条（§7，说明卡改为内联、滚动入场）', () => {
  it('三项标题、区块 aria-label、点亮项 data-lit', async () => {
    const { wrapper } = await mountAt('/', PrinciplesStrip);
    expect(wrapper.get('#principles').attributes('aria-label')).toBe('工作原则');
    expect(wrapper.get('.principles-row').attributes('data-reveal')).toBe('stagger');
    const items = wrapper.findAll('h3.principle');
    expect(items.map((b) => b.text())).toEqual(['对话组织任务', '脚本完成计算', '人工复核结果']);
    expect(wrapper.findAll('h3[data-lit="true"]')).toHaveLength(0);
    currentPrinciple.value = 'script';
    await nextTick();
    expect(wrapper.get('h3[data-lit="true"]').text()).toBe('脚本完成计算');
    currentPrinciple.value = null;
  });

  it('说明直接可见：正文、需要什么 / 得到什么、看示例与读文档，不需要点击', async () => {
    const { wrapper } = await mountAt('/', PrinciplesStrip);
    expect(wrapper.find('[popover]').exists()).toBe(false);
    const card = wrapper.findAll('.principle-card')[2]!;
    expect(card.text()).toContain('金额与数量一律标注需人工确认；投控疑似由您逐条判定，决定追加记录，可追溯。');
    expect(card.text()).toContain('您的判断与理由');
    expect(card.text()).toContain('复核.jsonl 里的逐条决定');
    expect(card.text()).toContain('看示例');
    expect(card.get('a').attributes('href')).toBe('/docs/basics/');
  });
});
