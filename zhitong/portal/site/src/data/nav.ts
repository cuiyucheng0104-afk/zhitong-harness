/** 顶栏与移动菜单的导航数据（01 章 §1）。 */
export type NavSectionId = 'capabilities' | 'workflow' | 'trust' | 'faq';

export const NAV_LINKS: readonly { id: NavSectionId; label: string }[] = [
  { id: 'capabilities', label: '产品能力' },
  { id: 'workflow', label: '使用流程' },
  { id: 'trust', label: '数据与复核' },
  { id: 'faq', label: '常见问题' },
];

export const DOCS_LINK = { to: '/docs/', label: '文档' } as const;

/** 比例尺上标出的首页七个章节起点（01 章 §4）；前四个以外为次要标记。 */
export const RULER_SECTIONS = ['roles', 'problem', 'capabilities', 'workflow', 'trust', 'install', 'faq'] as const;
export type RulerSectionId = (typeof RULER_SECTIONS)[number];
