/**
 * 同屏调度（07 章 §3.3）：处于 `live` 的装饰登记可见比例，同一时刻只有可见比例最大的一个运行待机动画
 * （D2 的闪烁与扫光、D3 的缓摆），其余停在静态终帧并休眠；可见比例变化时重新分配。
 * 入场动画、D1 的指针响应、D4 的滚动标注不参与调度。
 */

export interface DecoSlot {
  /** 更新可见比例（0..1；不可见或页面隐藏时传 0）。 */
  setRatio(ratio: number): void;
  /** 当前是否持有待机动画的运行权。 */
  readonly granted: boolean;
  /** 注销（组件卸载时）。 */
  release(): void;
}

interface Entry {
  ratio: number;
  granted: boolean;
  onChange: (granted: boolean) => void;
}

const entries = new Set<Entry>();
let current: Entry | null = null;

function assign() {
  let best: Entry | null = null;
  for (const entry of entries) {
    if (entry.ratio <= 0) continue;
    if (!best || entry.ratio > best.ratio) best = entry;
  }
  // 比例相同时保留当前持有者，避免来回切换
  if (best && current && current !== best && entries.has(current) && current.ratio >= best.ratio) best = current;
  if (best === current) return;
  const prev = current;
  current = best;
  if (prev) {
    prev.granted = false;
    prev.onChange(false);
  }
  if (best) {
    best.granted = true;
    best.onChange(true);
  }
}

/**
 * 登记一个 live 装饰。
 * @param onChange - 运行权变化时调用（true = 可以跑待机动画）。
 * @returns 登记句柄。
 */
export function registerDeco(onChange: (granted: boolean) => void): DecoSlot {
  const entry: Entry = { ratio: 0, granted: false, onChange };
  entries.add(entry);
  return {
    setRatio(ratio: number) {
      const next = Math.max(0, Math.min(1, ratio));
      if (next === entry.ratio) return;
      entry.ratio = next;
      assign();
    },
    get granted() {
      return entry.granted;
    },
    release() {
      if (!entries.delete(entry)) return;
      if (current === entry) {
        current = null;
        entry.granted = false;
      }
      assign();
    },
  };
}

/** 当前登记数与持有者数（测试用）。 */
export function schedulerSnapshot() {
  let granted = 0;
  for (const entry of entries) if (entry.granted) granted++;
  return { size: entries.size, granted };
}
