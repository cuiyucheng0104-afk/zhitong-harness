<script setup lang="ts">
/**
 * 任务入口（03 章 §1.5.5）：`<a href="/docs/features/<id>/">`。
 * 无 JS 时直达文档；普通点击打开说明卡；Ctrl / ⌘ / Shift / Alt 或中键点击不拦截。
 * 精确指针悬停或键盘聚焦：下划线由左画出、箭头右出左入（GSAP）；离开时下划线向右收回、箭头继续向右走。
 * 动效未加载或减少动效时只用 CSS（下划线直接 scaleX(1)，无过渡）。
 */
import { onBeforeUnmount, ref, watch } from 'vue';
import AppIcon from '../AppIcon.vue';
import { getMotion, hasFinePointer, prefersReducedMotion } from '../../lib/motion';
import { DUR, EASE } from '../../lib/motion-tokens';
import type { CapabilityId, RoleTask } from '../../data/roles';

const props = defineProps<{ task: RoleTask; expanded: boolean }>();
const emit = defineEmits<{
  open: [task: RoleTask, anchor: HTMLElement];
  hover: [capability: CapabilityId | null];
}>();

const el = ref<HTMLAnchorElement | null>(null);
const line = ref<HTMLElement | null>(null);
const a1 = ref<HTMLElement | null>(null);
const a2 = ref<HTMLElement | null>(null);
let engaged = false;
let pointerInside = false;

/** GSAP 已加载、`html.motion-ready`、精确指针或键盘时才走悬停时间线。 */
function gsapReady(keyboard: boolean) {
  const m = getMotion();
  if (!m || prefersReducedMotion() || !document.documentElement.classList.contains('motion-ready')) return null;
  if (!keyboard && !hasFinePointer()) return null;
  return m.gsap;
}

function enter(keyboard = false) {
  const gsap = gsapReady(keyboard);
  if (!gsap || engaged || !line.value || !a1.value || !a2.value) return;
  engaged = true;
  const d = { duration: DUR.short, ease: EASE.out, overwrite: 'auto' as const };
  gsap.to(line.value, { ...d, transformOrigin: 'left center', scaleX: 1 });
  gsap.to(a1.value, { ...d, x: 16, opacity: 0 });
  gsap.fromTo(a2.value, { x: -16, opacity: 0 }, { ...d, x: 0, opacity: 1, delay: 0.04 });
}

function leave() {
  const gsap = gsapReady(true);
  if (!engaged || props.expanded) return;
  engaged = false;
  if (!gsap || !line.value || !a1.value || !a2.value) return;
  const d = { duration: DUR.short, ease: EASE.out, overwrite: 'auto' as const };
  gsap.to(line.value, { ...d, transformOrigin: 'right center', scaleX: 0 });
  gsap.to(a2.value, { ...d, x: 16, opacity: 0 });
  gsap.fromTo(a1.value, { x: -16, opacity: 0 }, { ...d, x: 0, opacity: 1 });
}

function onPointerEnter(e: PointerEvent) {
  if (e.pointerType === 'touch') return;
  pointerInside = true;
  emit('hover', props.task.capability);
  enter();
}
function onPointerLeave(e: PointerEvent) {
  if (e.pointerType === 'touch') return;
  pointerInside = false;
  if (document.activeElement !== el.value) emit('hover', null);
  leave();
}
function onFocus() {
  emit('hover', props.task.capability);
  if (el.value?.matches(':focus-visible')) enter(true);
}
function onBlur() {
  if (!pointerInside) {
    emit('hover', null);
    leave();
  }
}

function onClick(e: MouseEvent) {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  if (el.value) emit('open', props.task, el.value);
}

watch(
  () => props.expanded,
  (open) => {
    if (open) {
      enter(true);
      return;
    }
    if (!pointerInside && document.activeElement !== el.value) leave();
  },
);

onBeforeUnmount(() => {
  const m = getMotion();
  if (m) m.gsap.killTweensOf([line.value, a1.value, a2.value].filter(Boolean) as HTMLElement[]);
});
</script>

<template>
  <a
    ref="el"
    v-magnetic="'link'"
    class="task-chip"
    :href="task.docs"
    :data-task="task.id"
    :data-capability="task.capability"
    aria-haspopup="dialog"
    :aria-expanded="expanded ? 'true' : 'false'"
    aria-controls="role-task-popover"
    @click="onClick"
    @pointerenter="onPointerEnter"
    @pointerleave="onPointerLeave"
    @focus="onFocus"
    @blur="onBlur"
  >
    <span class="task-chip__inner" data-magnetic-label>
      <span class="task-chip__no mono">{{ task.no }}</span>
      <span class="task-chip__label">{{ task.label }}</span>
      <span class="task-chip__arrows" aria-hidden="true">
        <span ref="a1" class="a1"><AppIcon name="arrow" /></span>
        <span ref="a2" class="a2"><AppIcon name="arrow" /></span>
      </span>
    </span>
    <span ref="line" class="task-chip__line" aria-hidden="true"></span>
  </a>
</template>
