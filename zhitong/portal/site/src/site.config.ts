/**
 * 站点配置（01 章 §8.2；05 章 §5.4 追加 legal）。空串表示未提供：该项不显示，不出现任何占位文字。
 * 取值由 05 章按 00 章 §15.4 在用户本机查找后填写；`ZT_LAUNCH=1 npm run build` 时由 `launchIssues()` 阻断未填项。
 */

/** 服务方联系方式；空串表示未提供，该行不显示。 */
export interface ServiceContact {
  /** 服务方名称，如“某某数字科技有限公司”。 */
  provider: string;
  /** 联系人，如“王工”。 */
  person: string;
  /** 显示原样；tel: 链接去掉空格、括号与短横。 */
  phone: string;
  email: string;
  /** 微信号。 */
  wechat: string;
  /** 服务时间，如“工作日 9:00–18:00”。 */
  hours: string;
}

/** 网站运营方的法律信息；空串表示未提供，该项不显示。 */
export interface LegalInfo {
  /** 网站运营主体全称。 */
  company: string;
  /** ICP 备案号，如“浙ICP备XXXXXXXX号-1”。 */
  icp: string;
  /** 公安联网备案号文字；与 psbHref 同时填写或同时留空。 */
  psbText: string;
  /** 该备案号的官方查询链接，原样填写。 */
  psbHref: string;
  /** 隐私说明路径；站内路径须带尾斜杠且在预渲染路由表内。 */
  privacyHref: string;
}

export interface SiteConfig {
  contact: ServiceContact;
  legal: LegalInfo;
}

/**
 * 取值来源（05 章按 00 章 §15.4 于 2026-10-21 在用户本机查得；未查到的项保持空串）：
 * - contact.phone、contact.email：用户 2026-10-21 要求暂时留空。
 * - legal.company：用户 2026-10-21 指定。
 * - legal.privacyHref：`/privacy/`，正文转录自同一份隐私政策（`components/sections05/privacy-policy.ts`）。
 * - legal.icp：用户 2026-10-21 提供。
 * - legal.psbText、legal.psbHref、contact.provider / person / wechat / hours：本机未查到，留空；
 *   联系方式全空时 `ZT_LAUNCH=1` 构建按设计失败（上线阻断项）。
 */
export const siteConfig: SiteConfig = {
  contact: {
    provider: '',
    person: '',
    phone: '',
    email: '',
    wechat: '',
    hours: '',
  },
  legal: {
    company: '杭州智通数工科技有限公司',
    icp: '浙ICP备2026074211号',
    psbText: '',
    psbHref: '',
    privacyHref: '/privacy/',
  },
};

export type ContactChannel =
  | { kind: 'phone'; value: string; href: `tel:${string}` }
  | { kind: 'email'; value: string; href: `mailto:${string}` }
  | { kind: 'wechat'; value: string };

export const PHONE_RE = /^[0-9+()\-\s]{5,20}$/;
export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export const WECHAT_RE = /^[A-Za-z][-_A-Za-z0-9]{5,19}$/;
/** 占位文字（01 章 §8.4）。 */
export const PLACEHOLDER_RE = /待配置|待填|TODO|xxx|示例/i;

/**
 * 可联系的渠道（电话、邮箱、微信中非空且格式正确的项），按电话、邮箱、微信顺序。
 * @param c - 联系方式。
 * @returns 渠道列表。
 */
export function contactChannels(c: ServiceContact): ContactChannel[] {
  const out: ContactChannel[] = [];
  const phone = c.phone.trim();
  const email = c.email.trim();
  const wechat = c.wechat.trim();
  if (phone && PHONE_RE.test(phone) && !PLACEHOLDER_RE.test(phone))
    out.push({ kind: 'phone', value: phone, href: `tel:${phone.replace(/[\s()-]/g, '')}` });
  if (email && EMAIL_RE.test(email) && !PLACEHOLDER_RE.test(email))
    out.push({ kind: 'email', value: email, href: `mailto:${email}` });
  if (wechat && WECHAT_RE.test(wechat) && !PLACEHOLDER_RE.test(wechat))
    out.push({ kind: 'wechat', value: wechat });
  return out;
}

/** 至少有一个可联系渠道时为 true。 */
export const hasContact: boolean = contactChannels(siteConfig.contact).length > 0;

/**
 * 联系方式的上线检查（01 章 §8.4）。
 * @param c - 联系方式。
 * @returns 问题清单，空数组表示可以上线。
 */
export function launchIssues(c: ServiceContact): string[] {
  const issues: string[] = [];
  if (!contactChannels(c).length)
    issues.push('site.config.ts：contact 至少需要电话、邮箱或微信之一');
  for (const key of Object.keys(c) as (keyof ServiceContact)[])
    if (PLACEHOLDER_RE.test(c[key])) issues.push(`site.config.ts：contact.${key} 含占位文字`);
  const formats: [keyof ServiceContact, RegExp][] = [
    ['phone', PHONE_RE],
    ['email', EMAIL_RE],
    ['wechat', WECHAT_RE],
  ];
  for (const [key, re] of formats) {
    const v = c[key].trim();
    if (v && !PLACEHOLDER_RE.test(v) && !re.test(v))
      issues.push(`site.config.ts：contact.${key} 格式不正确`);
  }
  return issues;
}

/**
 * 法律信息的上线检查（05 章 §5.4）。
 * @param l - 法律信息。
 * @param routes - 预渲染路由表。
 * @returns 问题清单，空数组表示可以上线。
 */
export function legalLaunchIssues(l: LegalInfo, routes: readonly string[]): string[] {
  const issues: string[] = [];
  for (const key of ['company', 'icp', 'privacyHref'] as const)
    if (!l[key].trim()) issues.push(`site.config.ts：legal.${key} 未填写`);
  for (const key of Object.keys(l) as (keyof LegalInfo)[])
    if (PLACEHOLDER_RE.test(l[key])) issues.push(`site.config.ts：legal.${key} 含占位文字`);
  if (Boolean(l.psbText.trim()) !== Boolean(l.psbHref.trim()))
    issues.push('site.config.ts：legal.psbText 与 legal.psbHref 须同时填写');
  if (l.privacyHref.startsWith('/') && !routes.includes(l.privacyHref))
    issues.push('site.config.ts：legal.privacyHref 不是已预渲染的页面');
  return issues;
}
