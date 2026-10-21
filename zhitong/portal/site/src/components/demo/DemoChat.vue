<script setup lang="ts">
/**
 * 对话栏（02 章 §2.4、§2.6）：装饰输入框、用户气泡、助手标题与思考点、工具条（ZtToolCall）、流式段落（ZtStream）、
 * 确认提问卡、结果状态（ZtStatus）与“需人工确认”、产出文件条。
 * 全部内容由场景时刻 `t` 推出；位移与透明度由样式表按 `--t`/`--at` 计算（见 engine.ts 头注释）。
 * 播放中未完成的文字 `aria-hidden`，完成后移除；容器 `aria-live="off"`。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import ZtStream from '../ui/ZtStream.vue';
import ZtToolCall from '../ui/ZtToolCall.vue';
import ZtStatus from '../ui/ZtStatus.vue';
import AppIcon from '../AppIcon.vue';
import DemoAskCard from './DemoAskCard.vue';
import { HOTSPOT_TITLES, STREAM_CPS, STREAM_PAUSE, type HitlState } from '../../data/demo';
import { getMotion } from '../../lib/motion';
import { DUR, EASE } from '../../lib/motion-tokens';
import { collapsedCount, composeChars, toolPhase, type CompiledScene, type ToolItem } from './engine';
import { useDemoContext } from './store';

const props = defineProps<{
  compiled: CompiledScene;
  t: number;
  /** 播放中：自动保持滚动到底。 */
  follow: boolean;
}>();

const ctx = useDemoContext();
const scroller = ref<HTMLElement | null>(null);
const inner = ref<HTMLElement | null>(null);
const c = computed(() => props.compiled);
const id = computed(() => c.value.scene.id);

const draftChars = computed(() => (props.t < c.value.send ? composeChars(c.value.compose, props.t) : 0));
const draft = computed(() => [...c.value.compose.text].slice(0, draftChars.value).join(''));
const composing = computed(() => props.t >= c.value.compose.at && props.t < c.value.send);
const sendPress = computed(() => {
  const d = props.t - c.value.send;
  if (d < 0 || d > 0.24) return 1;
  return d < 0.12 ? 1 - 0.06 * (d / 0.12) : 0.94 + 0.06 * ((d - 0.12) / 0.12);
});
const thinking = computed(() => props.t >= c.value.assistant && props.t < c.value.thinkingUntil);

const started = computed(() => c.value.tools.filter((x) => props.t >= x.at).length);
const collapsed = computed(() => (ctx.store.toolsOpen[id.value] ? 0 : collapsedCount(started.value, ctx.mobile.value)));

/** “已完成 k 步”第一次出现的时刻：桌面为第 5 个工具条开始，手机为第 2 个。 */
const collapseAt = computed(() => c.value.tools[ctx.mobile.value ? 1 : 4]?.at ?? 0);

const counts = computed(() => {
  if (id.value === 'check') return { warn: 1, info: 2 };
  if (id.value === 'review') return { info: 1 };
  return undefined;
});

const ask = computed(() => c.value.ask);
const askInstant = computed(() => ctx.mobile.value || ctx.still.value);

function phase(item: ToolItem) {
  return toolPhase(item, props.t);
}

function expandTools() {
  ctx.interact();
  ctx.store.toolsOpen[id.value] = true;
}

function onChoose(value: HitlState) {
  ctx.interact();
  ctx.store.askChoice.value = value;
}
function onSubmit(value: HitlState) {
  ctx.submitAsk(value);
}

function openSource(e: MouseEvent) {
  ctx.openSource(e.currentTarget as HTMLElement);
}

/* 自动滚动到底：内容高度变化且处于播放中。 */
let resize: ResizeObserver | undefined;
function toBottom(instant = false) {
  const el = scroller.value;
  if (!el) return;
  const top = el.scrollHeight - el.clientHeight;
  if (top <= 0 || Math.abs(el.scrollTop - top) < 1) return;
  const motion = getMotion();
  if (motion && !instant && !ctx.still.value)
    motion.gsap.to(el, { scrollTop: top, duration: DUR.short, ease: EASE.out, overwrite: true });
  else el.scrollTop = top;
}
watch(
  () => props.t < c.value.send,
  (reset) => {
    if (reset && scroller.value) scroller.value.scrollTop = 0;
  },
);
onMounted(() => {
  if (typeof ResizeObserver !== 'undefined' && inner.value) {
    resize = new ResizeObserver(() => {
      if (props.follow) toBottom();
    });
    resize.observe(inner.value);
  }
  void nextTick(() => toBottom(true));
});
onBeforeUnmount(() => resize?.disconnect());
defineExpose({ toBottom });
</script>

<template>
  <div class="demo-chat">
    <div ref="scroller" class="demo-chat-scroll" data-lenis-prevent aria-live="off">
      <div ref="inner" class="demo-chat-inner">
        <div v-if="t >= compiled.send" class="chat-user" data-a="fade up" :style="{ '--at': compiled.send, '--dy': '12px' }">
          <p class="chat-bubble"><span class="sr-only">示例用户张工：</span>{{ compiled.scene.prompt }}</p>
          <span class="chat-avatar" aria-hidden="true">张</span>
        </div>
        <div v-if="t >= compiled.assistant" class="chat-assistant" data-a="fade up" :style="{ '--at': compiled.assistant }">
          <span class="assistant-mark" aria-hidden="true"></span><span class="assistant-name">智通数工AI</span>
          <span v-if="thinking" class="thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span>
          <span v-if="thinking" class="sr-only">正在处理</span>
        </div>
        <template v-for="(entry, k) in compiled.entries" :key="k">
          <template v-if="entry.kind === 'tool'">
            <button
              v-if="entry.item.index === 0 && collapsed > 0"
              type="button"
              class="chat-collapsed"
              data-a="fade"
              :style="{ '--at': collapseAt }"
              @click="expandTools"
            >
              已完成 {{ collapsed }} 步 · 展开
            </button>
            <div
              v-if="phase(entry.item) !== 'hidden' && entry.item.index >= collapsed"
              class="chat-tool"
              :class="`is-${phase(entry.item)}`"
              data-a="fade up"
              :style="{ '--at': entry.item.at, '--done': entry.item.at + entry.item.run }"
              :aria-hidden="phase(entry.item) === 'running' ? 'true' : undefined"
              :data-tool="entry.item.spec.name"
            >
              <ZtToolCall
                :tool="entry.item.spec"
                :state="phase(entry.item) === 'running' ? 'running' : 'done'"
                :compact="ctx.mobile.value"
              />
            </div>
          </template>
          <ZtStream
            v-else-if="entry.kind === 'say' && t >= entry.item.at"
            class="chat-say"
            :segs="entry.item.segs"
            :time="t - entry.item.at"
            :cps="STREAM_CPS"
            :pause="STREAM_PAUSE"
            data-a="fade"
            :style="{ '--at': entry.item.at, '--dur': 0.16 }"
          >
            <template #seg="{ seg }">
              <button
                v-if="typeof seg !== 'string' && seg.hotspot === 'reduction'"
                type="button"
                class="mono chat-amount"
                :title="HOTSPOT_TITLES.reduction"
                :aria-label="`核减额 ${seg.t} 元，查看出处`"
                @click="openSource"
              >
                {{ seg.t }}
              </button>
              <span v-else-if="typeof seg !== 'string'" class="mono chat-mono">{{ seg.t }}</span>
            </template>
          </ZtStream>
          <DemoAskCard
            v-else-if="entry.kind === 'ask' && ask && t >= entry.at"
            :ask="ask"
            :t="t"
            :decision="compiled.decision"
            :choice="ctx.store.askChoice.value"
            :instant="askInstant"
            data-a="fade up"
            :style="{ '--at': entry.at, '--dy': '8px' }"
            @choose="onChoose"
            @submit="onSubmit"
          />
          <div v-else-if="entry.kind === 'status' && t >= entry.at" class="chat-status" data-a="fade pop" :style="{ '--at': entry.at }">
            <ZtStatus value="ok" :counts="counts" manual />
          </div>
          <ul v-else-if="entry.kind === 'files' && t >= entry.at" class="chat-files" aria-label="产出文件">
            <li
              v-for="(f, i) in entry.files"
              :key="f.name"
              :title="f.dir + f.name"
              data-a="fade left"
              :style="{ '--at': entry.at + i * 0.07 }"
            >
              <AppIcon name="file" /><span class="chat-file-name">{{ f.name }}</span
              ><span class="chat-file-dir mono">{{ f.dir }}</span>
            </li>
          </ul>
        </template>
      </div>
    </div>
    <div class="chat-input" aria-hidden="true">
      <span class="chat-input-box" :class="{ 'is-composing': composing }">
        <span v-if="draft" class="chat-draft">{{ draft }}<i class="chat-caret"></i></span>
        <span v-else class="chat-placeholder">输入任务…</span>
      </span>
      <span class="chat-send" :style="{ transform: `scale(${sendPress})` }"><AppIcon name="arrow" /></span>
    </div>
  </div>
</template>
