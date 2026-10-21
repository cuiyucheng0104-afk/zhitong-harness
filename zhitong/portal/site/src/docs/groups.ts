/**
 * 文档子站的组与路由表（06 章 §1.1、§1.2）。
 * - `DOC_GROUPS`：侧栏组顺序与组说明（文档首页卡片逐字使用）。
 * - `DOC_TABLE`：§1.1 路由表。构建期（build/docs-plugin.ts）逐项比对正文 frontmatter，不一致即构建失败；
 *   侧栏、上一页/下一页、文档首页卡片、预渲染、sitemap 都从 frontmatter 生成的清单派生（与本表一致）。
 * 新增或改名页面：同时改本表与对应文件的 frontmatter。
 */

export interface DocGroup {
  name: string;
  description: string;
}

/** 首页的组名（不进侧栏分组）。 */
export const HOME_GROUP = '首页';

/** §1.2：组顺序固定。 */
export const DOC_GROUPS: readonly DocGroup[] = [
  { name: '开始使用', description: '安装、导入配置包、第一次对话，以及多步任务怎么跑。' },
  { name: '项目与资料', description: '项目在桶里怎么放，怎么开项目、问资料、看图纸。' },
  { name: '核对与测算', description: '送审审定核对、造价指标、投控检查、概算。' },
  { name: '成果与归档', description: '报告、清单框架、归档与案例索引。' },
  { name: '知识与协作', description: '企业知识库与火山引擎运维。' },
  { name: '参考', description: '结果状态、数据安全、排错与版本。' },
];

export interface DocTableRow {
  group: string;
  order: number;
  title: string;
  /** URL 中 `/docs/` 之后、尾斜杠之前的部分；首页 `index`。 */
  slug: string;
}

const row = (group: string, order: number, title: string, slug: string): DocTableRow => ({ group, order, title, slug });

/** §1.1 路由表（共 23 页）。文件名 = slug 中 `/` 换成 `-` 再加 `.md`，位于 `src/docs/content/`。 */
export const DOC_TABLE: readonly DocTableRow[] = [
  row(HOME_GROUP, 0, '文档首页', 'index'),
  row('开始使用', 1, '快速开始', 'quick-start'),
  row('开始使用', 2, '安装', 'install'),
  row('开始使用', 3, '导入配置包', 'config-package'),
  row('开始使用', 4, '对话、确认与结果的基本用法', 'basics'),
  row('开始使用', 5, '多步任务与多代理', 'agents'),
  row('项目与资料', 1, '项目与存储桶目录', 'projects'),
  row('项目与资料', 2, '开项目与资料盘点', 'features/project'),
  row('项目与资料', 3, '项目与知识库问答', 'features/qa'),
  row('项目与资料', 4, 'CAD 看图', 'features/cad'),
  row('核对与测算', 1, '送审审定核对', 'features/check'),
  row('核对与测算', 2, '造价指标', 'features/metrics'),
  row('核对与测算', 3, '投控异常检测与复核', 'features/control'),
  row('核对与测算', 4, '概算编制辅助', 'features/estimate'),
  row('成果与归档', 1, '报告撰写', 'features/report'),
  row('成果与归档', 2, 'GB50854 清单框架', 'features/bills'),
  row('成果与归档', 3, '归档与案例索引', 'features/archive'),
  row('知识与协作', 1, '企业知识库', 'features/knowledge'),
  row('知识与协作', 2, '火山引擎运维', 'features/cloud'),
  row('参考', 1, '结果状态与告警', 'results'),
  row('参考', 2, '数据与安全', 'security'),
  row('参考', 3, '常见问题与排错', 'troubleshooting'),
  row('参考', 4, '版本与更新', 'releases'),
];

/** 能力页（`features-*.md`）的 H2，§6.2，顺序固定、不增不减。 */
export const FEATURE_H2: readonly string[] = [
  '一句话',
  '适用场景',
  '您可以这样说',
  '需要准备的资料',
  '它会怎么做',
  '得到什么',
  '结果怎么读',
  '需要您确认的事项',
  '限制与注意',
  '常见问题',
  '相关能力',
];

/** slug → 正文文件名。 */
export const docFile = (slug: string) => `${slug.replace(/\//g, '-')}.md`;
/** slug → URL。 */
export const docPath = (slug: string) => (slug === 'index' ? '/docs/' : `/docs/${slug}/`);
