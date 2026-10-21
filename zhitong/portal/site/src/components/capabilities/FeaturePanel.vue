<script setup lang="ts">
/**
 * 一项能力的详情（04 章 §4.1、§5.1）：眉题、h3、描述（术语首现处为说明卡触发按钮）、四项 dl、小动画、限定、链接。
 */
import { computed } from 'vue';
import { RouterLink } from 'vue-router';
import AppIcon from '../AppIcon.vue';
import CapabilityArt from './CapabilityArt.vue';
import { vMagnetic } from '../../composables/useMagnetic';
import { vSpotlight } from '../../composables/useSpotlight';
import type { Feature, GlossaryKey } from '../../data/capabilities';
import type { SceneId } from '../../types/portal';

const props = defineProps<{ feature: Feature; active: boolean }>();
const emit = defineEmits<{
  scene: [scene: SceneId, event: MouseEvent];
  term: [key: GlossaryKey, trigger: HTMLElement];
}>();

interface Segment {
  text: string;
  term?: GlossaryKey;
}

/**
 * 把描述、需要什么、得到什么切成片段：`terms` 中的词只在第一次出现处标为术语（04 章 §5.3 末段）。
 * @param texts - 依次扫描的文字。
 * @param terms - 本项术语。
 * @returns 与 texts 等长的片段数组。
 */
function splitTerms(texts: readonly string[], terms: readonly GlossaryKey[]): Segment[][] {
  const pending = new Set(terms);
  return texts.map((text) => {
    const out: Segment[] = [];
    let rest = text;
    for (;;) {
      let hit: { key: GlossaryKey; at: number } | null = null;
      for (const key of pending) {
        const at = rest.indexOf(key);
        if (at >= 0 && (!hit || at < hit.at)) hit = { key, at };
      }
      if (!hit) break;
      if (hit.at > 0) out.push({ text: rest.slice(0, hit.at) });
      out.push({ text: hit.key, term: hit.key });
      pending.delete(hit.key);
      rest = rest.slice(hit.at + hit.key.length);
    }
    if (rest) out.push({ text: rest });
    return out;
  });
}

const segs = computed(() =>
  splitTerms(
    [props.feature.description, props.feature.input, props.feature.output],
    props.feature.terms,
  ),
);

function onScene(event: MouseEvent) {
  const scene = props.feature.scene;
  if (
    !scene ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  )
    return;
  event.preventDefault();
  emit('scene', scene, event);
}
</script>

<template>
  <div v-spotlight class="feature-detail" data-panel>
    <p class="feature-kicker" data-panel-child>{{ feature.kicker }}</p>
    <h3 :id="`feature-${feature.id}-title`" tabindex="-1" data-panel-child>{{ feature.title }}</h3>
    <p class="feature-description" data-panel-child>
      <template v-for="(s, i) in segs[0]" :key="i"
        ><button
          v-if="s.term"
          type="button"
          class="term-link"
          :data-term="s.term"
          @click="emit('term', s.term, $event.currentTarget as HTMLElement)"
        >
          {{ s.text }}</button
        ><template v-else>{{ s.text }}</template></template
      >
    </p>
    <dl class="feature-io" data-panel-child>
      <div>
        <dt>需要什么</dt>
        <dd>
          <template v-for="(s, i) in segs[1]" :key="i"
            ><button
              v-if="s.term"
              type="button"
              class="term-link"
              :data-term="s.term"
              @click="emit('term', s.term, $event.currentTarget as HTMLElement)"
            >
              {{ s.text }}</button
            ><template v-else>{{ s.text }}</template></template
          >
        </dd>
      </div>
      <div>
        <dt>得到什么</dt>
        <dd>
          <template v-for="(s, i) in segs[2]" :key="i"
            ><button
              v-if="s.term"
              type="button"
              class="term-link"
              :data-term="s.term"
              @click="emit('term', s.term, $event.currentTarget as HTMLElement)"
            >
              {{ s.text }}</button
            ><template v-else>{{ s.text }}</template></template
          >
        </dd>
      </div>
      <div>
        <dt>您可以这样说</dt>
        <dd>
          <q v-for="line in feature.say" :key="line" class="feature-say">{{ line }}</q>
        </dd>
      </div>
      <div>
        <dt>产出位置</dt>
        <dd>
          <span v-for="o in feature.outputs" :key="o.path" class="feature-output"
            ><code class="mono">{{ o.path }}</code
            ><span v-if="o.note" class="feature-output-note">（{{ o.note }}）</span></span
          >
        </dd>
      </div>
    </dl>
    <CapabilityArt
      :id="feature.id"
      :caption="feature.art.caption"
      :active="active"
      data-panel-child
    />
    <p class="feature-caution" :data-level="feature.cautionLevel" data-panel-child>
      <AppIcon v-if="feature.cautionLevel === 'warn'" name="alert" />{{ feature.caution }}
    </p>
    <p class="feature-links" data-panel-child>
      <a
        v-if="feature.scene"
        v-magnetic="'link'"
        class="text-link"
        href="#demo"
        :data-scene="feature.scene"
        :aria-label="`查看工作示例：${feature.name}，跳到页面上方的示例窗口`"
        @click="onScene"
        ><span data-magnetic-label>查看工作示例<AppIcon name="arrow" /></span
      ></a>
      <RouterLink
        v-magnetic="'link'"
        class="text-link"
        :to="feature.docs"
        :aria-label="`读文档：${feature.name}`"
        ><span data-magnetic-label>读文档<AppIcon name="arrow" /></span
      ></RouterLink>
    </p>
  </div>
</template>
