<script setup lang="ts">
/**
 * 数据流图（05 章 §2.3–§2.7）：预渲染输出完整 SVG（节点、连线、标签、锁、处于 `rest` 的数据包）与节点覆盖按钮。
 * 覆盖按钮用原生 `popovertarget` 指向 TrustSection 里的 `ZtPopover`，水合前也能打开说明卡。
 * `focus` 非空时，不在 `FOCUS[focus]` 里的图元加 `.is-dim`（透明度在外层 `<g>`，GSAP 只动内层，互不覆盖）。
 */
import { computed, ref } from 'vue';
import {
  isLit,
  type FocusKey,
  type PacketKind,
  type TrustGeometry,
  type TrustNodeId,
  type TrustPathId,
} from './trust-geometry';
import { TRUST_COPY, TRUST_NODES } from '../../../data/trust';
import TrustPacket from './TrustPacket.vue';

const props = defineProps<{ geometry: TrustGeometry; focus: FocusKey | null }>();

const root = ref<HTMLElement | null>(null);
const svg = ref<SVGSVGElement | null>(null);
const g = computed(() => props.geometry);
const [, , vw, vh] = props.geometry.viewBox;
const id = (s: string) => `trust-${props.geometry.id}-${s}`;

const NODE_ORDER: TrustNodeId[] = ['tos', 'cache', 'script', 'cred', 'model', 'review'];
const LANES = new Set<TrustNodeId>(['cache', 'script', 'cred']);
const PATHS = computed(() =>
  (Object.entries(g.value.paths) as [TrustPathId, TrustGeometry['paths'][TrustPathId]][]).filter(
    (e): e is [TrustPathId, NonNullable<TrustGeometry['paths'][TrustPathId]>] => e[1] !== null,
  ),
);
const PACKETS: PacketKind[] = ['file', 'amount', 'amountEcho', 'credential', 'reply', 'result'];
const nodeTitle = (n: TrustNodeId) => TRUST_NODES.find((c) => c.node === n)!.title;
const lit = (owner: Parameters<typeof isLit>[1]) => isLit(props.focus, owner);
const pct = (v: number, total: number) => `${((v / total) * 100).toFixed(4)}%`;

defineExpose({ root, svg });
</script>

<template>
  <div ref="root" class="trust-geo" :class="`is-${geometry.id}`" :data-geometry="geometry.id">
    <svg
      ref="svg"
      class="trust-svg"
      :viewBox="geometry.viewBox.join(' ')"
      role="img"
      :aria-labelledby="`${id('title')} ${id('desc')}`"
      :style="{ '--fs-title': `${geometry.font.title}px`, '--fs-body': `${geometry.font.body}px` }"
    >
      <title :id="id('title')">{{ TRUST_COPY.figTitle }}</title>
      <desc :id="id('desc')">{{ TRUST_COPY.figDesc }}</desc>

      <g class="trust-frame" :class="{ 'is-dim': !lit({ frame: true }) }" data-enter="frame">
        <rect
          :x="geometry.frame.x"
          :y="geometry.frame.y"
          :width="geometry.frame.w"
          :height="geometry.frame.h"
          :rx="geometry.frame.rx"
        />
      </g>

      <g
        v-for="n in NODE_ORDER"
        :key="n"
        class="trust-node"
        :class="[{ 'is-dim': !lit({ node: n }), 'is-lane': LANES.has(n) }, `node-${n}`]"
        :data-node="n"
        :data-enter="LANES.has(n) ? 'lane' : n"
      >
        <rect
          class="trust-node-box"
          :x="geometry.nodes[n].x"
          :y="geometry.nodes[n].y"
          :width="geometry.nodes[n].w"
          :height="geometry.nodes[n].h"
          :rx="geometry.nodes[n].rx"
        />
      </g>

      <g
        v-for="[pid, p] in PATHS"
        :key="pid"
        class="trust-path"
        :class="[`line-${p.line}`, { 'is-dim': !lit({ path: pid }) }]"
        :data-path="pid"
      >
        <path :id="id(`path-${pid}`)" :d="p.d" />
      </g>

      <g
        v-for="(label, k) in geometry.labels"
        :key="k"
        class="trust-label"
        :class="{ 'is-dim': !lit(label.owner), 'is-title': label.title, 'is-mono': label.mono }"
        :data-lock-label="'key' in label.owner ? '' : undefined"
      >
        <text :x="label.at[0]" :y="label.at[1]" :text-anchor="label.anchor">{{ label.text }}</text>
      </g>

      <g v-if="geometry.keys" class="trust-keys" :class="{ 'is-dim': !lit({ key: 'lock' }) }">
        <g v-for="(k, i) in geometry.keys" :key="i" :transform="`translate(${k[0]} ${k[1]})`">
          <circle cx="3" cy="6" r="2.6" />
          <path d="M5.6 6 H12 M10 6 V8.5" />
        </g>
      </g>

      <g class="trust-lock" :class="{ 'is-dim': !lit({ key: 'lock' }) }">
        <g :transform="`translate(${geometry.lock[0]} ${geometry.lock[1]})`">
          <g class="trust-lock-inner">
            <path class="trust-lock-shackle" d="M-5 -2 V-5 A5 5 0 0 1 5 -5 V-2" />
            <rect class="trust-lock-body" x="-8" y="-2" width="16" height="12" rx="2" />
          </g>
        </g>
      </g>

      <g
        class="trust-tos-check"
        :transform="`translate(${geometry.nodes.tos.x + geometry.nodes.tos.w - 4} ${geometry.nodes.tos.y + 4})`"
        aria-hidden="true"
      >
        <circle r="7" />
        <path d="M-3 0 L-1 2 L3 -2.5" />
      </g>

      <g
        v-for="kind in PACKETS"
        :key="kind"
        class="trust-packet-wrap"
        :class="{ 'is-dim': !lit({ packet: kind }) }"
      >
        <g
          class="trust-packet"
          :data-packet="kind"
          :transform="`translate(${geometry.rest[kind][0]} ${geometry.rest[kind][1]})`"
        >
          <TrustPacket :kind="kind" />
        </g>
      </g>
    </svg>

    <button
      v-for="n in NODE_ORDER"
      :key="n"
      type="button"
      class="trust-hit"
      :class="`hit-${n}`"
      :popovertarget="`trust-pop-${n}`"
      :aria-label="`${nodeTitle(n)}：查看说明`"
      :data-node="n"
      :style="{
        left: pct(geometry.nodes[n].x, vw),
        top: pct(geometry.nodes[n].y, vh),
        width: pct(geometry.nodes[n].w, vw),
        height: pct(geometry.nodes[n].h, vh),
        borderRadius: `${geometry.nodes[n].rx}px`,
      }"
    ></button>
  </div>
</template>
