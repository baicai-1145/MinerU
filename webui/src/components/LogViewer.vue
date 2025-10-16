<template>
  <div ref="container" class="log-viewer">
    <pre class="log-content">
<code>
<span v-for="(line, index) in lines" :key="index">{{ line }}</span>
</code>
    </pre>
  </div>
</template>

<script setup lang="ts">
import { onUpdated, ref } from 'vue';

const props = defineProps<{
  lines: string[];
}>();

const container = ref<HTMLDivElement | null>(null);

onUpdated(() => {
  const el = container.value;
  if (el) {
    el.scrollTop = el.scrollHeight;
  }
});
</script>

<style scoped>
.log-viewer {
  max-height: 240px;
  overflow-y: auto;
  background: #111;
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  padding: 0.75rem;
}

.log-content {
  margin: 0;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.75rem;
  line-height: 1.5;
  color: var(--text-muted);
}
</style>
