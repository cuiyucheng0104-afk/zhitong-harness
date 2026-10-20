<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { loadMotion } from '../lib/motion';

const props = defineProps<{
  modelValue: boolean;
  labelledby: string;
  trigger?: HTMLElement | null;
}>();
const emit = defineEmits<{
  'update:modelValue': [value: boolean];
  opened: [element: HTMLDialogElement];
  closed: [];
}>();
const element = ref<HTMLDialogElement | null>(null);
let mounted = false;
let returnFocus: HTMLElement | null = null;
let animation: gsap.core.Tween | undefined;

function syncScrollLock() {
  document.body.classList.toggle('modal-open', Boolean(document.querySelector('dialog[open]')));
}

function close() {
  emit('update:modelValue', false);
}

function afterClose() {
  animation?.kill();
  syncScrollLock();
  emit('update:modelValue', false);
  emit('closed');
  if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
}

function sync() {
  const dialog = element.value;
  if (!mounted || !dialog) return;
  if (props.modelValue && !dialog.open) {
    returnFocus =
      props.trigger ??
      (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    dialog.showModal();
    syncScrollLock();
    emit('opened', dialog);
    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      void loadMotion().then((motion) => {
        if (!motion || !dialog.open || !mounted) return;
        animation = motion.gsap.fromTo(
          dialog,
          { autoAlpha: 0, y: 12 },
          {
            autoAlpha: 1,
            y: 0,
            duration: 0.22,
            ease: 'power2.out',
            clearProps: 'opacity,visibility,transform',
          },
        );
      });
    }
  } else if (!props.modelValue && dialog.open) {
    dialog.close();
  }
}

function onBackdrop(event: MouseEvent) {
  if (event.target !== element.value) return;
  const rect = element.value!.getBoundingClientRect();
  if (
    event.clientX < rect.left ||
    event.clientX > rect.right ||
    event.clientY < rect.top ||
    event.clientY > rect.bottom
  )
    close();
}

watch(() => props.modelValue, sync, { flush: 'post' });
onMounted(() => {
  mounted = true;
  sync();
});
onBeforeUnmount(() => {
  mounted = false;
  animation?.kill();
  if (element.value?.open) element.value.close();
  syncScrollLock();
});
defineExpose({ element, close });
</script>

<template>
  <dialog
    ref="element"
    :aria-labelledby="labelledby"
    @cancel.prevent="close"
    @close="afterClose"
    @click="onBackdrop"
  >
    <slot :close="close" />
  </dialog>
</template>
