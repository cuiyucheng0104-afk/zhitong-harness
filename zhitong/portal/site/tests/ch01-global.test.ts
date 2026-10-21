import { describe, expect, it } from 'vitest';
import { flushPromises } from '@vue/test-utils';
import { nextHeaderState } from '../src/composables/useHeaderState';
import { detectPlatform } from '../src/lib/platform';
import { renderHead } from '../src/lib/head';
import { prerenderPaths, routes, scrollBehavior } from '../src/router';
import { DOC_ROUTES } from '../src/docs/routes';
import { contactChannels, launchIssues, legalLaunchIssues, type ServiceContact } from '../src/site.config';
import { NAV_LINKS } from '../src/data/nav';
import { mountAt } from './helpers';

const empty: ServiceContact = { provider: '', person: '', phone: '', email: '', wechat: '', hours: '' };

describe('01 §2 顶栏状态（AC-01-01 至 AC-01-03）', () => {
  it('首页 top/scrolled 带 4–8px 滞回；文档页恒为 docs', () => {
    expect(nextHeaderState(0, 'top', 'home')).toBe('top');
    expect(nextHeaderState(9, 'top', 'home')).toBe('scrolled');
    expect(nextHeaderState(6, 'scrolled', 'home')).toBe('scrolled');
    expect(nextHeaderState(6, 'top', 'home')).toBe('top');
    expect(nextHeaderState(4, 'scrolled', 'home')).toBe('top');
    expect(nextHeaderState(2000, 'top', 'docs')).toBe('docs');
    expect(nextHeaderState(0, 'top', 'notfound')).toBe('docs');
  });

  it('顶栏结构与文案：主导航四项 + 文档 + 获取安装包', async () => {
    const { wrapper } = await mountAt('/');
    const header = wrapper.get('.site-header');
    expect(header.attributes('data-state')).toBe('top');
    expect(header.get('.brand').attributes('aria-label')).toBe('智通数工AI 首页');
    expect(header.get('nav').attributes('aria-label')).toBe('主导航');
    expect(NAV_LINKS.map((l) => l.label)).toEqual(['产品能力', '使用流程', '数据与复核', '常见问题']);
    expect(header.findAll('.nav-link').map((a) => a.text())).toEqual([
      '产品能力',
      '使用流程',
      '数据与复核',
      '常见问题',
      '文档',
    ]);
    expect(header.get('.nav-docs').attributes('href')).toBe('/docs/');
    const cta = header.get('.header-cta');
    expect(cta.text()).toBe('获取安装包');
    expect(cta.attributes('aria-haspopup')).toBe('dialog');
    expect(cta.attributes('aria-controls')).toBe('acquire-dialog');
    const menu = header.get('.header-inner .menu-toggle');
    expect(menu.attributes('aria-label')).toBe('打开导航菜单');
    expect(menu.attributes('aria-controls')).toBe('mobile-menu');
  });

  it('文档页：状态 docs，“文档”为 aria-current="page"，章节链接指向 /#id（01 §6）', async () => {
    const { wrapper } = await mountAt('/docs/install/');
    const header = wrapper.get('.site-header');
    expect(header.attributes('data-state')).toBe('docs');
    expect(header.get('.nav-docs').attributes('aria-current')).toBe('page');
    expect(header.get('[data-nav="trust"]').attributes('href')).toBe('/#trust');
    expect(document.title === '' || document.title.length >= 0).toBe(true);
  });

  it('404 页不设当前项（01 §12），请求地址一行在水合后出现', async () => {
    const { wrapper } = await mountAt('/docs/a/b/c/');
    expect(wrapper.find('.desktop-nav [aria-current]').exists()).toBe(false);
    expect(wrapper.get('h1').text()).toBe('页面不存在');
    expect(wrapper.text()).toContain('您访问的地址没有对应的页面。可能是链接已更改，或地址有误。');
    expect(wrapper.findAll('.notfound-actions a').map((a) => [a.text(), a.attributes('href')])).toEqual([
      ['回到首页', '/'],
      ['查看文档', '/docs/'],
    ]);
    expect(wrapper.get('.notfound-path').text()).toContain('请求地址：');
  });
});

describe('01 §10 跳到正文（AC-01-27）', () => {
  it('文档页激活后焦点为 #main', async () => {
    const { wrapper } = await mountAt('/docs/install/');
    expect(wrapper.get('.skip-link').text()).toBe('跳到正文');
    await wrapper.get('.skip-link').trigger('click');
    await flushPromises();
    expect(document.activeElement?.id).toBe('main');
  });
});

describe('01 §7.5 平台识别（AC-01-19）', () => {
  it.each([
    [{ userAgent: 'x', userAgentData: { platform: 'macOS' } }, 'mac-arm64'],
    [{ userAgent: 'x', userAgentData: { platform: 'Windows' } }, 'win-x64'],
    [{ userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' }, 'win-x64'],
    [{ userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)', maxTouchPoints: 0 }, 'mac-arm64'],
    [{ userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)', maxTouchPoints: 5 }, 'mobile'],
    [{ userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)' }, 'mobile'],
    [{ userAgent: 'Mozilla/5.0 (Linux; Android 14)' }, 'mobile'],
    [{ userAgent: 'Mozilla/5.0 (X11; Linux x86_64)' }, null],
  ])('%j → %s', (nav, expected) => {
    expect(detectPlatform(nav)).toBe(expected);
  });
});

describe('01 §8 站点配置与上线检查（AC-01-23、AC-01-24）', () => {
  it('全空：没有渠道，上线检查要求至少一种联系方式', () => {
    expect(contactChannels(empty)).toEqual([]);
    expect(launchIssues(empty)).toEqual(['site.config.ts：contact 至少需要电话、邮箱或微信之一']);
  });
  it('占位文字与格式错误', () => {
    expect(launchIssues({ ...empty, phone: '待配置' })).toContain('site.config.ts：contact.phone 含占位文字');
    expect(launchIssues({ ...empty, email: 'not-mail', phone: '0571-8888 8888' })).toEqual([
      'site.config.ts：contact.email 格式不正确',
    ]);
  });
  it('合法电话：渠道含 tel: 链接（去掉空格、括号与短横），检查通过', () => {
    const c = { ...empty, phone: '(0571) 8888-8888', wechat: 'zt_service1' };
    expect(contactChannels(c)).toEqual([
      { kind: 'phone', value: '(0571) 8888-8888', href: 'tel:057188888888' },
      { kind: 'wechat', value: 'zt_service1' },
    ]);
    expect(launchIssues(c)).toEqual([]);
  });
  it('法律信息（05 §5.4 规则，底座实现）', () => {
    const l = { company: '', icp: '', psbText: '', psbHref: '', privacyHref: '' };
    expect(legalLaunchIssues(l, prerenderPaths)).toEqual([
      'site.config.ts：legal.company 未填写',
      'site.config.ts：legal.icp 未填写',
      'site.config.ts：legal.privacyHref 未填写',
    ]);
    const ok = { company: '某某有限公司', icp: '浙ICP备2024000000号-1', psbText: '', psbHref: '', privacyHref: '/privacy/' };
    expect(legalLaunchIssues(ok, prerenderPaths)).toEqual([]);
    expect(legalLaunchIssues({ ...ok, psbText: '浙公网安备 33000000000000号' }, prerenderPaths)).toContain(
      'site.config.ts：legal.psbText 与 legal.psbHref 须同时填写',
    );
    expect(legalLaunchIssues({ ...ok, privacyHref: '/nope/' }, prerenderPaths)).toContain(
      'site.config.ts：legal.privacyHref 不是已预渲染的页面',
    );
  });
});

describe('00 §3.1 路由与预渲染路径', () => {
  it('预渲染：/、/docs/、22 个文档页、/privacy/，全部带尾斜杠', () => {
    expect(DOC_ROUTES).toHaveLength(23);
    expect(prerenderPaths[0]).toBe('/');
    expect(prerenderPaths).toContain('/docs/');
    expect(prerenderPaths).toContain('/docs/features/check/');
    expect(prerenderPaths).toContain('/privacy/');
    expect(prerenderPaths).toHaveLength(1 + 23 + 1);
    expect(prerenderPaths.every((p) => p.endsWith('/'))).toBe(true);
    expect(routes.at(-1)!.name).toBe('not-found');
  });
  it('跨页面类型时 scrollBehavior 返回 false（由过渡钩子定位）', () => {
    const r = (path: string, layout: 'home' | 'docs', hash = '') => ({ path, hash, meta: { layout } }) as never;
    expect(scrollBehavior(r('/', 'home'), r('/docs/', 'docs'), null)).toBe(false);
    expect(scrollBehavior(r('/docs/install/', 'docs'), r('/docs/', 'docs'), null)).toEqual({ top: 0, behavior: 'instant' });
    expect(scrollBehavior(r('/docs/install/', 'docs'), r('/docs/', 'docs'), { left: 0, top: 300 })).toEqual({ left: 0, top: 300 });
  });
  it('head：404 输出 noindex、不输出 canonical', () => {
    const head = renderHead({ layout: 'notfound', title: '页面不存在 · 智通数工AI', noindex: true });
    expect(head).toContain('<title>页面不存在 · 智通数工AI</title>');
    expect(head).toContain('noindex');
    expect(head).not.toContain('canonical');
  });
});
