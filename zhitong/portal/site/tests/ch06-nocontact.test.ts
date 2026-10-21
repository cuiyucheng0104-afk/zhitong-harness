/** 06 AC-06-24：没有可联系渠道（hasContact === false）时不渲染「内容有误或不清楚？」行。 */
import { mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../src/site.config', async (orig) => {
  const real = await orig<typeof import('../src/site.config')>();
  const contact = { provider: '', person: '', phone: '', email: '', wechat: '', hours: '' };
  return { ...real, siteConfig: { ...real.siteConfig, contact }, hasContact: false };
});

const DocsPage = (await import('../src/pages/docs/DocsPage.vue')).default;
const { docs } = await import('virtual:docs-manifest');

describe('06 AC-06-24 无联系方式', () => {
  it('不渲染联系行，也没有投票控件', () => {
    const w = mount(DocsPage, {
      props: { doc: docs.find((d) => d.slug === 'install')! },
      global: { stubs: { DocsPager: true, RouterLink: { template: '<a><slot /></a>' } } },
    });
    expect(w.find('.docs-feedback').exists()).toBe(false);
    expect(w.text()).not.toMatch(/有帮助|内容有误/);
  });
});
