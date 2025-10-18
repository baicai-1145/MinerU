<template>
  <div class="task-list">
    <header class="task-list__header">
      <h2>任务列表</h2>
      <button class="refresh" @click="$emit('refresh')">刷新</button>
    </header>
    <div class="task-list__items" v-if="tasks.length">
      <article
        v-for="task in tasks"
        :key="task.task_id"
        :class="['task-card', { active: task.task_id === currentTaskId }]"
        @click="$emit('select', task.task_id)"
      >
        <div class="task-card__row">
          <span class="task-card__id">{{ task.task_id.slice(0, 8) }}</span>
          <span class="task-card__status" :data-status="task.status">{{ statusLabel(task.status) }}</span>
        </div>
        <div class="task-card__meta">
          <span>后端: {{ task.backend }}</span>
          <span>方法: {{ task.parse_method }}</span>
          <span>{{ retentionLabel(task) }}</span>
        </div>
        <div class="task-card__time">
          <span>开始于 {{ formatTime(task.created_at) }}</span>
        </div>
        <p v-if="task.error" class="task-card__error">{{ task.error }}</p>
      </article>
    </div>
    <p v-else class="empty">暂无任务</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useTaskStore } from '@/stores/taskStore';
import type { TaskSummary } from '@/stores/taskStore';

defineEmits<{
  (e: 'select', taskId: string): void;
  (e: 'refresh'): void;
}>();

const taskStore = useTaskStore();

const tasks = computed(() => taskStore.tasks);
const currentTaskId = computed(() => taskStore.currentTaskId);

function statusLabel(status: string) {
  switch (status) {
    case 'queued':
      return '排队中';
    case 'running':
      return '运行中';
    case 'success':
      return '完成';
    case 'failed':
      return '失败';
    default:
      return status;
  }
}

function formatTime(value: string) {
  return new Date(value).toLocaleString();
}

function retentionLabel(task: TaskSummary) {
  return task.persistent ? '保存: 永久' : '保存: 7 天';
}
</script>

<style scoped>
.task-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.task-list__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.task-list__header h2 {
  margin: 0;
  font-size: 1rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.refresh {
  background: transparent;
  border: 1px solid var(--accent);
  color: var(--accent);
  padding: 0.5rem 1rem;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
}

.refresh:hover {
  background: var(--accent);
  color: #111;
}

.task-list__items {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.task-card {
  padding: 1rem;
  border-radius: 0.75rem;
  border: 1px solid var(--border-color);
  background: var(--bg-hover);
  cursor: pointer;
  transition: border-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
  box-shadow: none;
}

.task-card:hover {
  border-color: var(--accent);
  transform: translateY(-3px);
  box-shadow: var(--card-shadow);
}

.task-card.active {
  border-color: var(--accent);
  box-shadow: var(--card-shadow);
}

.task-card__row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.task-card__id {
  font-weight: 600;
  letter-spacing: 0.1em;
}

.task-card__status[data-status='running'] {
  color: var(--info);
}

.task-card__status[data-status='success'] {
  color: var(--success);
}

.task-card__status[data-status='failed'] {
  color: var(--danger);
}

.task-card__meta,
.task-card__time {
  display: flex;
  gap: 0.75rem;
  color: var(--text-muted);
  font-size: 0.85rem;
}

.task-card__error {
  margin: 0.5rem 0 0;
  color: var(--danger);
  font-size: 0.85rem;
}

.empty {
  text-align: center;
  color: var(--text-muted);
}
</style>
