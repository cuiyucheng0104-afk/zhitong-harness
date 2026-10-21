/** 05 章 §3 安装与交付：数据来源、平台卡、识别、复制、配置包、联系服务方、装饰插槽。 */
import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory } from 'vue-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseReleaseManifest } from '../src/data/release-manifest.mjs';
import { render } from '../src/entry-server';
import { vMagnetic } from '../src/composables/useMagnetic';
import { vSpotlight } from '../src/composables/useSpotlight';
import { createAppRouter } from '../src/router';

const HASH = 'c556880a0ab222582f907fe053106a481d029f9626473c127f39392a8bfd06fd';
const MAC = 'ztsgai-1.0.0-mac-arm64.dmg';
const WIN = 'ztsgai-1.0.0-win-x64-setup.exe';

function manifest(extra: Record<string, unknown> = {}, platforms?: Record<string, unknown>) {
  return {
    schema: 1,
    product: '智通数工AI',
    version: '1.0.0',
    date: '2026-10-21',
    platforms: platforms ?? {
      'mac-arm64': { file: MAC, sha256: HASH, size: 281694510 },
      'win-x64': { file: null, sha256: null, size: null },
    },
    ...extra,
  };
}

/** 与被测组件同一模块实例（mountInstall 里 resetModules 之后）。 */
const toast = async () => (await import('../src/composables/useToast')).toastState;

afterEach(() => {
  vi.doUnmock('../src/data/downloads');
  vi.doUnmock('../src/site.config');
  vi.restoreAllMocks();
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
  Object.defineProperty(navigator, 'maxTouchPoints', { configurable: true, value: 0 });
});

async function mountInstall(
  opts: { raw?: unknown; ua?: string; touch?: number; contact?: Record<string, string> } = {},
) {
  vi.resetModules();
  if (opts.ua) vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(opts.ua);
  if (opts.touch !== undefined)
    Object.defineProperty(navigator, 'maxTouchPoints', { configurable: true, value: opts.touch });
  const raw = opts.raw ?? manifest();
  vi.doMock('../src/data/downloads', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/data/downloads')>();
    return { ...actual, release: actual.downloadRelease(parseReleaseManifest(raw)) };
  });
  if (opts.contact) {
    const contact = opts.contact;
    vi.doMock('../src/site.config', async (importOriginal) => {
      const actual = await importOriginal<typeof import('../src/site.config')>();
      const c = {
        provider: '',
        person: '',
        phone: '',
        email: '',
        wechat: '',
        hours: '',
        ...contact,
      };
      return { ...actual, siteConfig: { ...actual.siteConfig, contact: c } };
    });
  }
  const { default: InstallSection } = await import('../src/components/InstallSection.vue');
  const router = createAppRouter(createMemoryHistory());
  await router.push('/');
  const w = mount(InstallSection, {
    attachTo: document.body,
    global: { plugins: [router], directives: { magnetic: vMagnetic, spotlight: vSpotlight } },
  });
  await flushPromises();
  return w;
}

describe('05 §3 安装与交付', () => {
  it('文案：眉标、标题、副标题、安装包、配置包、首次使用、文档链接', async () => {
    const w = await mountInstall();
    expect(w.get('.eyebrow').text()).toBe('安装与交付');
    expect(w.get('h2#install-title').text()).toBe('装好、导入、开始用');
    expect(w.get('.install-lead').text()).toBe('Mac 与 Windows 两个安装包，配置包由服务方交付。');
    expect(w.findAll('h3').map((h) => h.text())).toEqual([
      '安装包',
      '配置包',
      '首次使用',
      '联系服务方',
    ]);
    expect(w.text()).toContain(
      '提供 Mac（.dmg，Apple 芯片）和 Windows（.exe，x64）安装包。安装包内含 Python 运行时、脚本依赖库和 DWG 转换组件，无需另行安装 Python。',
    );
    expect(w.text()).toContain(
      '首次启动先在欢迎页填写模型 API Key（向贵司管理员或服务方获取，默认连接 DeepSeek 官方接口），再把配置包拖进对话，系统校验并写入本机配置，随后即可列出公司桶里的项目。本机只缓存用到的文件，目录与桶同构，缓存上限可配置，默认 20 GiB。',
    );
    expect(w.get('.install-help').attributes('href')).toBe('/docs/install/');
    expect(w.get('.install-help').text()).toBe('安装遇到问题？看安装说明');
    expect(w.get('.install-doc').attributes('href')).toBe('/docs/config-package/');
    expect(w.get('.install-doc').text()).toBe('读文档：导入配置包');
  });

  it('AC-05-41 / AC-05-53：版本、日期、文件名、大小、SHA256 来自清单；换清单页面随之变化；base 行按清单显示', async () => {
    const a = await mountInstall({ raw: manifest({ base: '0.2.1-rc.2' }) });
    expect(a.get('.install-version').text()).toBe('v1.0.0 · 2026-10-21 发布');
    expect(a.get('.install-base').text()).toBe('安装后，“关于”中显示的程序版本为 0.2.1-rc.2。');
    const mac = a.get('[data-platform="mac-arm64"]');
    expect(mac.text()).toContain(MAC);
    expect(mac.text()).toContain('268.6 MB');
    expect(mac.get('.platform-hash-value').text()).toBe(HASH);
    expect(a.get('ul.install-platforms').attributes('aria-label')).toBe('v1.0.0 安装包');
    a.unmount();
    const b = await mountInstall({
      raw: manifest(
        { version: '1.2.0', date: null },
        {
          'mac-arm64': { file: null, sha256: null, size: null },
          'win-x64': {
            file: 'ztsgai-1.2.0-win-x64-setup.exe',
            sha256: 'b'.repeat(64),
            size: 1048576,
          },
        },
      ),
    });
    expect(b.get('.install-version').text()).toBe('v1.2.0 · 发布日期待定');
    expect(b.find('.install-base').exists()).toBe(false);
    expect(b.get('[data-platform="win-x64"]').text()).toContain('ztsgai-1.2.0-win-x64-setup.exe');
    expect(b.get('[data-platform="win-x64"]').text()).toContain('1.0 MB');
  });

  it('AC-05-42：file 为 null 的平台是即将发布卡：没有 <a>、复制按钮与磁吸', async () => {
    const w = await mountInstall();
    const win = w.get('[data-platform="win-x64"]');
    expect(win.classes()).toContain('is-upcoming');
    expect(win.findAll('a')).toHaveLength(0);
    expect(win.findAll('button')).toHaveLength(0);
    expect(win.text()).toContain('即将发布');
    expect(win.text()).toContain('该平台的安装包尚未发布。');
  });

  it('AC-05-43：下载链接 /downloads/{file} 带 download；点击后“已开始下载”、展开首次打开与校验、#page-status 朗读', async () => {
    const status = document.createElement('div');
    status.id = 'page-status';
    document.body.append(status);
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    const w = await mountInstall();
    const link = w.get('[data-platform="mac-arm64"] a.platform-download');
    expect(link.attributes('href')).toBe(`/downloads/${MAC}`);
    expect(link.attributes()).toHaveProperty('download');
    link.element.addEventListener('click', (e) => e.preventDefault());
    await link.trigger('click');
    await Promise.resolve();
    expect(link.classes()).toContain('is-started');
    expect(link.text()).toContain('已开始下载');
    expect((w.get('[data-platform="mac-arm64"] details').element as HTMLDetailsElement).open).toBe(
      true,
    );
    expect(status.textContent).toBe(`已开始下载 ${MAC}`);
    vi.advanceTimersByTime(2400);
    await flushPromises();
    expect(link.classes()).not.toContain('is-started');
    vi.useRealTimers();
    status.remove();
  });

  it('AC-05-44 / AC-05-45：复制 SHA256 得 64 位小写十六进制；剪贴板被拒时选中文字并提示复制失败', async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const w = await mountInstall();
    await w.get('[data-platform="mac-arm64"] .platform-hash .platform-copy').trigger('click');
    await flushPromises();
    expect(writeText).toHaveBeenCalledWith(HASH);
    expect(HASH).toMatch(/^[0-9a-f]{64}$/);
    expect((await toast()).message).toBe('已复制 SHA256 校验值');
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn(async () => Promise.reject(new Error('denied'))) },
    });
    document.execCommand = vi.fn(() => false);
    await w.get('[data-platform="mac-arm64"] .platform-hash .platform-copy').trigger('click');
    await flushPromises();
    expect((await toast()).message).toBe('复制失败，请手动选择文本');
    expect(window.getSelection()?.toString().replace(/\s/g, '')).toBe(HASH);
  });

  it('AC-05-46 / AC-05-47：macOS 时 Mac 卡匹配、Windows 时 Windows 卡匹配；两卡顺序不变', async () => {
    const both = manifest(
      {},
      {
        'mac-arm64': { file: MAC, sha256: HASH, size: 10 },
        'win-x64': { file: WIN, sha256: HASH, size: 10 },
      },
    );
    const mac = await mountInstall({
      raw: both,
      ua: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15',
    });
    expect(mac.findAll('.platform-card').map((c) => c.attributes('data-platform'))).toEqual([
      'mac-arm64',
      'win-x64',
    ]);
    expect(mac.get('[data-platform="mac-arm64"]').classes()).toContain('is-matched');
    expect(mac.get('[data-platform="mac-arm64"] .platform-match').text()).toBe('，与您的电脑匹配');
    expect(mac.get('[data-platform="win-x64"]').classes()).not.toContain('is-matched');
    mac.unmount();
    const win = await mountInstall({ raw: both, ua: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' });
    expect(win.findAll('.platform-card').map((c) => c.attributes('data-platform'))).toEqual([
      'mac-arm64',
      'win-x64',
    ]);
    expect(win.get('[data-platform="win-x64"]').classes()).toContain('is-matched');
  });

  it('AC-05-48：iPhone / Android 显示手机与平板提示；复制页面链接为 origin + /#install；两卡都无匹配', async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const w = await mountInstall({ ua: 'Mozilla/5.0 (Linux; Android 14; Pixel 8)' });
    expect(w.get('.install-mobile-note').text()).toContain(
      '您正在使用手机或平板。安装包需要在 Mac 或 Windows 电脑上安装，可以把本页链接发到电脑上打开。',
    );
    const release = w.get('.install-release').element;
    expect(release.firstElementChild?.classList.contains('install-mobile-note')).toBe(true);
    await w.get('.install-mobile-note button').trigger('click');
    await flushPromises();
    expect(writeText).toHaveBeenCalledWith(`${location.origin}/#install`);
    expect((await toast()).message).toBe('已复制页面链接');
    expect(w.findAll('.platform-card')).toHaveLength(2);
    expect(w.findAll('.platform-match')).toHaveLength(0);
  });

  it('AC-05-49 / AC-05-55：预渲染 HTML 无匹配标记；DecoInstallField 是 .install-panel 的第一个子元素且 aria-hidden', async () => {
    const { html } = await render('/');
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const install = doc.getElementById('install')!;
    expect(install.querySelectorAll('.platform-match')).toHaveLength(0);
    const panel = install.querySelector('.install-panel')!;
    expect(panel.firstElementChild?.classList.contains('deco-install')).toBe(true);
    expect(panel.firstElementChild?.getAttribute('aria-hidden')).toBe('true');
    expect(panel.classList.contains('on-dark')).toBe(true);
  });

  it('AC-05-50 / AC-05-51：校验命令含实际文件名，与获取弹层同一组件同一数据', async () => {
    const w = await mountInstall();
    const card = w.get('[data-platform="mac-arm64"]');
    expect(card.get('.platform-command code').text()).toBe(`shasum -a 256 ${MAC}`);
    expect(card.findAll('.platform-first-body li').map((l) => l.text())).toEqual([
      '打开 .dmg，把“智通数工AI”拖进“应用程序”。',
      '首次打开：在“应用程序”里按住 Control 点按（或右键）应用 → 打开 → 打开。',
      'macOS 15 及以上若被拦截：到“系统设置 → 隐私与安全性”底部点“仍要打开”。',
      '欢迎窗口会请您填写模型 API Key（默认接口 https://api.deepseek.com，推荐模型 DeepSeek V4.1 Flash）。模型服务的接入方式由服务方在交付时说明。',
    ]);
  });

  it('AC-05-52：配置包小节列出 5 项与提醒；#install 内没有指向配置包的下载链接', async () => {
    const w = await mountInstall();
    expect(w.findAll('.install-config-items li').map((l) => l.text())).toEqual([
      '公司名称',
      '对象存储的地址、区域、桶名与目录前缀',
      '访问密钥（导入后存入本机凭据存储）',
      '可选：SSH 主机别名、地址与私钥',
      '可选：火山引擎 ve 的 profile 名（ve 自己的密钥由您在终端里单独设置，不放进配置包）',
    ]);
    expect(w.get('.install-warning').text()).toBe(
      '配置包含明文密钥：导入后请从下载目录删除，不要转发。更换密钥时，服务方发来新配置包，重新导入即可。',
    );
    expect(w.get('.install-config').text()).toContain(
      '配置包是服务方按贵司环境整理的一个压缩文件（内含 zhitong.config.json），不随安装包分发，也不在本站提供下载。',
    );
    for (const a of w.findAll('a'))
      expect(a.attributes('href') ?? '').not.toMatch(/\.zip$|config\.json$/);
  });

  it('AC-05-54：没有可联系渠道时没有“联系服务方”与占位文字；只填邮箱时只列邮箱', async () => {
    const empty = await mountInstall({ contact: { phone: '', email: '' } });
    expect(empty.text()).not.toContain('联系服务方');
    expect(empty.text()).not.toMatch(/待配置|待填/);
    empty.unmount();
    const mail = await mountInstall({ contact: { phone: '', email: 'service@example.com' } });
    const block = mail.get('.install-contact');
    expect(block.get('p').text()).toBe('安装包与配置包向服务方获取。');
    expect(block.findAll('dt').map((d) => d.text())).toEqual(['邮箱']);
    expect(block.get('dd a').attributes('href')).toBe('mailto:service@example.com');
  });

  it('AC-05-57：卡内键盘顺序为 下载 → 复制校验值 → .sha256 链接 → 首次打开与校验', async () => {
    const w = await mountInstall();
    const card = w.get('[data-platform="mac-arm64"]').element;
    const order = [...card.querySelectorAll('a, button, summary')].map((el) =>
      el.classList.contains('platform-download')
        ? 'download'
        : el.matches('.platform-hash .platform-copy')
          ? 'copy-hash'
          : el.classList.contains('platform-sha-file')
            ? 'sha-file'
            : el.tagName === 'SUMMARY'
              ? 'summary'
              : 'other',
    );
    expect(order.slice(0, 4)).toEqual(['download', 'copy-hash', 'sha-file', 'summary']);
  });

  it('AC-05-58：同一 PlatformCard 在获取弹层中为 light 面、无磁吸；本区为 dark 面', async () => {
    const w = await mountInstall();
    expect(w.get('[data-platform="mac-arm64"]').classes()).toContain('on-dark');
    vi.resetModules();
    const { default: AcquireDialog } = await import('../src/components/AcquireDialog.vue');
    const router = createAppRouter(createMemoryHistory());
    await router.push('/');
    const d = mount(AcquireDialog, {
      props: { modelValue: false },
      attachTo: document.body,
      global: { plugins: [router], directives: { magnetic: vMagnetic, spotlight: vSpotlight } },
    });
    await d.setProps({ modelValue: true });
    await flushPromises();
    expect(d.get('.platform-card').classes()).toContain('on-light');
  });
});
