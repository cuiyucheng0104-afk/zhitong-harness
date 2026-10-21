/** 06 章与外部数据的衔接：AC-06-17（ReleaseCurrent 的「即将发布」）、AC-06-24（有联系方式时显示第一个渠道）。 */
import { mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../src/data/downloads', async (orig) => {
  const real = await orig<typeof import('../src/data/downloads')>();
  const release = real.downloadRelease({
    schema: 1,
    product: '智通数工AI',
    version: '1.0.0',
    date: null,
    base: null,
    notes: [],
    platforms: {
      'mac-arm64': { file: 'ztsgai-1.0.0-mac-arm64.dmg', sha256: 'a'.repeat(64), size: 281694510, notes: null },
      'win-x64': { file: null, sha256: null, size: null, notes: '下周发布' },
    },
  } as Parameters<typeof real.downloadRelease>[0]);
  return { ...real, release };
});
vi.mock('../src/site.config', async (orig) => {
  const real = await orig<typeof import('../src/site.config')>();
  return { ...real, siteConfig: { ...real.siteConfig, contact: { ...real.siteConfig.contact, phone: '0571-8888 6666', email: 'a@b.cn' } } };
});

const ReleaseCurrent = (await import('../src/components/docs/ReleaseCurrent.vue')).default;
const DocsPage = (await import('../src/pages/docs/DocsPage.vue')).default;
const { docs } = await import('virtual:docs-manifest');

const stubs = { RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } };

describe('06 AC-06-17 当前版本卡片', () => {
  it('file 为 null 的平台显示「即将发布」且没有链接；有文件时下载 /downloads/{file}', () => {
    const w = mount(ReleaseCurrent, { global: { stubs } });
    expect(w.find('.release-date').text()).toBe('尚未发布');
    expect(w.find('.release-base').exists()).toBe(false);
    const [mac, win] = w.findAll('.release-platform');
    expect(win.text()).toContain('即将发布');
    expect(win.findAll('a')).toHaveLength(0);
    expect(win.find('.release-platform-notes').text()).toBe('下周发布');
    const links = mac.findAll('a');
    expect(links.map((a) => a.attributes('href'))).toEqual(['/downloads/ztsgai-1.0.0-mac-arm64.dmg', '/downloads/ztsgai-1.0.0-mac-arm64.dmg.sha256']);
    expect(links[0].attributes('download')).toBeDefined();
    expect(links[0].attributes('aria-label')).toBe('下载 Mac 安装包 ztsgai-1.0.0-mac-arm64.dmg，268.6 MB');
    expect(mac.find('.release-sha-value').text()).toBe('a'.repeat(64));
  });
});

describe('06 AC-06-24 联系行', () => {
  it('hasContact 为 true 时显示第一个渠道（电话为 tel: 链接）', () => {
    const doc = docs.find((d) => d.slug === 'install')!;
    const w = mount(DocsPage, { props: { doc }, global: { stubs: { ...stubs, DocsPager: true } } });
    const line = w.find('.docs-feedback');
    expect(line.text()).toBe('内容有误或不清楚？请联系服务方：0571-8888 6666');
    expect(line.find('a').attributes('href')).toBe('tel:057188886666');
  });
});
