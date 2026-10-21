<script setup lang="ts">
/**
 * 说明卡内容（03 章 §1.2、§1.3），放进 `ZtPopover` 默认插槽；标题由 ZtPopover 的 `title` 渲染
 * （id = `role-task-popover-title`）。多根节点：眉题、一句话、两行 `<dl>`、限定、动作行，
 * 在说明卡正文的纵向弹性布局里按 `order` 排在标题之前 / 小动画之后（样式见 sections/roles.css）。
 */
import AppIcon from '../AppIcon.vue';
import { primaryLabel, TASK_ROW_LABELS, type RoleTask } from '../../data/roles';

defineProps<{ task: RoleTask }>();
const emit = defineEmits<{ primary: [task: RoleTask] }>();
</script>

<template>
  <p class="task-pop__eyebrow" data-popover-row>{{ task.eyebrow }}</p>
  <p class="task-pop__summary" data-popover-row>{{ task.summary }}</p>
  <dl class="task-pop__rows" data-popover-row>
    <div>
      <dt>{{ TASK_ROW_LABELS.needs }}</dt>
      <dd>{{ task.needs }}</dd>
    </div>
    <div>
      <dt>{{ TASK_ROW_LABELS.yields }}</dt>
      <dd>{{ task.yields }}</dd>
    </div>
  </dl>
  <p v-if="task.note" class="task-pop__note" data-popover-row>{{ task.note }}</p>
  <div class="task-pop__actions" data-popover-row>
    <button
      type="button"
      class="button button-primary button-small"
      :data-primary="task.primary.kind"
      @click="emit('primary', task)"
    >
      {{ primaryLabel(task) }}
    </button>
    <RouterLink class="text-link task-pop__docs" :to="task.docs">读文档<AppIcon name="arrow" /></RouterLink>
  </div>
</template>
