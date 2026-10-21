/**
 * 使用流程（05 章 §1）：四步文案、写入位置、文档链接与四段示例会话的节拍。
 * 场景三的金额、比例、行数一律取自 `demo.ts` 的 `RECONCILE`（00 章 §8.2 的唯一出处），本文件不写这些数的字面量（AC-05-14）。
 */
import { RECONCILE } from './demo';
import { formatInt, formatMoney, formatPercent } from '../lib/format';

export type StepId = 'import' | 'open' | 'task' | 'archive';
export type ResultStatus = 'ok' | 'partial' | 'empty' | 'insufficient';

/** 一拍示例会话（05 章 §1.4）。`gap` 为距上一拍结束的秒数。 */
export type SceneBeat =
  | { kind: 'drop'; gap: number; file: string; size: string }
  | { kind: 'user'; gap: number; text: string; attachment?: string }
  | {
      kind: 'tool';
      gap: number;
      label: string;
      command: string;
      run: number;
      ms: number;
      result?: string;
      title?: string;
    }
  | { kind: 'stream'; gap: number; text: string }
  | {
      kind: 'status';
      gap: number;
      status: ResultStatus;
      counts?: { warn?: number; info?: number };
      manual?: boolean;
      lines?: string[];
    }
  | { kind: 'card'; gap: number; card: 'projects' | 'inventory' | 'reconcile' | 'files' }
  | {
      kind: 'ask';
      gap: number;
      title: string;
      lines: string[];
      options: [string, string];
      pick: 0 | 1;
    }
  | {
      kind: 'push';
      gap: number;
      title: string;
      rows: { path: string; size: string; note?: string }[];
    }
  | { kind: 'diff'; gap: number; file: '项目说明.md' | '案例索引.md' }
  | {
      kind: 'note';
      gap: number;
      title: string;
      rows: { field: string; value: string }[];
      footnote: string;
    }
  | { kind: 'outcome'; gap: number; text: string };

export interface WorkflowStep {
  id: StepId;
  label: '第一步' | '第二步' | '第三步' | '第四步';
  title: string;
  body: string;
  /** “写到哪里”：mono 为路径芯片；mono 为 false 的项按原文内联（含 ` · ` 分隔）。 */
  writes: { text: string; mono: boolean }[];
  /** href 必须在 06 章路由表内。 */
  doc: { text: string; href: string };
  scene: SceneBeat[];
  outcome: string;
  /** 输入框占位文字（不可输入）。 */
  placeholder: string;
}

/** 区块文案（05 章 §1.2）。 */
export const WORKFLOW_COPY = {
  eyebrow: '使用流程',
  title: '四步，从安装到归档',
  lead: '从连接公司的桶开始，到归档回桶结束。',
  stepsLabel: '使用流程四步',
  writesTitle: '写到哪里',
  windowTitle: '智通数工AI · 示例会话',
  badge: '示例',
  pause: '暂停示例',
  play: '播放示例',
  replay: (n: number) => `重播第 ${n} 步示例`,
  sceneLabel: (n: number, title: string) => `第 ${n} 步示例：${title}`,
  markerLabel: (n: number, title: string) => `第 ${n} 步：${title}`,
} as const;

const S = RECONCILE.summary;
const money = (v: number) => formatMoney(v);
const chapter = (name: string) => {
  const found = RECONCILE.chapters.find((c) => c.chapter_name === name);
  if (!found) throw new Error(`RECONCILE.chapters 缺少 ${name}`);
  return found;
};

/** 示例项目（00 章 §8.1）。 */
export const PROJECT = {
  dir: '2026-007-某综合办公楼',
  code: '2026-007',
  name: '某综合办公楼',
  /** 建筑面积 m²。 */
  area: 18600,
} as const;

/** 桶内 `项目/` 的 9 个目录，按 `tos_ls` 的字典序（05 章 §0.1）。 */
export const BUCKET_PROJECTS = [
  '2025-036-某安置房三期',
  '2025-041-某研发楼',
  '2026-001-某学校扩建',
  '2026-002-某市政道路改造',
  '2026-003-某人才公寓',
  '2026-004-某社区卫生服务中心',
  '2026-005-某雨污分流工程',
  '2026-006-某体育公园',
  '2026-007-某综合办公楼',
] as const;

/** 资料盘点（05 章 §0.1，实跑 `inventory.py scan` 所得）。 */
export const INVENTORY = { required: 7, ready: 3, pending: 1, missing: 3 } as const;
export const INVENTORY_RATE = formatPercent(INVENTORY.ready / INVENTORY.required);
export const INVENTORY_MAX = formatPercent(
  (INVENTORY.ready + INVENTORY.pending) / INVENTORY.required,
);

/** 盘点结果卡（行顺序固定）。 */
export const INVENTORY_CARD = {
  title: '资料盘点 · 结算审核 · 审定阶段（含此前各阶段）',
  metric: `必备 ${INVENTORY.required} · 已备 ${INVENTORY.ready} · 待确认 ${INVENTORY.pending} · 缺失 ${INVENTORY.missing} ｜ 齐备率 ${INVENTORY_RATE}（上限 ${INVENTORY_MAX}）`,
  rows: [
    { label: '缺失（必备）', parts: [{ t: '结算审核报告 · 结算审定单 · 审核汇总表' }] },
    {
      label: '待确认',
      parts: [
        { t: '变更签证费用 ← ' },
        { t: '资料/5 变更资料/签证单汇总.xlsx', mono: true },
        { t: '（文件名弱证据）' },
      ],
    },
    { label: '重要资料未找到', parts: [{ t: '投标报价文件' }] },
    { label: '未判出类目', parts: [{ t: '资料/6 其他/扫描件0001.pdf', mono: true }] },
  ] as { label: string; parts: { t: string; mono?: boolean }[] }[],
  footnote: '资料清单由旧系统迁来，待签核；盘点只看文件名，不给资料贴标签。',
};

/** 核对卡：上排 4 个数、中排 4 条横条（宽度按 |核减额| ÷ 最大一章）、下排逐行计数。 */
export const RECONCILE_CARD = (() => {
  const bars = ['混凝土及钢筋混凝土工程', '措施项目', '土石方工程', '门窗工程'].map((name) =>
    chapter(name),
  );
  const max = Math.max(...bars.map((b) => Math.abs(b.adjust)));
  return {
    figures: [
      { label: '送审合计', value: S.a_total, unit: '元', format: 'money' as const },
      { label: '审定合计', value: S.b_total, unit: '元', format: 'money' as const },
      { label: '核减额', value: S.adjust_amount, unit: '元', format: 'money' as const },
      { label: '核减率', value: S.adjust_rate, unit: '', format: 'percent' as const },
    ],
    bars: bars.map((b) => ({
      name: b.chapter_name,
      kind: b.adjust < 0 ? ('核增' as const) : ('核减' as const),
      amount: money(Math.abs(b.adjust)),
      ratio: Math.abs(b.adjust) / max,
    })),
    rows: `逐行 ${formatInt(S.count_total)}：一致 ${formatInt(S.count_same)} · 调整 ${formatInt(S.count_changed)} · 仅送审 ${formatInt(S.count_only_a)} · 仅审定 ${formatInt(S.count_only_b)} · 待核实 ${formatInt(S.count_uncertain)}`,
  };
})();

const CHECK_DIR = '工作/2026-10-19-核对/';
/** 产出文件条（场景三第 8 拍）。 */
export const OUTPUT_FILES = [
  `${CHECK_DIR}核对结果.xlsx`,
  `${CHECK_DIR}result.json`,
  `${CHECK_DIR}待确认清单.md`,
];

/** 单方造价（土建部分，按建筑面积），两位小数。 */
export const UNIT_COST = money(Math.round((S.b_total / PROJECT.area) * 100) / 100);
/** 案例索引“关键指标”（05 章 §0.1）。 */
export const KEY_METRICS = `审定 ${money(S.b_total)} 元；核减率 ${formatPercent(S.adjust_rate)}；土建单方 ${UNIT_COST} 元/m²（按建筑面积）`;

/** `项目说明.md` 改动卡：`-` 删除，`+` 插入，`' '` 上下文。 */
export const DIFF_PROJECT_DOC: { op: '-' | '+' | ' '; text: string }[] = [
  { op: '-', text: '状态: 进行中' },
  { op: '+', text: '状态: 已归档' },
  { op: ' ', text: '## 已出成果' },
  {
    op: '-',
    text: '尚无。成果推送到 `成果/` 后由 zt-archive 在这里逐行登记（相对项目目录的路径）。',
  },
  { op: '+', text: '- 成果/某综合办公楼结算审核报告.docx' },
  { op: '+', text: '- 成果/结算审定单.xlsx' },
  { op: '+', text: '- 成果/审核汇总表.xlsx' },
  { op: ' ', text: '## 工作记录' },
  {
    op: '+',
    text: '- 2026-10-28 归档。遗留：工作/2026-10-19-核对/待确认清单.md 尚有 2 条未确认；工作/2026-10-19-投控/待确认清单.md 尚有 4 条未确认。',
  },
];

/** `案例索引.md` 改动卡：表头 8 列同 `zt-project/templates/案例索引.md`；变动 3 格逐格替换。 */
export const CASE_INDEX = {
  columns: ['编号', '工程名', '业态', '规模', '咨询类型', '关键指标', '成果链接', '状态'],
  context: ['2026-006', '某体育公园', '…', '…', '…', '…', '…', '…'],
  before: [
    '2026-007',
    '某综合办公楼',
    '办公',
    '建筑面积 18,600.00 m²',
    '结算审核',
    '',
    '',
    '进行中',
  ],
  after: [
    '2026-007',
    '某综合办公楼',
    '办公',
    '建筑面积 18,600.00 m²',
    '结算审核',
    KEY_METRICS,
    `项目/${PROJECT.dir}/成果/`,
    '已归档',
  ],
  /** 逐格替换的列序号（关键指标、成果链接、状态）。 */
  changed: [5, 6, 7],
};

const STREAM_TASK = `送审合计 ${money(S.a_total)} 元，审定合计 ${money(S.b_total)} 元，核减额 ${money(S.adjust_amount)} 元，核减率 ${formatPercent(S.adjust_rate)}，均为脚本取数，需人工复核。核减最多的是混凝土及钢筋混凝土工程 ${money(chapter('混凝土及钢筋混凝土工程').adjust)} 元；门窗工程核增 ${money(Math.abs(chapter('门窗工程').adjust))} 元。量差 ${money(S.diff_by_qty)} 元，价差 ${money(S.diff_by_price)} 元。另有 ${formatInt(S.count_uncertain)} 行待核实，已写进待确认清单。`;

const IMPORT_RESULT =
  '已导入「某某工程造价咨询有限公司」的配置包：tos://zt-demo/示例咨询/（tos-cn-beijing.volces.com，cn-beijing）。密钥已存入本机凭据存储（ZT_TOS_ACCESS_KEY_ID、ZT_TOS_SECRET_ACCESS_KEY），TOS 工具已按新设置重新加载。';

/** 示例配置包内 `zhitong.config.json` 的字段（场景一第 4 拍的页边标注；密钥值不出现）。 */
export const IMPORT_NOTE_ROWS = [
  { field: 'format', value: 'zhitong.config/1' },
  { field: 'company.name', value: '某某工程造价咨询有限公司' },
  { field: 'tos.endpoint', value: 'tos-cn-beijing.volces.com' },
  { field: 'tos.region', value: 'cn-beijing' },
  { field: 'tos.bucket', value: 'zt-demo' },
  { field: 'tos.prefix', value: '示例咨询' },
  { field: 'tos.accessKeyId', value: '●●●●●●●● 不回显' },
  { field: 'tos.secretAccessKey', value: '●●●●●●●● 不回显' },
];

const ARCHIVE_APPLY = `archive.py apply --key-metrics "${KEY_METRICS}"`;

export const WORKFLOW_STEPS: WorkflowStep[] = [
  {
    id: 'import',
    label: '第一步',
    title: '导入配置包',
    body: '安装后首次启动，先在欢迎页填写模型 API Key，再把服务方交付的配置包拖进对话。系统校验内容，把访问密钥写入本机凭据存储、把桶的地址写入工作配置，不回显密钥，随后列出桶里的项目。',
    writes: [
      { text: '本机凭据存储（2 个密钥引用名）', mono: false },
      { text: ' · ', mono: false },
      { text: '当前 profile 的 TOS 设置', mono: false },
    ],
    doc: { text: '读文档：导入配置包', href: '/docs/config-package/' },
    placeholder: '把配置包拖到这里，或告诉我它的路径',
    outcome: '已连接 · 找到 9 个项目',
    scene: [
      { kind: 'drop', gap: 0.4, file: '示例咨询-配置包.zip', size: '2.1 KB' },
      {
        kind: 'user',
        gap: 0.1,
        attachment: '示例咨询-配置包.zip',
        text: '这是公司的配置包，帮我导入。',
      },
      {
        kind: 'tool',
        gap: 0.4,
        label: '导入配置包',
        command: 'config_import',
        run: 0.9,
        ms: 420,
        result: IMPORT_RESULT,
      },
      {
        kind: 'note',
        gap: 0,
        title: 'config_import 校验的字段',
        rows: IMPORT_NOTE_ROWS,
        footnote: '另查：文件 ≤ 1 MiB；zip 内恰好一个 zhitong.config.json；不认识的字段一律拒收。',
      },
      {
        kind: 'stream',
        gap: 0.3,
        text: '导入完成：桶 zt-demo，前缀 示例咨询。两个访问密钥存进了本机凭据存储，对话里不会显示。我先看看桶里有哪些项目。',
      },
      {
        kind: 'tool',
        gap: 0.3,
        label: '列出项目',
        command: 'tos_ls 项目/',
        run: 0.7,
        ms: 610,
        result: 'tos://zt-demo/示例咨询/项目/：9 个目录，0 个文件',
      },
      {
        kind: 'stream',
        gap: 0.2,
        text: '已连接。项目/ 下有 9 个项目，最近的是 2026-007-某综合办公楼。要打开哪一个？',
      },
      { kind: 'outcome', gap: 0.3, text: '已连接 · 找到 9 个项目' },
    ],
  },
  {
    id: 'open',
    label: '第二步',
    title: '开项目',
    body: '选择桶里已有项目，或新建一个。系统先读项目说明，缺少时按目录结构生成草稿，再按咨询类型对照应收资料清单盘点：缺什么直接说明，不替资料贴标签。',
    writes: [
      { text: '项目说明.md', mono: true },
      { text: '「资料盘点」小节', mono: false },
      { text: ' · ', mono: false },
      { text: '工作/2026-10-19-盘点/', mono: true },
    ],
    doc: { text: '读文档：开项目与资料盘点', href: '/docs/features/project/' },
    placeholder: '说说要做什么',
    outcome: `必备 ${INVENTORY.required} 项 · 已备 ${INVENTORY.ready} · 待确认 ${INVENTORY.pending} · 缺失 ${INVENTORY.missing}`,
    scene: [
      { kind: 'card', gap: 0.3, card: 'projects' },
      { kind: 'user', gap: 0.6, text: '打开 2026-007' },
      {
        kind: 'tool',
        gap: 0.3,
        label: '读取项目说明',
        command: `tos_pull 项目/${PROJECT.dir}/项目说明.md`,
        run: 0.5,
        ms: 380,
      },
      {
        kind: 'tool',
        gap: 0.1,
        label: '解析项目说明',
        command: 'project_doc.py show',
        run: 0.3,
        ms: 160,
      },
      {
        kind: 'stream',
        gap: 0.2,
        text: '2026-007 某综合办公楼：结算审核，审定阶段；办公，建筑面积 18,600.00 m²；别名 合同号 HT-DEMO-07。关键文件指引里有合同、招标文件、工程量清单、送审与审定计价表的位置。接着按结算审核的资料清单盘点。',
      },
      {
        kind: 'tool',
        gap: 0.3,
        label: '列出全部文件',
        command: `tos_ls 项目/${PROJECT.dir}/ recursive`,
        run: 0.6,
        ms: 540,
      },
      {
        kind: 'tool',
        gap: 0.1,
        label: '资料盘点',
        command: 'inventory.py scan',
        run: 0.8,
        ms: 730,
      },
      { kind: 'status', gap: 0.2, status: 'ok', counts: { warn: 4, info: 1 } },
      { kind: 'card', gap: 0.1, card: 'inventory' },
      {
        kind: 'stream',
        gap: 0.3,
        text: '盘点只看了文件名，没有读内容。缺 3 项必备资料：结算审核报告、结算审定单、审核汇总表。变更签证费用只找到疑似文件 签证单汇总.xlsx，打开确认后才能算已备。扫描件0001.pdf 从文件名判断不出类目，可以看图确认。',
      },
      {
        kind: 'outcome',
        gap: 0.3,
        text: `必备 ${INVENTORY.required} 项 · 已备 ${INVENTORY.ready} · 待确认 ${INVENTORY.pending} · 缺失 ${INVENTORY.missing}`,
      },
    ],
  },
  {
    id: 'task',
    label: '第三步',
    title: '对话完成任务',
    body: '直接说要做什么，例如“核对送审和审定计价表”“检测投控异常”“写结算审核报告”。判断、分类、摘录和写作由模型完成；金额、数量、核对、指标由脚本计算；每一步的状态如实转述。',
    writes: [
      { text: CHECK_DIR, mono: true },
      { text: '：', mono: false },
      { text: 'result.json', mono: true },
      { text: ' · ', mono: false },
      { text: '核对结果.xlsx', mono: true },
      { text: ' · ', mono: false },
      { text: '待确认清单.md', mono: true },
    ],
    doc: { text: '读文档：送审审定核对', href: '/docs/features/check/' },
    placeholder: '说说要做什么',
    outcome: `核减 ${money(S.adjust_amount)} 元 · ${formatPercent(S.adjust_rate)} · 需人工确认`,
    scene: [
      { kind: 'user', gap: 0.4, text: '核对一下送审和审定计价表' },
      {
        kind: 'tool',
        gap: 0.3,
        label: '拉取文件',
        command: 'tos_pull 资料/4 结算资料/送审计价表.xlsx',
        run: 0.5,
        ms: 820,
      },
      {
        kind: 'tool',
        gap: 0.1,
        label: '拉取文件',
        command: 'tos_pull 资料/4 结算资料/审定计价表.xlsx',
        run: 0.5,
        ms: 760,
      },
      {
        kind: 'tool',
        gap: 0.1,
        label: '预检计价表',
        command: 'probe.py probe',
        run: 0.4,
        ms: 290,
        result: '2 份都是计价表（kind=costsheet）',
      },
      {
        kind: 'tool',
        gap: 0.1,
        label: '运行核对',
        command: 'reconcile.py run --basis auto',
        run: 1.4,
        ms: 3840,
      },
      { kind: 'status', gap: 0.2, status: 'ok', manual: true },
      { kind: 'card', gap: 0.1, card: 'reconcile' },
      { kind: 'card', gap: 0.2, card: 'files' },
      { kind: 'stream', gap: 0.2, text: STREAM_TASK },
      {
        kind: 'outcome',
        gap: 0.3,
        text: `核减 ${money(S.adjust_amount)} 元 · ${formatPercent(S.adjust_rate)} · 需人工确认`,
      },
    ],
  },
  {
    id: 'archive',
    label: '第四步',
    title: '归档回桶',
    body: '归档时核对“成果”与“工作”目录是否完整，经您确认后推送回桶并回读校验，更新项目说明和案例索引，供下一个项目对标、下一位同事接手。',
    writes: [
      { text: '桶内 ', mono: false },
      { text: '成果/', mono: true },
      { text: '、', mono: false },
      { text: '工作/', mono: true },
      { text: ' · ', mono: false },
      { text: '项目说明.md', mono: true },
      { text: '（已出成果、状态）', mono: false },
      { text: ' · ', mono: false },
      { text: '案例索引.md', mono: true },
      { text: '（本项目一行）', mono: false },
    ],
    doc: { text: '读文档：归档与案例索引', href: '/docs/features/archive/' },
    placeholder: '说说要做什么',
    outcome: '回桶 58 个文件 · 回读校验通过',
    scene: [
      { kind: 'user', gap: 0.4, text: '2026-007 做完了，归档吧' },
      {
        kind: 'tool',
        gap: 0.3,
        label: '列出项目文件',
        command: `tos_ls 项目/${PROJECT.dir}/ recursive`,
        run: 0.6,
        ms: 640,
      },
      {
        kind: 'tool',
        gap: 0.1,
        label: '拉取案例索引',
        command: 'tos_pull 案例索引.md',
        run: 0.4,
        ms: 310,
      },
      { kind: 'tool', gap: 0.1, label: '归档核对', command: 'archive.py check', run: 0.5, ms: 450 },
      {
        kind: 'status',
        gap: 0.2,
        status: 'ok',
        counts: { warn: 2 },
        lines: [
          '2026-10-19-核对/待确认清单.md 还有 2 条未勾选的待确认事项',
          '2026-10-19-投控/待确认清单.md 还有 4 条未勾选的待确认事项',
        ],
      },
      {
        kind: 'ask',
        gap: 0.3,
        title: '按这样归档？',
        lines: [
          '成果 3 份：某综合办公楼结算审核报告.docx、结算审定单.xlsx、审核汇总表.xlsx',
          '推送：成果/ 3 个文件、工作/ 6 个目录 53 个文件',
          `案例索引关键指标：${KEY_METRICS}`,
          '提醒：两份待确认清单共 6 条未勾选，作为遗留写进项目说明',
        ],
        options: ['按这样归档', '先不归档'],
        pick: 0,
      },
      {
        kind: 'push',
        gap: 0.3,
        title: 'tos_push × 56',
        rows: [
          { path: '成果/某综合办公楼结算审核报告.docx', size: '1.2 MiB' },
          { path: '成果/结算审定单.xlsx', size: '38.6 KiB' },
          { path: '成果/审核汇总表.xlsx', size: '52.3 KiB' },
          { path: '工作/2026-10-19-盘点/', size: '2 个文件 10.9 KiB' },
          { path: '工作/2026-10-19-核对/', size: '3 个文件 2.8 MiB' },
          { path: '工作/2026-10-20-报告/', size: '39 个文件 1.6 MiB' },
          { path: '另 3 个目录 · 9 个文件', size: '', note: '投控、图纸核对、指标' },
        ],
      },
      {
        kind: 'tool',
        gap: 0.2,
        label: '登记',
        command: 'archive.py apply --key-metrics "…"',
        title: ARCHIVE_APPLY,
        run: 0.4,
        ms: 230,
      },
      { kind: 'diff', gap: 0.2, file: '项目说明.md' },
      { kind: 'diff', gap: 0.2, file: '案例索引.md' },
      {
        kind: 'push',
        gap: 0.2,
        title: 'tos_push × 2',
        rows: [
          { path: '项目说明.md', size: '3.6 KiB' },
          {
            path: '案例索引.md',
            size: '4.1 KiB',
            note: '覆盖了 2026-10-27 16:42 的旧版本，可从版本历史恢复',
          },
        ],
      },
      {
        kind: 'stream',
        gap: 0.2,
        text: '已归档 2026-007：推送 58 个文件，回读校验全部通过。项目说明的状态改为「已归档」，登记了 3 份成果；案例索引只更新了本项目这一行。6 条待确认事项作为遗留写进了项目说明的工作记录。',
      },
      { kind: 'outcome', gap: 0.3, text: '回桶 58 个文件 · 回读校验通过' },
    ],
  },
];
