/** 访客平台识别（01 章 §7.5）：只影响排序、匹配标记与手机提示，不隐藏任何平台。 */
export type VisitorPlatform = 'mac-arm64' | 'win-x64' | 'mobile' | null;

interface NavigatorLike {
  userAgent: string;
  maxTouchPoints?: number;
  userAgentData?: { platform?: string } | undefined;
}

/**
 * 识别访客平台。
 * @param nav - 默认取全局 `navigator`；测试可传入桩。
 * @returns `mac-arm64`、`win-x64`、`mobile` 或 null（无法识别、SSR）。
 */
export function detectPlatform(nav?: NavigatorLike): VisitorPlatform {
  const n = nav ?? (typeof navigator === 'undefined' ? undefined : (navigator as NavigatorLike));
  if (!n) return null;
  const hinted = n.userAgentData?.platform;
  if (hinted === 'macOS') return 'mac-arm64';
  if (hinted === 'Windows') return 'win-x64';
  const ua = n.userAgent ?? '';
  const touch = n.maxTouchPoints ?? 0;
  if (ua.includes('Windows NT')) return 'win-x64';
  if (/Android|iPhone|iPad/.test(ua)) return 'mobile';
  if (ua.includes('Macintosh')) return touch > 1 ? 'mobile' : 'mac-arm64';
  return null;
}
