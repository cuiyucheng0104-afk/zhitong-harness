/** 首屏文案区与原则条的逐字文案（02 章 §1.2、§7.2）。 */
import type { Principle } from './demo';
import type { SceneId } from '../types/portal';

export const HERO = {
  eyebrow: '为造价咨询团队而做',
  /** 构建期按字拆成 span（02 章 §1.4）；SSR 直接输出，不依赖 SplitText。 */
  titleLines: [
    ['造', '价', '咨', '询', '公', '司', '的'],
    ['对', '话', '式', '工', '作', '台'],
  ] as const,
  /** 说明段。 */
  description: [
    '在工程师自己的电脑上，用对话完成开项目、核对、指标、投控、清单、概算、报告和看图。',
  ] as const,
  primary: '获取安装包',
  secondary: '看它怎么工作',
  secondaryLabel: '看它怎么工作：从第 1 个场景播放工作示例',
  platform: '支持 Mac 与 Windows',
  /** 平台说明第二段：“配置包”三个字是说明卡触发按钮。 */
  configTerm: '配置包',
  configSuffix: '由服务方交付',
  configPopover: {
    title: '配置包',
    lead: '一个压缩文件，由服务方按贵司环境整理并交付，内含对象存储地址、区域、桶名、目录前缀、访问密钥和公司名；不随安装包分发。',
    rows: [
      { label: '需要什么', text: '向服务方获取。' },
      { label: '得到什么', text: '导入后即可列出公司桶里的项目。' },
    ],
  },
  playingStatus: '正在播放：计价表核对',
  noscript: '安装包下载见页面下方「安装与交付」',
} as const;

export interface PrincipleItem {
  id: Principle;
  label: string;
  icon: 'chat' | 'calc' | 'shield';
  lead: string;
  need: string;
  get: string;
  scene: SceneId;
  /** 06 章文档页（00 章 §14 第 9 条）。 */
  doc: string;
}

export const PRINCIPLES: readonly PrincipleItem[] = [
  {
    id: 'dialog',
    label: '对话组织任务',
    icon: 'chat',
    lead: '您说要做什么，它先读项目说明，再拉需要的文件；顺序由对话决定，不由页面决定。',
    need: '一句话任务和项目目录',
    get: '按需读取的资料与逐步状态',
    scene: 'check',
    doc: '/docs/agents/',
  },
  {
    id: 'script',
    label: '脚本完成计算',
    icon: 'calc',
    lead: '金额、数量、核对、指标由脚本计算，可复算；模型负责阅读、判断和写作，不算钱。',
    need: '计价表、图纸等原始文件',
    get: '带出处的数字与工作底稿',
    scene: 'check',
    doc: '/docs/results/',
  },
  {
    id: 'review',
    label: '人工复核结果',
    icon: 'shield',
    lead: '金额与数量一律标注需人工确认；投控疑似由您逐条判定，决定追加记录，可追溯。',
    need: '您的判断与理由',
    get: '复核.jsonl 里的逐条决定',
    scene: 'review',
    doc: '/docs/basics/',
  },
];

export const PRINCIPLES_LABEL = '工作原则';
