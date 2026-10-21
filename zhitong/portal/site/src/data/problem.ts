/**
 * 它解决什么（03 章 §2.2、§2.4）：旧方式九个面板、100 个点击标记（固定种子）、对话线程与对照列表。
 * 对照列表逐字取自 `zhitong/portal/门户文案.txt`【它解决什么】（引号统一为中文引号）。
 */
import { formatMoney, formatPercent } from '../lib/format';
import { ROLE_FIGURES } from './roles';

export type LegacyId =
  | 'tag'
  | 'kit'
  | 'extract'
  | 'check'
  | 'metrics'
  | 'control'
  | 'report'
  | 'bills'
  | 'estimate';
export type ThreadRowId =
  | 'open'
  | 'inventory'
  | 'check'
  | 'metrics'
  | 'control'
  | 'idle'
  | 'report'
  | 'archive';

export interface LegacyPanel {
  id: LegacyId;
  label: '标注' | '齐套' | '抽取' | '核对' | '指标' | '投控' | '报告' | '清单' | '概算';
  /** 该面板的点击标记数（示意）。 */
  clicks: number;
  /** 汇入线程 / 不再单独做 / 本项目未调用。 */
  fate: 'converge' | 'retired' | 'idle';
  /** fate 为 converge 或 idle 时的线程行。 */
  target: ThreadRowId | null;
  /** 待确认标记数。 */
  pending: 0 | 2 | 3;
  /** 显示“上次结果”。 */
  lastResult: boolean;
  /** 接收“送审计价表.xlsx”扇形线。 */
  fan: boolean;
}

export const LEGACY_PANELS: readonly LegacyPanel[] = [
  { id: 'tag', label: '标注', clicks: 18, fate: 'retired', target: null, pending: 3, lastResult: false, fan: false },
  { id: 'kit', label: '齐套', clicks: 8, fate: 'converge', target: 'inventory', pending: 0, lastResult: false, fan: false },
  { id: 'extract', label: '抽取', clicks: 12, fate: 'retired', target: null, pending: 2, lastResult: false, fan: false },
  { id: 'check', label: '核对', clicks: 10, fate: 'converge', target: 'check', pending: 0, lastResult: true, fan: true },
  { id: 'metrics', label: '指标', clicks: 8, fate: 'converge', target: 'metrics', pending: 0, lastResult: true, fan: true },
  { id: 'control', label: '投控', clicks: 18, fate: 'converge', target: 'control', pending: 3, lastResult: false, fan: true },
  { id: 'report', label: '报告', clicks: 10, fate: 'converge', target: 'report', pending: 0, lastResult: false, fan: false },
  { id: 'bills', label: '清单', clicks: 6, fate: 'idle', target: 'idle', pending: 0, lastResult: false, fan: false },
  { id: 'estimate', label: '概算', clicks: 10, fate: 'idle', target: 'idle', pending: 0, lastResult: false, fan: false },
];
// 点击标记合计 100 个（18+8+12+10+8+18+10+6+10），落在 60–150 之间，只作示意，页面不显示该数。
// 标注与投控最多，对应勘察记录“点击主要花在逐行标注确认与逐条异常复核上”。
// 扇形线只连核对、指标、投控：三者各自打开同一个计价表选择器且不共享选择。

/** 面板内热点（百分比），按 k % 6 轮流取用；jx、jy 为抖动幅度。 */
const HOTSPOTS = [
  { x: 24, y: 34, jx: 10, jy: 6 }, // 选择文件
  { x: 54, y: 34, jx: 6, jy: 6 }, // 开始
  { x: 50, y: 50, jx: 36, jy: 3 }, // 表格行 1
  { x: 50, y: 62, jx: 36, jy: 3 }, // 表格行 2
  { x: 50, y: 74, jx: 36, jy: 3 }, // 表格行 3
  { x: 21, y: 88, jx: 8, jy: 4 }, // 导出
] as const;

/**
 * mulberry32 伪随机数（标准实现）。
 * @param seed - 32 位种子。
 * @returns 每次调用返回 [0, 1) 的下一个数。
 */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface ClickMarker {
  panel: LegacyId;
  k: number;
  x: number;
  y: number;
}

/**
 * 由固定种子生成全部点击标记（服务端与浏览器结果相同）。
 * @returns 100 个标记，按面板、序号排列。
 */
export function buildClickMarkers(): ClickMarker[] {
  return LEGACY_PANELS.flatMap((p, pi) => {
    const rnd = mulberry32(20261020 + pi);
    return Array.from({ length: p.clicks }, (_, k) => {
      const h = HOTSPOTS[k % HOTSPOTS.length]!;
      return {
        panel: p.id,
        k,
        x: +(h.x + (rnd() - 0.5) * 2 * h.jx).toFixed(1),
        y: +(h.y + (rnd() - 0.5) * 2 * h.jy).toFixed(1),
      };
    });
  });
}

export const CLICK_MARKERS: readonly ClickMarker[] = buildClickMarkers();

/** 待确认菱形所在的表格行（百分比）。 */
export const PENDING_ROWS = [50, 62, 74] as const;

export interface ThreadRow {
  id: ThreadRowId;
  label: string;
  command: string | null;
  result: string;
  /** 结果带“需人工确认”徽标。 */
  manual: boolean;
  /** 本项目未调用（灰色）。 */
  muted: boolean;
}

const F = ROLE_FIGURES;

/** 对话线程 8 行（§2.2 线程表，顺序同表）。 */
export const THREAD_ROWS: readonly ThreadRow[] = [
  { id: 'open', label: '读取项目说明', command: 'project_doc.py show', result: '2026-007 · 结算审核 · 审定', manual: false, muted: false },
  { id: 'inventory', label: '资料盘点', command: 'inventory.py scan', result: '已列出缺件与待确认项', manual: false, muted: false },
  {
    id: 'check',
    label: '运行核对',
    command: 'reconcile.py run',
    result: `核减 ${formatMoney(F.reduction)} 元 · 核减率 ${formatPercent(F.reductionRate)} · 需人工确认`,
    manual: true,
    muted: false,
  },
  {
    id: 'metrics',
    label: '计算指标',
    command: 'indicator.py run',
    result: `审定单方（土建）${formatMoney(F.approvedUnit)} 元/m² · 需人工确认`,
    manual: true,
    muted: false,
  },
  { id: 'control', label: '投控检测', command: 'tk.py detect', result: '疑似异常待您逐条判定：确认 / 误报', manual: false, muted: false },
  { id: 'idle', label: '清单框架 · 概算', command: null, result: '本项目未调用', manual: false, muted: true },
  { id: 'report', label: '报告初稿', command: 'report.py export', result: '成果/某综合办公楼结算审核报告-初稿.docx', manual: false, muted: false },
  { id: 'archive', label: '归档登记', command: 'archive.py apply', result: '案例索引追加 2026-007 一行', manual: false, muted: false },
];

/** 结果行里“需人工确认”之前的部分（徽标单独渲染）。 */
export const MANUAL_SUFFIX = '需人工确认';

/** 对照列表（逐字取自门户文案稿）。 */
/** 文案（§2.2）。 */
export const PROBLEM_COPY = {
  /** 按用户意见：原眉题放大为章节标题，原大标题删除。 */
  title: '它解决什么',
  subtitle: '依据对一套现有造价 AI 系统的代码与文档审阅',
  counterOld: { value: '60–150', head: '60', tail: '–150', unit: '次点击', note: '一个典型项目，据代码走查估算（估算值，非实测）' },
  counterNew: { value: '一次对话', note: '顺序由对话决定，不由页面决定' },
  counterSr: '约 60 至 150 次点击（估算值，非实测）',
  captions: [
    '各功能各点一轮：打开、选文件、等待、复核、导出',
    '同一份计价表，核对、指标、投控各选一遍',
    '工程师自己当调度员：先标注再齐套，再逐个启动',
    '一次对话：按需调用，结果有固定去处',
  ],
  gridCaption: '旧方式：九个功能各点一轮（每个圆点代表一次点击，示意）',
  threadCaption: '新方式：同一项目在一次对话中完成（示例）',
  threadTitle: '对话 · 2026-007 某综合办公楼（示例）',
  userBubble:
    '打开 2026-007 某综合办公楼：盘点资料，核对送审和审定计价表，算指标、查投控，写结算审核报告，最后归档。',
  fileTag: '送审计价表.xlsx',
  retired: '不再单独做',
  lastResult: '上次结果',
  buttons: { pick: '选择文件', start: '开始', export: '导出' },
  sceneDesc: `示意图。旧方式：标注、齐套、抽取、核对、指标、投控、报告、清单、概算九个功能各自要打开、选文件、等待、复核、导出，一个典型项目约 60 至 150 次点击（估算值，非实测）。新方式（示例）：2026-007 某综合办公楼在一次对话中依次读取项目说明、盘点资料、核对（核减 ${formatMoney(F.reduction)} 元，核减率 ${formatPercent(F.reductionRate)}，需人工确认）、计算指标（审定单方 ${formatMoney(F.approvedUnit)} 元/m²，需人工确认）、投控检测、写报告初稿并归档；清单框架与概算本项目未调用；标注与抽取不再单独做。`,
} as const;
