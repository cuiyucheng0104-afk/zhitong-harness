/**
 * 数据与复核（05 章 §2.2）：标题、图的读屏文字、图例、四条原则与六个节点说明卡。文案逐字取自 spec。
 * 说明卡行内的反引号片段以等宽显示。
 */
import type {
  FocusKey,
  TrustNodeId,
} from '../components/sections05/trust/trust-geometry';

export const TRUST_COPY = {
  eyebrow: '数据与复核',
  title: '数据在您自己的桶里，数字有出处',
  lead: '四条原则，写进产品的工作方式。',
  figTitle: '数据流向示意',
  figDesc: '公司存储桶、工程师电脑、模型服务与人工复核之间，五类内容的去向。',
  hoverHint: '悬停查看图中对应位置。',
  readDoc: '读文档',
  docHref: '/docs/security/',
} as const;

/** 读屏用的流向列表（`<ol class="sr-only">`）。 */
export const TRUST_FLOWS = [
  '文件内容：从公司存储桶按需拉取到本机缓存；对话中读取时，作为对话上下文发送给模型服务。',
  '金额与数量：只在本机脚本中计算，结果写进工作底稿，交人工复核；结果摘要作为上下文交给模型转述。',
  '凭据：保存在本机凭据存储，只用于连接公司存储桶和模型服务，不写进对话。',
  '模型回复：判断、摘录与写作的文字回到对话，作为初稿交人工复核。',
  '成果：推送回公司存储桶，并回读校验。',
] as const;

export interface Principle {
  no: string;
  title: string;
  body: string;
  key: Extract<FocusKey, 'owned' | 'credential' | 'source' | 'review'>;
}

export const TRUST_PRINCIPLES: Principle[] = [
  {
    no: '01',
    title: '数据归客户所有',
    body: '项目资料、成果和知识库都存放在公司自己的火山引擎 TOS 桶里。桶开启版本控制；多人共用时不加锁，出现覆盖通过版本回退恢复。',
    key: 'owned',
  },
  {
    no: '02',
    title: '凭据不离开本机',
    body: '访问桶所需的密钥由配置包导入，保存在本机的凭据存储中，导入时不回显。工程师在自己的电脑上直接读写公司的桶。',
    key: 'credential',
  },
  {
    no: '03',
    title: '每个数字有出处',
    body: '模型不算钱，金额和数量由脚本计算。报告中的数字必须在送入的资料里逐字找到；金额带出处；找不到出处的数字会被标出，不会被悄悄放行。',
    key: 'source',
  },
  {
    no: '04',
    title: 'AI 结果需人工确认',
    body: '金额与数量一律标注“需人工确认”。脚本失败时以错误结束，不会输出“成功但为空”；状态和警示项如实转述。最终签发由人负责。',
    key: 'review',
  },
];

export interface NodeCard {
  node: TrustNodeId;
  title: string;
  lead: string;
  rows: { label: string; text: string }[];
}

/** 节点说明卡（`ZtPopover`）。 */
export const TRUST_NODES: NodeCard[] = [
  {
    node: 'tos',
    title: '公司存储桶（TOS）',
    lead: '项目资料、成果和知识库存放在贵司自己的火山引擎对象存储（TOS）桶里，由贵司持有。',
    rows: [
      {
        label: '存放',
        text: '`项目/`、`知识库/`、`案例索引.md`；桶开启版本控制，被覆盖的版本可以回退。',
      },
      { label: '进出', text: '工程师电脑按需拉取单个文件；推送后回读大小与 SHA-256 校验。' },
    ],
  },
  {
    node: 'cache',
    title: '本机缓存',
    lead: '只缓存用到的文件，目录与桶同构。',
    rows: [
      {
        label: '位置',
        text: '`~/zhitong`（Windows `%USERPROFILE%\\zhitong`），默认上限 20 GiB，满了先淘汰最久未用且未改动的文件。',
      },
      {
        label: '规则',
        text: '本机改过、未推送的文件不会被拉取覆盖；图纸与压缩包不随目录自动拉取。',
      },
    ],
  },
  {
    node: 'script',
    title: '脚本计算',
    lead: '金额、数量、核对和指标由安装包内置的 Python 脚本计算。',
    rows: [
      {
        label: '产出',
        text: '结果 JSON（状态、告警、`needs_manual: true`）与 xlsx 工作底稿，写进项目的 `工作/`。',
      },
      {
        label: '与模型',
        text: '结果摘要会作为对话上下文交给模型转述；按技能规则，模型只引用原值，不做加减乘除。',
      },
    ],
  },
  {
    node: 'cred',
    title: '本机凭据存储',
    lead: '访问桶的密钥由配置包导入，保存在本机，仅当前用户可读。',
    rows: [
      {
        label: '存放',
        text: 'TOS 访问密钥（引用名 `ZT_TOS_ACCESS_KEY_ID`、`ZT_TOS_SECRET_ACCESS_KEY`）与模型 API Key。',
      },
      {
        label: '去向',
        text: 'TOS 密钥只供本机的 TOS 工具连接公司桶，导入结果与报错里不出现密钥值，也不写进对话；模型 API Key 只用于向所配置的模型服务验证身份。',
      },
    ],
  },
  {
    node: 'model',
    title: '模型服务 · DeepSeek V4.1 Flash',
    lead: '负责阅读、判断、分类、摘录和写作，不负责算钱。',
    rows: [
      {
        label: '收到',
        text: '对话内容，以及对话中读取的文件内容、扫描页与图纸图片、脚本结果摘要。',
      },
      {
        label: '送出',
        text: '文字回复与报告初稿；报告里的金额先写成事实编号，由脚本换成原值并带出处。',
      },
    ],
  },
  {
    node: 'review',
    title: '人工复核与签发',
    lead: '结果是供您复核的初稿，签发由人负责。',
    rows: [
      {
        label: '标注',
        text: '金额与数量标“需人工确认”；报告中未核实的程序性陈述标“待核”；导出的 Word 页眉写明“AI 初稿，金额未经人工核对，不得直接出具”。',
      },
      { label: '记录', text: '投控异常的“确认 / 误报”决策追加记录在项目 `工作/` 目录。' },
    ],
  },
];

/**
 * 把带反引号的文字拆成普通与等宽片段。
 * @param text - 文字。
 * @returns 片段（奇数位为等宽）。
 */
export function splitTicks(text: string): { t: string; mono: boolean }[] {
  return text
    .split('`')
    .map((t, i) => ({ t, mono: i % 2 === 1 }))
    .filter((p) => p.t !== '');
}
