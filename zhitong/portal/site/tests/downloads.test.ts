import { readFileSync } from 'node:fs';
import { mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import { parseReleaseManifest, releaseFileName } from '../src/data/release-manifest.mjs';
import { downloadRelease, formatSize } from '../src/data/downloads';

const HASH = 'a'.repeat(64);

function manifest(platforms: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  return {
    schema: 1,
    product: '智通数工AI',
    version: '1.0.0',
    date: '2026-10-20',
    platforms,
    ...extra,
  };
}

const macOnly = manifest({
  'mac-arm64': { file: 'ztsgai-1.0.0-mac-arm64.dmg', sha256: HASH, size: 190_840_832 },
  'win-x64': { file: null, sha256: null, size: null },
});

describe('安装包清单', () => {
  it('仓库里的清单可以通过校验', () => {
    const raw: unknown = JSON.parse(readFileSync('public/downloads/releases.json', 'utf8'));
    expect(parseReleaseManifest(raw).version).toMatch(/^\d+\.\d+\.\d+/);
  });

  it('按平台给出约定的文件名', () => {
    expect(releaseFileName('mac-arm64', '1.0.0')).toBe('ztsgai-1.0.0-mac-arm64.dmg');
    expect(releaseFileName('win-x64', '1.0.0')).toBe('ztsgai-1.0.0-win-x64-setup.exe');
  });

  it('缺失的平台视为即将发布', () => {
    const parsed = parseReleaseManifest(manifest({}));
    expect(parsed.platforms['mac-arm64'].file).toBeNull();
    expect(parsed.platforms['win-x64'].file).toBeNull();
  });

  it.each([
    [
      '文件名与版本不符',
      { file: 'ztsgai-0.9.0-mac-arm64.dmg', sha256: HASH, size: 1 },
      /must be ztsgai-1\.0\.0-mac-arm64\.dmg/,
    ],
    ['有文件没有校验值', { file: 'ztsgai-1.0.0-mac-arm64.dmg', sha256: null, size: 1 }, /sha256/],
    [
      '校验值大写',
      { file: 'ztsgai-1.0.0-mac-arm64.dmg', sha256: HASH.toUpperCase(), size: 1 },
      /sha256/,
    ],
    ['大小为零', { file: 'ztsgai-1.0.0-mac-arm64.dmg', sha256: HASH, size: 0 }, /size/],
    ['没有文件却有校验值', { file: null, sha256: HASH, size: null }, /without a file/],
  ])('拒绝%s', (_name, entry, message) => {
    expect(() => parseReleaseManifest(manifest({ 'mac-arm64': entry }))).toThrow(message);
  });

  it('拒绝未知平台与错误的版本、日期', () => {
    expect(() => parseReleaseManifest(manifest({ 'linux-x64': {} }))).toThrow(
      /not a known platform/,
    );
    expect(() => parseReleaseManifest(manifest({}, { version: 'v1' }))).toThrow(/version/);
    expect(() => parseReleaseManifest(manifest({}, { date: '2026/10/20' }))).toThrow(/date/);
    expect(() => parseReleaseManifest(manifest({}, { schema: 2 }))).toThrow(/schema/);
  });

  it('有文件的平台给出下载与校验链接，没有文件的平台不给链接', () => {
    const view = downloadRelease(parseReleaseManifest(macOnly));
    const [mac, win] = view.platforms;
    expect(mac).toMatchObject({
      available: true,
      href: '/downloads/ztsgai-1.0.0-mac-arm64.dmg',
      sha256Href: '/downloads/ztsgai-1.0.0-mac-arm64.dmg.sha256',
      size: '182.0 MB',
    });
    expect(win).toMatchObject({ platform: 'win-x64', available: false });
    expect(win).not.toHaveProperty('href');
    expect(formatSize(1024 * 1024 * 1.25)).toBe('1.3 MB');
  });
});

describe('获取安装与配置包弹层', () => {
  async function mountWith(raw: unknown) {
    vi.resetModules();
    vi.doMock('../src/data/downloads', async (importOriginal) => {
      const actual = await importOriginal<typeof import('../src/data/downloads')>();
      return { ...actual, release: actual.downloadRelease(parseReleaseManifest(raw)) };
    });
    const { default: AcquireDialog } = await import('../src/components/AcquireDialog.vue');
    const { default: InstallSection } = await import('../src/components/InstallSection.vue');
    const dialog = mount(AcquireDialog, { props: { modelValue: true } });
    const section = mount(InstallSection);
    vi.doUnmock('../src/data/downloads');
    return { dialog, section };
  }

  it('Mac 已发布：给出下载、SHA256 与首次打开提示；Windows 显示即将发布', async () => {
    const { dialog, section } = await mountWith(macOnly);
    const mac = dialog.get('[data-platform="mac-arm64"]');
    expect(mac.get('a[download]').attributes('href')).toBe('/downloads/ztsgai-1.0.0-mac-arm64.dmg');
    expect(mac.get('a[href$=".sha256"]').text()).toContain('SHA256');
    expect(mac.text()).toContain('仍要打开');
    expect(mac.text()).toContain(HASH);
    const win = dialog.get('[data-platform="win-x64"]');
    expect(win.find('a').exists()).toBe(false);
    expect(win.text()).toContain('即将发布');
    expect(dialog.text()).toContain('v1.0.0');
    expect(dialog.text()).toContain('2026-10-20 发布');
    expect(dialog.text()).toContain('配置包由服务方单独交付');
    expect(section.findAll('.install-downloads a')).toHaveLength(1);
    expect(section.get('.install-downloads').text()).toContain('即将发布');
  });

  it('两个平台都已发布时 Windows 提示 SmartScreen', async () => {
    const both = manifest({
      'mac-arm64': { file: 'ztsgai-1.0.0-mac-arm64.dmg', sha256: HASH, size: 10 },
      'win-x64': { file: 'ztsgai-1.0.0-win-x64-setup.exe', sha256: HASH, size: 10 },
    });
    const { dialog } = await mountWith(both);
    const win = dialog.get('[data-platform="win-x64"]');
    expect(win.get('a[download]').attributes('href')).toBe(
      '/downloads/ztsgai-1.0.0-win-x64-setup.exe',
    );
    expect(win.text()).toContain('仍要运行');
  });

  it('没有任何安装包时只显示即将发布，没有下载链接', async () => {
    const { dialog, section } = await mountWith(manifest({}, { date: null }));
    expect(dialog.findAll('a[download]')).toHaveLength(0);
    expect(dialog.findAll('.package-download-upcoming')).toHaveLength(2);
    expect(dialog.text()).toContain('发布日期待定');
    expect(section.findAll('.install-downloads a')).toHaveLength(0);
  });
});
