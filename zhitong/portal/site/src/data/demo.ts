/**
 * 首屏工作示例的全部数据（02 章 §8.1）。字段与数值与 spec 一致；唯一改动见 `RECONCILE.summary.diff_by_price` 的注释。
 * 05 章等其它章节的核对数字也从这里导入（05 章 §2）。
 */
import type { SceneId } from '../types/portal';
export { formatMoney } from '../lib/format';

export type Principle = 'dialog' | 'script' | 'review';
export type HitlState = 'confirmed' | 'dismissed' | 'pending';
export type HotspotId = 'reduction' | 'sheet-tabs' | 'decision' | 'anomaly-source' | 'room-list' | 'view-toggle';

/** 流式片段：字符串逐字出现；mono 片段整段出现、等宽显示；带 hotspot 的片段出现后可点 */
export type Seg = string | { t: string; mono: true; hotspot?: HotspotId };
const m = (t: string, hotspot?: HotspotId): Seg => ({ t, mono: true, ...(hotspot ? { hotspot } : {}) });

export interface ToolSpec {
  label: string; // 中文标签
  name: string; // 等宽原名
  args: string; // 等宽参数摘要（窄屏省略）
  times?: number; // 并发次数，>1 显示 ×n
  elapsed: string; // 产品实际耗时量级
  detail: string; // 完成后的结果行
  warnings?: string[]; // 工具返回的警告原文
}
export interface AskSpec {
  tool: 'ask_user_question';
  header: string;
  question: string;
  detail: string;
  options: { value: HitlState; label: string; description: string }[];
  reasonLabel: string;
  reasons: Record<HitlState, string>;
  submitLabel: string;
  anomalyId: string;
}
export interface OutputFile {
  name: string;
  dir: string;
}
export type Cue =
  | 'files'
  | 'probe'
  | 'loading'
  | 'summary'
  | 'chapters'
  | 'rows'
  | 'warnings'
  | 'tk-loading'
  | 'distribution'
  | 'focus'
  | 'focus-a1'
  | 'record'
  | 'plot'
  | 'unit'
  | 'frame'
  | 'rooms'
  | 'grid'
  | 'scan-s1'
  | 'zoom'
  | 'scan-e4'
  | 'highlight';

export type Branch<T> = T | Record<HitlState, T>;
export type Step = { at: number; p: Principle } & (
  | { kind: 'compose'; text: string; dur: number }
  | { kind: 'send' }
  | { kind: 'assistant' }
  | { kind: 'tool'; run: number; tool: Branch<ToolSpec> }
  | { kind: 'say'; segs: Branch<Seg[]> }
  | { kind: 'cue'; cue: Cue }
  | { kind: 'ask'; ask: AskSpec }
  | { kind: 'cursor'; target: string; click: boolean; dur: number }
  | { kind: 'type'; target: string; text: string; dur: number }
  | { kind: 'mark'; label: 'ask:submitted' }
  | { kind: 'status'; status: 'ok'; manual: true }
  | { kind: 'files'; files: OutputFile[] }
  | { kind: 'hotspots'; ids: HotspotId[] }
);

export interface Scene {
  id: SceneId;
  tab: string;
  icon: 'sheet' | 'shield' | 'cad';
  prompt: string;
  steps: Step[];
  end: number;
  hold: number;
  footnote: string;
  footerFile: OutputFile & { state: string };
}

export const STREAM_CPS = 36;
export const STREAM_PAUSE = 0.12;
const PUNCT = /[，。；：、！？]/g;
/** 段落时长（秒）：字数 ÷ 36 + 中文标点数 × 0.12；mono 片段计 1 字 */
export function streamDuration(segs: Seg[]): number {
  let units = 0;
  let pauses = 0;
  for (const s of segs) {
    if (typeof s === 'string') {
      units += [...s].length;
      pauses += s.match(PUNCT)?.length ?? 0;
    } else units += 1;
  }
  return units / STREAM_CPS + pauses * STREAM_PAUSE;
}

const DIR_CHECK = '工作/2026-10-19-核对/';
const DIR_TK = '工作/2026-10-19-投控/';
const DIR_CAD = '工作/2026-10-19-图纸核对/';
const A1_ID = '3eb1778e-6da3-574a-bbab-aa16b02411ff';
const A1_REASON = '与第 28 行编码、名称、特征、工程量相同，重复列项';

export const SCENES: Scene[] = [
  {
    id: 'check',
    tab: '计价表核对',
    icon: 'sheet',
    prompt: '核对一下送审和审定计价表',
    end: 14.6,
    hold: 3.2,
    footnote: '金额由脚本取数计算；点金额，看它来自哪两张表、哪几行。',
    footerFile: { name: '核对结果.xlsx', dir: DIR_CHECK, state: '已推回公司存储桶' },
    steps: [
      { at: 0, p: 'dialog', kind: 'compose', text: '核对一下送审和审定计价表', dur: 0.72 },
      { at: 0.8, p: 'dialog', kind: 'send' },
      { at: 1.1, p: 'dialog', kind: 'assistant' },
      {
        at: 1.25,
        p: 'script',
        kind: 'tool',
        run: 0.3,
        tool: {
          label: '读取项目说明',
          name: 'read',
          args: '项目说明.md',
          elapsed: '0.1 s',
          detail: '关键文件指引：送审计价表、审定计价表 → 资料/4 结算资料/',
        },
      },
      {
        at: 1.6,
        p: 'script',
        kind: 'tool',
        run: 0.55,
        tool: {
          label: '拉取计价表',
          name: 'tos_pull',
          args: '资料/4 结算资料/送审计价表.xlsx 等 2 个',
          times: 2,
          elapsed: '1.6 s',
          detail: '2 个文件已到本机缓存（2.8 MB、2.7 MB）',
        },
      },
      { at: 2.15, p: 'script', kind: 'cue', cue: 'files' },
      {
        at: 2.2,
        p: 'script',
        kind: 'tool',
        run: 0.45,
        tool: {
          label: '预检计价表',
          name: 'probe.py probe',
          args: '--files 送审计价表.xlsx 审定计价表.xlsx',
          elapsed: '0.8 s',
          detail: '两份均为 kind=costsheet（各 2 张清单表，共 9 张表）',
        },
      },
      { at: 2.65, p: 'script', kind: 'cue', cue: 'probe' },
      {
        at: 2.7,
        p: 'script',
        kind: 'tool',
        run: 1.1,
        tool: {
          label: '运行核对',
          name: 'reconcile.py run',
          args: `--basis auto --out ${DIR_CHECK}`,
          elapsed: '5.9 s',
          detail: 'status=ok · 告警 3 条 · 写出 result.json、核对结果.xlsx',
        },
      },
      { at: 2.7, p: 'script', kind: 'cue', cue: 'loading' },
      { at: 3.8, p: 'script', kind: 'cue', cue: 'summary' },
      {
        at: 3.95,
        p: 'dialog',
        kind: 'say',
        segs: [
          '核对完成（脚本取数，需人工复核）：送审 ',
          m('30,530,406.80'),
          ' 元，审定 ',
          m('29,623,713.84'),
          ' 元，核减 ',
          m('906,692.96', 'reduction'),
          ' 元，核减率 ',
          m('2.97%'),
          '。',
        ],
      },
      { at: 6.0, p: 'dialog', kind: 'cue', cue: 'chapters' },
      {
        at: 6.0,
        p: 'dialog',
        kind: 'say',
        segs: ['按章看，核减最多的是混凝土及钢筋混凝土工程、措施项目、土石方工程；门窗工程核增 ', m('32,612.74'), ' 元。'],
      },
      {
        at: 7.9,
        p: 'script',
        kind: 'tool',
        run: 0.3,
        tool: {
          label: '筛选调整行',
          name: 'python',
          args: 'result.json → rows 按 |diff| 取前 20',
          elapsed: '0.3 s',
          detail: '调整 214 行、仅送审 23 行、仅审定 9 行、待核实 7 行',
        },
      },
      { at: 8.25, p: 'dialog', kind: 'cue', cue: 'rows' },
      {
        at: 8.25,
        p: 'dialog',
        kind: 'say',
        segs: [
          '最大一行：现浇构件钢筋核减 ',
          m('303,556.71'),
          ' 元（送审第 ',
          m('768'),
          ' 行，审定第 ',
          m('761'),
          ' 行）。量差 ',
          m('612,418.27'),
          ' 元，价差 ',
          m('147,749.55'),
          ' 元。',
        ],
      },
      { at: 10.3, p: 'review', kind: 'cue', cue: 'warnings' },
      {
        at: 10.3,
        p: 'review',
        kind: 'say',
        segs: [
          '告警 3 条：1 条 ',
          m('warn'),
          '，送审侧 1 行量×价与合价不符；2 条 ',
          m('info'),
          '，两份文件各按标题跳过 7 张非清单表。另有 7 行待核实，已列入待确认清单。',
        ],
      },
      { at: 13.25, p: 'review', kind: 'status', status: 'ok', manual: true },
      {
        at: 13.45,
        p: 'script',
        kind: 'tool',
        run: 0.2,
        tool: {
          label: '写待确认清单',
          name: 'write',
          args: `${DIR_CHECK}待确认清单.md`,
          elapsed: '0.1 s',
          detail: '8 条：待核实 7 行、计算错误 1 行',
        },
      },
      {
        at: 13.7,
        p: 'script',
        kind: 'tool',
        run: 0.5,
        tool: {
          label: '推回公司存储桶',
          name: 'tos_push',
          args: `${DIR_CHECK} 3 个文件`,
          times: 3,
          elapsed: '2.1 s',
          detail: '已上传并回读校验',
        },
      },
      {
        at: 14.3,
        p: 'review',
        kind: 'files',
        files: [
          { name: '核对结果.xlsx', dir: DIR_CHECK },
          { name: '待确认清单.md', dir: DIR_CHECK },
          { name: 'result.json', dir: DIR_CHECK },
        ],
      },
      { at: 14.5, p: 'review', kind: 'hotspots', ids: ['reduction', 'sheet-tabs'] },
    ],
  },
  {
    id: 'review',
    tab: '投控复核',
    icon: 'shield',
    prompt: '查一下这份结算送审的投控异常',
    end: 18.15,
    hold: 3.2,
    footnote: '疑似由规则给出，结论由您逐条判定，每个决定追加记录。',
    footerFile: { name: '复核.jsonl', dir: DIR_TK, state: '已记录 1 条' },
    steps: [
      { at: 0, p: 'dialog', kind: 'compose', text: '查一下这份结算送审的投控异常', dur: 0.84 },
      { at: 0.92, p: 'dialog', kind: 'send' },
      { at: 1.2, p: 'dialog', kind: 'assistant' },
      {
        at: 1.35,
        p: 'script',
        kind: 'tool',
        run: 0.3,
        tool: {
          label: '读取项目说明',
          name: 'read',
          args: '项目说明.md',
          elapsed: '0.1 s',
          detail: '送审计价表：资料/4 结算资料/送审计价表.xlsx；合同或中标清单：未登记',
        },
      },
      {
        at: 1.7,
        p: 'script',
        kind: 'tool',
        run: 0.3,
        tool: {
          label: '拉取送审计价表',
          name: 'tos_pull',
          args: '资料/4 结算资料/送审计价表.xlsx',
          elapsed: '0.2 s',
          detail: '本机副本与桶内一致，未重复下载',
        },
      },
      {
        at: 2.05,
        p: 'script',
        kind: 'tool',
        run: 1.2,
        tool: {
          label: '运行投控检测',
          name: 'tk.py detect',
          args: `--files 资料/4 结算资料/送审计价表.xlsx --project-id 2026-007 --out ${DIR_TK}`,
          elapsed: '4.6 s',
          detail: 'status=ok · 疑似 290 条 · 阈值 v1-20260711（草案）',
        },
      },
      { at: 2.05, p: 'script', kind: 'cue', cue: 'tk-loading' },
      { at: 3.25, p: 'script', kind: 'cue', cue: 'distribution' },
      {
        at: 3.35,
        p: 'dialog',
        kind: 'say',
        segs: ['检测完成，共 ', m('290'), ' 条疑似：重复计取 2、暂估价 1、行内自洽 1、大额粗筛 286。大额粗筛置信最低，只按金额排序供抽查。'],
      },
      { at: 3.7, p: 'dialog', kind: 'cue', cue: 'focus' },
      {
        at: 6.05,
        p: 'dialog',
        kind: 'say',
        segs: [
          '重点 4 条见右侧：综合脚手架第 28、46 行编码相同，金额各 ',
          m('125,120.00'),
          ' 元，疑似重复计取；钢质防火门按暂估价计入；构造柱量×价与合价偏差 ',
          m('3.28%'),
          '。',
        ],
      },
      {
        at: 8.9,
        p: 'dialog',
        kind: 'say',
        segs: [
          '没有合同或中标清单，单价超合同、量超合同、漏报、合同外新增 4 条规则本轮未跑。告警 1 条 ',
          m('info'),
          '：按标题跳过 7 张非清单表。阈值 ',
          m('v1-20260711'),
          ' 仍是草案。',
        ],
      },
      { at: 11.95, p: 'dialog', kind: 'say', segs: ['疑似不是结论。先看第 1 条，请您判定：'] },
      {
        at: 12.95,
        p: 'review',
        kind: 'ask',
        ask: {
          tool: 'ask_user_question',
          header: '需要您判定 · 异常 1 / 4',
          question: '第 46 行 综合脚手架（重复计取，置信 0.7）',
          detail: '与第 28 行编码 011701001001、名称、特征、工程量相同，金额各 125,120.00 元。',
          options: [
            { value: 'confirmed', label: '确认异常', description: '追加 confirmed' },
            { value: 'dismissed', label: '判为误报', description: '追加 dismissed' },
            { value: 'pending', label: '暂不判断', description: '保持待复核' },
          ],
          reasonLabel: '理由（必填）',
          reasons: { confirmed: A1_REASON, dismissed: '经核对为不同部位，非重复', pending: '待查施工方案后再定' },
          submitLabel: '提交',
          anomalyId: A1_ID,
        },
      },
      { at: 12.95, p: 'review', kind: 'cue', cue: 'focus-a1' },
      { at: 13.4, p: 'review', kind: 'cursor', target: '[data-ask-option="confirmed"]', click: true, dur: 0.5 },
      { at: 14.0, p: 'review', kind: 'type', target: '[data-ask-reason]', text: A1_REASON, dur: 0.8 },
      { at: 14.9, p: 'review', kind: 'cursor', target: '[data-ask-submit]', click: true, dur: 0.4 },
      { at: 15.4, p: 'review', kind: 'mark', label: 'ask:submitted' },
      {
        at: 15.4,
        p: 'script',
        kind: 'tool',
        run: 0.3,
        tool: {
          confirmed: {
            label: '记录复核决定',
            name: 'tk.py review',
            args: '--anomaly-id 3eb1778e… --state confirmed --reviewer 张工',
            elapsed: '0.2 s',
            detail: '已追加 1 条 · 已确认 1 · 待复核 289',
          },
          dismissed: {
            label: '记录复核决定',
            name: 'tk.py review',
            args: '--anomaly-id 3eb1778e… --state dismissed --reviewer 张工',
            elapsed: '0.2 s',
            detail: '已追加 1 条 · 判为误报 1 · 待复核 289',
          },
          pending: {
            label: '记录复核决定',
            name: 'tk.py review',
            args: '--anomaly-id 3eb1778e… --state pending --reviewer 张工',
            elapsed: '0.2 s',
            detail: '已追加 1 条 · 待复核 290',
          },
        },
      },
      { at: 15.7, p: 'script', kind: 'cue', cue: 'record' },
      {
        at: 15.8,
        p: 'dialog',
        kind: 'say',
        segs: {
          confirmed: ['已记录到 ', m('复核.jsonl'), '。重点还剩 3 条待复核；第 28 行是同组的另一行，请您另行判定。'],
          dismissed: ['已记录为误报，写入 ', m('复核.jsonl'), '。重点还剩 3 条待复核。'],
          pending: ['已记录为暂不判断，这条仍是待复核。重点还剩 4 条待复核。'],
        },
      },
      {
        at: 17.45,
        p: 'script',
        kind: 'tool',
        run: 0.2,
        tool: {
          confirmed: { label: '写待确认清单', name: 'write', args: `${DIR_TK}待确认清单.md`, elapsed: '0.1 s', detail: '未复核 289 条（重点 3 条）' },
          dismissed: { label: '写待确认清单', name: 'write', args: `${DIR_TK}待确认清单.md`, elapsed: '0.1 s', detail: '未复核 289 条（重点 3 条）' },
          pending: { label: '写待确认清单', name: 'write', args: `${DIR_TK}待确认清单.md`, elapsed: '0.1 s', detail: '未复核 290 条（重点 4 条）' },
        },
      },
      { at: 17.75, p: 'review', kind: 'status', status: 'ok', manual: true },
      {
        at: 17.9,
        p: 'review',
        kind: 'files',
        files: [
          { name: '投控异常.xlsx', dir: DIR_TK },
          { name: '复核.jsonl', dir: DIR_TK },
          { name: '待确认清单.md', dir: DIR_TK },
          { name: 'result.json', dir: DIR_TK },
        ],
      },
      { at: 18.05, p: 'review', kind: 'hotspots', ids: ['decision', 'anomaly-source'] },
    ],
  },
  {
    id: 'cad',
    tab: 'CAD 看图',
    icon: 'cad',
    prompt: '看一下 A-02 二层平面图，列出各房间面积',
    end: 17.85,
    hold: 3.2,
    footnote: '面积由代码计算，图片只用来定位与核对。',
    footerFile: { name: 'A-02 二层平面图-房间面积.md', dir: DIR_CAD, state: '已写入' },
    steps: [
      { at: 0, p: 'dialog', kind: 'compose', text: '看一下 A-02 二层平面图，列出各房间面积', dur: 1.1 },
      { at: 1.18, p: 'dialog', kind: 'send' },
      { at: 1.45, p: 'dialog', kind: 'assistant' },
      {
        at: 1.6,
        p: 'script',
        kind: 'tool',
        run: 0.5,
        tool: { label: '拉取图纸', name: 'tos_pull', args: '图纸/A-02 二层平面图.dwg', elapsed: '2.2 s', detail: '6.4 MB 已到本机缓存' },
      },
      {
        at: 2.15,
        p: 'script',
        kind: 'tool',
        run: 1.6,
        tool: {
          label: '打开图纸',
          name: 'cad_open',
          args: '…/图纸/A-02 二层平面图.dwg',
          elapsed: '3.1 s',
          detail: 'doc=d4f1c09a2b7e3 · DWG AC1027 · LibreDWG 0.14 转换 · 图框 S1 · 单位未确认',
          warnings: ['跳过了 37 个图纸空间（布局）实体；只读取模型空间', '单位未确认：量纲类工具（cad_rooms）会拒绝执行，见 unit.evidence'],
        },
      },
      { at: 2.15, p: 'script', kind: 'cue', cue: 'plot' },
      {
        at: 3.8,
        p: 'script',
        kind: 'tool',
        run: 0.3,
        tool: { label: '确认单位', name: 'cad_set_unit', args: 'verify=true', elapsed: '0.1 s', detail: '单位 mm（尺寸比对）：9 个尺寸标注一致率 100%' },
      },
      { at: 4.1, p: 'script', kind: 'cue', cue: 'unit' },
      {
        at: 4.15,
        p: 'script',
        kind: 'tool',
        run: 0.3,
        tool: {
          label: '列图框',
          name: 'cad_frames',
          args: 'doc=d4f1c09a2b7e3',
          elapsed: '0.2 s',
          detail: 'S1 · A1 1:100 · 二层平面图（T41）· A-02（T43）· 1:100（T45）· 2F',
        },
      },
      { at: 4.45, p: 'script', kind: 'cue', cue: 'frame' },
      {
        at: 4.5,
        p: 'script',
        kind: 'tool',
        run: 0.4,
        tool: { label: '房间面积核对', name: 'cad_rooms', args: 'frame=S1', elapsed: '0.3 s', detail: '锚点 10 个，匹配 9 间；未匹配 1 个' },
      },
      { at: 4.9, p: 'script', kind: 'cue', cue: 'rooms' },
      {
        at: 5.9,
        p: 'script',
        kind: 'tool',
        run: 0.5,
        tool: { label: '出总览图', name: 'cad_render', args: 'frame=S1', elapsed: '0.9 s', detail: '1600×1151 px · 网格 A–H × 1–6' },
      },
      { at: 6.4, p: 'script', kind: 'cue', cue: 'grid' },
      {
        at: 6.45,
        p: 'script',
        kind: 'tool',
        run: 0.7,
        tool: { label: '看图', name: 'read_image', args: 'd4f1c09a2b7e3-S1-7c2e91ab.png', elapsed: '1.4 s', detail: '已读入总览图' },
      },
      { at: 6.45, p: 'script', kind: 'cue', cue: 'scan-s1' },
      {
        at: 7.25,
        p: 'script',
        kind: 'tool',
        run: 0.4,
        tool: { label: '放大 E4', name: 'cad_render', args: 'frame=S1 cell=E4', elapsed: '0.6 s', detail: '1600×1515 px · 文字中位高度约 48 px' },
      },
      { at: 7.65, p: 'script', kind: 'cue', cue: 'zoom' },
      {
        at: 8.5,
        p: 'script',
        kind: 'tool',
        run: 0.6,
        tool: { label: '看图', name: 'read_image', args: 'd4f1c09a2b7e3-S1-E4-3b8d0f42.png', elapsed: '1.2 s', detail: '已读入 E4 放大图' },
      },
      { at: 8.5, p: 'script', kind: 'cue', cue: 'scan-e4' },
      { at: 9.1, p: 'script', kind: 'cue', cue: 'highlight' },
      {
        at: 9.15,
        p: 'dialog',
        kind: 'say',
        segs: [
          '图纸 ',
          m('S1'),
          '：二层平面图（',
          m('T41'),
          '），图号 ',
          m('A-02'),
          '，比例 ',
          m('1:100'),
          '。单位按 9 个尺寸标注自动比对确认为 ',
          m('mm'),
          '。',
          m('cad_rooms'),
          ' 匹配 9 间，见右侧房间表。',
        ],
      },
      {
        at: 11.75,
        p: 'dialog',
        kind: 'say',
        segs: [
          '会议室201 面积文字 ',
          m('69.70'),
          ' m²，几何面积 ',
          m('73.08'),
          ' m²，相差 ',
          m('4.85%'),
          '。放大 ',
          m('E4'),
          ' 看，它的边界线画在墙中线上，其余房间画在墙内皮；以哪个为准需人工确认。',
        ],
      },
      {
        at: 14.65,
        p: 'dialog',
        kind: 'say',
        segs: ['楼梯间2 没有面积文字，只有几何面积；走道未匹配，边界不闭合，未匹配不等于没有房间。图纸空间（布局）里的 37 个实体未读取。'],
      },
      {
        at: 17.2,
        p: 'script',
        kind: 'tool',
        run: 0.2,
        tool: {
          label: '写入结果',
          name: 'write',
          args: `${DIR_CAD}A-02 二层平面图-房间面积.md`,
          elapsed: '0.1 s',
          detail: '注明来源图纸、doc、图框 S1',
        },
      },
      { at: 17.45, p: 'review', kind: 'status', status: 'ok', manual: true },
      { at: 17.6, p: 'review', kind: 'files', files: [{ name: 'A-02 二层平面图-房间面积.md', dir: DIR_CAD }] },
      { at: 17.75, p: 'review', kind: 'hotspots', ids: ['room-list', 'view-toggle'] },
    ],
  },
];

/** 热区目标元素的 title 文字（§2.2），热区本身不显示文字 */
export const HOTSPOT_TITLES: Record<HotspotId, string> = {
  reduction: '点金额，看出处',
  'sheet-tabs': '切换工作表',
  decision: '由您判定',
  'anomaly-source': '看原表这一行',
  'room-list': '点房间，在图上定位',
  'view-toggle': '切换总览 / 放大',
};

/* ---------- 场景一：核对结果（zt.reconcile 字段名） ---------- */
export const RECONCILE = {
  workDir: DIR_CHECK,
  inputs: [
    { name: '送审计价表.xlsx', dir: '资料/4 结算资料/', size: '2.8 MB', kind: 'costsheet', listSheets: 2, sheetsTotal: 9 },
    { name: '审定计价表.xlsx', dir: '资料/4 结算资料/', size: '2.7 MB', kind: 'costsheet', listSheets: 2, sheetsTotal: 9 },
  ],
  usedSheets: ['分部分项工程清单与计价表', '施工技术措施项目清单与计价表'],
  status: 'ok' as const,
  summary: {
    label_a: '送审',
    label_b: '审定',
    a_total: 30530406.8,
    b_total: 29623713.84,
    adjust_amount: 906692.96,
    adjust_rate: 0.0297,
    count_total: 1284,
    count_same: 1031,
    count_changed: 214,
    count_only_a: 23,
    count_only_b: 9,
    count_uncertain: 7,
    count_a_items: 1275,
    count_b_items: 1261,
    diff_by_qty: 612418.27,
    // 02 章 §8.1 原稿为 294274.69（= 核减额 − 量差，即“量差 + 价差 = 核减额”的旧口径）；
    // 按 00 章 §8.2 与 §14 第 12 条（优先级最高）改为匹配行价差 147,749.55，与页面所有出现处一致。
    diff_by_price: 147749.55,
    count_calc_error_a: 1,
    count_calc_error_b: 0,
    basis: 'auto',
    basis_label: { submitted: '不分期', approved: '不分期' },
    needs_manual: true,
  },
  chapters: [
    { chapter: '0105', chapter_name: '混凝土及钢筋混凝土工程', count: 486, a_amount: 18762307.42, b_amount: 18215641.08, adjust: 546666.34 },
    { chapter: '0117', chapter_name: '措施项目', count: 94, a_amount: 4230817.6, b_amount: 3991286.35, adjust: 239531.25 },
    { chapter: '0101', chapter_name: '土石方工程', count: 64, a_amount: 2186452.36, b_amount: 2104918.71, adjust: 81533.65 },
    { chapter: '0104', chapter_name: '砌筑工程', count: 132, a_amount: 1348906.15, b_amount: 1302457.9, adjust: 46448.25 },
    { chapter: '0108', chapter_name: '门窗工程', count: 268, a_amount: 2915613.8, b_amount: 2948226.54, adjust: -32612.74 },
    { chapter: '0109', chapter_name: '屋面及防水工程', count: 240, a_amount: 1086309.47, b_amount: 1061183.26, adjust: 25126.21 },
  ],
  rows: [
    {
      status: '调整',
      item_code: '010515001002',
      item_name: '现浇构件钢筋',
      feature: 'HRB400 Φ12–25',
      unit: 't',
      submitted_qty: 1186.415,
      approved_qty: 1127.226,
      submitted_price: 5128.6,
      approved_price: 5128.6,
      submitted_amount: 6084647.97,
      approved_amount: 5781091.26,
      diff: 303556.71,
      matched_by: '编码',
      submitted_sheet: '分部分项工程清单与计价表',
      submitted_row: 768,
      approved_sheet: '分部分项工程清单与计价表',
      approved_row: 761,
      calc_flags: [],
      diff_by_qty: 303556.71,
      diff_by_price: 0,
    },
    {
      status: '仅送审',
      item_code: '011701001001',
      item_name: '综合脚手架',
      feature: '地下室，框架结构',
      unit: 'm²',
      submitted_qty: 3400,
      approved_qty: null,
      submitted_price: 36.8,
      approved_price: null,
      submitted_amount: 125120,
      approved_amount: 0,
      diff: 125120,
      matched_by: null,
      submitted_sheet: '施工技术措施项目清单与计价表',
      submitted_row: 46,
      approved_sheet: null,
      approved_row: null,
      calc_flags: [],
      diff_by_qty: null,
      diff_by_price: null,
    },
    {
      status: '调整',
      item_code: '010505001001',
      item_name: '有梁板',
      feature: 'C30',
      unit: 'm³',
      submitted_qty: 2486.35,
      approved_qty: 2486.35,
      submitted_price: 612.4,
      approved_price: 589.6,
      submitted_amount: 1522640.74,
      approved_amount: 1465951.96,
      diff: 56688.78,
      matched_by: '编码',
      submitted_sheet: '分部分项工程清单与计价表',
      submitted_row: 386,
      approved_sheet: '分部分项工程清单与计价表',
      approved_row: 383,
      calc_flags: [],
      diff_by_qty: 0,
      diff_by_price: 56688.78,
    },
    {
      status: '调整',
      item_code: '010502002001',
      item_name: '构造柱',
      feature: 'C25',
      unit: 'm³',
      submitted_qty: 96.4,
      approved_qty: 96.4,
      submitted_price: 612.3,
      approved_price: 612.3,
      submitted_amount: 61025.72,
      approved_amount: 59025.72,
      diff: 2000,
      matched_by: '编码',
      submitted_sheet: '分部分项工程清单与计价表',
      submitted_row: 374,
      approved_sheet: '分部分项工程清单与计价表',
      approved_row: 371,
      calc_flags: ['送审计算错误'],
      diff_by_qty: 0,
      diff_by_price: 0,
    },
  ],
  warnings: [
    {
      code: 'calc_error_rows',
      level: 'warn',
      file: null,
      message: '送审侧 1 行、审定侧 0 行 量×价 与合价不符（超过 max(1 元, 0.5%)），已在行上标记「送审计算错误 / 审定计算错误」',
    },
    { code: 'sheets_skipped_by_title', level: 'info', file: '送审计价表.xlsx', message: '按标题跳过 7 张表（综合单价分析 2、封面 1、总说明 1 等 6 类）' },
    { code: 'sheets_skipped_by_title', level: 'info', file: '审定计价表.xlsx', message: '按标题跳过 7 张表（综合单价分析 2、封面 1、总说明 1 等 6 类）' },
  ],
} as const;

/* ---------- 场景二：投控结果（zt.tk 字段名） ---------- */
export interface SourceRow {
  row: number;
  code: string;
  name: string;
  feature: string;
  unit: string;
  qty: string;
  price: string;
  amount: string;
  provisional?: string;
  hit?: true;
}
export interface Anomaly {
  anomaly_id: string;
  type: 'duplicate' | 'zangu' | 'self_check';
  anomaly_type: string;
  confidence: number;
  confidence_tier: '中';
  item_code: string;
  item_name: string;
  unit: string;
  line_amount: number;
  excess_amount: null;
  source_file: string;
  sheet: string;
  row: number;
  detail: string;
  title: string;
  reasons: Record<'confirmed' | 'dismissed', string>;
  source: { sheet: string; rows: SourceRow[] };
}
const TECH = '施工技术措施项目清单与计价表';
const PART = '分部分项工程清单与计价表';
const SCAFFOLD_ROWS: SourceRow[] = [
  { row: 27, code: '011701001002', name: '综合脚手架', feature: '地上部分，框架结构', unit: 'm²', qty: '15,200.00', price: '38.60', amount: '586,720.00' },
  { row: 28, code: '011701001001', name: '综合脚手架', feature: '地下室，框架结构', unit: 'm²', qty: '3,400.00', price: '36.80', amount: '125,120.00', hit: true },
  { row: 29, code: '011702001001', name: '基础', feature: '筏板基础模板', unit: 'm²', qty: '1,286.40', price: '52.60', amount: '67,664.64' },
  { row: 45, code: '011703001001', name: '垂直运输', feature: '框架结构', unit: 'm²', qty: '18,600.00', price: '31.20', amount: '580,320.00' },
  { row: 46, code: '011701001001', name: '综合脚手架', feature: '地下室，框架结构', unit: 'm²', qty: '3,400.00', price: '36.80', amount: '125,120.00', hit: true },
  { row: 47, code: '011705001001', name: '大型机械设备进出场及安拆', feature: '塔式起重机', unit: '台次', qty: '1.00', price: '38,500.00', amount: '38,500.00' },
];
export const TK = {
  workDir: DIR_TK,
  rules_version: 'v1-20260711',
  status: 'ok' as const,
  project_id: '2026-007',
  total: 290,
  byRule: { duplicate: 2, zangu: 1, self_check: 1, big_amount: 286, code_repeat: 0 },
  focusCount: 4,
  screenCount: 286,
  rules_skipped: {
    price_over_baseline: 'baseline_not_provided',
    qty_over_baseline: 'baseline_not_provided',
    missing_submit: 'baseline_not_provided',
    new_item: 'baseline_not_provided',
  },
  skippedLabels: ['单价超合同', '量超合同', '漏报', '合同外新增'],
  baseline: { status: 'not_provided', rows: 0 },
  warnings: [{ code: 'sheets_skipped_by_title', level: 'info', file: '送审计价表.xlsx', message: '按标题跳过 7 张表（综合单价分析 2、封面 1、总说明 1 等 6 类）' }],
  focus: [
    {
      anomaly_id: A1_ID,
      type: 'duplicate',
      anomaly_type: '重复计取',
      confidence: 0.7,
      confidence_tier: '中',
      item_code: '011701001001',
      item_name: '综合脚手架',
      unit: 'm²',
      line_amount: 125120,
      excess_amount: null,
      source_file: '送审计价表.xlsx',
      sheet: TECH,
      row: 46,
      title: '综合脚手架 · 第 46 行',
      detail:
        '重复计取｜综合脚手架（同文件同单位工程内同编码 2 行（金额非零的至少 2 行），送审金额 125,120.00，编码 011701001001，来源 送审计价表.xlsx·施工技术措施项目清单与计价表·第46行，置信度 0.7）',
      reasons: { confirmed: A1_REASON, dismissed: '经核对为不同部位，非重复' },
      source: { sheet: TECH, rows: SCAFFOLD_ROWS },
    },
    {
      anomaly_id: 'df23ed7e-d2c0-5b8e-afc1-0d740f93d643',
      type: 'duplicate',
      anomaly_type: '重复计取',
      confidence: 0.7,
      confidence_tier: '中',
      item_code: '011701001001',
      item_name: '综合脚手架',
      unit: 'm²',
      line_amount: 125120,
      excess_amount: null,
      source_file: '送审计价表.xlsx',
      sheet: TECH,
      row: 28,
      title: '综合脚手架 · 第 28 行',
      detail:
        '重复计取｜综合脚手架（同文件同单位工程内同编码 2 行（金额非零的至少 2 行），送审金额 125,120.00，编码 011701001001，来源 送审计价表.xlsx·施工技术措施项目清单与计价表·第28行，置信度 0.7）',
      reasons: { confirmed: '与第 46 行重复列项', dismissed: '保留行：地下室综合脚手架只计一次，本行保留' },
      source: { sheet: TECH, rows: SCAFFOLD_ROWS },
    },
    {
      anomaly_id: 'a51f3df4-c86f-5e98-9711-3039efd1d0dd',
      type: 'zangu',
      anomaly_type: '整项存疑-暂估价',
      confidence: 0.6,
      confidence_tier: '中',
      item_code: '010802003001',
      item_name: '钢质防火门',
      unit: 'm²',
      line_amount: 69384,
      excess_amount: null,
      source_file: '送审计价表.xlsx',
      sheet: PART,
      row: 836,
      title: '钢质防火门 · 第 836 行',
      detail:
        '整项存疑-暂估价｜钢质防火门（清单表「暂估价」列本行 50,568.00，送审金额 69,384.00，编码 010802003001，来源 送审计价表.xlsx·分部分项工程清单与计价表·第836行，置信度 0.6）',
      reasons: { confirmed: '结算仍按暂估单价 860.00 元/m² 计入，未见认价单', dismissed: '已有认价单，暂估价列为原样保留' },
      source: {
        sheet: PART,
        rows: [
          { row: 835, code: '010802001001', name: '金属（塑钢）门', feature: '铝合金平开门，含五金', unit: 'm²', qty: '46.20', price: '728.00', amount: '33,633.60' },
          {
            row: 836,
            code: '010802003001',
            name: '钢质防火门',
            feature: '甲级，含闭门器、顺序器',
            unit: 'm²',
            qty: '58.80',
            price: '1,180.00',
            amount: '69,384.00',
            provisional: '50,568.00',
            hit: true,
          },
          { row: 837, code: '010802003002', name: '钢质防火门', feature: '乙级，含闭门器', unit: 'm²', qty: '112.35', price: '980.00', amount: '110,103.00' },
        ],
      },
    },
    {
      anomaly_id: '2b23dd9f-92c0-5b95-abb2-699df8f35287',
      type: 'self_check',
      anomaly_type: '整项存疑-自洽',
      confidence: 0.55,
      confidence_tier: '中',
      item_code: '010502002001',
      item_name: '构造柱',
      unit: 'm³',
      line_amount: 61025.72,
      excess_amount: null,
      source_file: '送审计价表.xlsx',
      sheet: PART,
      row: 374,
      title: '构造柱 · 第 374 行',
      detail:
        '整项存疑-自洽｜构造柱（量 96.4 × 单价 612.30 = 59,025.72，与送审金额 61,025.72 偏差 3.28%，编码 010502002001，来源 送审计价表.xlsx·分部分项工程清单与计价表·第374行，置信度 0.55）',
      reasons: { confirmed: '送审合价与量×价不符，退回更正', dismissed: '合价含调差，量×价不含' },
      source: {
        sheet: PART,
        rows: [
          { row: 373, code: '010502001001', name: '矩形柱', feature: 'C35 商品混凝土', unit: 'm³', qty: '386.42', price: '628.50', amount: '242,864.97' },
          { row: 374, code: '010502002001', name: '构造柱', feature: 'C25 商品混凝土', unit: 'm³', qty: '96.40', price: '612.30', amount: '61,025.72', hit: true },
          { row: 375, code: '010503002001', name: '矩形梁', feature: 'C30 商品混凝土', unit: 'm³', qty: '412.65', price: '598.20', amount: '246,847.23' },
        ],
      },
    },
  ] satisfies Anomaly[],
  reviewer: '张工',
  autoRecordTs: '2026-10-19T06:42:18+00:00',
  undoReason: '撤回，重新复核',
}; // 不加 as const：focus 用 satisfies Anomaly[] 保留字面量类型且保持可变数组

/**
 * 复核.jsonl 一行：字段顺序与 zt.tk.review.append_decision 一致；
 * 分隔符同 Python json.dumps 默认（", " 与 ": "），中文不转义（ensure_ascii=False），金额按 Python float 输出（125120.0）。
 */
export function reviewRecordLine(a: Anomaly, from: HitlState, to: HitlState, reason: string, ts: string): string {
  const s = (v: string) => JSON.stringify(v);
  const f = (v: number) => (Number.isInteger(v) ? `${v}.0` : String(v));
  const snap =
    `{"type": ${s(a.type)}, "anomaly_type": ${s(a.anomaly_type)}, "item_code": ${s(a.item_code)}, ` +
    `"item_name": ${s(a.item_name)}, "source_file": ${s(a.source_file)}, "sheet": ${s(a.sheet)}, ` +
    `"row": ${a.row}, "line_amount": ${f(a.line_amount)}, "excess_amount": null}`;
  return (
    `{"ts": ${s(ts)}, "anomaly_id": ${s(a.anomaly_id)}, "from_state": ${s(from)}, "hitl_state": ${s(to)}, ` +
    `"reason": ${s(reason)}, "reviewer": ${s(TK.reviewer)}, "anomaly": ${snap}}`
  );
}

/* ---------- 场景三：看图结果（tool-cad 字段名） ---------- */
export const CAD = {
  file: '图纸/A-02 二层平面图.dwg',
  size: '6.4 MB',
  workDir: DIR_CAD,
  doc: 'd4f1c09a2b7e3',
  open: {
    format: 'dwg',
    acadver: 'AC1027',
    converter: { version: '0.14' },
    bbox: { x1: 0, y1: 0, x2: 84100, y2: 59400 },
    counts: { entities: 412, segments: 1386, texts: 48, inserts: 18, closed_polylines: 11, hatches: 20, layers: 12, dimensions_sampled: 9 },
    skipped: { paperspace: 37 },
    unit: {
      unit: 'mm',
      status: 'unconfirmed',
      method: '待确认',
      evidence: '$INSUNITS=0；图幅跨度约 84k 单位，建筑图按惯例疑似 mm；9 个尺寸标注的「显示值÷实测长度」中位数 1.000，一致率 100%，指向 mm',
    },
    frames: { ids: ['S1'], sheets: 1, clusters: 0 },
  },
  frame: {
    id: 'S1',
    kind: 'sheet',
    rect: { x1: 0, y1: 0, x2: 84100, y2: 59400 },
    area_m2: 4995.5,
    paper: 'A1',
    border_scale: 100,
    name: { value: '二层平面图', ref: 'T41' },
    number: { value: 'A-02', ref: 'T43' },
    scale: { value: '1:100', ref: 'T45' },
    floor: '2F',
    floor_confidence: 'high',
    texts: 48,
    inserts: 18,
  },
  rooms: {
    anchors: 10,
    matched: 9,
    unit: 'mm',
    frame: 'S1',
    needs_manual: true,
    note: '未匹配 1 个锚点：常见原因是墙为双线、房间边界不闭合；未匹配不等于没有房间',
    file: '图纸/.cache/out/d4f1c09a2b7e3-rooms-5e0a7d13.tsv',
    rows: [
      { label: '会议室201', text_m2: 69.7, geom_m2: 73.08, diff_pct: 4.85, x: 46160, y: 24800, poly_handle: '2A4D', text: 'T16' },
      { label: '卫生间', text_m2: 34.0, geom_m2: 34.06, diff_pct: 0.18, x: 56975, y: 36500, poly_handle: '2A49', text: 'T13' },
      { label: '培训室', text_m2: 69.7, geom_m2: 69.7, diff_pct: 0, x: 29675, y: 36500, poly_handle: '2A41', text: 'T9' },
      { label: '资料室', text_m2: 69.7, geom_m2: 69.7, diff_pct: 0, x: 38075, y: 36500, poly_handle: '2A43', text: 'T10' },
      { label: '会议室202', text_m2: 69.7, geom_m2: 69.7, diff_pct: 0, x: 46160, y: 36500, poly_handle: '2A45', text: 'T11' },
      { label: '开放办公区', text_m2: 141.1, geom_m2: 141.1, diff_pct: 0, x: 33525, y: 24800, poly_handle: '2A4B', text: 'T15' },
      { label: '楼梯间1', text_m2: 34.0, geom_m2: 34.0, diff_pct: 0, x: 52670, y: 24800, poly_handle: '2A4F', text: 'T17' },
      { label: '设备间', text_m2: 23.2, geom_m2: 23.2, diff_pct: 0, x: 56975, y: 23400, poly_handle: '2A51', text: 'T18' },
      { label: '楼梯间2', text_m2: null, geom_m2: 34.0, diff_pct: null, x: 52670, y: 36500, poly_handle: '2A47', text: 'T12' },
    ],
    unmatched: [{ label: '走道', text: 'T14' }],
  },
  renders: {
    S1: {
      path: '图纸/.cache/render/d4f1c09a2b7e3-S1-7c2e91ab.png',
      image_size: [1600, 1151],
      px_per_unit: 0.0181688,
      grid: { cols: 8, rows: 6, rect: { x1: 0, y1: 0, x2: 84100, y2: 59400 } },
    },
    E4: {
      path: '图纸/.cache/render/d4f1c09a2b7e3-S1-E4-3b8d0f42.png',
      image_size: [1600, 1515],
      px_per_unit: 0.138363,
      world_rect: { x1: 41524, y1: 19274, x2: 53088, y2: 30226 },
      text_px_median: 48,
    },
  },
} as const;

/** 文字版：用户原话 → 每个工具（中文标签、原名、结果行、警告）→ 回答段落 → 提问与回答 → 状态 → 产出文件 */
export function buildTranscript(scene: Scene, decision: HitlState = 'confirmed'): string {
  const pick = <T,>(b: Branch<T>): T =>
    b !== null && typeof b === 'object' && !Array.isArray(b) && 'confirmed' in b ? (b as Record<HitlState, T>)[decision] : (b as T);
  const text = (segs: Seg[]) => segs.map((x) => (typeof x === 'string' ? x : x.t)).join('');
  const out = [`示例（${scene.tab}）。用户：${scene.prompt}`];
  for (const st of scene.steps) {
    if (st.kind === 'tool') {
      const t = pick(st.tool);
      out.push(
        `调用 ${t.label}（${t.name}${t.times ? ` ×${t.times}` : ''}，耗时 ${t.elapsed}）：${t.detail}` +
          (t.warnings ? `；警告：${t.warnings.join('；')}` : ''),
      );
    } else if (st.kind === 'say') out.push(`智通数工AI：${text(pick(st.segs))}`);
    else if (st.kind === 'ask') {
      const chosen = st.ask.options.find((o) => o.value === decision)!;
      out.push(
        `提问（ask_user_question）：${st.ask.question}。${st.ask.detail}选项：${st.ask.options.map((o) => o.label).join('、')}。` +
          `用户回答：${chosen.label}，理由：${st.ask.reasons[decision]}`,
      );
    } else if (st.kind === 'status') out.push('状态：完成。金额与数量需人工确认。');
    else if (st.kind === 'files') out.push(`产出文件：${st.files.map((x) => x.dir + x.name).join('、')}`);
  }
  return out.join('\n');
}
