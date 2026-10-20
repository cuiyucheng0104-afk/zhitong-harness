<script setup lang="ts">
import { ref } from 'vue';
import { roles } from '../data/content';
import { onTabKeydown } from '../lib/navigation';
import type { PortalAction } from '../types/portal';
import AppIcon from './AppIcon.vue';

const emit = defineEmits<{ action: [action: PortalAction] }>();
const selectedRole = ref('engineer');
</script>

<template>
  <section id="roles" class="roles-section section-space" aria-labelledby="roles-title">
    <div class="container roles-grid">
      <div class="section-heading reveal">
        <p class="eyebrow">适用岗位</p>
        <h2 id="roles-title">同一个工作台，<br />各有用处。</h2>
        <p>从经手资料的人，到签发成果的人。</p>
      </div>
      <div class="roles-content">
        <div class="role-tabs" role="tablist" aria-label="选择岗位" @keydown="onTabKeydown">
          <button
            v-for="role in roles"
            :id="`role-${role.id}`"
            :key="role.id"
            type="button"
            role="tab"
            :aria-selected="selectedRole === role.id"
            :aria-controls="`panel-${role.id}`"
            :tabindex="selectedRole === role.id ? 0 : -1"
            :data-role="role.id"
            @click="selectedRole = role.id"
          >
            <AppIcon :name="role.icon" />{{ role.name }}
          </button>
        </div>
        <div class="role-panels">
          <div
            v-for="role in roles"
            :id="`panel-${role.id}`"
            :key="role.id"
            class="role-panel"
            role="tabpanel"
            :aria-labelledby="`role-${role.id}`"
            :hidden="selectedRole !== role.id"
          >
            <h3>{{ role.title }}</h3>
            <p>
              <template v-for="(line, index) in role.description.split('\n')" :key="index"
                ><br v-if="index > 0" class="desktop-break" />{{ line }}</template
              >
            </p>
            <div class="task-links">
              <template v-for="task in role.tasks" :key="task.label">
                <a
                  v-if="task.action.type === 'section'"
                  :href="`#${task.action.id}`"
                  @click.prevent="emit('action', task.action)"
                  >{{ task.label }}<AppIcon name="arrow"
                /></a>
                <button
                  v-else
                  type="button"
                  :data-go-feature="task.action.type === 'feature' ? task.action.id : undefined"
                  :data-go-scene="task.action.type === 'scene' ? task.action.id : undefined"
                  :data-view-source="task.action.type === 'source' ? '' : undefined"
                  @click="emit('action', task.action)"
                >
                  {{ task.label }}<AppIcon name="arrow" />
                </button>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
