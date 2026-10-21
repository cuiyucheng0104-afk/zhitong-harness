<script setup lang="ts">
/**
 * 场景三预览：图纸（02 章 §5.5）。路径条（右侧当前图片名与尺寸，选中房间时改为“房间 · 文字 id · 多段线句柄”）、
 * “S1 总览 ｜ E4 放大”分段切换（cue `zoom` 之前禁用）、平面图、房间面积表（cue `rooms` 起）。
 * 手动：点表格行或图上房间高亮该房间（会议室201 在放大视图时保持 E4，其余切回总览）；视图切换 viewBox 补间 0.6 s。
 */
import { computed, onBeforeUnmount, ref } from 'vue';
import CadDrawing from './CadDrawing.vue';
import { CAD, HOTSPOT_TITLES } from '../../data/demo';
import { formatMoney } from '../../lib/format';
import { prefersReducedMotion } from '../../lib/motion';
import { clamp01, type CompiledScene } from './engine';
import { useDemoContext, type CadView } from './store';

const props = defineProps<{ compiled: CompiledScene; t: number }>();
const ctx = useDemoContext();
const store = ctx.store;

const cues = computed(() => props.compiled.cues);
const at = (name: keyof CompiledScene['cues']) => cues.value[name] ?? 0;
const zoomAt = computed(() => at('zoom'));

/* 视图补间（手动切换，0.6 s）。 */
const tween = ref<{ from: number; to: number; start: number } | null>(null);
const tweenNow = ref(0);
let frame = 0;
function stepTween(now: number) {
  tweenNow.value = now;
  const tw = tween.value;
  if (!tw) return;
  if ((now - tw.start) / 600 >= 1) {
    tween.value = null;
    return;
  }
  frame = requestAnimationFrame(stepTween);
}
onBeforeUnmount(() => cancelAnimationFrame(frame));

const timelineZ = computed(() => clamp01((props.t - zoomAt.value) / 0.8));
const z = computed(() => {
  const tw = tween.value;
  if (tw) {
    const p = clamp01((tweenNow.value - tw.start) / 600);
    return tw.from + (tw.to - tw.from) * p;
  }
  if (store.views.cad) return store.views.cad === 'E4' ? 1 : 0;
  return timelineZ.value;
});
const current = computed<CadView>(() => (z.value >= 0.5 ? 'E4' : 'S1'));
const enabled = computed(() => store.views.cad !== null || props.t >= zoomAt.value);

function setView(v: CadView) {
  const from = z.value;
  const to = v === 'E4' ? 1 : 0;
  store.views.cad = v;
  if (from === to || prefersReducedMotion() || ctx.still.value || typeof requestAnimationFrame !== 'function') {
    tween.value = null;
    return;
  }
  const now = performance.now();
  tween.value = { from, to, start: now };
  tweenNow.value = now;
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(stepTween);
}

function chooseView(v: CadView) {
  ctx.interact();
  setView(v);
}

/** 只有会议室201 的多段线完全在 E4 范围内。 */
const IN_E4 = new Set(['会议室201']);
function selectRoom(label: string) {
  ctx.interact();
  store.room.value = label;
  store.roomPulse.value += 1;
  if (!(IN_E4.has(label) && current.value === 'E4')) setView('S1');
}

const selected = computed(() => CAD.rooms.rows.find((r) => r.label === store.room.value) ?? null);
const imageInfo = computed(() =>
  current.value === 'E4' ? 'd4f1c09a2b7e3-S1-E4-3b8d0f42.png · 1600×1515' : 'd4f1c09a2b7e3-S1-7c2e91ab.png · 1600×1151',
);
const num = (v: number | null) => (v === null ? '—' : formatMoney(v));
</script>

<template>
  <div class="preview cad-preview" :data-view="current" :style="store.views.cad ? { '--t': 999 } : undefined">
    <div class="preview-path">
      <span class="mono">{{ CAD.file }}</span>
      <span class="preview-path-aside mono">{{
        selected ? `${selected.label} · ${selected.text} · 多段线 ${selected.poly_handle}` : imageInfo
      }}</span>
    </div>
    <div class="cad-toolbar">
      <div
        class="cad-toggle"
        role="group"
        aria-label="图纸视图"
        :title="HOTSPOT_TITLES['view-toggle']"
        data-hotspot-target="view-toggle"
      >
        <button type="button" :aria-pressed="current === 'S1'" :disabled="!enabled" data-cad-view="S1" @click="chooseView('S1')">
          S1 总览
        </button>
        <button type="button" :aria-pressed="current === 'E4'" :disabled="!enabled" data-cad-view="E4" @click="chooseView('E4')">
          E4 放大
        </button>
      </div>
    </div>
    <CadDrawing :cues="cues" :z="z" :room="store.room.value" :pulse="store.roomPulse.value" @select="selectRoom" />
    <div class="cad-rooms-panel" data-a="fade" :style="{ '--at': at('rooms') }">
      <p class="cad-rooms-title">
        房间面积 · <span class="mono">cad_rooms</span> · S1 · 锚点 {{ CAD.rooms.anchors }}，匹配 {{ CAD.rooms.matched }}
      </p>
      <div class="cad-rooms-scroll" data-lenis-prevent :title="HOTSPOT_TITLES['room-list']" data-hotspot-target="room-list">
        <table class="demo-table cad-room-table">
          <caption class="sr-only">房间面积，cad_rooms 返回，按差异降序</caption>
          <thead>
            <tr><th>房间</th><th class="num">文字面积 m²</th><th class="num">几何面积 m²</th><th class="num">差异%</th></tr>
          </thead>
          <tbody>
            <tr
              v-for="(r, i) in CAD.rooms.rows"
              :key="r.poly_handle"
              :class="{ 'is-warn': (r.diff_pct ?? 0) > 1, 'is-selected': store.room.value === r.label }"
              :data-room-row="r.label"
              data-a="fade up"
              :style="{ '--at': at('rooms') + i * 0.08, '--dy': '-6px' }"
            >
              <td>
                <button type="button" class="room-button" :aria-pressed="store.room.value === r.label" @click="selectRoom(r.label)">
                  {{ r.label }}<span v-if="(r.diff_pct ?? 0) > 1" class="check-tag">需核对</span>
                </button>
              </td>
              <td class="num mono">{{ num(r.text_m2) }}</td>
              <td class="num mono">{{ num(r.geom_m2) }}</td>
              <td class="num mono">{{ num(r.diff_pct) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="cad-note">{{ CAD.rooms.note }}</p>
    </div>
  </div>
</template>
