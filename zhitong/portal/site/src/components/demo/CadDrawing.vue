<script setup lang="ts">
/**
 * 示例平面图（02 章 §5.4、§5.5）：静态图层（CadLayers）+ 随时间线出现的叠加层：
 * unit（DIM 闪蓝 + 角标）、frame（外框虚线描出 + 图名/图号/比例文字框描蓝）、rooms（9 个多段线填充 + 走道“未匹配”）、
 * grid（8×6 网格与 A–H、1–6 标签）、scan-s1 / scan-e4（读图扫描带）、zoom（viewBox 补间到 E4）、highlight（会议室201 沿轴线重画）。
 * 网格标签与说明标签用 HTML 叠在图上（12px），位置按当前 viewBox 换算，保证示例窗口内文字 ≥ 12px（00 章 §4.3）。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import CadLayers from './CadLayers.vue';
import { CAD } from '../../data/demo';
import { GRID, ROOMS, TEXTS, UNMATCHED, VIEW } from '../../data/demo-drawing';
import { clamp01, easeInOut } from './engine';

const props = defineProps<{
  cues: Partial<Record<string, number>>;
  /** 视图补间的线性进度：0 = S1 总览，1 = E4 放大。 */
  z: number;
  /** 选中的房间（label）。 */
  room: string | null;
  /** 选中次数（驱动脉冲重播）。 */
  pulse: number;
}>();
const emit = defineEmits<{ select: [label: string, event: Event] }>();

const at = (name: string) => props.cues[name] ?? 0;
const q = computed(() => easeInOut(clamp01(props.z)));
const view = computed(() => {
  const a = VIEW.S1;
  const b = VIEW.E4;
  const k = q.value;
  return { x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k, w: a.w + (b.w - a.w) * k, h: a.h + (b.h - a.h) * k };
});
const viewBox = computed(() => {
  const v = view.value;
  return [v.x, v.y, v.w, v.h].map((n) => Number(n.toFixed(2))).join(' ');
});
/** 文字框淡出（放大开始 0.3 s 内）、文字本身在进度 60% 后淡入（0.2 s）。 */
const frameFade = computed(() => 1 - clamp01(props.z / 0.375));
const textMix = computed(() => clamp01((props.z - 0.6) / 0.25));

/* 屏幕宽度 → 每单位像素数，用于放大视图最小字高。 */
const root = ref<HTMLElement | null>(null);
const widthPx = ref(477);
let resize: ResizeObserver | undefined;
onMounted(() => {
  if (!root.value) return;
  widthPx.value = root.value.clientWidth || 477;
  if (typeof ResizeObserver !== 'undefined') {
    resize = new ResizeObserver(() => {
      if (root.value?.clientWidth) widthPx.value = root.value.clientWidth;
    });
    resize.observe(root.value);
  }
});
onBeforeUnmount(() => resize?.disconnect());
const minText = computed(() => Number((12 / (widthPx.value / VIEW.E4.w)).toFixed(3)));

const pct = (x: number, y: number) => {
  const v = view.value;
  return { left: `${((x - v.x) / v.w) * 100}%`, top: `${((y - v.y) / v.h) * 100}%` };
};

/* 网格：图框 S1 0,0–841,594 上 8×6 等分。 */
const cw = 841 / GRID.cols;
const rh = 594 / GRID.rows;
const vLines = Array.from({ length: GRID.cols - 1 }, (_, i) => (i + 1) * cw);
const hLines = Array.from({ length: GRID.rows - 1 }, (_, i) => (i + 1) * rh);
const colLabels = 'ABCDEFGH'.split('').map((l, i) => ({ l, x: (i + 0.5) * cw }));
const rowLabels = Array.from({ length: GRID.rows }, (_, i) => ({ l: String(i + 1), y: (i + 0.5) * rh }));
const e4Cell = { x: 4 * cw, y: 3 * rh, w: cw, h: rh };

/* 房间：按房间表顺序填充。 */
const order = CAD.rooms.rows.map((r) => r.label);
const rooms = [...ROOMS].sort((a, b) => order.indexOf(a.label) - order.indexOf(b.label));
const roomAt = (i: number) => at('rooms') + i * 0.08;
const unmatched = UNMATCHED[0];
const refs = (['T41', 'T43', 'T45'] as const).map((id) => {
  const t = TEXTS.find((x) => x[0] === id)!;
  const [, text, x, y, h] = t;
  const w = [...text].reduce((s, ch) => s + (ch.charCodeAt(0) > 0x2e80 ? h : 0.6 * h), 0);
  return { id, x, y: y - h, w, h };
});
const meeting = ROOMS.find((r) => r.label === '会议室201')!;
const meetingRect = {
  x: meeting.rect[0],
  y: meeting.rect[1],
  width: meeting.rect[2] - meeting.rect[0],
  height: meeting.rect[3] - meeting.rect[1],
};

function select(label: string, e: Event) {
  emit('select', label, e);
}
</script>

<template>
  <div
    ref="root"
    class="cad-drawing"
    :style="{ '--rf': frameFade, '--tx': textMix, '--zoomed': q }"
    :data-view="z >= 1 ? 'E4' : z <= 0 ? 'S1' : 'zoom'"
  >
    <svg
      class="cad-svg"
      :viewBox="viewBox"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      :aria-label="`示例图纸 A-02 二层平面图，${z >= 1 ? 'E4 放大' : 'S1 总览'}`"
    >
      <defs>
        <linearGradient id="demo-cad-scan" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#0666f5" stop-opacity="0" />
          <stop offset=".5" stop-color="#0666f5" stop-opacity=".18" />
          <stop offset="1" stop-color="#0666f5" stop-opacity="0" />
        </linearGradient>
        <mask id="demo-cad-frame-mask" maskUnits="userSpaceOnUse" x="-20" y="-20" width="881" height="634">
          <rect
            x="0"
            y="0"
            width="841"
            height="594"
            fill="none"
            stroke="#fff"
            stroke-width="12"
            pathLength="1"
            data-a="draw"
            :style="{ '--at': at('frame'), '--dur': 0.6 }"
          />
        </mask>
        <mask id="demo-cad-hl-mask" maskUnits="userSpaceOnUse" x="400" y="290" width="140" height="120">
          <rect
            v-bind="meetingRect"
            fill="none"
            stroke="#fff"
            stroke-width="3"
            pathLength="1"
            data-a="draw"
            :style="{ '--at': at('highlight'), '--dur': 0.45 }"
          />
        </mask>
      </defs>
      <rect class="cad-paper" x="-19.81" y="-19.81" width="880.62" height="633.62" />
      <CadLayers
        :plot-at="at('plot')"
        :unit-at="at('unit')"
        :show-rects="textMix < 1"
        :show-texts="z >= 0.6"
        :min-text="minText"
      />
      <!-- rooms：房间多段线（TXTROOM 层，平时不描边） -->
      <g class="cad-rooms">
        <rect
          v-for="(r, i) in rooms"
          :key="r.handle"
          class="cad-room"
          :class="{ 'is-warn': r.label === '会议室201', 'is-selected': room === r.label }"
          :x="r.rect[0]"
          :y="r.rect[1]"
          :width="r.rect[2] - r.rect[0]"
          :height="r.rect[3] - r.rect[1]"
          :data-room="r.label"
          :data-pulse="room === r.label ? pulse : undefined"
          data-a="fade"
          :style="{ '--at': roomAt(i), '--dur': 0.28 }"
          @click="select(r.label, $event)"
        />
        <rect
          class="cad-unmatched"
          :x="unmatched.rect[0]"
          :y="unmatched.rect[1]"
          :width="unmatched.rect[2] - unmatched.rect[0]"
          :height="unmatched.rect[3] - unmatched.rect[1]"
          data-a="fade"
          :style="{ '--at': roomAt(9), '--dur': 0.28 }"
        />
      </g>
      <!-- frame：外框虚线（顺时针描出）与标题栏文字框描蓝 -->
      <rect class="cad-frame-dash" x="0" y="0" width="841" height="594" mask="url(#demo-cad-frame-mask)" />
      <rect
        v-for="(r, i) in refs"
        :key="r.id"
        class="cad-ref"
        :x="r.x - 0.6"
        :y="r.y - 0.6"
        :width="r.w + 1.2"
        :height="r.h + 1.2"
        data-a="fade"
        :style="{ '--at': at('frame') + i * 0.07 }"
      />
      <!-- grid：8×6 网格（内部 7 竖 5 横），放大时淡出 -->
      <g class="cad-grid">
        <line
          v-for="(x, i) in vLines"
          :key="`v${i}`"
          :x1="x"
          y1="0"
          :x2="x"
          y2="594"
          data-grid="v"
          data-a="grow-y"
          :style="{ '--at': at('grid') + i * 0.03, '--dur': 0.3 }"
        />
        <line
          v-for="(y, i) in hLines"
          :key="`h${i}`"
          x1="0"
          :y1="y"
          x2="841"
          :y2="y"
          data-grid="h"
          data-a="grow-x"
          :style="{ '--at': at('grid') + (vLines.length + i) * 0.03, '--dur': 0.3 }"
        />
      </g>
      <rect
        class="cad-e4-cell"
        :x="e4Cell.x"
        :y="e4Cell.y"
        :width="e4Cell.w"
        :height="e4Cell.h"
        data-a="fade"
        :style="{ '--at': at('scan-s1') + 0.7, '--dur': 0.16 }"
      />
      <!-- highlight：会议室201 沿轴线虚线重画 + 面积文字下划线 -->
      <g class="cad-highlight">
        <rect class="cad-hl-room" v-bind="meetingRect" mask="url(#demo-cad-hl-mask)" />
        <line
          class="cad-hl-underline"
          x1="464"
          y1="357.2"
          x2="477.8"
          y2="357.2"
          pathLength="1"
          data-a="draw"
          :style="{ '--at': at('highlight') + 0.2, '--dur': 0.25 }"
        />
      </g>
      <!-- scan：读入图片的扫描带 -->
      <rect
        class="cad-scan"
        x="0"
        y="-12"
        width="841"
        height="24"
        fill="url(#demo-cad-scan)"
        data-a="scan"
        :style="{ '--at': at('scan-s1'), '--dur': 0.7, '--span': '594px' }"
      />
      <rect
        class="cad-scan"
        :x="VIEW.E4.x"
        :y="VIEW.E4.y - 2.1"
        :width="VIEW.E4.w"
        height="4.2"
        fill="url(#demo-cad-scan)"
        data-a="scan"
        :style="{ '--at': at('scan-e4'), '--dur': 0.6, '--span': `${VIEW.E4.h}px` }"
      />
    </svg>
    <!-- 12px 标签层 -->
    <div class="cad-labels" aria-hidden="true">
      <span class="cad-tag cad-unit-tag" data-a="fade" :style="{ '--at': at('unit') }">单位 mm · 尺寸比对</span>
      <span class="cad-tag cad-frame-tag" data-a="fade" :style="{ '--at': at('frame'), ...pct(0, 0) }">S1 · A1 1:100</span>
      <template v-if="z < 1">
        <span
          v-for="(r, i) in refs"
          :key="r.id"
          class="cad-tag cad-ref-tag"
          data-a="fade"
          :style="{ '--at': at('frame') + i * 0.07, ...pct(r.x + r.w + 2, r.y + r.h / 2) }"
          >{{ r.id }}</span
        >
        <span class="cad-tag cad-unmatched-tag" data-a="fade" :style="{ '--at': roomAt(9), ...pct(unmatched.rect[0] + 4, (unmatched.rect[1] + unmatched.rect[3]) / 2) }"
          >未匹配</span
        >
      </template>
      <template v-if="z < 1">
        <span
          v-for="(c, i) in colLabels"
          :key="`ct${c.l}`"
          class="cad-grid-label"
          data-a="fade pop"
          :style="{ '--at': at('grid') + i * 0.04, '--s0': 0.6, ...pct(c.x, -9.9) }"
          >{{ c.l }}</span
        >
        <span
          v-for="(c, i) in colLabels"
          :key="`cb${c.l}`"
          class="cad-grid-label"
          data-a="fade pop"
          :style="{ '--at': at('grid') + i * 0.04, '--s0': 0.6, ...pct(c.x, 603.9) }"
          >{{ c.l }}</span
        >
        <span
          v-for="(r, i) in rowLabels"
          :key="`rl${r.l}`"
          class="cad-grid-label"
          data-a="fade pop"
          :style="{ '--at': at('grid') + (8 + i) * 0.04, '--s0': 0.6, ...pct(-9.9, r.y) }"
          >{{ r.l }}</span
        >
        <span
          v-for="(r, i) in rowLabels"
          :key="`rr${r.l}`"
          class="cad-grid-label"
          data-a="fade pop"
          :style="{ '--at': at('grid') + (8 + i) * 0.04, '--s0': 0.6, ...pct(850.9, r.y) }"
          >{{ r.l }}</span
        >
      </template>
      <span
        v-if="z > 0"
        class="cad-tag cad-hl-tag"
        data-a="fade"
        :style="{ '--at': at('highlight') + 0.3, ...pct(meeting.rect[0] + 2, meeting.rect[1] + 3) }"
        >多段线 73.08 m² · 面积文字 69.70 m²</span
      >
    </div>
  </div>
</template>
