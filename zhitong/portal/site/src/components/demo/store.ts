/**
 * 工作示例的交互状态（02 章 §2.4 中 `useDemoState` 的职责：复核记录、选中房间、预览视图、决定分支）。
 * 由 WorkDemo 创建并 provide 给对话栏与三个预览；每个 WorkDemo 实例独立（不在模块级共享）。
 */
import { inject, reactive, ref, type InjectionKey, type Ref } from 'vue';
import { TK, reviewRecordLine, type Anomaly, type HitlState } from '../../data/demo';
import type { SceneId } from '../../types/portal';
import type { CheckView } from './engine';

export interface ReviewRecord {
  anomalyId: string;
  from: HitlState;
  to: HitlState;
  reason: string;
  ts: string;
  line: string;
}

export type CheckSheet = Exclude<CheckView, 'empty' | 'files'>;
export type ReviewSheet = 'summary' | 'list' | 'unaligned';
export type CadView = 'S1' | 'E4';

/** 当前时间的 UTC 秒级 ISO 串（与 zt.tk.review 一致，形如 2026-10-19T06:42:18+00:00）。 */
export function utcSeconds(date = new Date()): string {
  return `${date.toISOString().slice(0, 19)}+00:00`;
}

/** 按记录顺序折叠出每条异常的当前状态（未出现记录的为 pending）。 */
export function foldStates(records: readonly Pick<ReviewRecord, 'anomalyId' | 'to'>[]): Record<string, HitlState> {
  const out: Record<string, HitlState> = {};
  for (const a of TK.focus) out[a.anomaly_id] = 'pending';
  for (const r of records) out[r.anomalyId] = r.to;
  return out;
}

/** 自动播放写入的那一行（§4.5，逐字由 reviewRecordLine 生成）。 */
export function autoRecord(decision: HitlState, reason: string, ts = TK.autoRecordTs): ReviewRecord {
  const a = TK.focus[0]! as Anomaly;
  return { anomalyId: a.anomaly_id, from: 'pending', to: decision, reason, ts, line: reviewRecordLine(a, 'pending', decision, reason, ts) };
}

export function createDemoStore() {
  /** 确认提问卡的决定（自动播放为 confirmed）。 */
  const decision = ref<HitlState>('confirmed');
  /** 用户在提问卡里点过的选项（提交前）；null 表示未操作。 */
  const askChoice = ref<HitlState | null>(null);
  /** 用户亲手提交过：提交时间（UTC 秒）。 */
  const askUserTs = ref<string | null>(null);
  /** 手动决定追加的记录（演示记录，仅当前页面有效）。 */
  const manualRecords = ref<ReviewRecord[]>([]);
  /** 投控卡片展开项。 */
  const expanded = ref<string[]>([TK.focus[0]!.anomaly_id]);
  /** 复核记录抽屉：null = 跟随时间线。 */
  const drawer = ref<boolean | null>(null);
  /** 各预览的手动视图：null = 跟随时间线。 */
  const views = reactive<{ check: CheckSheet | null; review: ReviewSheet | null; cad: CadView | null }>({
    check: null,
    review: null,
    cad: null,
  });
  /** 选中的房间（label）与最近一次选中的时间戳（驱动脉冲）。 */
  const room = ref<string | null>(null);
  const roomPulse = ref(0);
  /** 对话栏“已完成 k 步 · 展开”。 */
  const toolsOpen = reactive<Record<SceneId, boolean>>({ check: false, review: false, cad: false });
  /** 逐行核对行闪烁（“看逐行核对”后第 1 行闪两次）。 */
  const flashRow = ref(0);

  /** 回到初态（场景从 0 s 重新播放时调用）。 */
  function reset(id: SceneId) {
    toolsOpen[id] = false;
    views[id] = null;
    if (id === 'review') {
      decision.value = 'confirmed';
      askChoice.value = null;
      askUserTs.value = null;
      manualRecords.value = [];
      expanded.value = [TK.focus[0]!.anomaly_id];
      drawer.value = null;
    }
    if (id === 'cad') room.value = null;
  }

  /**
   * 手动决定：追加一行（只追加不改写，与 zt.tk.review 一致）。
   * @param a - 异常。
   * @param from - 当前状态。
   * @param to - 新状态。
   */
  function appendDecision(a: Anomaly, from: HitlState, to: HitlState) {
    const reason = to === 'pending' ? TK.undoReason : a.reasons[to];
    const ts = utcSeconds();
    manualRecords.value = [
      ...manualRecords.value,
      { anomalyId: a.anomaly_id, from, to, reason, ts, line: reviewRecordLine(a, from, to, reason, ts) },
    ];
  }

  return {
    decision,
    askChoice,
    askUserTs,
    manualRecords,
    expanded,
    drawer,
    views,
    room,
    roomPulse,
    toolsOpen,
    flashRow,
    reset,
    appendDecision,
  };
}

export type DemoStore = ReturnType<typeof createDemoStore>;

/** WorkDemo 提供给子组件的上下文。 */
export interface DemoContext {
  store: DemoStore;
  /** 手机单栏。 */
  mobile: Ref<boolean>;
  /** 减少动效或动效块不可用：只显示终态。 */
  still: Ref<boolean>;
  /** 用户在示例内操作：进入手动模式。 */
  interact: () => void;
  /** 打开出处弹层（核减额按钮）。 */
  openSource: (trigger: HTMLElement) => void;
  /** 打开原表片段说明卡。 */
  openRows: (a: Anomaly, trigger: HTMLElement) => void;
  /** 确认提问卡提交（手动）。 */
  submitAsk: (choice: HitlState) => void;
}

export const DEMO_CONTEXT: InjectionKey<DemoContext> = Symbol('demo-context');

/** 子组件取上下文；单独挂载（测试）时给一份独立的默认值。 */
export function useDemoContext(): DemoContext {
  return (
    inject(DEMO_CONTEXT, null) ?? {
      store: createDemoStore(),
      mobile: ref(false),
      still: ref(true),
      interact: () => undefined,
      openSource: () => undefined,
      openRows: () => undefined,
      submitAsk: () => undefined,
    }
  );
}
