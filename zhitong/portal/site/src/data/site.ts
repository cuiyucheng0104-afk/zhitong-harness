/**
 * 由 `site.config.ts` 派生的站点信息（05 章 §5.4）。
 * 06 章文档页底部“内容有误或不清楚？{联系方式}”取 `SUPPORT_CONTACT`。
 */
import { contactChannels, siteConfig, type ContactChannel } from '../site.config';

/** 第一个可联系渠道（电话、邮箱、微信顺序）；没有可联系渠道时为 null。 */
export const SUPPORT_CONTACT: ContactChannel | null =
  contactChannels(siteConfig.contact)[0] ?? null;
