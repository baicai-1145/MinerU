<template>
  <transition name="fade">
    <div v-if="message" class="error-banner">
      <span>{{ message }}</span>
      <button class="close" @click="$emit('close')">×</button>
    </div>
  </transition>
</template>

<script setup lang="ts">
defineProps<{
  message: string | null;
}>();

defineEmits<{
  (e: 'close'): void;
}>();
</script>

<style scoped>
.error-banner {
  position: fixed;
  top: 1rem;
  right: 1rem;
  background: rgba(248, 113, 113, 0.95);
  color: #111;
  padding: 0.75rem 1.25rem;
  border-radius: 0.75rem;
  box-shadow: 0 10px 20px rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  gap: 0.75rem;
  z-index: 999;
  min-width: 220px;
}

.close {
  background: transparent;
  border: none;
  color: inherit;
  font-size: 1.2rem;
  cursor: pointer;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
