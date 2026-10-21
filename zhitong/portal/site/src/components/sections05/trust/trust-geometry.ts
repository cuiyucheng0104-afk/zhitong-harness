/**
 * 数据与复核的数据流图几何（05 章 §2.3、§2.4）：宽几何（viewBox 0 0 1040 576，≥ 1024px）与窄几何（0 0 360 656）。
 * 坐标为 SVG 用户单位。`FOCUS` 是原则卡、图例与说明卡对应的高亮集合。
 */
export type TrustNodeId = 'tos' | 'cache' | 'script' | 'cred' | 'model' | 'review';
export type TrustPathId =
  | 'pull'
  | 'push'
  | 'credTos'
  | 'ctxFile'
  | 'ctxSum'
  | 'credStub'
  | 'reply'
  | 'reviewPath';
export type PacketKind = 'file' | 'amount' | 'amountEcho' | 'credential' | 'reply' | 'result';
/** 原则卡用前四个键；图例用后四个键，图例“凭据”复用 credential。 */
export type FocusKey =
  | 'owned'
  | 'credential'
  | 'source'
  | 'review'
  | 'file'
  | 'amount'
  | 'reply'
  | 'result';

/** 图内文字的归属：随节点、连线或聚焦键一起高亮。 */
export type LabelOwner =
  | { node: TrustNodeId }
  | { path: TrustPathId }
  | { key: 'lock' }
  | { frame: true };

export interface TrustLabel {
  at: [number, number];
  anchor: 'start' | 'middle' | 'end';
  text: string;
  mono?: boolean;
  /** 标题字号（宽 20、窄 16）；否则正文字号。 */
  title?: boolean;
  owner: LabelOwner;
}

export interface TrustGeometry {
  id: 'wide' | 'narrow';
  viewBox: [0, 0, number, number];
  nodes: Record<TrustNodeId, { x: number; y: number; w: number; h: number; rx: number }>;
  /** 工程师电脑外框。 */
  frame: { x: number; y: number; w: number; h: number; rx: number };
  paths: Record<TrustPathId, { d: string; line: 'solid' | 'dashed' | 'dotted' } | null>;
  labels: TrustLabel[];
  lock: [number, number];
  /** 窄几何：`pull` / `push` 标签旁的 12×12 钥匙图标位置（代替 credTos 点线）。 */
  keys?: [number, number][];
  /** 减少动效与无 JS 时数据包的静止位置。 */
  rest: Record<PacketKind, [number, number]>;
  /** 字号（用户单位）。 */
  font: { title: number; body: number };
}

/**
 * 宽几何左侧三组连线标签的中心 x。05 章 §2.4 原写 300，但电脑外框左边在 x = 336，
 * 15px 的“tos_pull / tos_push / 直连公司桶”宽约 72–75，以 300 居中会压在外框虚线上；
 * 改为 TOS 右边（240）与外框左边（336）的中点。
 */
const LINK_LABEL_X = 288;

export const WIDE: TrustGeometry = {
  id: 'wide',
  viewBox: [0, 0, 1040, 576],
  font: { title: 20, body: 15 },
  nodes: {
    tos: { x: 16, y: 160, w: 224, h: 208, rx: 12 },
    cache: { x: 360, y: 160, w: 264, h: 64, rx: 8 },
    script: { x: 360, y: 240, w: 264, h: 64, rx: 8 },
    cred: { x: 360, y: 320, w: 264, h: 64, rx: 8 },
    model: { x: 800, y: 160, w: 224, h: 208, rx: 12 },
    review: { x: 336, y: 472, w: 368, h: 88, rx: 12 },
  },
  frame: { x: 336, y: 88, w: 368, h: 320, rx: 14 },
  paths: {
    pull: { d: 'M240 180 H360', line: 'solid' },
    push: { d: 'M360 204 H240', line: 'solid' },
    credTos: { d: 'M360 352 H240', line: 'dotted' },
    ctxFile: { d: 'M624 192 H656 Q664 192 664 200 V224 Q664 232 672 232 H800', line: 'solid' },
    ctxSum: { d: 'M624 272 H656 Q664 272 664 264 V240 Q664 232 672 232 H800', line: 'dashed' },
    credStub: { d: 'M624 352 H636', line: 'solid' },
    reply: { d: 'M800 292 H692 Q684 292 684 300 V472', line: 'solid' },
    reviewPath: { d: 'M360 272 H352 Q344 272 344 280 V472', line: 'solid' },
  },
  lock: [648, 352],
  rest: {
    file: [736, 232],
    amount: [344, 400],
    amountEcho: [664, 252],
    credential: [630, 352],
    reply: [684, 400],
    result: [300, 204],
  },
  labels: [
    { at: [32, 196], anchor: 'start', text: '公司存储桶', title: true, owner: { node: 'tos' } },
    { at: [32, 222], anchor: 'start', text: '火山引擎 TOS', owner: { node: 'tos' } },
    { at: [32, 246], anchor: 'start', text: '开启版本控制', owner: { node: 'tos' } },
    { at: [32, 290], anchor: 'start', text: '项目/', mono: true, owner: { node: 'tos' } },
    { at: [32, 314], anchor: 'start', text: '知识库/', mono: true, owner: { node: 'tos' } },
    { at: [32, 338], anchor: 'start', text: '案例索引.md', mono: true, owner: { node: 'tos' } },
    { at: [360, 120], anchor: 'start', text: '工程师电脑', title: true, owner: { frame: true } },
    { at: [360, 144], anchor: 'start', text: '智通数工AI 桌面版', owner: { frame: true } },
    { at: [376, 188], anchor: 'start', text: '本机缓存', owner: { node: 'cache' } },
    {
      at: [376, 210],
      anchor: 'start',
      text: '~/zhitong · 只缓存用到的文件',
      owner: { node: 'cache' },
    },
    { at: [376, 268], anchor: 'start', text: '脚本计算', owner: { node: 'script' } },
    {
      at: [376, 290],
      anchor: 'start',
      text: '内置 Python · 金额与数量',
      owner: { node: 'script' },
    },
    { at: [376, 348], anchor: 'start', text: '凭据存储', owner: { node: 'cred' } },
    { at: [376, 370], anchor: 'start', text: 'TOS 密钥 · 模型 API Key', owner: { node: 'cred' } },
    { at: [816, 196], anchor: 'start', text: '模型服务', title: true, owner: { node: 'model' } },
    { at: [816, 220], anchor: 'start', text: 'DeepSeek V4.1 Flash', owner: { node: 'model' } },
    { at: [816, 260], anchor: 'start', text: '阅读 · 判断 · 分类', owner: { node: 'model' } },
    { at: [816, 284], anchor: 'start', text: '摘录 · 写作', owner: { node: 'model' } },
    { at: [816, 332], anchor: 'start', text: '不计算金额', owner: { node: 'model' } },
    {
      at: [360, 506],
      anchor: 'start',
      text: '人工复核与签发',
      title: true,
      owner: { node: 'review' },
    },
    {
      at: [360, 534],
      anchor: 'start',
      text: '需人工确认 · 待核 · 由人签发',
      owner: { node: 'review' },
    },
    { at: [LINK_LABEL_X, 152], anchor: 'middle', text: '按需拉取', owner: { path: 'pull' } },
    { at: [LINK_LABEL_X, 170], anchor: 'middle', text: 'tos_pull', mono: true, owner: { path: 'pull' } },
    { at: [LINK_LABEL_X, 224], anchor: 'middle', text: '回读校验', owner: { path: 'push' } },
    { at: [LINK_LABEL_X, 242], anchor: 'middle', text: 'tos_push', mono: true, owner: { path: 'push' } },
    { at: [LINK_LABEL_X, 326], anchor: 'middle', text: '仅用于', owner: { path: 'credTos' } },
    { at: [LINK_LABEL_X, 342], anchor: 'middle', text: '直连公司桶', owner: { path: 'credTos' } },
    { at: [736, 222], anchor: 'middle', text: '对话上下文', owner: { path: 'ctxFile' } },
    { at: [742, 284], anchor: 'middle', text: '回复文字', owner: { path: 'reply' } },
    { at: [648, 392], anchor: 'middle', text: '不进对话', owner: { key: 'lock' } },
  ],
};

export const NARROW: TrustGeometry = {
  id: 'narrow',
  viewBox: [0, 0, 360, 656],
  font: { title: 16, body: 13 },
  nodes: {
    tos: { x: 16, y: 16, w: 328, h: 80, rx: 12 },
    cache: { x: 32, y: 208, w: 232, h: 64, rx: 8 },
    script: { x: 32, y: 288, w: 232, h: 64, rx: 8 },
    cred: { x: 32, y: 368, w: 232, h: 64, rx: 8 },
    review: { x: 16, y: 544, w: 144, h: 96, rx: 12 },
    model: { x: 200, y: 544, w: 144, h: 96, rx: 12 },
  },
  frame: { x: 16, y: 152, w: 328, h: 320, rx: 14 },
  paths: {
    pull: { d: 'M120 96 V208', line: 'solid' },
    push: { d: 'M152 208 V96', line: 'solid' },
    credTos: null,
    ctxFile: { d: 'M264 240 H288 Q296 240 296 248 V544', line: 'solid' },
    ctxSum: { d: 'M264 320 H288 Q296 320 296 328 V544', line: 'dashed' },
    credStub: { d: 'M264 400 H276', line: 'solid' },
    reply: { d: 'M200 592 H160', line: 'solid' },
    reviewPath: { d: 'M32 320 H28 Q24 320 24 328 V544', line: 'solid' },
  },
  lock: [284, 400],
  keys: [
    [40, 118],
    [216, 118],
  ],
  rest: {
    file: [296, 500],
    amount: [24, 480],
    amountEcho: [280, 320],
    credential: [270, 400],
    reply: [180, 592],
    result: [152, 150],
  },
  labels: [
    { at: [32, 48], anchor: 'start', text: '公司存储桶', title: true, owner: { node: 'tos' } },
    { at: [32, 72], anchor: 'start', text: '火山引擎 TOS · 开启版本控制', owner: { node: 'tos' } },
    {
      at: [32, 180],
      anchor: 'start',
      text: '工程师电脑 · 智通数工AI 桌面版',
      title: true,
      owner: { frame: true },
    },
    { at: [48, 236], anchor: 'start', text: '本机缓存', owner: { node: 'cache' } },
    {
      at: [48, 258],
      anchor: 'start',
      text: '~/zhitong · 只缓存用到的文件',
      owner: { node: 'cache' },
    },
    { at: [48, 316], anchor: 'start', text: '脚本计算', owner: { node: 'script' } },
    { at: [48, 338], anchor: 'start', text: '内置 Python · 金额与数量', owner: { node: 'script' } },
    { at: [48, 396], anchor: 'start', text: '凭据存储', owner: { node: 'cred' } },
    { at: [48, 418], anchor: 'start', text: 'TOS 密钥 · 模型 API Key', owner: { node: 'cred' } },
    { at: [28, 572], anchor: 'start', text: '人工复核与签发', owner: { node: 'review' } },
    { at: [28, 596], anchor: 'start', text: '需人工确认', owner: { node: 'review' } },
    { at: [28, 618], anchor: 'start', text: '由人签发', owner: { node: 'review' } },
    { at: [212, 572], anchor: 'start', text: '模型服务', owner: { node: 'model' } },
    { at: [212, 596], anchor: 'start', text: 'DeepSeek V4.1 Flash', owner: { node: 'model' } },
    { at: [212, 618], anchor: 'start', text: '不计算金额', owner: { node: 'model' } },
    { at: [112, 128], anchor: 'end', text: '按需拉取', owner: { path: 'pull' } },
    { at: [112, 146], anchor: 'end', text: 'tos_pull', mono: true, owner: { path: 'pull' } },
    { at: [160, 128], anchor: 'start', text: '回读校验', owner: { path: 'push' } },
    { at: [160, 146], anchor: 'start', text: 'tos_push', mono: true, owner: { path: 'push' } },
    { at: [284, 440], anchor: 'middle', text: '不进对话', owner: { key: 'lock' } },
  ],
};

export const FOCUS: Record<
  FocusKey,
  { nodes: TrustNodeId[]; paths: TrustPathId[]; packets: PacketKind[] }
> = {
  owned: { nodes: ['tos', 'cache'], paths: ['pull', 'push'], packets: ['file', 'result'] },
  credential: { nodes: ['cred'], paths: ['credStub', 'credTos'], packets: ['credential'] },
  source: {
    nodes: ['script', 'review'],
    paths: ['reviewPath', 'ctxSum'],
    packets: ['amount', 'amountEcho'],
  },
  review: {
    nodes: ['review', 'model'],
    paths: ['reply', 'reviewPath'],
    packets: ['reply', 'amount'],
  },
  file: { nodes: ['tos', 'cache', 'model'], paths: ['pull', 'ctxFile'], packets: ['file'] },
  amount: {
    nodes: ['script', 'review'],
    paths: ['reviewPath', 'ctxSum'],
    packets: ['amount', 'amountEcho'],
  },
  reply: { nodes: ['model', 'review'], paths: ['reply'], packets: ['reply'] },
  result: { nodes: ['cache', 'tos'], paths: ['push'], packets: ['result'] },
};

/** 电脑外框内的三条车道。 */
export const LANES: TrustNodeId[] = ['cache', 'script', 'cred'];

/**
 * 某个图元在当前聚焦键下是否高亮（focus 为 null 时全部高亮）。
 * @param focus - 聚焦键。
 * @param owner - 图元归属。
 * @returns 高亮为 true。
 */
export function isLit(focus: FocusKey | null, owner: LabelOwner | { packet: PacketKind }): boolean {
  if (!focus) return true;
  const f = FOCUS[focus];
  if ('node' in owner) return f.nodes.includes(owner.node);
  if ('path' in owner) return f.paths.includes(owner.path);
  if ('packet' in owner) return f.packets.includes(owner.packet);
  if ('key' in owner) return focus === 'credential';
  return f.nodes.some((n) => LANES.includes(n));
}

/** 说明卡打开时对应的聚焦键（05 章 §2.5）。 */
export const NODE_FOCUS: Record<TrustNodeId, FocusKey> = {
  tos: 'owned',
  cache: 'file',
  script: 'source',
  cred: 'credential',
  model: 'review',
  review: 'review',
};
