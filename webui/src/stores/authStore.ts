import { defineStore } from 'pinia';
import { registerUser, loginUser, type AuthPayload } from '@/services/auth';
import { getUserId, setUserId, getUsername, setUsername } from '@/utils/session';

export type AuthMode = 'login' | 'register';

interface AuthState {
  userId: string | null;
  username: string | null;
  showDialog: boolean;
  mode: AuthMode;
  loading: boolean;
  error: string | null;
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    userId: null,
    username: null,
    showDialog: false,
    mode: 'login',
    loading: false,
    error: null
  }),
  getters: {
    isLoggedIn(state): boolean {
      return Boolean(state.userId);
    }
  },
  actions: {
    initialize() {
      this.userId = getUserId();
      this.username = getUsername();
    },
    open(mode: AuthMode) {
      this.mode = mode;
      this.showDialog = true;
      this.error = null;
    },
    close() {
      this.showDialog = false;
      this.error = null;
    },
    setError(message: string | null) {
      this.error = message;
    },
    async register(payload: AuthPayload) {
      this.loading = true;
      this.error = null;
      try {
        const response = await registerUser(payload);
        setUserId(response.user_id);
        setUsername(response.username);
        this.userId = response.user_id;
        this.username = response.username;
        this.showDialog = false;
      } catch (error: any) {
        const detail = error?.response?.data?.detail ?? error?.message ?? '注册失败';
        this.error = detail;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    async login(payload: AuthPayload) {
      this.loading = true;
      this.error = null;
      try {
        const response = await loginUser(payload);
        setUserId(response.user_id);
        setUsername(response.username);
        this.userId = response.user_id;
        this.username = response.username;
        this.showDialog = false;
      } catch (error: any) {
        const detail = error?.response?.data?.detail ?? error?.message ?? '登录失败';
        this.error = detail;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    logout() {
      setUserId(null);
      setUsername(null);
      this.userId = null;
      this.username = null;
    },
    switchMode(mode: AuthMode) {
      this.mode = mode;
      this.error = null;
    }
  }
});
