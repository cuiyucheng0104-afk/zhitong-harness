import manifestJson from '../../public/downloads/releases.json';
import {
  parseReleaseManifest,
  RELEASE_PLATFORMS,
  type ReleaseManifest,
  type ReleasePlatform,
} from './release-manifest.mjs';

/** URL prefix nginx serves `/opt/ztsgai/downloads` under (zhitong/portal/deploy/nginx/ztsgai.conf). */
const DOWNLOADS = '/downloads/';

/** 01 章 §7.4。 */
interface PlatformCopy {
  name: 'Mac' | 'Windows';
  /** 'Apple 芯片' | 'x64' */
  arch: string;
  icon: 'apple' | 'window';
  /** 适用说明（01 章 §7.2）。 */
  fits: string;
  /** '下载 Mac 版' | '下载 Windows 版' */
  downloadLabel: string;
  /** 首次打开步骤（现有文本不改）。 */
  firstLaunch: string[];
  verifyShell: '终端' | 'PowerShell';
  /** 按实际文件名生成校验命令。 */
  verify: (file: string) => string;
  /** Windows：大写字母说明；Mac 为 null。 */
  verifyNote: string | null;
}

/** 首次打开步骤之后追加的一条（01 章 §7.2）。 */
export const FIRST_LAUNCH_API_KEY =
  '欢迎窗口会请您填写模型 API Key（默认接口 `https://api.deepseek.com`，推荐模型 DeepSeek V4.1 Flash）。模型服务的接入方式由服务方在交付时说明。';

const PLATFORM_COPY: Record<ReleasePlatform, PlatformCopy> = {
  'mac-arm64': {
    name: 'Mac',
    arch: 'Apple 芯片',
    icon: 'apple',
    fits: '适用于 Apple 芯片的 Mac',
    downloadLabel: '下载 Mac 版',
    firstLaunch: [
      '打开 .dmg，把“智通数工AI”拖进“应用程序”。',
      '首次打开：在“应用程序”里按住 Control 点按（或右键）应用 → 打开 → 打开。',
      'macOS 15 及以上若被拦截：到“系统设置 → 隐私与安全性”底部点“仍要打开”。',
    ],
    verifyShell: '终端',
    verify: (file) => `shasum -a 256 ${file}`,
    verifyNote: null,
  },
  'win-x64': {
    name: 'Windows',
    arch: 'x64',
    icon: 'window',
    fits: '适用于 x64 的 Windows 电脑',
    downloadLabel: '下载 Windows 版',
    firstLaunch: [
      '双击安装程序，安装到当前用户，无需管理员权限。',
      '出现“Windows 已保护你的电脑”时，点“更多信息” → “仍要运行”。',
    ],
    verifyShell: 'PowerShell',
    verify: (file) => `Get-FileHash .\\${file} -Algorithm SHA256`,
    verifyNote: 'PowerShell 输出为大写字母，比对时不区分大小写',
  },
};

/** One platform card in the install section and the acquire dialog. */
export type PlatformDownload = PlatformCopy & {
  platform: ReleasePlatform;
  notes: string | null;
} & (
    | {
        available: true;
        file: string;
        href: string;
        sha256: string;
        sha256Href: string;
        size: string;
      }
    | { available: false }
  );

/** Release the portal offers, with every platform in display order. */
export interface DownloadRelease {
  version: string;
  date: string | null;
  /** manifest.base：安装后“关于”中显示的程序版本。 */
  base: string | null;
  notes: string[];
  platforms: PlatformDownload[];
}

/**
 * Format a byte count for display.
 * @param bytes - File size in bytes.
 * @returns Size in MB (1 MB = 1024 × 1024 bytes) with one decimal.
 */
export function formatSize(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * Build the download view of a manifest.
 * @param manifest - Validated manifest.
 * @returns Version, date, and one entry per platform; a platform without a file is not available.
 */
export function downloadRelease(manifest: ReleaseManifest): DownloadRelease {
  return {
    version: manifest.version,
    date: manifest.date,
    base: manifest.base,
    notes: manifest.notes,
    platforms: RELEASE_PLATFORMS.map((platform): PlatformDownload => {
      const entry = manifest.platforms[platform];
      const copy = { platform, notes: entry.notes, ...PLATFORM_COPY[platform] };
      if (entry.file === null) return { ...copy, available: false };
      return {
        ...copy,
        available: true,
        file: entry.file,
        href: `${DOWNLOADS}${entry.file}`,
        sha256: entry.sha256,
        sha256Href: `${DOWNLOADS}${entry.file}.sha256`,
        size: formatSize(entry.size),
      };
    }),
  };
}

/** The release in `public/downloads/releases.json`; an invalid manifest fails the build. */
export const release = downloadRelease(parseReleaseManifest(manifestJson));
