/** 05 章 §5 页脚、§5.4 法律信息与上线检查、/privacy/ 页。 */
import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory } from 'vue-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, launchIssues, routes } from '../src/entry-server';
import {
  contactChannels,
  legalLaunchIssues,
  siteConfig,
  type LegalInfo,
  type ServiceContact,
} from '../src/site.config';
import { SUPPORT_CONTACT } from '../src/data/site';
import { prerenderPaths, createAppRouter } from '../src/router';
import { vMagnetic } from '../src/composables/useMagnetic';
import { vSpotlight } from '../src/composables/useSpotlight';
import { PRIVACY_BLOCKS } from '../src/components/sections05/privacy-policy';

afterEach(() => {
  vi.doUnmock('../src/site.config');
  vi.restoreAllMocks();
});

const EMPTY_CONTACT: ServiceContact = {
  provider: '',
  person: '',
  phone: '',
  email: '',
  wechat: '',
  hours: '',
};
const EMPTY_LEGAL: LegalInfo = { company: '', icp: '', psbText: '', psbHref: '', privacyHref: '' };

async function mountFooter(
  opts: {
    context?: 'home' | 'docs';
    contact?: Partial<ServiceContact>;
    legal?: Partial<LegalInfo>;
  } = {},
) {
  vi.resetModules();
  if (opts.contact || opts.legal) {
    vi.doMock('../src/site.config', async (importOriginal) => {
      const actual = await importOriginal<typeof import('../src/site.config')>();
      return {
        ...actual,
        siteConfig: {
          contact: { ...actual.siteConfig.contact, ...opts.contact },
          legal: { ...actual.siteConfig.legal, ...opts.legal },
        },
      };
    });
  }
  const { default: SiteFooter } = await import('../src/components/SiteFooter.vue');
  const { createAppRouter: make } = await import('../src/router');
  const router = make(createMemoryHistory());
  await router.push(opts.context === 'docs' ? '/docs/install/' : '/');
  const w = mount(SiteFooter, {
    props: { context: opts.context ?? 'home' },
    attachTo: document.body,
    global: { plugins: [router], directives: { magnetic: vMagnetic, spotlight: vSpotlight } },
  });
  await flushPromises();
  return w;
}

describe('05 §5 页脚', () => {
  it('AC-05-74：品牌一句话与说明行逐字一致（按用户意见删去“基于 DeepSeek Harness 构建”），页脚内没有 DeepSeek 字样与图形', async () => {
    const w = await mountFooter();
    expect(w.get('.footer-tagline').text()).toBe(
      '智通数工AI：把造价咨询里重复的读资料、算数、核对和归档，收进一次对话。',
    );
    expect(w.get('.footer-site').text()).toBe('官网：https://ztsgai.com');
    expect(w.get('.footer-note').text()).toBe(
      '页面中的项目、金额与文件均为示例数据',
    );
    expect(w.text()).not.toContain('DeepSeek');
    const imgs = w.findAll('img');
    expect(imgs).toHaveLength(1);
    expect(imgs[0]!.classes()).toContain('brand-mark');
    expect(w.html()).not.toMatch(/deepseek[^"]*\.(svg|png)/i);
    expect(w.get('.footer-acquire').text()).toBe('获取安装包');
  });

  it('AC-05-75：首页 8 个产品链接写 #<id> 并经 navigate 滚动；文档页写 /#<id>', async () => {
    const home = await mountFooter();
    const links = home.findAll('.footer-product a');
    expect(links.map((a) => [a.text(), a.attributes('href')])).toEqual([
      ['工作示例', '#demo'],
      ['适用岗位', '#roles'],
      ['它解决什么', '#problem'],
      ['产品能力', '#capabilities'],
      ['使用流程', '#workflow'],
      ['数据与复核', '#trust'],
      ['安装与交付', '#install'],
      ['常见问题', '#faq'],
    ]);
    await links[4]!.trigger('click');
    expect(home.emitted('navigate')).toEqual([['workflow']]);
    home.unmount();
    const docs = await mountFooter({ context: 'docs' });
    expect(docs.findAll('.footer-product a').map((a) => a.attributes('href'))).toEqual(
      ['demo', 'roles', 'problem', 'capabilities', 'workflow', 'trust', 'install', 'faq'].map(
        (id) => `/#${id}`,
      ),
    );
  });

  it('AC-05-76：文档栏 6 个链接都解析到预渲染页面或页内锚点', async () => {
    const w = await mountFooter();
    const links = w.findAll('.footer-docs a');
    expect(links.map((a) => a.text())).toEqual([
      '快速开始',
      '安装',
      '导入配置包',
      '12 项能力',
      '数据与安全',
      '常见问题与排错',
    ]);
    for (const a of links) {
      const [path] = decodeURIComponent(a.attributes('href')!).split('#');
      expect(prerenderPaths).toContain(path);
    }
    expect(decodeURIComponent(links[3]!.attributes('href')!)).toBe('/docs/#按任务找');
  });

  it('AC-05-77：没有可联系渠道时无“联系”栏、文档栏占 6 列；只填 email 时只有邮箱且为 mailto:', async () => {
    const none = await mountFooter({ contact: EMPTY_CONTACT });
    expect(none.find('.footer-contact').exists()).toBe(false);
    expect(none.classes()).not.toContain('has-contact');
    none.unmount();
    const mail = await mountFooter({ contact: { ...EMPTY_CONTACT, email: 'service@example.com' } });
    const col = mail.get('section.footer-contact');
    expect(col.attributes('aria-label')).toBe('联系');
    expect(col.findAll('dt').map((d) => d.text())).toEqual(['邮箱']);
    expect(col.get('a').attributes('href')).toBe('mailto:service@example.com');
    expect(col.get('a').text()).toBe('service@example.com');
    expect(mail.classes()).toContain('has-contact');
  });

  it('AC-05-78：填写 icp 时链接到工信部备案系统、新窗口打开；legal 为空串时法律行不出现该项也没有占位文字', async () => {
    const filled = await mountFooter({
      legal: {
        company: '某某有限公司',
        icp: '浙ICP备2024000000号-1',
        psbText: '浙公网安备 33000000000000号',
        psbHref: 'https://beian.mps.gov.cn/#/query/webSearch?code=33000000000000',
        privacyHref: '/privacy/',
      },
    });
    const icp = filled.get('.footer-legal a[href="https://beian.miit.gov.cn/"]');
    expect(icp.attributes('target')).toBe('_blank');
    expect(icp.attributes('rel')).toBe('noopener noreferrer');
    expect(icp.text()).toBe('浙ICP备2024000000号-1（在新窗口打开）');
    expect(filled.get('.footer-legal').text()).toContain(
      `© ${new Date().getFullYear()} 某某有限公司`,
    );
    expect(filled.get('.footer-legal a[href="/privacy/"]').text()).toBe('隐私说明');
    filled.unmount();
    const empty = await mountFooter({ legal: EMPTY_LEGAL });
    expect(empty.get('.footer-legal').text()).toBe('');
    expect(empty.text()).not.toMatch(/待配置|待填|ICP|备案/);
  });

  it('AC-05-79：legalLaunchIssues 的规则与文字；当前配置下 ICP 备案号缺失会阻断上线', () => {
    expect(legalLaunchIssues(EMPTY_LEGAL, routes)).toEqual([
      'site.config.ts：legal.company 未填写',
      'site.config.ts：legal.icp 未填写',
      'site.config.ts：legal.privacyHref 未填写',
    ]);
    const ok: LegalInfo = {
      company: '某某有限公司',
      icp: '浙ICP备2024000000号-1',
      psbText: '',
      psbHref: '',
      privacyHref: '/privacy/',
    };
    expect(legalLaunchIssues(ok, routes)).toEqual([]);
    expect(legalLaunchIssues({ ...ok, privacyHref: '/nope/' }, routes)).toEqual([
      'site.config.ts：legal.privacyHref 不是已预渲染的页面',
    ]);
    expect(legalLaunchIssues({ ...ok, psbText: '浙公网安备 1号' }, routes)).toEqual([
      'site.config.ts：legal.psbText 与 legal.psbHref 须同时填写',
    ]);
    expect(legalLaunchIssues({ ...ok, icp: 'TODO' }, routes)).toEqual([
      'site.config.ts：legal.icp 含占位文字',
    ]);
    expect(launchIssues()).toEqual(['site.config.ts：contact 至少需要电话、邮箱或微信之一']);
  });

  it('AC-05-80：SUPPORT_CONTACT 等于 contactChannels(siteConfig.contact)[0]', () => {
    expect(SUPPORT_CONTACT).toEqual(contactChannels(siteConfig.contact)[0] ?? null);
    expect(contactChannels(EMPTY_CONTACT)[0] ?? null).toBeNull();
  });

  it('AC-05-81 / §5.6：无 JS 时回到顶部是 <a href="#main">；水合后为按钮，点击后焦点在 #main（减少动效立即完成）', async () => {
    const { html } = await render('/');
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const top = doc.querySelector('.site-footer .footer-top')!;
    expect(top.tagName).toBe('A');
    expect(top.getAttribute('href')).toBe('#main');
    const main = document.createElement('main');
    main.id = 'main';
    main.tabIndex = -1;
    document.body.prepend(main);
    const w = await mountFooter();
    const btn = w.get('button.footer-top');
    expect(btn.attributes('aria-label')).toBe('回到页面顶部');
    await btn.trigger('click');
    await flushPromises();
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'instant' });
    expect(document.activeElement).toBe(main);
    main.remove();
  });

  it('§5.7：三栏为 nav（产品、文档）与 section（联系）；法律行为 p；页脚末行有 DecoFooterMark', async () => {
    const w = await mountFooter({ contact: { ...EMPTY_CONTACT, phone: '0571-0000 0000' } });
    expect(w.findAll('nav').map((n) => n.attributes('aria-label'))).toEqual(['产品', '文档']);
    expect(w.get('.footer-contact a').attributes('href')).toBe('tel:057100000000');
    expect(w.get('.footer-legal').element.tagName).toBe('P');
    expect(w.get('.footer-deco-row .deco-footer').attributes('aria-hidden')).toBe('true');
  });
});

describe('§15.4 上线信息与 /privacy/', () => {
  it('site.config.ts：公司主体与隐私说明路径已填；ICP 已填；电话、邮箱与公安备案留空', () => {
    expect(siteConfig.legal.company).toBe('杭州智通数工科技有限公司');
    expect(siteConfig.legal.privacyHref).toBe('/privacy/');
    expect(siteConfig.legal.icp).toBe('浙ICP备2026074211号');
    expect(siteConfig.legal.psbText).toBe('');
    expect(contactChannels(siteConfig.contact)).toEqual([]);
    expect(routes).toContain(siteConfig.legal.privacyHref);
  });

  it('/privacy/ 预渲染：<main id="main">、隐私政策正文与联系方式', async () => {
    const { html, status, layout } = await render('/privacy/');
    expect(status).toBe(200);
    expect(layout).toBe('docs');
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const main = doc.querySelector('main#main.privacy-page')!;
    expect(main.getAttribute('tabindex')).toBe('-1');
    expect(main.querySelector('h1')?.textContent).toBe('隐私说明');
    expect(main.textContent).toContain('我们：杭州智通数工科技有限公司。');
    expect(main.textContent).not.toMatch(/亿渡|18201566868|cuiyucheng0104|客服热线/);
    expect(main.querySelectorAll('h2').length).toBe(
      PRIVACY_BLOCKS.filter((b) => b.kind === 'h2').length,
    );
    expect(main.textContent).toContain('九、如何联系我们');
  });

  it('隐私说明未填写时页脚不显示该链接', async () => {
    const w = await mountFooter({ legal: { privacyHref: '' } });
    expect(w.find('.footer-legal a[href="/privacy/"]').exists()).toBe(false);
  });
});

// 保证路由工厂被使用（mountFooter 里 resetModules 后重新导入）。
void createAppRouter;
