<script lang="ts">
import type { StreamSeg } from './types';

/** 中文标点：遇到后停顿（02 章 §0）。 */
export const STREAM_PUNCT = '，。；：、！？';

export interface StreamUnit {
  /** 所在片段序号。 */
  seg: number;
  /** 片段内到此单元结束为止的字符数（mono 片段为全长）。 */
  end: number;
  /** 出现时刻（秒）。 */
  at: number;
}

/**
 * 把片段拆成逐字出现的单元（纯函数）。
 * @param segs - 片段。
 * @param cps - 字/秒。
 * @param pause - 标点停顿秒数。
 * @returns 单元列表与总时长。
 */
export function streamUnits(segs: readonly StreamSeg[], cps = 32, pause = 0.12) {
  const units: StreamUnit[] = [];
  let t = 0;
  segs.forEach((seg, i) => {
    if (typeof seg !== 'string') {
      units.push({ seg: i, end: seg.t.length, at: t });
      t += 1 / cps;
      return;
    }
    [...seg].forEach((ch, j) => {
      units.push({ seg: i, end: j + 1, at: t });
      t += 1 / cps + (STREAM_PUNCT.includes(ch) ? pause : 0);
    });
  });
  return { units, duration: t };
}

/**
 * 计算某片段在 t 秒时可见的文字（纯函数）。
 * @param segs - 片段。
 * @param visible - 已出现的单元数。
 * @param units - `streamUnits` 结果。
 * @returns 每个片段已出现的字符数。
 */
export function visibleLengths(segs: readonly StreamSeg[], visible: number, units: readonly StreamUnit[]) {
  const out = segs.map(() => 0);
  for (let k = 0; k < Math.min(visible, units.length); k++) out[units[k]!.seg] = units[k]!.end;
  return out;
}
</script>

<script setup lang="ts">
/**
 * 模拟流式输出的文字（00 章 §6.9）：按字符逐段出现，默认 32 字/秒（00 章范围 28–36），遇中文标点停 120 ms；
 * mono 片段整段出现，计 1 字。末尾 2px 闪烁光标，结束后淡出。
 * 读屏只读完整文本：容器 `aria-live="off"`；播放中可视文本 `aria-hidden`，完成后整段对读屏可见（`fullText` 已暴露）。
 *
 * 两种驱动：传 `time`（秒）为受控模式，由调用方时间线定位；不传时用 `play()`/`pause()`/`reset()`/`finish()` 自播。
 * 预渲染与未启动时显示终态。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue';

const props = withDefaults(
  defineProps<{
    /** 片段；与 text 二选一。 */
    segs?: readonly StreamSeg[];
    text?: string;
    /** 字/秒，默认 32。 */
    cps?: number;
    /** 标点停顿秒数，默认 0.12。 */
    pause?: number;
    /** 受控时刻（秒）；undefined 时为自播模式。 */
    time?: number;
    tag?: string;
  }>(),
  { segs: undefined, text: '', cps: 32, pause: 0.12, time: undefined, tag: 'p' },
);
const emit = defineEmits<{ done: [] }>();

const list = computed<readonly StreamSeg[]>(() => props.segs ?? [props.text]);
const plan = computed(() => streamUnits(list.value, props.cps, props.pause));
const fullText = computed(() => list.value.map((s) => (typeof s === 'string' ? s : s.t)).join(''));

const selfTime = ref<number | null>(null);
let frame = 0;
let last = 0;

const now = computed(() => props.time ?? selfTime.value ?? Infinity);
const visible = computed(() => {
  const t = now.value;
  if (t === Infinity) return plan.value.units.length;
  let n = 0;
  for (const u of plan.value.units) if (u.at <= t) n++;
  return n;
});
const lengths = computed(() => visibleLengths(list.value, visible.value, plan.value.units));
const done = computed(() => visible.value >= plan.value.units.length);
const typing = computed(() => !done.value && visible.value >= 0 && now.value !== Infinity);

watch(done, (value, old) => {
  if (value && old === false) emit('done');
});

function stop() {
  cancelAnimationFrame(frame);
  frame = 0;
}
function tick(ts: number) {
  const dt = last ? (ts - last) / 1000 : 0;
  last = ts;
  selfTime.value = (selfTime.value ?? 0) + dt;
  if (selfTime.value >= plan.value.duration) {
    stop();
    return;
  }
  frame = requestAnimationFrame(tick);
}

defineExpose({
  /** 完整文本。 */
  fullText,
  /** 总时长（秒）。 */
  duration: computed(() => plan.value.duration),
  /** 从当前位置开始自播；处于终态时从头开始。 */
  play() {
    if (selfTime.value === null || selfTime.value >= plan.value.duration) selfTime.value = 0;
    stop();
    last = 0;
    if (typeof requestAnimationFrame === 'function') frame = requestAnimationFrame(tick);
    else selfTime.value = plan.value.duration;
  },
  pause: stop,
  /** 回到空白初态。 */
  reset() {
    stop();
    selfTime.value = 0;
  },
  /** 直接显示终态。 */
  finish() {
    stop();
    selfTime.value = null;
  },
});
onBeforeUnmount(stop);
</script>

<template>
  <component :is="tag" class="zt-stream" :class="{ 'is-typing': typing, 'is-done': done }" aria-live="off">
    <span :aria-hidden="done ? undefined : 'true'" class="zt-stream-visible"
      ><template v-for="(seg, i) in list" :key="i"
        ><template v-if="typeof seg === 'string'">{{ seg.slice(0, lengths[i]) }}</template
        ><template v-else-if="lengths[i]"
          ><slot name="seg" :seg="seg" :index="i"
            ><span class="mono">{{ seg.t }}</span></slot
          ></template
        ></template
      ><i class="zt-stream-caret"></i
    ></span>
  </component>
</template>
