<script setup lang="ts">
/**
 * 旧方式网格（03 章 §2.3、§2.4）：九个功能面板（3×3）、100 个点击标记、待确认菱形、“上次结果”、
 * “不再单独做”；覆盖层 `.legacy-overlay`（文件签、扇形线、顺序虚线与 ①–⑨、删除线）只在钉住模式显示，
 * 其几何在 `layout()` 时按面板实际位置直接写入 DOM（ScrollTrigger refreshInit 时同步调用，滚动中不重算）。
 */
import { computed, ref } from 'vue';
import { PENDING_ROWS, PROBLEM_COPY, type ClickMarker, type LegacyId, type LegacyPanel } from '../../data/problem';

const props = defineProps<{ panels: readonly LegacyPanel[]; markers: readonly ClickMarker[] }>();

const root = ref<HTMLElement | null>(null);
const overlay = ref<SVGSVGElement | null>(null);
const byPanel = computed(() => {
  const map = new Map<LegacyId, ClickMarker[]>();
  for (const m of props.markers) {
    const list = map.get(m.panel) ?? [];
    list.push(m);
    map.set(m.panel, list);
  }
  return map;
});
const fanPanels = computed(() => props.panels.filter((p) => p.fan));
const retiredPanels = computed(() => props.panels.filter((p) => p.fate === 'retired'));
const TAG_W = 132;
const TAG_H = 24;

interface PanelBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** 面板相对网格的位置（不受 transform 影响）。 */
function boxes(): Map<LegacyId, PanelBox> {
  const map = new Map<LegacyId, PanelBox>();
  root.value?.querySelectorAll<HTMLElement>('.legacy-panel').forEach((el) => {
    map.set(el.dataset.panel as LegacyId, { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight });
  });
  return map;
}

/**
 * 按当前布局重算覆盖层几何。
 * @returns 各面板中心（顺序同 panels），供顺序线序号定时使用。
 */
function layout(): { x: number; y: number }[] {
  const el = root.value;
  const svg = overlay.value;
  if (!el || !svg) return [];
  const w = el.offsetWidth;
  const h = el.offsetHeight;
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  const map = boxes();
  const center = (id: LegacyId) => {
    const b = map.get(id)!;
    return { x: b.x + b.w / 2, y: b.y + b.h / 2 };
  };
  const centers = props.panels.map((p) => center(p.id));
  // 文件签放在第 1、2 行之间的水平中线上。
  const row2 = map.get(fanPanels.value[0]?.id ?? 'check');
  const tx = w / 2;
  const ty = row2 ? row2.y - 8 - TAG_H / 2 : h / 2;
  svg.querySelector('[data-o="tag"]')?.setAttribute('transform', `translate(${tx - TAG_W / 2} ${ty - TAG_H / 2})`);
  svg.querySelectorAll<SVGPathElement>('[data-o="fan"]').forEach((path, i) => {
    const b = map.get(fanPanels.value[i]!.id)!;
    const px = b.x + b.w / 2;
    const py = b.y + b.h * 0.1;
    const sy = ty + TAG_H / 2;
    const my = (sy + py) / 2;
    path.setAttribute('d', `M${tx} ${sy}C${tx} ${my} ${px} ${my} ${px} ${py}`);
  });
  const seq = centers.map((c, i) => `${i ? 'L' : 'M'}${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join('');
  svg.querySelectorAll('[data-o="seq"], [data-o="seq-line"]').forEach((p) => p.setAttribute('d', seq));
  const mask = svg.querySelector('mask');
  mask?.setAttribute('width', String(w + 100));
  mask?.setAttribute('height', String(h + 100));
  svg.querySelectorAll<SVGGElement>('[data-o="no"]').forEach((g, i) => {
    const c = centers[i]!;
    g.setAttribute('transform', `translate(${c.x} ${c.y})`);
  });
  svg.querySelectorAll<SVGPathElement>('[data-o="strike"]').forEach((path, i) => {
    const b = map.get(retiredPanels.value[i]!.id)!;
    path.setAttribute('d', `M${b.x + 8} ${b.y + 8}L${b.x + b.w - 8} ${b.y + b.h - 8}`);
  });
  return centers;
}

/**
 * 某个标记相对网格的基准位置（像素，不受 transform 影响）。
 * @param dot - `.click-dot` 元素。
 * @returns 坐标。
 */
function dotBase(dot: HTMLElement): { x: number; y: number } {
  const panel = dot.closest<HTMLElement>('.legacy-panel');
  if (!panel) return { x: 0, y: 0 };
  return {
    x: panel.offsetLeft + (parseFloat(dot.style.left) / 100) * panel.offsetWidth,
    y: panel.offsetTop + (parseFloat(dot.style.top) / 100) * panel.offsetHeight,
  };
}

defineExpose({ root, overlay, layout, dotBase });
</script>

<template>
  <div ref="root" class="legacy-grid">
    <div
      v-for="(p, pi) in panels"
      :key="p.id"
      class="legacy-panel"
      :data-panel="p.id"
      :data-fate="p.fate"
      :data-index="pi"
    >
      <div class="lp-bar">{{ p.label }}</div>
      <span class="lp-btn lp-pick"><span>{{ PROBLEM_COPY.buttons.pick }}</span></span>
      <span class="lp-btn lp-start"><span>{{ PROBLEM_COPY.buttons.start }}</span></span>
      <span class="lp-row" style="top: 50%"></span>
      <span class="lp-row" style="top: 62%"></span>
      <span class="lp-row" style="top: 74%"></span>
      <span class="lp-btn lp-export"><span>{{ PROBLEM_COPY.buttons.export }}</span></span>
      <span v-if="p.lastResult" class="lp-last">{{ PROBLEM_COPY.lastResult }}</span>
      <span v-if="p.fate === 'retired'" class="lp-retired">{{ PROBLEM_COPY.retired }}</span>
      <i
        v-for="n in p.pending"
        :key="`p${n}`"
        class="pending-mark"
        :style="{ left: '86%', top: `${PENDING_ROWS[n - 1]}%` }"
      ></i>
      <i
        v-for="m in byPanel.get(p.id) ?? []"
        :key="m.k"
        class="click-dot"
        :data-k="m.k"
        :style="{ left: `${m.x}%`, top: `${m.y}%` }"
        ><b class="click-ripple"></b
      ></i>
    </div>
    <svg ref="overlay" class="legacy-overlay" viewBox="0 0 600 400" preserveAspectRatio="none">
      <path v-for="p in fanPanels" :key="`f${p.id}`" class="lo-fan" data-o="fan" :data-to="p.id" d="M0 0" />
      <defs>
        <mask id="legacy-seq-mask" maskUnits="userSpaceOnUse" x="-50" y="-50" width="700" height="500">
          <path class="lo-seq-mask" data-o="seq" d="M0 0" />
        </mask>
      </defs>
      <!-- 虚线本身不做 DrawSVG（会改写 dasharray），由遮罩里的实线路径画出 -->
      <path class="lo-seq" data-o="seq-line" mask="url(#legacy-seq-mask)" d="M0 0" />
      <g v-for="(p, i) in panels" :key="`n${p.id}`" data-o="no" :data-panel="p.id" transform="translate(0 0)">
        <circle class="lo-no" r="10" />
        <text class="lo-no-t" y="4" text-anchor="middle">{{ i + 1 }}</text>
      </g>
      <path v-for="p in retiredPanels" :key="`s${p.id}`" class="lo-strike" data-o="strike" :data-panel="p.id" d="M0 0" />
      <g data-o="tag" transform="translate(0 0)">
        <rect class="lo-tag" :width="TAG_W" :height="TAG_H" rx="4" />
        <text class="lo-tag-t" :x="TAG_W / 2" y="16" text-anchor="middle">{{ PROBLEM_COPY.fileTag }}</text>
      </g>
    </svg>
  </div>
</template>
