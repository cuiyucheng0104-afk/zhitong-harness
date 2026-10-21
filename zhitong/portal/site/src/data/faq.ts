/**
 * 常见问题（05 章 §4.2、§4.4）：八问，显示顺序 = 文案稿顺序；答案按事实来源校正（见 spec“校正与依据”列）。
 * 相关文档的标题与 06 章路由表一致（测试对照 `DOC_ROUTES`）。
 */
export type FaqGroup = 'install' | 'data' | 'result' | 'collab';

export const FAQ_GROUPS: { id: FaqGroup | 'all'; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'install', label: '安装' },
  { id: 'data', label: '数据' },
  { id: 'result', label: '结果' },
  { id: 'collab', label: '协作' },
];

export interface FaqItem {
  id:
    | 'calc'
    | 'use-directly'
    | 'data-location'
    | 'concurrent'
    | 'scans-drawings'
    | 'vector-index'
    | 'migrate'
    | 'other-documents';
  group: FaqGroup;
  question: string;
  answer: string;
  doc: { title: string; href: string } | null;
}

export const FAQ_COPY = {
  eyebrow: '常见问题',
  title: '常见问题',
  lead: '安装、数据、结果与协作',
  filterLabel: '按主题筛选',
  docLink: { text: '在文档中查看更多', href: '/docs/troubleshooting/' },
  copyLabel: '复制本问题的链接',
  copied: '已复制问题链接',
  related: '相关文档：',
  /** 筛选播报。 */
  status: (n: number, label: string | null) =>
    label ? `显示 ${n} 个问题：${label}` : `显示全部 ${n} 个问题`,
  /** 复制得到的绝对地址。 */
  link: (id: string) => `https://ztsgai.com/#faq-${id}`,
} as const;

export const FAQS: FaqItem[] = [
  {
    id: 'calc',
    group: 'result',
    question: '它会替我算造价吗？',
    answer:
      '不会由模型算。金额与数量由脚本计算，规则和数据是普通文件，可以查看，也可以修改；脚本算出的金额与数量同样标注“需人工确认”。模型负责阅读资料、判断、分类、摘录和写作。',
    doc: { title: '数据与安全', href: '/docs/security/' },
  },
  {
    id: 'use-directly',
    group: 'result',
    question: 'AI 给出的结果能直接用吗？',
    answer:
      '不能不经确认直接用。金额与数量一律标注“需人工确认”，报告里未核实的程序性陈述标注“待核”，导出的 Word 页眉写明“AI 初稿，金额未经人工核对，不得直接出具”。结果是供您复核的初稿，签发由人负责。',
    doc: { title: '结果状态与告警', href: '/docs/results/' },
  },
  {
    id: 'data-location',
    group: 'data',
    question: '我们的资料会放到哪里？',
    answer:
      '放在贵司自己的火山引擎 TOS 桶里，由贵司持有；工程师电脑只缓存用到的文件。对话中读取的文件内容（包括交给模型看的扫描页和图纸图片）会作为对话上下文发送给所配置的模型服务。模型为 DeepSeek V4.1 Flash，默认连接 DeepSeek 官方接口，也可改为贵司指定的兼容接口，部署方式在交付配置时说明。',
    doc: { title: '数据与安全', href: '/docs/security/' },
  },
  {
    id: 'concurrent',
    group: 'collab',
    question: '几个人同时用同一个项目会冲突吗？',
    answer:
      '多人共用同一个桶，桶开启版本控制，不加锁。推送时如果发现文件在您拉取之后被别人改过，会在对话里告诉您；被覆盖的版本可以从版本历史恢复。',
    doc: { title: '项目与存储桶目录', href: '/docs/projects/' },
  },
  {
    id: 'scans-drawings',
    group: 'data',
    question: '扫描件和图纸能看吗？',
    answer:
      '能。扫描件优先读与原件并列的识别文本，没有时由模型看图。DWG 图纸转换后先读结构化内容：图框、标题栏、文字、图块和房间面积，计数与面积由代码计算；需要看空间关系时，再把图框渲染成图片交给模型阅读。看图结果同样需人工确认。',
    doc: { title: 'CAD 看图', href: '/docs/features/cad/' },
  },
  {
    id: 'vector-index',
    group: 'install',
    question: '需要建知识库的向量索引吗？',
    answer:
      '不需要。产品不建向量库，也不建数据库，按需读文件：先读项目说明，再读具体文件；跨项目查询读案例索引。知识库按目录组织，每个目录有一份说明。',
    doc: { title: '项目与知识库问答', href: '/docs/features/qa/' },
  },
  {
    id: 'migrate',
    group: 'install',
    question: '原来的资料怎么搬进来？',
    answer:
      '由服务方在交付前整理：按统一目录规范重排、清理重复件和系统生成物、核对文件数与总字节，再上传到桶，并出具整理报告，说明删除和改名情况。',
    doc: null,
  },
  {
    id: 'other-documents',
    group: 'collab',
    question: '能写报告以外的文书吗？',
    answer:
      '可以，但要先加模板。内置 24 套模板，覆盖咨询成果报告、编制说明、审核报告、审定单和投资控制月报等；函件、方案、意见书等，由服务方按报告模板机制增加对应模板后即可使用。',
    doc: { title: '报告撰写', href: '/docs/features/report/' },
  },
];

/** 主题的中文名。 */
export const GROUP_LABEL: Record<FaqGroup, string> = {
  install: '安装',
  data: '数据',
  result: '结果',
  collab: '协作',
};
