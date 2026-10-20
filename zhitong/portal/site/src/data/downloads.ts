import manifestJson from '../../public/downloads/releases.json';
import {
  parseReleaseManifest,
  RELEASE_PLATFORMS,
  type ReleaseManifest,
  type ReleasePlatform,
} from './release-manifest.mjs';

/** URL prefix nginx serves `/opt/ztsgai/downloads` under (zhitong/portal/deploy/nginx/ztsgai.conf). */
const DOWNLOADS = '/downloads/';

interface PlatformCopy {
  name: string;
  arch: string;
  icon: 'apple' | 'window';
  firstLaunch: string[];
  verify: string;
}

const PLATFORM_COPY: Record<ReleasePlatform, PlatformCopy> = {
  'mac-arm64': {
    name: 'Mac',
    arch: 'Apple 芯片',
    icon: 'apple',
    firstLaunch: [
      '打开 .dmg，把“智通数工AI”拖进“应用程序”。',
      '首次打开：在“应用程序”里按住 Control 点按（或右键）应用 → 打开 → 打开。',
      'macOS 15 及以上若被拦截：到“系统设置 → 隐私与安全性”底部点“仍要打开”。',
    ],
    verify: 'shasum -a 256 文件名',
  },
  'win-x64': {
    name: 'Windows',
    arch: 'x64',
    icon: 'window',
    firstLaunch: [
      '双击安装程序，安装到当前用户，无需管理员权限。',
      '出现“Windows 已保护你的电脑”时，点“更多信息” → “仍要运行”。',
    ],
    verify: 'Get-FileHash 文件名 -Algorithm SHA256',
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
