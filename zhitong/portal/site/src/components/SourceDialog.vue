<script setup lang="ts">
/**
 * 出处弹层（02 章 §6）：点核减额，看它由哪两份文件、哪些表、哪些行、按什么公式得出，并能跳到逐行核对。
 * - 桌面与平板（≥ 768）：原生 `<dialog>` 全视口透明，内含连线 `svg.source-connector`、金额副本 `.source-amount-echo` 与面板；
 *   面板首选放在金额左侧（右缘 = 金额左缘 − 56），放不下改放金额下方；连线为三次贝塞尔，两端 4px 圆点。
 *   打开时序（§6.4）：遮罩 0.2 s → 0.05 副本光晕 → 0.10 起点圆点、连线描出 0.45 s → 0.35 面板 → 0.55 终点圆点
 *   → 0.50 起各区块错开 → 0.70 大数字滚动 0.8 s → 0.80 量差/价差条。用 Web Animations API，不依赖 GSAP。
 * - 手机（≤ 767）：底部弹层（BaseDialog sheet，下拉 80px 关闭），无连线与副本，“核减最大的 3 行”改为三张小卡。
 * 打开后焦点在 h2；Esc 关闭，焦点回到触发金额。
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import BaseDialog from './BaseDialog.vue';
import AppIcon from './AppIcon.vue';
import { RECONCILE } from '../data/demo';
import { formatInt, formatMoney, formatPercent } from '../lib/format';
import { CSS_EASE, MS } from '../lib/motion-tokens';
import { prefersReducedMotion } from '../lib/motion';
import { useMediaQuery } from '../composables/useMediaQuery';

const props = defineProps<{
  modelValue: boolean;
  /** 触发金额（定位起点与焦点归还）。 */
  trigger?: HTMLElement | null;
}>();
const emit = defineEmits<{
  'update:modelValue': [value: boolean];
  opened: [dialog: HTMLDialogElement];
  closed: [];
  /** “看逐行核对”。 */
  rows: [];
}>();

const S = RECONCILE.summary;
const mobile = useMediaQuery('(max-width: 767px)');
const dialogRef = ref<InstanceType<typeof BaseDialog> | null>(null);
const panel = ref<HTMLElement | null>(null);
const bigRow = ref<HTMLElement | null>(null);
const title = ref<HTMLElement | null>(null);
const connector = ref<SVGSVGElement | null>(null);
const echo = ref<HTMLElement | null>(null);

const SHEET_SHORT: Record<string, string> = {
  分部分项工程清单与计价表: '分部分项',
  施工技术措施项目清单与计价表: '技术措施',
};
const topRows = RECONCILE.rows.slice(0, 3).map((r) => ({
  name: r.item_name,
  code: r.item_code,
  a: { short: SHEET_SHORT[r.submitted_sheet] ?? r.submitted_sheet, full: r.submitted_sheet, row: r.submitted_row },
  b: r.approved_sheet ? { short: SHEET_SHORT[r.approved_sheet] ?? r.approved_sheet, full: r.approved_sheet, row: r.approved_row } : null,
  diff: formatMoney(r.diff),
}));
const qtyShare = S.diff_by_qty / (S.diff_by_qty + S.diff_by_price);

/* 位置与连线（视口坐标）。 */
type Layout = 'left' | 'below';
const geo = ref({
  layout: 'left' as Layout,
  panel: { left: 16, top: 16 },
  echo: { left: 0, top: 0, width: 0, height: 0 },
  path: '',
  start: { x: 0, y: 0 },
  end: { x: 0, y: 0 },
  vw: 1280,
  vh: 800,
});

function place() {
  const a = props.trigger?.getBoundingClientRect();
  const p = panel.value;
  if (!a || !p || mobile.value) return;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const w = 420;
  const h = p.offsetHeight;
  const rowCenter = bigRow.value ? bigRow.value.offsetTop + bigRow.value.offsetHeight / 2 : 60;
  const right = a.left - 56;
  const cy = a.top + a.height / 2;
  let layout: Layout = 'left';
  let left = right - w;
  let top = cy - rowCenter;
  if (left < 16) {
    layout = 'below';
    left = Math.min(Math.max(16, a.left - 120), Math.max(16, vw - w - 16));
    top = a.bottom + 40;
  }
  top = Math.min(Math.max(16, top), Math.max(16, vh - h - 16));
  let start: { x: number; y: number };
  let end: { x: number; y: number };
  let path: string;
  if (layout === 'left') {
    start = { x: a.left, y: cy };
    end = { x: left + w, y: top + rowCenter };
    const mx = (start.x + end.x) / 2;
    path = `M${start.x} ${start.y}C${mx} ${start.y} ${mx} ${end.y} ${end.x} ${end.y}`;
  } else {
    start = { x: a.left + a.width / 2, y: a.bottom };
    end = { x: Math.min(Math.max(start.x, left + 24), left + w - 24), y: top };
    const my = (start.y + end.y) / 2;
    path = `M${start.x} ${start.y}C${start.x} ${my} ${end.x} ${my} ${end.x} ${end.y}`;
  }
  geo.value = { layout, panel: { left, top }, echo: { left: a.left, top: a.top, width: a.width, height: a.height }, path, start, end, vw, vh };
}

let frame = 0;
const onResize = () => {
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(place);
};

/* 大数字滚动：真实值节点保持终值，滚动值写在 aria-hidden 副本里。 */
const counting = ref(false);
const countText = ref('');
let countFrame = 0;
function countUp(delay: number) {
  cancelAnimationFrame(countFrame);
  if (prefersReducedMotion() || typeof requestAnimationFrame !== 'function') return;
  const start = performance.now() + delay;
  const run = (now: number) => {
    const p = Math.min(1, Math.max(0, (now - start) / MS.long));
    counting.value = p < 1;
    countText.value = formatMoney(S.adjust_amount * (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p)));
    if (p < 1) countFrame = requestAnimationFrame(run);
  };
  counting.value = true;
  countText.value = formatMoney(0);
  countFrame = requestAnimationFrame(run);
}

function anim(el: Element | null | undefined, frames: Keyframe[], opts: KeyframeAnimationOptions) {
  if (!el || typeof (el as HTMLElement).animate !== 'function') return null;
  try {
    return (el as HTMLElement).animate(frames, { fill: 'both', ...opts });
  } catch {
    // 不支持的伪元素等：按无动画处理。
    return null;
  }
}

async function enter(dialog: HTMLDialogElement) {
  await nextTick();
  place();
  const g = geo.value;
  const ease = CSS_EASE.out;
  anim(dialog, [{ opacity: 0 }, { opacity: 1 }], { duration: 200, pseudoElement: '::backdrop' });
  anim(
    echo.value,
    [
      { boxShadow: '0 0 0 0 rgba(6,102,245,.18)', outlineColor: 'rgba(6,102,245,0)' },
      { boxShadow: '0 0 0 6px rgba(6,102,245,.18)', outlineColor: 'rgba(6,102,245,1)' },
    ],
    { duration: MS.short, delay: 50, easing: ease },
  );
  const svg = connector.value;
  anim(svg?.querySelector('.source-dot-start'), [{ transform: 'scale(0)' }, { transform: 'scale(1)' }], { duration: MS.micro, delay: 100, easing: ease });
  anim(svg?.querySelector('path'), [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { duration: 450, delay: 100, easing: ease });
  anim(svg?.querySelector('.source-dot-end'), [{ transform: 'scale(0)' }, { transform: 'scale(1)' }], { duration: MS.micro, delay: 550, easing: ease });
  anim(
    panel.value,
    [
      { opacity: 0, transform: g.layout === 'left' ? 'translateX(16px)' : 'translateY(12px)' },
      { opacity: 1, transform: 'none' },
    ],
    { duration: MS.short, delay: 350, easing: ease },
  );
  panel.value?.querySelectorAll('[data-source-block]').forEach((el, i) =>
    anim(el, [{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }], {
      duration: MS.short,
      delay: 500 + i * 40,
      easing: ease,
    }),
  );
  panel.value?.querySelectorAll('.qp-bar > i').forEach((el, i) =>
    anim(el, [{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }], { duration: MS.base, delay: 800 + i * 120, easing: ease }),
  );
  countUp(700);
}

function leave(dialog: HTMLDialogElement) {
  cancelAnimationFrame(countFrame);
  counting.value = false;
  const list = [
    anim(panel.value, [{ opacity: 1 }, { opacity: 0 }], { duration: MS.micro, easing: CSS_EASE.out }),
    anim(connector.value?.querySelector('path'), [{ strokeDashoffset: 0 }, { strokeDashoffset: 1 }], { duration: 200, easing: CSS_EASE.out }),
    anim(dialog, [{ opacity: 1 }, { opacity: 0 }], { duration: 200, pseudoElement: '::backdrop' }),
  ];
  return Promise.all(list.map((a) => a?.finished.catch(() => undefined)));
}

function onOpened(dialog: HTMLDialogElement) {
  window.addEventListener('resize', onResize);
  void nextTick(() => {
    place();
    title.value?.focus({ preventScroll: true });
    if (mobile.value) countUp(300);
  });
  emit('opened', dialog);
}
function onClosed() {
  window.removeEventListener('resize', onResize);
  cancelAnimationFrame(countFrame);
  counting.value = false;
  emit('closed');
  if (rowsPending) {
    rowsPending = false;
    emit('rows');
  }
}
watch(mobile, () => props.modelValue && place());
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize);
  cancelAnimationFrame(frame);
  cancelAnimationFrame(countFrame);
});

/** 点透明区域（不在面板内）关闭。 */
function onDialogClick(e: MouseEvent) {
  if (mobile.value) return;
  if (e.target === dialogRef.value?.element) dialogRef.value?.close();
}

let rowsPending = false;
function viewRows() {
  rowsPending = true;
  dialogRef.value?.close({ returnFocus: false });
}

const variant = computed(() => (mobile.value ? 'sheet' : 'custom'));
</script>

<template>
  <BaseDialog
    id="source-dialog"
    ref="dialogRef"
    class="source-dialog"
    :class="`is-${geo.layout}`"
    :model-value="modelValue"
    :trigger="trigger ?? null"
    :variant="variant"
    :enter="enter"
    :leave="leave"
    labelledby="source-title"
    @update:model-value="emit('update:modelValue', $event)"
    @opened="onOpened"
    @closed="onClosed"
    @click="onDialogClick"
  >
    <template #default="{ close, sheet }">
      <svg
        v-if="!sheet"
        ref="connector"
        class="source-connector"
        :viewBox="`0 0 ${geo.vw} ${geo.vh}`"
        aria-hidden="true"
      >
        <path :d="geo.path" pathLength="1" />
        <circle class="source-dot-start" :cx="geo.start.x" :cy="geo.start.y" r="4" />
        <circle class="source-dot-end" :cx="geo.end.x" :cy="geo.end.y" r="4" />
      </svg>
      <div
        v-if="!sheet"
        ref="echo"
        class="source-amount-echo mono"
        aria-hidden="true"
        :style="{ left: `${geo.echo.left}px`, top: `${geo.echo.top}px`, width: `${geo.echo.width}px`, height: `${geo.echo.height}px` }"
      >
        {{ formatMoney(S.adjust_amount) }}
      </div>
      <section
        ref="panel"
        class="source-panel"
        data-lenis-prevent
        :style="sheet ? undefined : { left: `${geo.panel.left}px`, top: `${geo.panel.top}px` }"
      >
        <div class="source-head" data-source-block>
          <span class="eyebrow">出处 · 示例数据</span>
          <button type="button" class="icon-button" aria-label="关闭出处" @click="close()"><AppIcon name="close" /></button>
        </div>
        <h2 id="source-title" ref="title" tabindex="-1" data-source-block>核减额从哪里来</h2>
        <p ref="bigRow" class="source-big" data-source-block>
          <span class="source-big-amount mono" :class="{ 'is-counting': counting }"
            >{{ formatMoney(S.adjust_amount) }}<span v-if="counting" class="count-up-shadow" aria-hidden="true">{{ countText }}</span></span
          >
          <span class="source-big-unit">{{ ' 元 ' }}</span><span class="source-sep" aria-hidden="true">｜</span>
          {{ ' ' }}<span class="source-big-rate">核减率 <b class="mono">{{ formatPercent(S.adjust_rate) }}</b></span>
        </p>

        <div class="source-block" data-source-block>
          <h3>计算</h3>
          <p>核减额 = 送审合计 − 审定合计</p>
          <p class="mono">{{ formatMoney(S.a_total) }} − {{ formatMoney(S.b_total) }} = {{ formatMoney(S.adjust_amount) }}</p>
          <p class="mono">
            核减率 = {{ formatMoney(S.adjust_amount) }} ÷ {{ formatMoney(S.a_total) }} ≈ {{ formatPercent(S.adjust_rate) }}（脚本字段
            adjust_rate = {{ S.adjust_rate }}）
          </p>
        </div>

        <div class="source-block" data-source-block>
          <h3>两份计价表</h3>
          <div class="source-file">
            <AppIcon name="sheet" />
            <div>
              <p>
                <strong>送审计价表.xlsx</strong> · <span class="mono">资料/4 结算资料/</span> · 送审合计
                <b class="mono">{{ formatMoney(S.a_total) }}</b>
              </p>
              <p class="source-file-detail">
                计入 2 张表：{{ RECONCILE.usedSheets.join('、') }} · 清单行 {{ formatInt(S.count_a_items) }} · 按标题跳过 7 张
              </p>
            </div>
          </div>
          <div class="source-file">
            <AppIcon name="sheet" />
            <div>
              <p>
                <strong>审定计价表.xlsx</strong> · <span class="mono">资料/4 结算资料/</span> · 审定合计
                <b class="mono">{{ formatMoney(S.b_total) }}</b>
              </p>
              <p class="source-file-detail">
                计入 2 张表：{{ RECONCILE.usedSheets.join('、') }} · 清单行 {{ formatInt(S.count_b_items) }} · 按标题跳过 7 张
              </p>
            </div>
          </div>
        </div>

        <div class="source-block" data-source-block>
          <h3>逐行对上 {{ formatInt(S.count_total) }} 行</h3>
          <p>
            一致 {{ formatInt(S.count_same) }} · 调整 {{ S.count_changed }} · 仅送审 {{ S.count_only_a }} · 仅审定 {{ S.count_only_b }} · 待核实
            {{ S.count_uncertain }}
          </p>
        </div>

        <div class="source-block" data-source-block>
          <h3>量差与价差</h3>
          <p>
            量差 <b class="mono">{{ formatMoney(S.diff_by_qty) }}</b>{{ ' ' }}<span class="source-sep" aria-hidden="true">｜</span>{{ ' ' }}价差
            <b class="mono">{{ formatMoney(S.diff_by_price) }}</b>
          </p>
          <div class="qp-bar" aria-hidden="true">
            <i class="qp-qty" :style="{ width: `${qtyShare * 100}%` }"></i><i class="qp-price" :style="{ width: `${(1 - qtyShare) * 100}%` }"></i>
          </div>
          <p class="source-note">
            量差 =（送审量 − 审定量）× 审定单价；价差 =（送审单价 − 审定单价）× 送审量。只统计两侧量、价都取到的匹配行。
          </p>
        </div>

        <div class="source-block" data-source-block>
          <h3>核减最大的 3 行</h3>
          <table v-if="!sheet" class="demo-table source-top">
            <caption class="sr-only">核减最大的 3 行，金额单位元</caption>
            <thead>
              <tr><th>项目</th><th>送审位置</th><th>审定位置</th><th class="num">核减额</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in topRows" :key="r.code">
                <td>{{ r.name }} <span class="mono">{{ r.code }}</span></td>
                <td :title="r.a.full">{{ r.a.short }} · 第 {{ r.a.row }} 行</td>
                <td :title="r.b?.full">{{ r.b ? `${r.b.short} · 第 ${r.b.row} 行` : '—（仅送审）' }}</td>
                <td class="num mono">{{ r.diff }}</td>
              </tr>
            </tbody>
          </table>
          <ul v-else class="source-top-cards">
            <li v-for="r in topRows" :key="r.code">
              <p><strong>{{ r.name }}</strong> <span class="mono">{{ r.code }}</span></p>
              <p :title="r.a.full">送审位置：{{ r.a.short }} · 第 {{ r.a.row }} 行</p>
              <p :title="r.b?.full">审定位置：{{ r.b ? `${r.b.short} · 第 ${r.b.row} 行` : '—（仅送审）' }}</p>
              <p>核减额 <b class="mono">{{ r.diff }}</b></p>
            </li>
          </ul>
          <p class="source-note">位置取自 rows[].submitted_sheet / submitted_row 与 approved_sheet / approved_row。</p>
        </div>

        <p class="source-foot" data-source-block>金额由 zt.reconcile 脚本从两张表取数计算，模型不做加减。</p>
        <div class="source-actions" data-source-block>
          <span class="manual-badge">需人工确认</span>
          <span class="source-buttons">
            <button type="button" class="button button-primary" @click="viewRows">看逐行核对</button>
            <button type="button" class="button button-outline" @click="close()">关闭</button>
          </span>
        </div>
      </section>
    </template>
  </BaseDialog>
</template>
