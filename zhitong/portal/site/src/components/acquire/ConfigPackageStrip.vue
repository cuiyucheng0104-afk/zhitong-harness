<script setup lang="ts">
/**
 * 配置包三步示意（01 章 §7.2、§7.5）：① 安装并打开 ② 把配置包拖进对话 ③ 列出公司桶里的项目。
 * 打开后 300ms 开始：两段连接线 stroke-dashoffset 600ms（依次延迟 0 / 200ms）；② 的 zip 图标 450ms 落入输入框（延迟 500ms）。
 * 由父组件给根元素加 `.is-playing` 触发，减少动效时直接画全。
 */
</script>

<template>
  <figure class="config-strip">
    <svg viewBox="0 0 240 120" aria-hidden="true" focusable="false">
      <g class="cs-step cs-step-1">
        <rect x="8" y="22" width="56" height="40" rx="6" />
        <path d="M18 34h20M18 42h30M18 50h14" />
        <path d="M30 62v8h12v-8" />
      </g>
      <path class="cs-link cs-link-1" d="M68 42h22" pathLength="1" />
      <g class="cs-step cs-step-2">
        <rect x="94" y="22" width="56" height="40" rx="6" />
        <rect class="cs-input" x="100" y="46" width="44" height="10" rx="5" />
        <g class="cs-zip">
          <path d="M114 26h12l4 4v12h-16z" />
          <path d="M120 28v2m0 2v2m0 2v2" />
        </g>
      </g>
      <path class="cs-link cs-link-2" d="M154 42h22" pathLength="1" />
      <g class="cs-step cs-step-3">
        <rect x="180" y="22" width="56" height="40" rx="6" />
        <path d="M188 32h6l2 3h12v12h-20z" />
        <path d="M212 34h16M212 40h12M212 46h14M188 54h40" />
      </g>
    </svg>
    <figcaption>
      <ol class="config-strip-steps">
        <li>① 安装并打开</li>
        <li>② 把配置包拖进对话</li>
        <li>③ 列出公司桶里的项目</li>
      </ol>
    </figcaption>
  </figure>
</template>
