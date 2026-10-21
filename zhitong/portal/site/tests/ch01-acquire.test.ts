import { mount, flushPromises } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseReleaseManifest, RELEASE_PLATFORMS } from '../src/data/release-manifest.mjs';
import { downloadRelease } from '../src/data/downloads';
import { COPY_FAILED } from '../src/composables/useCopy';
import { toastState, useToast } from '../src/composables/useToast';
import PlatformCard from '../src/components/acquire/PlatformCard.vue';
import ZtToast from '../src/components/ui/ZtToast.vue';

const HASH = 'c556880a0ab222582f907fe053106a481d029f9626473c127f39392a8bfd06fd';
const both = downloadRelease(
  parseReleaseManifest({
    schema: 1,
    product: '智通数工AI',
    version: '1.0.0',
    date: '2026-10-21',
    base: '0.2.1-rc.2',
    platforms: {
      'mac-arm64': { file: 'ztsgai-1.0.0-mac-arm64.dmg', sha256: HASH, size: 281694510 },
      'win-x64': { file: 'ztsgai-1.0.0-win-x64-setup.exe', sha256: HASH, size: 10 },
    },
  }),
);
const [mac, win] = both.platforms as [(typeof both.platforms)[0], (typeof both.platforms)[0]];

function stubClipboard(impl: (text: string) => Promise<void>) {
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn(impl) } });
  return (navigator.clipboard.writeText as ReturnType<typeof vi.fn>);
}

afterEach(() => {
  vi.useRealTimers();
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
});

describe('01 §7 获取安装包弹层', () => {
  async function mountDialog(nav?: { userAgent: string; maxTouchPoints?: number }) {
    if (nav) {
      vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(nav.userAgent);
      Object.defineProperty(navigator, 'maxTouchPoints', { configurable: true, value: nav.maxTouchPoints ?? 0 });
    }
    const { default: AcquireDialog } = await import('../src/components/AcquireDialog.vue');
    const w = mount(AcquireDialog, { props: { modelValue: false }, attachTo: document.body });
    await w.setProps({ modelValue: true });
    await flushPromises();
    return w;
  }

  it('AC-01-15：卡片数等于 RELEASE_PLATFORMS.length；文案与结构', async () => {
    const w = await mountDialog();
    expect(w.findAll('.platform-card')).toHaveLength(RELEASE_PLATFORMS.length);
    expect(w.get('h2').text()).toBe('获取安装包');
    expect(w.get('.dialog-close').attributes('aria-label')).toBe('关闭获取安装包');
    expect(w.text()).toContain('选择您的电脑');
    expect(w.text()).toContain('① 安装并打开');
    expect(w.get('dialog').attributes('aria-labelledby')).toBe('acquire-title');
    expect(w.find('a[href="/docs/config-package/"], routerlink').exists() || w.text().includes('读文档：导入配置包')).toBe(true);
    // site.config 的电话与邮箱按用户要求暂留空：联系区不渲染，且无占位字样。
    expect(w.text()).not.toContain('联系服务方');
    expect(w.text()).not.toContain('联系方式待配置');
    expect(w.find('[data-dialog-status]').exists()).toBe(true);
  });

  it('AC-01-19：Windows UA 时 Windows 卡排第一并带匹配标记；iPhone 显示手机提示且无匹配', async () => {
    const w = await mountDialog({ userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' });
    const cards = w.findAll('.platform-card');
    expect(cards[0]!.attributes('data-platform')).toBe('win-x64');
    expect(cards[0]!.text()).toContain('与您的电脑匹配');
    w.unmount();
    vi.restoreAllMocks();
    const m = await mountDialog({ userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)' });
    expect(m.find('.platform-match').exists()).toBe(false);
    expect(m.text()).toContain('您正在使用手机或平板。');
    const writeText = stubClipboard(async () => {});
    await m.get('.acquire-mobile-note button').trigger('click');
    await flushPromises();
    expect(writeText).toHaveBeenCalledWith(`${location.origin}/`);
    expect(toastState.message).toBe('已复制页面链接');
  });
});

describe('01 §7.4 平台卡片', () => {
  it('AC-01-16、AC-01-18：链接、文件名、大小、校验值与校验命令', () => {
    const w = mount(PlatformCard, { props: { item: mac, matched: false, base: null } });
    expect(w.get('a[download]').attributes('href')).toBe('/downloads/ztsgai-1.0.0-mac-arm64.dmg');
    expect(w.get('a[download]').text()).toContain('下载 Mac 版');
    expect(w.get('.platform-sha-file').attributes('href')).toBe('/downloads/ztsgai-1.0.0-mac-arm64.dmg.sha256');
    expect(w.get('.platform-hash-value').text().replace(/\s/g, '')).toBe(HASH);
    expect(w.findAll('.platform-hash-value > span')).toHaveLength(4);
    expect(w.get('.platform-command code').text()).toBe('shasum -a 256 ztsgai-1.0.0-mac-arm64.dmg');
    expect(w.text()).toContain('适用于 Apple 芯片的 Mac');
    expect(w.text()).toContain('欢迎窗口会请您填写模型 API Key');
    const v = mount(PlatformCard, { props: { item: win, matched: true, base: null } });
    expect(v.get('.platform-command code').text()).toBe('Get-FileHash .\\ztsgai-1.0.0-win-x64-setup.exe -Algorithm SHA256');
    expect(v.text()).toContain('比对时不区分大小写');
    expect(v.get('.platform-card-name').text()).toBe('Windows，与您的电脑匹配');
  });

  it('AC-01-21：base 为 null 时无程序版本一句，否则显示', () => {
    expect(mount(PlatformCard, { props: { item: mac, matched: false, base: null } }).text()).not.toContain('程序版本');
    expect(mount(PlatformCard, { props: { item: mac, matched: false, base: '0.2.1-rc.2' } }).text()).toContain(
      '安装后，“关于”中显示的程序版本为 0.2.1-rc.2。',
    );
  });

  it('AC-01-15：file 为 null 的平台无 <a download>，显示即将发布', () => {
    const upcoming = downloadRelease(
      parseReleaseManifest({ schema: 1, product: 'p', version: '1.0.0', date: null, platforms: {} }),
    ).platforms[0]!;
    const w = mount(PlatformCard, { props: { item: upcoming, matched: false, base: null } });
    expect(w.find('a').exists()).toBe(false);
    expect(w.text()).toContain('即将发布');
    expect(w.text()).toContain('该平台的安装包尚未发布。');
  });

  it('AC-01-20：点下载后 2.4s 内为“已开始下载”，并自动展开首次打开与校验', async () => {
    vi.useFakeTimers();
    const w = mount(PlatformCard, { props: { item: mac, matched: false, base: null }, attachTo: document.body });
    const link = w.get('a[download]');
    link.element.addEventListener('click', (e) => e.preventDefault());
    await link.trigger('click');
    expect(link.classes()).toContain('is-started');
    expect((w.get('details').element as HTMLDetailsElement).open).toBe(true);
    vi.advanceTimersByTime(2399);
    await w.vm.$nextTick();
    expect(link.classes()).toContain('is-started');
    vi.advanceTimersByTime(2);
    await w.vm.$nextTick();
    expect(link.classes()).not.toContain('is-started');
    w.unmount();
  });

  it('AC-01-17：复制校验值 → 剪贴板为 64 位小写十六进制，提示“已复制 SHA256 校验值”', async () => {
    const writeText = stubClipboard(async () => {});
    const w = mount(PlatformCard, { props: { item: mac, matched: false, base: null }, attachTo: document.body });
    await flushPromises(); // 复制按钮水合后才渲染（05 章 §3.6）
    await w.get('[aria-label="复制 SHA256 校验值"]').trigger('click');
    await flushPromises();
    expect(writeText).toHaveBeenCalledWith(HASH);
    expect(toastState.message).toBe('已复制 SHA256 校验值');
    expect(toastState.tone).toBe('ok');
    w.unmount();
  });

  it('AC-01-29：剪贴板与 execCommand 都失败时提示错误并选中哈希文本', async () => {
    stubClipboard(async () => {
      throw new Error('denied');
    });
    document.execCommand = vi.fn(() => false);
    const w = mount(PlatformCard, { props: { item: mac, matched: false, base: null }, attachTo: document.body });
    await flushPromises(); // 复制按钮水合后才渲染（05 章 §3.6）
    await w.get('[aria-label="复制 SHA256 校验值"]').trigger('click');
    await flushPromises();
    expect(toastState.message).toBe(COPY_FAILED);
    expect(toastState.tone).toBe('error');
    expect(toastState.duration).toBe(3200);
    expect(window.getSelection()?.toString().replace(/\s/g, '')).toBe(HASH);
    w.unmount();
  });
});

describe('01 §11 ZtToast 与朗读区', () => {
  it('提示写入最上层打开对话框内的朗读区；没有对话框时写入 #page-status', async () => {
    const page = document.createElement('div');
    page.id = 'page-status';
    document.body.append(page);
    const dialog = document.createElement('dialog');
    dialog.innerHTML = '<div data-dialog-status></div>';
    document.body.append(dialog);
    const toast = mount(ZtToast, { attachTo: document.body });
    useToast().show('已复制校验命令');
    await flushPromises();
    expect(page.textContent).toBe('已复制校验命令');
    dialog.setAttribute('open', '');
    useToast().show('已复制微信号');
    await flushPromises();
    expect(dialog.querySelector('[data-dialog-status]')!.textContent).toBe('已复制微信号');
    expect(toast.get('.zt-toast').attributes('aria-hidden')).toBe('true');
    expect(toast.text()).toContain('已复制微信号');
    toast.unmount();
    dialog.remove();
    page.remove();
  });
});
