<script setup lang="ts">
/** 安装区的“配置包”与“首次使用”两小节（05 章 §3.2、§3.4），纯展示，无 props。本区没有任何指向配置包的下载链接。 */
import { INSTALL_COPY } from '../../../data/install';
import { splitTicks } from '../../../data/trust';
</script>

<template>
  <div class="install-block install-config" data-reveal="block">
    <h3>{{ INSTALL_COPY.configTitle }}</h3>
    <p>
      <template v-for="(part, k) in splitTicks(INSTALL_COPY.configBody)" :key="k"
        ><code v-if="part.mono" class="mono">{{ part.t }}</code
        ><template v-else>{{ part.t }}</template></template
      >
    </p>
    <ul class="install-config-items">
      <li v-for="item in INSTALL_COPY.configItems" :key="item">{{ item }}</li>
    </ul>
    <p class="install-warning">{{ INSTALL_COPY.configWarning }}</p>
  </div>
  <div class="install-block install-first" data-reveal="block">
    <h3>{{ INSTALL_COPY.firstTitle }}</h3>
    <p>{{ INSTALL_COPY.firstBody }}</p>
  </div>
</template>
