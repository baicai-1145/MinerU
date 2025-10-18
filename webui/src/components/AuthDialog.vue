<template>
  <Teleport to="body">
    <div v-if="store.showDialog" class="auth-overlay" @click="store.close">
      <div class="auth-dialog" @click.stop>
        <header class="auth-header">
          <h3>{{ store.mode === 'login' ? '登录账号' : '注册账号' }}</h3>
          <button class="close" @click="store.close" aria-label="关闭">×</button>
        </header>
        <p class="auth-hint">
          <span v-if="store.mode === 'login'">登陆后任务将永久保存，未登录的任务默认保存 7 天。</span>
          <span v-else>创建新账户即可永久保存任务，未登录用户的任务将在 7 天后自动清理。</span>
        </p>
        <form class="auth-form" @submit.prevent="handleSubmit">
          <label>
            用户名
            <input v-model.trim="username" type="text" minlength="3" maxlength="32" required autocomplete="username" />
          </label>
          <label>
            密码
            <input v-model="password" type="password" minlength="6" maxlength="128" required autocomplete="current-password" />
          </label>
          <p v-if="store.error" class="auth-error">{{ store.error }}</p>
          <button class="primary" type="submit" :disabled="store.loading">
            {{ store.mode === 'login' ? (store.loading ? '登录中…' : '登录') : store.loading ? '注册中…' : '注册' }}
          </button>
        </form>
        <footer class="auth-footer">
          <span v-if="store.mode === 'login'">
            还没有账号？<button type="button" class="link" @click="switchMode('register')">立即注册</button>
          </span>
          <span v-else>
            已有账号？<button type="button" class="link" @click="switchMode('login')">立即登录</button>
          </span>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useAuthStore, type AuthMode } from '@/stores/authStore';

const store = useAuthStore();
const username = ref(store.username ?? '');
const password = ref('');

watch(
  () => store.showDialog,
  visible => {
    if (visible) {
      username.value = store.username ?? '';
      password.value = '';
      store.setError(null);
    }
  }
);

function switchMode(mode: AuthMode) {
  store.switchMode(mode);
  password.value = '';
  store.setError(null);
}

async function handleSubmit() {
  const trimmedName = username.value.trim();
  if (!trimmedName || password.value.length < 6) {
    store.setError('请输入合法的用户名和密码');
    return;
  }
  try {
    if (store.mode === 'login') {
      await store.login({ username: trimmedName, password: password.value });
    } else {
      await store.register({ username: trimmedName, password: password.value });
    }
  } catch (error) {
    // error 已在 store 内处理
  }
}
</script>

<style scoped>
.auth-overlay {
  position: fixed;
  inset: 0;
  background: rgba(12, 16, 24, 0.55);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}

.auth-dialog {
  width: min(420px, calc(100vw - 2rem));
  background: var(--bg-primary);
  color: var(--text-primary);
  border-radius: 1rem;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.45);
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.auth-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.auth-header h3 {
  margin: 0;
  font-size: 1.25rem;
}

.close {
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-size: 1.5rem;
  cursor: pointer;
}

.auth-hint {
  margin: 0;
  color: var(--text-muted);
  font-size: 0.9rem;
  line-height: 1.5;
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.auth-form label {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  font-size: 0.9rem;
}

.auth-form input {
  padding: 0.6rem 0.75rem;
  border-radius: 0.65rem;
  border: 1px solid var(--border-color);
  background: var(--bg-hover);
  color: var(--text-primary);
}

.auth-error {
  margin: 0;
  color: var(--danger);
  font-size: 0.85rem;
}

.auth-form .primary {
  margin-top: 0.5rem;
}

.auth-footer {
  font-size: 0.85rem;
  color: var(--text-muted);
}

button.link {
  background: none;
  border: none;
  color: var(--accent);
  cursor: pointer;
  padding: 0;
  margin-left: 0.25rem;
}

button.primary {
  border: none;
  background: var(--accent);
  color: #111;
  border-radius: 0.75rem;
  padding: 0.7rem;
  cursor: pointer;
  font-weight: 600;
}

button.primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
