<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="brand">
        <span class="brand-mark">MinerU</span>
        <span class="brand-subtitle">Web Console</span>
      </div>
      <div class="header-actions">
        <nav class="header-nav">
          <a href="https://github.com/baicai-1145/MinerU" target="_blank" rel="noopener">GitHub</a>
          <a href="https://opendatalab.github.io/MinerU/zh/quick_start/index.html" target="_blank" rel="noopener"
            >文档</a
          >
        </nav>
        <div class="auth-actions">
          <template v-if="authStore.isLoggedIn">
            <span class="user-tag">已登录：{{ authStore.username }}</span>
            <button class="ghost" @click="handleLogout">退出</button>
          </template>
          <template v-else>
            <button class="ghost" @click="authStore.open('login')">登录 / 注册</button>
          </template>
        </div>
        <button class="ghost" @click="toggleTheme">{{ themeLabel }}</button>
        <button class="accent" @click="refreshTasks">刷新任务</button>
      </div>
    </header>
    <main class="app-main">
      <aside class="app-sidebar">
        <UploadPanel @submit="onSubmit" />
        <TaskList @select="onSelectTask" @refresh="refreshTasks" />
      </aside>
      <section class="content">
        <TaskDetail @refresh="refreshTaskDetail" @retry="onRetry" />
      </section>
    </main>
    <ErrorBanner :message="errorMessage" @close="uiStore.clearError" />
    <AuthDialog />
  </div>
</template>

<script setup lang="ts">
import UploadPanel from '@/components/UploadPanel.vue';
import TaskList from '@/components/TaskList.vue';
import TaskDetail from '@/components/TaskDetail.vue';
import ErrorBanner from '@/components/ErrorBanner.vue';
import AuthDialog from '@/components/AuthDialog.vue';
import { useTaskStore } from '@/stores/taskStore';
import { useUiStore } from '@/stores/uiStore';
import { useAuthStore } from '@/stores/authStore';
import { createTask, fetchTask, fetchTasks, retryTask } from '@/services/api';
import type { CreateTaskPayload } from '@/services/api';
import { TaskWebSocket } from '@/services/websocket';
import { computed, onMounted, onBeforeUnmount, watch, ref } from 'vue';
import { appConfig } from '@/config';

const taskStore = useTaskStore();
const uiStore = useUiStore();
const authStore = useAuthStore();
const socket = new TaskWebSocket(appConfig.apiBase);
const errorMessage = computed(() => uiStore.errorMessage);
const theme = ref(localStorage.getItem('mineru-webui-theme') ?? 'light');
const themeLabel = computed(() => (theme.value === 'dark' ? '亮色模式' : '暗色模式'));

async function refreshTasks() {
  taskStore.isLoading = true;
  try {
    const response = await fetchTasks();
    if (response?.tasks) {
      taskStore.setTasks(response.tasks);
    }
  } catch (error) {
    console.error(error);
    uiStore.setError('获取任务列表失败');
  } finally {
    taskStore.isLoading = false;
  }
}

async function onSubmit(payload: CreateTaskPayload) {
  uiStore.setUploading(true);
  try {
    const response = await createTask(payload);
    if (response?.task_id) {
      await refreshTasks();
      taskStore.setCurrentTask(response.task_id);
      connectSocket(response.task_id);
      await refreshTaskDetail(response.task_id);
    }
  } catch (error) {
    console.error(error);
    uiStore.setError('任务提交失败');
  } finally {
    uiStore.setUploading(false);
  }
}

async function onSelectTask(taskId: string) {
  taskStore.setCurrentTask(taskId);
  await refreshTaskDetail(taskId);
  connectSocket(taskId);
}

async function refreshTaskDetail(taskId: string) {
  try {
    const response = await fetchTask(taskId, true);
    taskStore.setTaskDetail(response);
  } catch (error) {
    console.error(error);
    uiStore.setError('获取任务详情失败');
  }
}

async function onRetry(taskId: string) {
  try {
    const response = await retryTask(taskId);
    taskStore.setTaskDetail(response);
    taskStore.setCurrentTask(taskId);
    connectSocket(taskId);
    uiStore.clearError();
  } catch (error) {
    console.error(error);
    uiStore.setError('重新解析失败，请稍后再试');
  }
}

function connectSocket(taskId: string) {
  if (taskStore.socketTaskId === taskId) {
    return;
  }
  socket.close();
  socket.on(handleSocketEvent);
  socket.connect(taskId);
  taskStore.setSocketTask(taskId);
}

function handleSocketEvent(event: any) {
  if (event.event === 'snapshot') {
    taskStore.setTaskDetail(event.task);
  } else if (event.event === 'status') {
    const existing = taskStore.tasks.find(t => t.task_id === event.task_id);
    if (existing) {
      taskStore.upsertTask({
        ...existing,
        status: event.status,
        updated_at: event.timestamp
      });
    } else {
      refreshTasks();
    }
    if (taskStore.currentTaskId === event.task_id && ['success', 'failed'].includes(event.status)) {
      refreshTaskDetail(event.task_id);
    }
  } else if (event.event === 'log') {
    taskStore.appendLog(event.task_id, event.line);
  } else if (event.event === 'error') {
    uiStore.setError(event.message);
  }
}

onMounted(() => {
  authStore.initialize();
  refreshTasks();
  applyTheme(theme.value);
});

onBeforeUnmount(() => {
  socket.close();
});

watch(
  () => uiStore.errorMessage,
  value => {
    if (value) {
      const currentMessage = value;
      setTimeout(() => {
        if (uiStore.errorMessage === currentMessage) {
          uiStore.clearError();
        }
      }, 4000);
    }
  }
);

watch(
  () => theme.value,
  value => {
    applyTheme(value);
    localStorage.setItem('mineru-webui-theme', value);
  },
  { immediate: true }
);

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark';
}

function applyTheme(value: string) {
  const body = document.body;
  if (value === 'light') {
    body.classList.add('theme-light');
  } else {
    body.classList.remove('theme-light');
  }
}

function handleLogout() {
  authStore.logout();
  uiStore.setError('已退出登录，匿名任务将在 7 天后自动清理');
}

watch(
  () => authStore.userId,
  () => {
    taskStore.setCurrentTask(null);
    socket.close();
    refreshTasks();
  }
);
</script>

<style scoped>
.app-shell {
  min-height: 100vh;
  background: var(--bg-primary);
  color: var(--text-primary);
  display: flex;
  flex-direction: column;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.5rem 2rem;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-elevated);
}

.brand {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.brand-mark {
  font-size: 1.25rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.brand-subtitle {
  font-size: 0.75rem;
  color: var(--text-muted);
  letter-spacing: 0.2em;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.auth-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.85rem;
  color: var(--text-muted);
}

.auth-actions .user-tag {
  padding: 0.25rem 0.6rem;
  background: var(--bg-hover);
  border-radius: 999px;
  font-size: 0.8rem;
}

.header-nav {
  display: flex;
  align-items: center;
  gap: 1rem;
  font-size: 0.85rem;
}

.header-nav a {
  color: var(--text-muted);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  transition: color 0.2s ease;
}

.header-nav a:hover {
  color: var(--accent);
}

.ghost {
  padding: 0.45rem 1.1rem;
  border-radius: 999px;
  border: 1px solid var(--border-color);
  background: transparent;
  color: var(--text-primary);
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease;
}

.ghost:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--bg-hover);
}

.app-main {
  flex: 1;
  display: grid;
  grid-template-columns: clamp(240px, 26vw, 320px) minmax(0, 1fr);
  gap: 1.5rem;
  padding: 1.5rem 2rem 2rem;
}

.app-sidebar,
.content {
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: 1rem;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-width: 0;
}

.accent {
  padding: 0.5rem 1.25rem;
  border-radius: 999px;
  border: none;
  background: var(--accent);
  color: var(--accent-text);
  font-weight: 600;
  cursor: pointer;
}

@media (max-width: 960px) {
  .app-main {
    grid-template-columns: 1fr;
  }
}
</style>
