<script setup lang="ts">
/**
 * 搜索对话框（06 章 §8.2）：BaseDialog（原生模态 `<dialog>`），桌面宽 640px、距顶 12vh、最大高 70vh，手机全屏。
 * 输入框为 combobox，结果为 listbox；输入防抖 80ms，结果更新后朗读「找到 {n} 条结果」或「没有结果」。
 * ↑/↓ 循环移动当前项，Enter 打开并关闭对话框，Esc 关闭；鼠标悬停也改变当前项。
 * 动效：opacity 0 → 1、scale(0.98 → 1)，160ms ease-out；减少动效时直接出现。
 */
import { computed, nextTick, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import BaseDialog from '../BaseDialog.vue';
import { CSS_EASE, MS } from '../../lib/motion-tokens';
import { docsUi, prefetchSearch } from '../../docs/docs-ui';
import type { SearchResult, Searcher } from '../../docs/search';

const router = useRouter();
const QUICK = ['安装', '配置包', '需人工确认', '报错'];

const query = ref('');
const results = ref<SearchResult[]>([]);
const activeIndex = ref(0);
const status = ref<'idle' | 'loading' | 'ready' | 'error'>('idle');
const live = ref('');
const input = ref<HTMLInputElement | null>(null);
const listbox = ref<HTMLElement | null>(null);
let searcher: Searcher | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
const dialog = ref<InstanceType<typeof BaseDialog> | null>(null);

const expanded = computed(() => results.value.length > 0);
const optionId = (i: number) => `docs-search-opt-${i}`;
const activeId = computed(() => (expanded.value ? optionId(activeIndex.value) : undefined));

async function ensureIndex() {
  if (searcher) return;
  status.value = 'loading';
  try {
    searcher = await prefetchSearch();
    status.value = 'ready';
    run();
  } catch {
    status.value = 'error';
  }
}

function run() {
  if (!searcher) return;
  const q = query.value.trim();
  results.value = q ? searcher.search(q) : [];
  activeIndex.value = 0;
  if (q) live.value = results.value.length ? `找到 ${results.value.length} 条结果` : '没有结果';
  else live.value = '';
}

watch(query, () => {
  clearTimeout(timer);
  timer = setTimeout(run, 80);
});

function onOpened() {
  // 保留上次查询时全选，新输入直接替换而不是接在后面。
  void nextTick(() => {
    input.value?.focus();
    input.value?.select();
  });
  void ensureIndex();
}

function onClosed() {
  clearTimeout(timer);
}

function close(returnFocus = true) {
  if (dialog.value) dialog.value.close({ returnFocus });
  else docsUi.searchOpen = false;
}

function setOpen(v: boolean) {
  docsUi.searchOpen = v;
}

async function openResult(r: SearchResult | undefined) {
  if (!r) return;
  close(false);
  // 已跳到结果页：下次打开从空查询开始。
  query.value = '';
  results.value = [];
  live.value = '';
  await router.push(r.href);
  await nextTick();
  const target = r.anchor ? document.getElementById(r.anchor) : document.querySelector<HTMLElement>('#main h1');
  if (target) {
    target.scrollIntoView({ block: 'start', behavior: 'instant' });
    target.focus({ preventScroll: true });
  }
}

function move(delta: number) {
  const n = results.value.length;
  if (!n) return;
  activeIndex.value = (activeIndex.value + delta + n) % n;
  void nextTick(() => document.getElementById(optionId(activeIndex.value))?.scrollIntoView({ block: 'nearest' }));
}

function onKeydown(e: KeyboardEvent) {
  if (e.isComposing) return;
  if (e.key === 'Escape') {
    // type="search" 的默认行为是按 Esc 先清空输入、不关闭对话框；06 章 §9 要求 Esc 直接关闭。
    e.preventDefault();
    close();
  } else if (e.key === 'ArrowDown') {
    e.preventDefault();
    move(1);
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    move(-1);
  } else if (e.key === 'Enter') {
    e.preventDefault();
    void openResult(results.value[activeIndex.value]);
  }
}

function pick(word: string) {
  query.value = word;
  clearTimeout(timer);
  run();
  input.value?.focus();
}

function enter(dialog: HTMLDialogElement) {
  return dialog.animate(
    [
      { opacity: 0, transform: 'scale(0.98)' },
      { opacity: 1, transform: 'none' },
    ],
    { duration: MS.micro, easing: CSS_EASE.out },
  ).finished;
}
function leave(dialog: HTMLDialogElement) {
  return dialog.animate([{ opacity: 1 }, { opacity: 0 }], { duration: MS.micro, easing: CSS_EASE.out, fill: 'forwards' })
    .finished;
}

</script>

<template>
  <BaseDialog
    ref="dialog"
    :model-value="docsUi.searchOpen"
    labelledby="docs-search-label"
    :trigger="docsUi.searchTrigger"
    variant="custom"
    class="docs-search-dialog"
    :enter="enter"
    :leave="leave"
    @update:model-value="setOpen"
    @opened="onOpened"
    @closed="onClosed"
  >
    <div class="search-panel">
      <h2 id="docs-search-label" class="sr-only">搜索文档</h2>
      <div class="search-field">
        <svg class="search-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <circle cx="11" cy="11" r="6.5" /><path d="m16 16 4.5 4.5" />
        </svg>
        <input
          ref="input"
          v-model="query"
          type="search"
          class="search-input"
          placeholder="搜索文档"
          aria-label="搜索文档"
          role="combobox"
          :aria-expanded="expanded ? 'true' : 'false'"
          aria-controls="docs-search-results"
          aria-autocomplete="list"
          :aria-activedescendant="activeId"
          autocomplete="off"
          spellcheck="false"
          enterkeyhint="go"
          @keydown="onKeydown"
        />
        <button type="button" class="icon-button search-close" aria-label="关闭搜索" @click="close()">
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m6 6 12 12M18 6 6 18" /></svg>
        </button>
      </div>

      <div class="search-body">
        <p v-if="status === 'loading'" class="search-note">正在载入索引…</p>
        <p v-else-if="status === 'error'" class="search-note is-error">搜索索引载入失败，请刷新页面后重试。</p>
        <div v-else-if="!query.trim()" class="search-quick">
          <span>常用：</span>
          <button v-for="w in QUICK" :key="w" type="button" class="search-chip" @click="pick(w)">{{ w }}</button>
        </div>
        <p v-else-if="status === 'ready' && !results.length" class="search-note">
          没有找到与“{{ query.trim() }}”相关的内容。可以换个说法，或查看<RouterLink
            to="/docs/troubleshooting/"
            @click="close(false)"
            >常见问题与排错</RouterLink
          >
        </p>
        <ul
          id="docs-search-results"
          ref="listbox"
          class="search-results"
          role="listbox"
          aria-label="搜索结果"
          :hidden="!results.length"
        >
          <li
            v-for="(r, i) in results"
            :id="optionId(i)"
            :key="`${r.href}-${i}`"
            role="option"
            :aria-selected="i === activeIndex ? 'true' : 'false'"
            :class="['search-result', { 'is-active': i === activeIndex }]"
            @mousemove="activeIndex = i"
            @click="openResult(r)"
          >
            <p class="result-title">
              {{ r.pageTitle }}<span class="result-sep"> › </span>{{ r.heading }}
            </p>
            <p class="result-excerpt">
              <template v-for="(part, k) in r.excerpt" :key="k"
                ><mark v-if="part.mark">{{ part.text }}</mark
                ><template v-else>{{ part.text }}</template></template
              >
            </p>
          </li>
        </ul>
      </div>

      <p class="search-foot" aria-hidden="true">↑↓ 选择 · Enter 打开 · Esc 关闭</p>
      <p class="sr-only" aria-live="polite">{{ live }}</p>
    </div>
  </BaseDialog>
</template>
