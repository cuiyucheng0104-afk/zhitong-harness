<script setup lang="ts">
/** 7.13 火山引擎运维：验证身份 → 预演 → 确认卡 → 带 --yes 执行。 */
import { A } from './anim';
import ArtTool from './parts/ArtTool.vue';
import ArtLink from './parts/ArtLink.vue';
import ArtPointer from './parts/ArtPointer.vue';
</script>

<template>
  <svg class="art-in" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <g v-bind="A('bubble')">
      <rect x="64" y="2" width="200" height="44" rx="12" fill="var(--blue-tint)" />
      <text class="at" x="76" y="20">把我现在的 IP 加进</text>
      <text class="at" x="76" y="38">zt-prod 的 SSH 白名单</text>
    </g>
    <ArtTool a="t1" :top="56" label="验证身份" name="whoami" result="zt-ak" />
    <ArtTool a="t2" :top="86" label="预演" name="sg-sync-ip --dry-run" />
    <text v-bind="A('p0')" class="as" x="0" y="132">zt-prod-sg（sg-aaaaaaaa01）</text>
    <text v-bind="A('p1')" class="at" x="0" y="154">放行 &lt;新 IP&gt;/32 端口 22</text>
    <text v-bind="A('p2')" class="at" x="0" y="176">撤销 alice 标记下的 &lt;旧 IP&gt;/32</text>
    <text v-bind="A('p3')" class="as" x="0" y="196">预演不调用任何写接口</text>
  </svg>
  <ArtLink />
  <svg class="art-out" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <rect v-bind="A('card')" x="0" y="0" width="264" height="200" rx="8" class="art-card" />
    <text v-bind="A('c-t')" class="ah" x="12" y="24">确认执行这条命令？</text>
    <g v-bind="A('c-1')">
      <text class="as" x="12" y="48">对象</text>
      <text class="at" x="48" y="48">zt-prod-sg 安全组</text>
    </g>
    <g v-bind="A('c-2')">
      <text class="as" x="12" y="70">动作</text>
      <text class="at" x="48" y="70">放行新 IP 的 22 端口，撤销旧 IP</text>
    </g>
    <g v-bind="A('c-3')">
      <text class="as" x="12" y="92">影响</text>
      <text class="at" x="48" y="92">旧 IP 不能再 SSH 登录</text>
    </g>
    <text v-bind="A('c-4')" class="as" x="12" y="114">其他同事的标记不受影响</text>
    <g v-bind="A('c-cmd')">
      <rect x="12" y="124" width="240" height="22" rx="4" fill="var(--blue-050)" />
      <text class="am" x="18" y="140">sg-sync-ip … --yes</text>
    </g>
    <g v-bind="A('b1', true)">
      <rect x="12" y="156" width="64" height="24" rx="6" fill="var(--brand-blue)" />
      <text class="at art-on-blue" text-anchor="middle" x="44" y="173">执行</text>
    </g>
    <g v-bind="A('b2', true)">
      <rect x="84" y="156" width="76" height="24" rx="6" class="art-btn-ghost" />
      <text class="at" text-anchor="middle" x="122" y="173">不执行</text>
    </g>
    <ArtTool a="run" :x="12" :top="156" label="执行" name="sg-sync-ip --yes" />
    <text v-bind="A('res')" class="at" x="12" y="194">先放行新 IP，再撤销旧 IP · 完成</text>
    <ArtPointer :x="200" :y="196" />
  </svg>
</template>
