<script setup lang="ts">
/**
 * 岗位图（03 章 §1.4）：一张 `viewBox="0 0 400 260"` 的内联 SVG，公共图框 + 三组岗位图
 * `<g data-art="engineer|reviewer|manager">`。需要绘制动画的元素带 `data-draw`，文字带 `data-fade`，
 * 节点组带 `data-node="<能力 id>"`。虚线（托盘、引线）用 `data-fade` 而非 `data-draw`：DrawSVG 会改写 stroke-dasharray，虚线会变实线（入口悬停时高亮，§1.5.4）。
 *
 * 切换（§1.5.4）：调用 `animateNext()` 后改变 `active` 会播放切换时间线；否则直接替换（减少动效、
 * 动效未加载、窗口尺寸变化后的重算）。公共图框与网格不参与切换。
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { getMotion } from '../../lib/motion';
import { DUR, EASE, STAGGER } from '../../lib/motion-tokens';
import { ROLE_DRAWING_NO, ROLES, type CapabilityId, type RoleId } from '../../data/roles';

const props = defineProps<{ active: RoleId; highlight: CapabilityId | null }>();

const svg = ref<SVGSVGElement | null>(null);
/** 当前显示的组（切换途中新旧两组同时显示）。 */
const shown = ref<RoleId[]>([props.active]);
const titleShown = ref<RoleId[]>([props.active]);
let animateOnce = false;
let tl: gsap.core.Timeline | null = null;

const ROLE_NAMES = Object.fromEntries(ROLES.map((r) => [r.id, r.name])) as Record<RoleId, string>;
const IDS: RoleId[] = ['engineer', 'reviewer', 'manager'];

const hot = (id: CapabilityId) => props.highlight === id;
const gridPath = computed(() => {
  let d = '';
  for (let x = 20; x < 400; x += 20) d += `M${x} 1V259`;
  for (let y = 20; y < 260; y += 20) d += `M1 ${y}H399`;
  return d;
});

function group(id: RoleId) {
  return svg.value?.querySelector<SVGGElement>(`[data-art="${id}"]`) ?? null;
}

/** 下一次 `active` 变化播放切换动画。 */
function animateNext() {
  animateOnce = true;
}

watch(
  () => props.active,
  async (next, prev) => {
    const play = animateOnce;
    animateOnce = false;
    tl?.progress(1).kill();
    tl = null;
    const motion = getMotion();
    if (!play || !motion || !prev) {
      shown.value = [next];
      titleShown.value = [next];
      return;
    }
    shown.value = [prev, next];
    titleShown.value = [prev, next];
    await nextTick();
    const oldG = group(prev);
    const newG = group(next);
    const root = svg.value;
    if (!oldG || !newG || !root) return;
    const { gsap } = motion;
    const oldTitle = root.querySelectorAll(`[data-title="${prev}"]`);
    const newTitle = root.querySelectorAll(`[data-title="${next}"]`);
    const t = gsap.timeline({
      onComplete: () => {
        shown.value = [next];
        titleShown.value = [next];
        gsap.set([...oldG.querySelectorAll('[data-draw],[data-fade]'), ...oldTitle], { clearProps: 'all' });
      },
    });
    t.to(oldG.querySelectorAll('[data-fade]'), { opacity: 0, duration: DUR.micro, ease: EASE.out }, 0);
    t.to(
      oldG.querySelectorAll('[data-draw]'),
      { drawSVG: '100% 100%', duration: DUR.short, ease: EASE.inOut, stagger: { each: 0.01, from: 'end' } },
      0,
    );
    t.to(oldTitle, { opacity: 0, duration: DUR.micro, ease: EASE.out }, 0);
    t.call(() => {
      titleShown.value = [next];
    }, undefined, 0.16);
    t.fromTo(newTitle, { opacity: 0 }, { opacity: 1, duration: DUR.short, ease: EASE.out }, 0.16);
    t.fromTo(
      newG.querySelectorAll('[data-draw]'),
      { drawSVG: '0% 0%' },
      { drawSVG: '0% 100%', duration: DUR.long, ease: EASE.inOut, stagger: { amount: 0.3 } },
      0.16,
    );
    t.fromTo(
      newG.querySelectorAll('[data-fade]'),
      { opacity: 0 },
      { opacity: 1, duration: DUR.short, ease: EASE.out, stagger: STAGGER.tight },
      0.6,
    );
    t.call(() => {
      shown.value = [next];
    }, undefined, DUR.short + 0.02 * oldG.querySelectorAll('[data-draw]').length);
    tl = t;
  },
);

onBeforeUnmount(() => {
  tl?.kill();
  tl = null;
});

defineExpose({ svg, animateNext, group });
</script>

<template>
  <svg
    ref="svg"
    class="role-art"
    viewBox="0 0 400 260"
    preserveAspectRatio="xMidYMid meet"
    aria-hidden="true"
    focusable="false"
    :data-active="active"
  >
    <!-- 公共：网格、外框、标题栏 -->
    <path class="art-grid" :d="gridPath" />
    <rect class="art-frame" data-draw data-frame x="0.5" y="0.5" width="399" height="259" />
    <path class="art-s" data-draw data-frame d="M248 224H400M248 224V260M296 224V260M248 242H400" />
    <text class="art-t" x="256" y="237">岗位</text>
    <text class="art-t" x="256" y="255">图号</text>
    <template v-for="id in IDS" :key="id">
      <g v-if="titleShown.includes(id)" class="art-title" :data-title="id">
        <text class="art-t" x="304" y="237">{{ ROLE_NAMES[id] }}</text>
        <text class="art-t art-mono" x="304" y="255">{{ ROLE_DRAWING_NO[id] }}</text>
      </g>
    </template>

    <!-- R-01 造价工程师：编制 -->
    <g v-show="shown.includes('engineer')" data-art="engineer">
      <text class="art-t" data-fade x="16" y="28">项目/2026-007-某综合办公楼/</text>
      <path class="art-s" data-draw d="M16 38V34H372V38" />
      <rect class="art-tray" data-fade x="16" y="168" width="268" height="36" />
      <text class="art-t art-muted" data-fade x="24" y="190">工作/</text>
      <rect class="art-tray" data-fade x="304" y="168" width="76" height="36" />
      <text class="art-t art-muted" data-fade x="312" y="190">成果/</text>
      <path class="art-s" data-draw d="M92 96H108M104 92L108 96L104 100" />
      <path class="art-s" data-draw d="M188 96H204M200 92L204 96L200 100" />
      <path class="art-s" data-draw d="M284 96H300M296 92L300 96L296 100" />
      <g data-node="project" :class="{ 'is-hot': hot('project') }">
        <path class="art-link art-dash" data-fade d="M54 120V168" />
        <rect class="art-box" data-draw x="16" y="72" width="76" height="48" rx="6" />
        <text class="art-t art-mono art-no" data-fade x="22" y="86">01</text>
        <text class="art-t" data-fade x="54" y="108" text-anchor="middle">资料盘点</text>
      </g>
      <g data-node="check" :class="{ 'is-hot': hot('check') }">
        <path class="art-link art-dash" data-fade d="M150 120V168" />
        <rect class="art-box" data-draw x="112" y="72" width="76" height="48" rx="6" />
        <text class="art-t art-mono art-no" data-fade x="118" y="86">02</text>
        <text class="art-t" data-fade x="150" y="101" text-anchor="middle">送审审定</text>
        <text class="art-t" data-fade x="150" y="115" text-anchor="middle">核对</text>
      </g>
      <g data-node="estimate" :class="{ 'is-hot': hot('estimate') }">
        <path class="art-link art-dash" data-fade d="M246 120V168" />
        <rect class="art-box" data-draw x="208" y="72" width="76" height="48" rx="6" />
        <text class="art-t art-mono art-no" data-fade x="214" y="86">03</text>
        <text class="art-t" data-fade x="246" y="108" text-anchor="middle">概算编制</text>
      </g>
      <g data-node="report" :class="{ 'is-hot': hot('report') }">
        <path class="art-link art-dash" data-fade d="M342 120V168" />
        <rect class="art-box" data-draw x="304" y="72" width="76" height="48" rx="6" />
        <text class="art-t art-mono art-no" data-fade x="310" y="86">04</text>
        <text class="art-t" data-fade x="342" y="108" text-anchor="middle">报告撰写</text>
      </g>
    </g>

    <!-- R-02 审核负责人：复核 -->
    <g v-show="shown.includes('reviewer')" data-art="reviewer">
      <rect class="art-box" data-draw x="136" y="24" width="128" height="184" />
      <text class="art-t art-strong" data-fade x="148" y="44">复核记录</text>
      <path class="art-s" data-draw d="M136 52H264" />
      <g v-for="(row, i) in [
          { y: 72, stamp: '确认', tone: 'ok' },
          { y: 108, stamp: '复核', tone: 'info' },
          { y: 144, stamp: '待核', tone: 'warn' },
          { y: 180, stamp: '核对', tone: 'info' },
        ]" :key="i">
        <rect class="art-s" data-draw x="148" :y="row.y - 6" width="12" height="12" rx="2" />
        <rect class="art-bar" data-fade x="168" :y="row.y - 3" width="64" height="6" rx="3" />
        <rect :class="['art-stamp', `tone-${row.tone}`]" data-fade x="234" :y="row.y - 9" width="28" height="18" rx="3" />
        <text :class="['art-t', 'art-stamp-t', `tone-${row.tone}`]" data-fade x="248" :y="row.y + 4" text-anchor="middle">{{ row.stamp }}</text>
      </g>
      <g data-node="control" :class="{ 'is-hot': hot('control') }">
        <path class="art-link" data-draw d="M96 72H136" />
        <circle class="art-dot" data-fade cx="96" cy="72" r="2.5" />
        <circle class="art-dot" data-fade cx="136" cy="72" r="2.5" />
        <rect class="art-box" data-draw x="16" y="48" width="80" height="48" rx="4" />
        <text class="art-t" data-fade x="22" y="63">投控</text>
        <path class="art-s art-thin" data-draw d="M52 56H88V88H52ZM52 67H88M52 78H88M70 56V88" />
      </g>
      <g data-node="metrics" :class="{ 'is-hot': hot('metrics') }">
        <path class="art-link" data-draw d="M96 152H116V108H136" />
        <circle class="art-dot" data-fade cx="96" cy="152" r="2.5" />
        <circle class="art-dot" data-fade cx="136" cy="108" r="2.5" />
        <rect class="art-box" data-draw x="16" y="128" width="80" height="48" rx="4" />
        <text class="art-t" data-fade x="22" y="143">指标</text>
        <path class="art-s art-thin" data-draw d="M50 168H90M56 168V156M66 168V146M76 168V152M86 168V140" />
      </g>
      <g data-node="bills" :class="{ 'is-hot': hot('bills') }">
        <path class="art-link" data-draw d="M304 72H284V144H264" />
        <circle class="art-dot" data-fade cx="304" cy="72" r="2.5" />
        <circle class="art-dot" data-fade cx="264" cy="144" r="2.5" />
        <rect class="art-box" data-draw x="304" y="48" width="80" height="48" rx="4" />
        <text class="art-t" data-fade x="310" y="63">清单</text>
        <path class="art-s art-thin" data-draw d="M310 72H330M336 72H376M310 80H330M336 80H366M310 88H330M336 88H372" />
      </g>
      <g data-node="cad" :class="{ 'is-hot': hot('cad') }">
        <path class="art-link" data-draw d="M304 152H292V180H264" />
        <circle class="art-dot" data-fade cx="304" cy="152" r="2.5" />
        <circle class="art-dot" data-fade cx="264" cy="180" r="2.5" />
        <rect class="art-box" data-draw x="304" y="128" width="80" height="48" rx="4" />
        <text class="art-t" data-fade x="310" y="143">图纸</text>
        <path class="art-s art-thin" data-draw d="M340 136H378V170H340ZM354 136V170M366 136V158H378" />
      </g>
    </g>

    <!-- R-03 公司管理者：积累 -->
    <g v-show="shown.includes('manager')" data-art="manager">
      <path class="art-ghost" data-draw transform="translate(12 -12)" d="M156 78A44 10 0 0 1 244 78A44 10 0 0 1 156 78M156 78V150A44 10 0 0 0 244 150V78" />
      <path class="art-ghost" data-draw transform="translate(6 -6)" d="M156 78A44 10 0 0 1 244 78A44 10 0 0 1 156 78M156 78V150A44 10 0 0 0 244 150V78" />
      <path class="art-fill" d="M156 78V150A44 10 0 0 0 244 150V78Z" />
      <ellipse class="art-box" data-draw cx="200" cy="78" rx="44" ry="10" />
      <path class="art-s" data-draw d="M156 78V150M244 78V150M156 150A44 10 0 0 0 244 150" />
      <text class="art-t" data-fade x="200" y="110" text-anchor="middle">公司桶</text>
      <text class="art-t art-muted" data-fade x="200" y="128" text-anchor="middle">版本控制</text>
      <g data-node="archive" :class="{ 'is-hot': hot('archive') }">
        <path class="art-link" data-draw d="M120 46C140 46 140 84 156 84" />
        <rect class="art-box" data-draw x="16" y="24" width="104" height="44" rx="4" />
        <text class="art-t" data-fade x="24" y="42">案例索引.md</text>
        <path class="art-s art-thin" data-draw d="M24 52H112M24 59H96" />
      </g>
      <g data-node="knowledge" :class="{ 'is-hot': hot('knowledge') }">
        <path class="art-link" data-draw d="M280 46C260 46 260 84 244 84" />
        <rect class="art-box" data-draw x="280" y="24" width="104" height="44" rx="4" />
        <text class="art-t" data-fade x="288" y="42">知识库/</text>
        <path class="art-s art-thin" data-draw d="M288 50h12v8h-12ZM306 50h12v8h-12ZM324 50h12v8h-12ZM342 50h12v8h-12ZM360 50h12v8h-12Z" />
      </g>
      <g data-node="qa" :class="{ 'is-hot': hot('qa') }">
        <path class="art-link" data-draw d="M120 190C140 190 140 144 156 144" />
        <rect class="art-box" data-draw x="16" y="168" width="104" height="44" rx="4" />
        <text class="art-t" data-fade x="24" y="186">项目说明.md</text>
        <path class="art-s art-thin" data-draw d="M24 198H76M24 204H64" />
        <path class="art-s" data-draw d="M90 194a9 8 0 1 1 6 7.5l-5 3 1-5" />
        <text class="art-t art-mono" data-fade x="99" y="200" text-anchor="middle">?</text>
      </g>
      <g data-node="cloud" :class="{ 'is-hot': hot('cloud') }">
        <path class="art-link" data-draw d="M280 190C260 190 260 144 244 144" />
        <rect class="art-box" data-draw x="280" y="168" width="104" height="44" rx="4" />
        <text class="art-t" data-fade x="288" y="186">ECS · SSH</text>
        <path class="art-s art-thin" data-draw d="M350 176h26v13h-26ZM350 193h26v13h-26ZM355 182.5h4M355 199.5h4" />
      </g>
    </g>
  </svg>
</template>
