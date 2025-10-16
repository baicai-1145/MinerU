import { defineStore } from 'pinia';

interface UiState {
  isUploading: boolean;
  isSidebarCollapsed: boolean;
  errorMessage: string | null;
}

export const useUiStore = defineStore('ui', {
  state: (): UiState => ({
    isUploading: false,
    isSidebarCollapsed: false,
    errorMessage: null
  }),
  actions: {
    setUploading(flag: boolean) {
      this.isUploading = flag;
    },
    toggleSidebar() {
      this.isSidebarCollapsed = !this.isSidebarCollapsed;
    },
    setError(message: string | null) {
      this.errorMessage = message;
    },
    clearError() {
      this.errorMessage = null;
    }
  }
});
