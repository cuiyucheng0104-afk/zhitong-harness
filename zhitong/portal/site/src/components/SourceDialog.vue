<script setup lang="ts">
import BaseDialog from './BaseDialog.vue';
import AppIcon from './AppIcon.vue';
import { formatMoney } from '../data/demo';
defineProps<{
  modelValue: boolean;
  trigger?: HTMLElement | null;
  totals: { submitted: number; approved: number; reduction: number; rate: string };
}>();
defineEmits<{
  'update:modelValue': [value: boolean];
  opened: [dialog: HTMLDialogElement];
  closed: [];
}>();
</script>

<template>
  <BaseDialog
    id="source-dialog"
    class="source-dialog"
    :model-value="modelValue"
    :trigger="trigger"
    labelledby="source-title"
    @update:model-value="$emit('update:modelValue', $event)"
    @opened="$emit('opened', $event)"
    @closed="$emit('closed')"
  >
    <div class="source-panel">
      <div class="source-panel-heading">
        <span class="eyebrow">回到原始资料</span
        ><button
          class="icon-button"
          aria-label="关闭资料出处"
          @click="$emit('update:modelValue', false)"
        >
          <AppIcon name="close" />
        </button>
      </div>
      <h2 id="source-title">这个数字，从哪里来？</h2>
      <p class="source-sample">以下为示例文件与位置</p>
      <div class="source-file">
        <span class="file-type">XLS</span>
        <div><strong>送审计价表.xlsx</strong><span class="mono">土建工程 / F20</span></div>
        <b class="mono">{{ formatMoney(totals.submitted) }}</b>
      </div>
      <div class="source-file">
        <span class="file-type">XLS</span>
        <div><strong>审定计价表.xlsx</strong><span class="mono">土建工程 / F20</span></div>
        <b class="mono">{{ formatMoney(totals.approved) }}</b>
      </div>
      <div class="source-calculation">
        <span>核减额 = 送审合计 − 审定合计</span
        ><strong class="mono">{{ formatMoney(totals.reduction) }} <small>元</small></strong
        ><span class="mono"
          >{{ formatMoney(totals.reduction).replace('.00', '') }} ÷
          {{ formatMoney(totals.submitted).replace('.00', '') }} ≈ {{ totals.rate }}%</span
        >
      </div>
      <span class="badge badge-warning"><AppIcon name="alert" />需人工确认</span>
    </div>
  </BaseDialog>
</template>
