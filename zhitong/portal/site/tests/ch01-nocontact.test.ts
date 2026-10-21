/** 01 AC-01-15 / AC-01-23（空配置）：联系方式全空时不渲染“联系服务方”，也没有任何占位字样。 */
import { flushPromises, mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../src/site.config', async (orig) => {
  const real = await orig<typeof import('../src/site.config')>();
  const contact = { provider: '', person: '', phone: '', email: '', wechat: '', hours: '' };
  return { ...real, siteConfig: { ...real.siteConfig, contact }, hasContact: false };
});

const { RELEASE_PLATFORMS } = await import('../src/data/release-manifest.mjs');
const { default: AcquireDialog } = await import('../src/components/AcquireDialog.vue');
const { render, launchIssues } = await import('../src/entry-server');

describe('01 联系方式全空', () => {
  it('AC-01-15：获取安装包弹层不渲染“联系服务方”区，也无占位字样', async () => {
    const w = mount(AcquireDialog, { props: { modelValue: false }, attachTo: document.body });
    await w.setProps({ modelValue: true });
    await flushPromises();
    expect(w.findAll('.platform-card')).toHaveLength(RELEASE_PLATFORMS.length);
    expect(w.text()).not.toContain('联系服务方');
    expect(w.text()).not.toContain('联系方式待配置');
    w.unmount();
  });

  it('AC-01-23：首页预渲染不输出“联系服务方”与占位字样；上线检查列出联系方式阻断项', async () => {
    const { html } = await render('/');
    expect(html).not.toContain('联系方式待配置');
    expect(html).not.toContain('联系服务方');
    expect(launchIssues()).toContain('site.config.ts：contact 至少需要电话、邮箱或微信之一');
  });
});
