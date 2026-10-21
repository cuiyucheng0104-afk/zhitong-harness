<script setup lang="ts">
/**
 * 平面图的静态图层（02 章 §5.4）：FRAME → AXIS → COLUMN → WALL → WINDOW/DOOR → STAIR/EVTR → DIM → 文字。
 * 出图动画由样式表按场景面板的 `--t` 与每个图元的 `--at`/`--dur` 计算（与 cue `plot` 对齐），本组件只在
 * 文字画法切换（框 ↔ 文字）或屏幕最小字高变化时重新渲染。
 * 文字两种画法与 `cad_render` 一致：总览只画文字框（rect，左下角在插入点），放大后画文字本身（font-size = max(字高, 12 ÷ 每单位像素数)）。
 */
import { LAYER_STYLE, PLOT_PHASES, PRIMS, TEXT_ITEMS, textWidth, type Layer } from './cadGeometry';
import { PLAN_TITLE_LINES } from '../../data/demo-drawing';

const props = defineProps<{
  /** cue `plot` 的时刻。 */
  plotAt: number;
  /** cue `unit` 的时刻（DIM 图层描边闪蓝）。 */
  unitAt: number;
  showRects: boolean;
  showTexts: boolean;
  /** 放大视图下保证屏幕 ≥ 12px 的最小字高（用户单位）。 */
  minText: number;
}>();

const LAYERS: Layer[] = ['FRAME', 'AXIS', 'COLUMN', 'WALL', 'WINDOW', 'DOOR', 'STAIR', 'EVTR', 'DIM'];
const byLayer = LAYERS.map((layer) => ({ layer, prims: PRIMS.filter((p) => p.layer === layer) }));
const textAt = PLOT_PHASES.TEXT[0];
const textDur = PLOT_PHASES.TEXT[1];
const rectOf = (it: (typeof TEXT_ITEMS)[number]) => {
  const w = textWidth(it.text, it.h);
  return it.rotate
    ? { x: it.x - it.h, y: it.y - w, width: it.h, height: w }
    : { x: it.x, y: it.y - it.h, width: w, height: it.h };
};
const fontOf = (h: number) => Math.max(h, props.minText);
</script>

<template>
  <g class="cad-layers">
    <g
      v-for="group in byLayer"
      :key="group.layer"
      :class="`cad-layer cad-${group.layer.toLowerCase()}`"
      :stroke="LAYER_STYLE[group.layer].color"
      :stroke-width="LAYER_STYLE[group.layer].width"
      :style="group.layer === 'DIM' ? { '--ua': unitAt } : undefined"
      fill="none"
    >
      <component
        :is="p.tag"
        v-for="p in group.prims"
        :key="p.key"
        v-bind="p.attrs"
        :stroke-width="p.width"
        :stroke-dasharray="p.dash"
        :fill="p.fill"
        :stroke="p.fill ? 'none' : undefined"
        :pathLength="p.anim === 'draw' ? 1 : undefined"
        :data-a="p.anim"
        :style="p.anim === 'pop' ? { '--at': plotAt + p.at, '--dur': p.dur, '--s0': 0 } : { '--at': plotAt + p.at, '--dur': p.dur }"
      />
    </g>
    <g class="cad-layer cad-pub" stroke="#162943" data-a="fade" :style="{ '--at': plotAt + textAt, '--dur': textDur }">
      <line
        v-for="(l, i) in PLAN_TITLE_LINES"
        :key="i"
        :x1="l[0]"
        :y1="l[1]"
        :x2="l[2]"
        :y2="l[3]"
        :stroke-width="l[4]"
      />
    </g>
    <g v-if="showRects" class="cad-text-frames" data-a="fade" :style="{ '--at': plotAt + textAt, '--dur': textDur }">
      <rect v-for="it in TEXT_ITEMS" :key="it.id" v-bind="rectOf(it)" :data-text="it.id" :data-layer="it.layer" />
    </g>
    <g v-if="showTexts" class="cad-texts">
      <text
        v-for="it in TEXT_ITEMS"
        :key="it.id"
        :x="it.x"
        :y="it.y"
        :font-size="fontOf(it.h)"
        :fill="LAYER_STYLE[it.layer].color"
        :transform="it.rotate ? `rotate(-90 ${it.x} ${it.y})` : undefined"
        :data-text="it.id"
        :data-layer="it.layer"
      >
        {{ it.text }}
      </text>
    </g>
  </g>
</template>
