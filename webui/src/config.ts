export interface AppConfig {
  apiBase?: string;
}

export const appConfig: AppConfig = {
  apiBase: undefined
};

function normalizeBase(url?: string | null): string | undefined {
  if (!url) {
    return undefined;
  }
  return url.replace(/\/$/, '');
}

export function resolveApiBase(): string | undefined {
  return (
    normalizeBase(appConfig.apiBase) ??
    normalizeBase(import.meta.env.VITE_MINERU_API_BASE) ??
    (typeof window !== 'undefined' ? normalizeBase(window.location.origin) : undefined)
  );
}

export async function loadConfig(): Promise<void> {
  try {
    const response = await fetch('/app-config.json', { cache: 'no-cache' });
    if (!response.ok) {
      throw new Error(`unexpected status ${response.status}`);
    }
    const data = (await response.json()) as AppConfig;
    Object.assign(appConfig, data);
  } catch (error) {
    console.warn('Failed to load app-config.json, fallback to defaults', error);
  }
}
