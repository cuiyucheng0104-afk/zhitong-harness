/**
 * 03 章 §1 适用岗位：结构、页签、任务入口、说明卡（测试环境为减少动效：无钉住、无动画）。
 */
import { describe, expect, it } from 'vitest';
import { flushPromises } from '@vue/test-utils';
import RolesSection from '../src/components/RolesSection.vue';
import TaskPopoverBody from '../src/components/roles/TaskPopoverBody.vue';
import RoleArt from '../src/components/roles/RoleArt.vue';
import { ROLES, ROLE_TASKS } from '../src/data/roles';
import { loadMotion } from '../src/lib/motion';
import { mountAt } from './helpers';

const norm = (s: string) => s.replace(/\s+/g, '');

describe('03 §1 适用岗位', () => {
  it('标题区、页签与面板的角色与关联（§1.2、§1.7）', async () => {
    const { wrapper } = await mountAt('/', RolesSection);
    const section = wrapper.get('#roles');
    expect(section.attributes('aria-labelledby')).toBe('roles-title');
    expect(section.get('.eyebrow').text()).toBe('适用岗位');
    expect(section.get('#roles-title').html()).toContain('一个项目，<br>多人协同。');
    expect(section.get('.roles-heading > p:last-child').text()).toBe('从经手资料的人，到签发成果的人。');
    const list = section.get('[role="tablist"]');
    expect(list.attributes('aria-label')).toBe('选择岗位');
    const tabs = list.findAll('[role="tab"]');
    expect(tabs.map((t) => t.text())).toEqual(['造价工程师', '审核负责人', '公司管理者']);
    for (const r of ROLES) {
      const tab = section.get(`#role-tab-${r.id}`);
      expect(tab.attributes('aria-controls')).toBe(`role-panel-${r.id}`);
      expect(section.get(`#role-panel-${r.id}`).attributes('aria-labelledby')).toBe(`role-tab-${r.id}`);
      expect(section.get(`#role-panel-${r.id}`).attributes('role')).toBe('tabpanel');
    }
    expect(tabs[0]!.attributes('aria-selected')).toBe('true');
    expect(tabs[0]!.attributes('tabindex')).toBe('0');
    expect(tabs[1]!.attributes('tabindex')).toBe('-1');
  });

  it('水合后三个面板去掉 hidden，非当前面板 inert + 不可见（§1.3）', async () => {
    const { wrapper } = await mountAt('/', RolesSection);
    const panels = wrapper.findAll('.role-panel');
    expect(panels).toHaveLength(3);
    expect(wrapper.get('.role-panels').classes()).toContain('is-hydrated');
    for (const p of panels) expect(p.attributes('hidden')).toBeUndefined();
    expect(panels[0]!.attributes('inert')).toBeUndefined();
    expect(panels[0]!.classes()).toContain('is-shown');
    expect(panels[1]!.attributes('inert')).toBeDefined();
    expect(panels[1]!.classes()).not.toContain('is-shown');
  });

  it('AC-03-17：减少动效下点页签直接切换，aria-selected 与漫游 tabindex 同步；方向键 / Home / End', async () => {
    const { wrapper } = await mountAt('/', RolesSection);
    await wrapper.get('#role-tab-manager').trigger('click');
    await flushPromises();
    expect(wrapper.get('#role-tab-manager').attributes('aria-selected')).toBe('true');
    expect(wrapper.get('#role-tab-engineer').attributes('aria-selected')).toBe('false');
    expect(wrapper.get('#role-panel-manager').classes()).toContain('is-shown');
    expect(wrapper.get('#role-panel-engineer').attributes('inert')).toBeDefined();
    expect(wrapper.get('.role-art').attributes('data-active')).toBe('manager');
    await wrapper.get('#role-tab-manager').trigger('keydown', { key: 'Home' });
    await flushPromises();
    expect(wrapper.get('#role-tab-engineer').attributes('aria-selected')).toBe('true');
    await wrapper.get('#role-tab-engineer').trigger('keydown', { key: 'ArrowRight' });
    await flushPromises();
    expect(wrapper.get('#role-tab-reviewer').attributes('aria-selected')).toBe('true');
    expect(document.activeElement?.id).toBe('role-tab-reviewer');
    await wrapper.get('#role-tab-reviewer').trigger('keydown', { key: 'End' });
    await flushPromises();
    expect(wrapper.get('#role-tab-manager').attributes('aria-selected')).toBe('true');
  });

  it('AC-03-17：减少动效下不钉住、没有本区块的 ScrollTrigger', async () => {
    const { wrapper } = await mountAt('/', RolesSection);
    const motion = await loadMotion();
    await flushPromises();
    expect(wrapper.get('#roles').classes()).not.toContain('is-pinned');
    expect(document.documentElement.classList.contains('motion-ready')).toBe(false);
    if (motion) expect(motion.ScrollTrigger.getAll()).toHaveLength(0);
  });

  it('每个面板 4 个入口：链接到文档、序号可读、aria-haspopup / aria-controls（§1.5.5、§1.7）', async () => {
    const { wrapper } = await mountAt('/', RolesSection);
    for (const r of ROLES) {
      const chips = wrapper.findAll(`#role-panel-${r.id} .task-chip`);
      expect(chips).toHaveLength(4);
      chips.forEach((chip, i) => {
        const t = r.tasks[i]!;
        expect(chip.element.tagName).toBe('A');
        expect(chip.attributes('href')).toBe(`/docs/features/${t.capability}/`);
        expect(chip.attributes('aria-haspopup')).toBe('dialog');
        expect(chip.attributes('aria-expanded')).toBe('false');
        expect(chip.attributes('aria-controls')).toBe('role-task-popover');
        expect(norm(chip.text())).toBe(norm(`${t.no}${t.label}`));
        expect(chip.get('.task-chip__arrows').attributes('aria-hidden')).toBe('true');
      });
    }
  });

  it('AC-03-14：⌘ / Ctrl / Shift / 中键点击不拦截；普通点击拦截并打开说明卡', async () => {
    const { wrapper } = await mountAt('/', RolesSection);
    const chip = wrapper.get('[data-task="engineer-check"]');
    for (const init of [{ metaKey: true }, { ctrlKey: true }, { shiftKey: true }, { button: 1 }]) {
      const ev = new MouseEvent('click', { bubbles: true, cancelable: true, ...init });
      chip.element.dispatchEvent(ev);
      expect(ev.defaultPrevented).toBe(false);
    }
    await flushPromises();
    expect(wrapper.get('#role-task-popover').attributes('hidden')).toBeDefined();
    const ev = new MouseEvent('click', { bubbles: true, cancelable: true });
    chip.element.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
    await flushPromises();
    const pop = wrapper.get('#role-task-popover');
    expect(pop.attributes('hidden')).toBeUndefined();
    expect(pop.attributes('role')).toBe('dialog');
    expect(pop.attributes('aria-labelledby')).toBe('role-task-popover-title');
    expect(pop.get('#role-task-popover-title').text()).toBe('送审审定核对');
    expect(chip.attributes('aria-expanded')).toBe('true');
  });

  it('AC-03-15：打开另一个入口时只有一张说明卡，锚定新入口', async () => {
    const { wrapper } = await mountAt('/', RolesSection);
    await wrapper.get('[data-task="engineer-project"]').trigger('click');
    await flushPromises();
    expect(wrapper.get('#role-task-popover-title').text()).toBe('资料盘点');
    await wrapper.get('[data-task="engineer-report"]').trigger('click');
    await new Promise((r) => setTimeout(r, 200));
    await flushPromises();
    expect(wrapper.findAll('[role="dialog"]#role-task-popover')).toHaveLength(1);
    expect(wrapper.get('#role-task-popover-title').text()).toBe('报告撰写');
    expect(wrapper.get('[data-task="engineer-report"]').attributes('aria-expanded')).toBe('true');
    expect(wrapper.get('[data-task="engineer-project"]').attributes('aria-expanded')).toBe('false');
  });

  it('AC-03-11：Esc 关闭后焦点回到该入口', async () => {
    const { wrapper } = await mountAt('/', RolesSection);
    await wrapper.get('#role-tab-reviewer').trigger('click');
    const chip = wrapper.get('[data-task="reviewer-control"]');
    (chip.element as HTMLElement).focus();
    await chip.trigger('click');
    await flushPromises();
    expect(wrapper.get('#role-task-popover').attributes('hidden')).toBeUndefined();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await flushPromises();
    expect(wrapper.get('#role-task-popover').attributes('hidden')).toBeDefined();
    expect(document.activeElement).toBe(chip.element);
  });

  it('AC-03-12 / AC-03-13：看示例发出 scene 动作；看能力介绍发出 feature 动作；都先关闭说明卡', async () => {
    const { wrapper } = await mountAt('/', RolesSection);
    const section = wrapper.findComponent(RolesSection);
    await wrapper.get('#role-tab-reviewer').trigger('click');
    await wrapper.get('[data-task="reviewer-control"]').trigger('click');
    await flushPromises();
    const primary = wrapper.get('#role-task-popover .task-pop__actions .button-primary');
    expect(primary.text()).toBe('看示例');
    await primary.trigger('click');
    await flushPromises();
    expect(wrapper.get('#role-task-popover').attributes('hidden')).toBeDefined();
    await wrapper.get('#role-tab-engineer').trigger('click');
    await wrapper.get('[data-task="engineer-project"]').trigger('click');
    await flushPromises();
    const second = wrapper.get('#role-task-popover .task-pop__actions .button-primary');
    expect(second.text()).toBe('看能力介绍');
    await second.trigger('click');
    expect(section.emitted('action')).toEqual([[{ type: 'scene', id: 'review' }], [{ type: 'feature', id: 'project' }]]);
  });

  it('悬停入口时岗位图对应节点高亮（AC-03-10 的联动部分）', async () => {
    const { wrapper } = await mountAt('/', RolesSection);
    const chip = wrapper.get('[data-task="engineer-check"]');
    chip.element.dispatchEvent(new MouseEvent('pointerenter'));
    await flushPromises();
    expect(wrapper.get('[data-art="engineer"] [data-node="check"]').classes()).toContain('is-hot');
    chip.element.dispatchEvent(new MouseEvent('pointerleave'));
    await flushPromises();
    expect(wrapper.get('[data-art="engineer"] [data-node="check"]').classes()).not.toContain('is-hot');
  });
});

describe('03 §1.2 说明卡内容', () => {
  it('AC-03-09：12 张说明卡渲染的文字与数据逐字一致；无限定时不渲染限定行', async () => {
    for (const t of ROLE_TASKS) {
      const { wrapper } = await mountAt('/', TaskPopoverBody, { task: t });
      expect(wrapper.get('.task-pop__eyebrow').text()).toBe(t.eyebrow);
      expect(wrapper.get('.task-pop__summary').text()).toBe(t.summary);
      expect(wrapper.findAll('dt').map((d) => d.text())).toEqual(['需要什么', '得到什么']);
      expect(wrapper.findAll('dd').map((d) => d.text())).toEqual([t.needs, t.yields]);
      if (t.note) expect(wrapper.get('.task-pop__note').text()).toBe(t.note);
      else expect(wrapper.find('.task-pop__note').exists()).toBe(false);
      expect(wrapper.get('.button-primary').text()).toBe(t.primary.kind === 'scene' ? '看示例' : '看能力介绍');
      const docs = wrapper.get('.task-pop__docs');
      expect(docs.text()).toBe('读文档');
      expect(docs.attributes('href')).toBe(t.docs);
      wrapper.unmount();
    }
  });
});

describe('03 §1.4 岗位图', () => {
  it('viewBox 400×260，三组 data-art，12 个 data-node，标题栏图号', async () => {
    const { wrapper } = await mountAt('/', RoleArt, { active: 'reviewer', highlight: null });
    const svg = wrapper.get('svg');
    expect(svg.attributes('viewBox')).toBe('0 0 400 260');
    expect(svg.attributes('aria-hidden')).toBe('true');
    expect(wrapper.findAll('[data-art]').map((g) => g.attributes('data-art'))).toEqual(['engineer', 'reviewer', 'manager']);
    expect(wrapper.findAll('[data-art="reviewer"] [data-node]').map((g) => g.attributes('data-node'))).toEqual([
      'control',
      'metrics',
      'bills',
      'cad',
    ]);
    expect(wrapper.findAll('[data-node]')).toHaveLength(12);
    expect(norm(wrapper.get('[data-title="reviewer"]').text())).toBe('审核负责人R-02');
    expect((wrapper.get('[data-art="engineer"]').element as SVGElement).style.display).toBe('none');
  });
});
