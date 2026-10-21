<script setup lang="ts">
/** 7.4 CAD 看图：总览组 ov 与放大组 zm 叠放，底部工具条同位（数据与 02 章 §5.2–§5.4 相同）。 */
import { A } from './anim';
import ArtChip from './parts/ArtChip.vue';
import ArtTool from './parts/ArtTool.vue';
import ArtLink from './parts/ArtLink.vue';

const gridX = [63, 90, 117, 144, 171, 198, 225];
const gridY = [31.5, 57, 82.5, 108, 133.5];
const cols = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'];
const rowsN = [1, 2, 3, 4, 5, 6];
const stairs = [191.3, 195.15, 199, 202.85, 206.7, 210.55];
const rooms = [
  { name: '会议室201', t: '69.70', g: '73.08', d: '4.85', warn: true },
  { name: '卫生间', t: '34.00', g: '34.06', d: '0.18', warn: false },
  { name: '培训室', t: '69.70', g: '69.70', d: '0.00', warn: false },
  { name: '资料室', t: '69.70', g: '69.70', d: '0.00', warn: false },
];
</script>

<template>
  <svg class="art-in" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <g v-bind="A('ov', true)">
      <rect
        v-bind="A('r201')"
        x="145.9"
        y="85.1"
        width="21.6"
        height="22.4"
        fill="var(--warning-bg)"
      />
      <rect
        v-bind="A('e4')"
        x="144"
        y="82.5"
        width="27"
        height="25.5"
        class="art-e4"
        opacity="0.8"
      />
      <rect
        v-bind="A('frame')"
        x="36"
        y="6"
        width="216"
        height="153"
        fill="none"
        stroke="var(--ink)"
        stroke-width="1.2"
      />
      <g v-bind="A('plan')" fill="none" stroke="var(--ink)" stroke-width="1">
        <rect x="102.8" y="54.9" width="86.3" height="52.6" />
        <path d="M102.8 77.3 H189.1 M102.8 85.1 H189.1" />
        <path d="M145.9 85.1 V107.5 M167.5 85.1 V107.5" />
        <path d="M124.4 54.9 V77.3 M145.9 54.9 V77.3 M167.5 54.9 V77.3" />
      </g>
      <g v-bind="A('title')">
        <rect
          x="112"
          y="139"
          width="140"
          height="20"
          fill="var(--surface)"
          stroke="var(--ink)"
          stroke-width="1"
        />
        <text class="at" x="118" y="154">二层平面图 · 1:100</text>
      </g>
      <g class="art-grid">
        <line
          v-for="x in gridX"
          :key="`gx${x}`"
          v-bind="A('grid')"
          :x1="x"
          y1="6"
          :x2="x"
          y2="159"
          opacity="0.35"
        />
        <line
          v-for="y in gridY"
          :key="`gy${y}`"
          v-bind="A('grid')"
          x1="36"
          :y1="y"
          x2="252"
          :y2="y"
          opacity="0.35"
        />
      </g>
      <text
        v-for="(c, k) in cols"
        :key="c"
        v-bind="A('grid-l')"
        class="as"
        text-anchor="middle"
        :x="49.5 + 27 * k"
        y="22"
      >
        {{ c }}
      </text>
      <text
        v-for="(n, k) in rowsN"
        :key="`n${n}`"
        v-bind="A('grid-l')"
        class="as"
        text-anchor="middle"
        x="26"
        :y="6 + 25.5 * k + 17"
      >
        {{ n }}
      </text>
    </g>
    <g v-bind="A('zm')">
      <rect
        v-bind="A('zm-wall')"
        x="67.8"
        y="25.7"
        width="119.7"
        height="124"
        fill="none"
        stroke="var(--ink)"
        stroke-width="2.85"
      />
      <line
        v-for="x in stairs"
        :key="`s${x}`"
        v-bind="A('zm-stair')"
        :x1="x"
        y1="25.7"
        :x2="x"
        y2="149.7"
        stroke="var(--text-muted)"
        stroke-width="0.6"
      />
      <text v-bind="A('zm-hall')" class="as" text-anchor="middle" x="127.6" y="18">走道</text>
      <text v-bind="A('zm-room')" class="at" text-anchor="middle" x="127.6" y="80">会议室201</text>
      <text v-bind="A('zm-area')" class="am" text-anchor="middle" x="127.6" y="100">69.70㎡</text>
      <rect
        v-bind="A('axisline')"
        data-dashed
        x="67.8"
        y="25.7"
        width="119.7"
        height="124"
        fill="none"
        class="art-axisline"
      />
      <rect
        v-bind="A('innerline')"
        x="69.2"
        y="27.1"
        width="116.9"
        height="121.2"
        fill="none"
        stroke="var(--success-text)"
        stroke-width="1"
      />
      <text v-bind="A('zlabel')" class="as" x="40" y="164">多段线 73.08 · 面积文字 69.70</text>
    </g>
    <ArtTool a="tl-a" transient :top="168" label="打开图纸" name="cad_open" />
    <ArtTool a="tl-b" transient :top="168" label="房间面积" name="cad_rooms" />
    <ArtTool a="tl-c" transient :top="168" label="看总览" name="cad_render" />
    <ArtTool a="tl-d" :top="168" label="放大 E4" name="cad_render" />
  </svg>
  <ArtLink />
  <svg class="art-out" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <rect v-bind="A('o-r1bg')" x="-2" y="69" width="268" height="22" fill="var(--warning-bg)" />
    <text v-bind="A('o-hdr')" class="ah" x="0" y="16">cad_rooms · S1 · 二层平面图</text>
    <text v-bind="A('o-unit')" class="as" x="0" y="36">单位 mm · 尺寸标注 9 处比对一致</text>
    <g v-bind="A('o-th')" class="as">
      <text x="0" y="60">房间</text>
      <text x="140" y="60" text-anchor="end">文字面积</text>
      <text x="204" y="60" text-anchor="end">几何面积</text>
      <text x="264" y="60" text-anchor="end">差异%</text>
    </g>
    <g
      v-for="(r, k) in rooms"
      :key="r.name"
      v-bind="A(`o-r${k + 1}`)"
      :class="{ 'art-warn-text': r.warn }"
    >
      <text class="at" x="0" :y="84 + 22 * k">{{ r.name }}</text>
      <text class="am" x="140" :y="84 + 22 * k" text-anchor="end">{{ r.t }}</text>
      <text class="am" x="204" :y="84 + 22 * k" text-anchor="end">{{ r.g }}</text>
      <text class="am" x="264" :y="84 + 22 * k" text-anchor="end">{{ r.d }}</text>
    </g>
    <text v-bind="A('o-more')" class="as" x="0" y="172">锚点 10，匹配 9 · 走道未匹配</text>
    <ArtChip a="o-warn" :top="180" text="会议室201 差 4.85%，边界画在墙中线" variant="warn" />
  </svg>
</template>
