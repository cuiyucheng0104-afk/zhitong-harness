/**
 * 工作示例的时间线引擎（02 章 §2.6）：把 `SCENES[i].steps` 编译成“任一时刻 t 的画面状态”。
 *
 * 实现方式：每个场景只有一个时刻 `t`（秒），由 `useAutoplay` 的时钟或响应片段推进；
 * - 文字类状态（逐字、工具条进行中/完成、提问卡、热区）由本文件的纯函数按 t 求出，Vue 渲染；
 * - 位移、透明度、描线等补间写在样式表里，以场景面板上的 `--t` 与元素自身的 `--at`/`--dur` 计算
 *   （`styles/sections/hero.css` 的 `[data-a]`），因此任意时刻都可直接定位（暂停 = t 停住，终态 = t = end），
 *   SSR 时 `--t` 写成 end 即为终态。
 * 分支（`Record<HitlState, …>`）在编译时按决定取值。
 */
import {
  streamDuration,
  type AskSpec,
  type Branch,
  type Cue,
  type HitlState,
  type HotspotId,
  type OutputFile,
  type Principle,
  type Scene,
  type Seg,
  type Step,
  type ToolSpec,
} from '../../data/demo';

/** 取分支值。 */
export function pick<T>(b: Branch<T>, decision: HitlState): T {
  return b !== null && typeof b === 'object' && !Array.isArray(b) && 'confirmed' in (b as object)
    ? (b as Record<HitlState, T>)[decision]
    : (b as T);
}

export interface ToolItem {
  /** 工具在场景内的序号（0 起）。 */
  index: number;
  at: number;
  run: number;
  spec: ToolSpec;
  /** 所在步骤序号。 */
  step: number;
}
export interface SayItem {
  index: number;
  at: number;
  segs: Seg[];
  dur: number;
  step: number;
}
export interface AskTimeline {
  at: number;
  spec: AskSpec;
  /** 模拟指针选中“确认异常”的时刻与时长。 */
  option?: { at: number; dur: number; target: string };
  /** 理由逐字写入。 */
  type?: { at: number; dur: number; text: string };
  /** 模拟指针点“提交”。 */
  submit?: { at: number; dur: number; target: string };
  /** 标签 `ask:submitted`。 */
  submitted: number;
}

/** 按步骤顺序排列的对话栏条目（渲染顺序）。 */
export type ChatEntry =
  | { kind: 'tool'; item: ToolItem }
  | { kind: 'say'; item: SayItem }
  | { kind: 'ask'; at: number }
  | { kind: 'status'; at: number }
  | { kind: 'files'; at: number; files: OutputFile[] };

export interface CompiledScene {
  scene: Scene;
  decision: HitlState;
  compose: { at: number; dur: number; text: string };
  send: number;
  assistant: number;
  /** 思考点显示到第一个工具步开始。 */
  thinkingUntil: number;
  tools: ToolItem[];
  says: SayItem[];
  entries: ChatEntry[];
  ask: AskTimeline | null;
  status: number | null;
  files: { at: number; files: OutputFile[] } | null;
  hotspots: { at: number; ids: HotspotId[] } | null;
  cues: Partial<Record<Cue, number>>;
  end: number;
}

/**
 * 编译一个场景。
 * @param scene - 场景数据。
 * @param decision - 确认提问卡的决定（自动播放为 confirmed）。
 * @returns 各类步骤的时刻表。
 */
export function compileScene(scene: Scene, decision: HitlState = 'confirmed'): CompiledScene {
  const out: CompiledScene = {
    scene,
    decision,
    compose: { at: 0, dur: 0, text: scene.prompt },
    send: 0,
    assistant: 0,
    thinkingUntil: 0,
    tools: [],
    says: [],
    entries: [],
    ask: null,
    status: null,
    files: null,
    hotspots: null,
    cues: {},
    end: scene.end,
  };
  const cursors: Extract<Step, { kind: 'cursor' }>[] = [];
  scene.steps.forEach((st, i) => {
    switch (st.kind) {
      case 'compose':
        out.compose = { at: st.at, dur: st.dur, text: st.text };
        break;
      case 'send':
        out.send = st.at;
        break;
      case 'assistant':
        out.assistant = st.at;
        break;
      case 'tool': {
        const item = { index: out.tools.length, at: st.at, run: st.run, spec: pick(st.tool, decision), step: i };
        out.tools.push(item);
        out.entries.push({ kind: 'tool', item });
        break;
      }
      case 'say': {
        const segs = pick(st.segs, decision);
        const item = { index: out.says.length, at: st.at, segs, dur: streamDuration(segs), step: i };
        out.says.push(item);
        out.entries.push({ kind: 'say', item });
        break;
      }
      case 'cue':
        out.cues[st.cue] = st.at;
        break;
      case 'ask':
        out.ask = { at: st.at, spec: st.ask, submitted: st.at };
        out.entries.push({ kind: 'ask', at: st.at });
        break;
      case 'cursor':
        cursors.push(st);
        break;
      case 'type':
        if (out.ask) out.ask.type = { at: st.at, dur: st.dur, text: st.text };
        break;
      case 'mark':
        if (out.ask) out.ask.submitted = st.at;
        break;
      case 'status':
        out.status = st.at;
        out.entries.push({ kind: 'status', at: st.at });
        break;
      case 'files':
        out.files = { at: st.at, files: st.files };
        out.entries.push({ kind: 'files', at: st.at, files: st.files });
        break;
      case 'hotspots':
        out.hotspots = { at: st.at, ids: st.ids };
        break;
    }
  });
  if (out.ask) {
    const [first, second] = cursors;
    if (first) out.ask.option = { at: first.at, dur: first.dur, target: first.target };
    if (second) out.ask.submit = { at: second.at, dur: second.dur, target: second.target };
  }
  out.thinkingUntil = out.tools.find((x) => x.at >= out.assistant)?.at ?? out.assistant;
  return out;
}

export type ToolPhase = 'hidden' | 'running' | 'done';

/** 工具条在 t 时的状态。 */
export function toolPhase(tool: Pick<ToolItem, 'at' | 'run'>, t: number): ToolPhase {
  if (t < tool.at) return 'hidden';
  return t < tool.at + tool.run - 1e-9 ? 'running' : 'done';
}

/**
 * 已收起的工具条数（02 章 §2.6）：第 5 个工具条开始时，最早的 (n − 3) 条收成一行；
 * 手机只显示当前一步，其余收为“已完成 k 步”（§2.3）。
 * @param started - 已出现的工具条数。
 * @param mobile - 手机单栏。
 * @returns 收起条数。
 */
export function collapsedCount(started: number, mobile = false): number {
  if (mobile) return Math.max(0, started - 1);
  return started >= 5 ? started - 3 : 0;
}

/** 输入框在 t 时已出现的字数（匀速）。 */
export function composeChars(c: CompiledScene['compose'], t: number): number {
  const len = [...c.text].length;
  if (t < c.at) return 0;
  if (c.dur <= 0) return len;
  return Math.min(len, Math.floor(((t - c.at) / c.dur) * len + 1e-9));
}

/** 匀速逐字写入（`type` 步骤）。 */
export function typedText(text: string, at: number, dur: number, t: number): string {
  const chars = [...text];
  if (t < at) return '';
  if (dur <= 0 || t >= at + dur) return text;
  return chars.slice(0, Math.floor(((t - at) / dur) * chars.length)).join('');
}

/**
 * 原则条点亮项（02 章 §7.4）：播放中取 `at ≤ t` 的最后一个步骤的 `p`；停留阶段为 review。
 * @param scene - 场景。
 * @param t - 场景时刻（含停留，可大于 end）。
 * @returns 点亮的原则。
 */
export function principleAt(scene: Scene, t: number): Principle {
  if (t >= scene.end) return 'review';
  let p: Principle = scene.steps[0]?.p ?? 'dialog';
  for (const st of scene.steps) {
    if (st.at <= t) p = st.p;
    else break;
  }
  return p;
}

/**
 * 热区目标“已经出现”的时刻：暂停时只显示这些时刻已过的热区（02 章 §2.7）。
 * 与各预览的 cue 一致：核减额与工作表页签随“汇总”出现，投控出处随重点卡片，判定随提问卡，房间表随 rooms，视图切换在放大完成后可用。
 */
export const HOTSPOT_READY: Record<HotspotId, number> = {
  reduction: 3.8,
  'sheet-tabs': 3.8,
  'anomaly-source': 3.7,
  decision: 12.95,
  'room-list': 4.9,
  'view-toggle': 8.45,
};

/** 某场景的热区 id（取 `hotspots` 步骤）。 */
export function sceneHotspots(c: CompiledScene): HotspotId[] {
  return c.hotspots?.ids ?? [];
}

/**
 * t 时应显示的热区。
 * @param c - 编译后的场景。
 * @param t - 场景时刻。
 * @param paused - 是否处于 hover / focus / user 暂停。
 * @returns 热区 id。
 */
export function visibleHotspots(c: CompiledScene, t: number, paused: boolean): HotspotId[] {
  const ids = sceneHotspots(c);
  if (c.hotspots && t >= c.hotspots.at) return ids;
  if (!paused) return [];
  return ids.filter((id) => t >= HOTSPOT_READY[id]);
}

/** 计价表核对预览在 t 时的工作表视图（§3.2 时间线）。 */
export type CheckView = 'empty' | 'files' | 'summary' | 'chapters' | 'rows';
export function checkViewAt(cues: CompiledScene['cues'], t: number): CheckView {
  const at = (c: Cue, d = Infinity) => cues[c] ?? d;
  if (t >= at('warnings')) return 'summary';
  if (t >= at('rows')) return 'rows';
  if (t >= at('chapters')) return 'chapters';
  if (t >= at('summary')) return 'summary';
  if (t >= at('files')) return 'files';
  return 'empty';
}

/** 投控预览在 t 时的阶段。 */
export type ReviewPhase = 'empty' | 'loading' | 'ready';
export function reviewPhaseAt(cues: CompiledScene['cues'], t: number): ReviewPhase {
  if (t >= (cues.distribution ?? Infinity)) return 'ready';
  if (t >= (cues['tk-loading'] ?? Infinity)) return 'loading';
  return 'empty';
}

/** 0..1 区间裁剪。 */
export const clamp01 = (v: number) => (v <= 0 ? 0 : v >= 1 ? 1 : v);
/** power2.inOut。 */
export const easeInOut = (p: number) => (p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2);
/** expo.out。 */
export const easeExpo = (p: number) => (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p));
/** power3.out。 */
export const easeOut = (p: number) => 1 - Math.pow(1 - p, 3);

/**
 * 校验场景时刻表（02 章 AC-02-24）：每个 say 在下一个 say/ask/status 之前结束；每个 tool 在下一个 tool 之前结束；最后一步 ≤ end。
 * @param scene - 场景。
 * @param decision - 分支。
 * @returns 违反项说明；空数组表示通过。
 */
export function scheduleIssues(scene: Scene, decision: HitlState): string[] {
  const issues: string[] = [];
  const steps = scene.steps;
  steps.forEach((st, i) => {
    if (st.kind === 'say') {
      const next = steps.slice(i + 1).find((x) => x.kind === 'say' || x.kind === 'ask' || x.kind === 'status');
      const finish = st.at + streamDuration(pick(st.segs, decision));
      if (next && finish > next.at + 1e-9) issues.push(`${scene.id} say@${st.at} 结束于 ${finish.toFixed(3)} > ${next.at}`);
      if (!next && finish > scene.end + 1e-9) issues.push(`${scene.id} say@${st.at} 结束于 ${finish.toFixed(3)} > end`);
    }
    if (st.kind === 'tool') {
      const next = steps.slice(i + 1).find((x) => x.kind === 'tool');
      if (next && st.at + st.run > next.at + 1e-9) issues.push(`${scene.id} tool@${st.at} 超过下一个工具 ${next.at}`);
    }
  });
  const last = steps[steps.length - 1];
  if (last && last.at > scene.end) issues.push(`${scene.id} 最后一步 ${last.at} > end ${scene.end}`);
  return issues;
}
