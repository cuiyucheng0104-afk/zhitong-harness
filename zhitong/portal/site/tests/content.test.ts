/**
 * 内容数据（v1.1）。v1.0 原型的组件行为用例已由各章测试取代：
 * 能力浏览器见 ch04-*.test.ts，岗位入口见 ch03-*.test.ts，常见问题见 ch05-faq.test.ts。
 */
import { describe, expect, it } from 'vitest';
import { featureGroups as legacyGroups } from '../src/data/content';
import { allFeatures, featureGroups } from '../src/data/capabilities';
import { ROLES } from '../src/data/roles';
import { FAQS } from '../src/data/faq';

describe('内容数据', () => {
  it('保留四组十二项能力、三种岗位和八项常见问题', () => {
    expect(legacyGroups).toBe(featureGroups);
    expect(featureGroups.map((group) => [group.id, group.features.length])).toEqual([
      ['project', 3],
      ['calculate', 4],
      ['output', 3],
      ['knowledge', 2],
    ]);
    const features = allFeatures;
    expect(new Set(features.map((feature) => feature.id)).size).toBe(12);
    expect(features.every((feature) => feature.caution.length > 0)).toBe(true);
    expect(features.every((feature) => feature.docs === `/docs/features/${feature.id}/`)).toBe(true);
    expect(ROLES.map((role) => role.id)).toEqual(['engineer', 'reviewer', 'manager']);
    expect(FAQS).toHaveLength(8);
  });
});
