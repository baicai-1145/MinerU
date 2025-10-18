import axios from 'axios';
import { resolveApiBase } from '@/config';
import { getSessionId, getUserId } from '@/utils/session';

const client = axios.create({
  timeout: 120000
});

const initialBase = resolveApiBase();
if (initialBase) {
  client.defaults.baseURL = initialBase;
}

client.interceptors.request.use(config => {
  const base = resolveApiBase();
  if (base) {
    config.baseURL = base;
  }
  const headers = config.headers ?? (config.headers = {});
  const sessionId = getSessionId();
  if (sessionId) {
    headers['X-Mineru-Session'] = sessionId;
  }
  const userId = getUserId();
  if (userId) {
    headers['X-Mineru-User'] = userId;
  }
  return config;
});

function appendScopeParams(url: string): string {
  const sessionId = getSessionId();
  const userId = getUserId();
  const [path, query] = url.split('?', 2);
  const params = new URLSearchParams(query ?? '');
  if (sessionId) {
    params.set('session', sessionId);
  } else {
    params.delete('session');
  }
  if (userId) {
    params.set('user', userId);
  } else {
    params.delete('user');
  }
  const queryString = params.toString();
  return queryString ? `${path}?${queryString}` : path;
}

export interface CreateTaskPayload {
  files: File[];
  lang_list?: string[];
  backend?: string;
  parse_method?: string;
  formula_enable?: boolean;
  table_enable?: boolean;
  device_mode?: string;
  virtual_vram?: number;
  model_source?: string;
  server_url?: string;
  start_page_id?: number;
  end_page_id?: number;
  return_md?: boolean;
  return_middle_json?: boolean;
  return_model_output?: boolean;
  return_content_list?: boolean;
  return_images?: boolean;
  return_orig_pdf?: boolean;
  return_html?: boolean;
  return_docx?: boolean;
  return_latex?: boolean;
}

export async function createTask(payload: CreateTaskPayload) {
  const form = new FormData();
  payload.files.forEach(file => form.append('files', file));

  if (payload.lang_list?.length) {
    payload.lang_list.forEach(lang => form.append('lang_list', lang));
  }
  if (payload.backend) form.append('backend', payload.backend);
  if (payload.parse_method) form.append('parse_method', payload.parse_method);
  if (payload.formula_enable !== undefined) {
    form.append('formula_enable', String(payload.formula_enable));
  }
  if (payload.table_enable !== undefined) {
    form.append('table_enable', String(payload.table_enable));
  }
  if (payload.device_mode) form.append('device_mode', payload.device_mode);
  if (payload.virtual_vram !== undefined) {
    form.append('virtual_vram', String(payload.virtual_vram));
  }
  if (payload.model_source) form.append('model_source', payload.model_source);
  if (payload.server_url) form.append('server_url', payload.server_url);
  if (payload.start_page_id !== undefined) form.append('start_page_id', String(payload.start_page_id));
  if (payload.end_page_id !== undefined) form.append('end_page_id', String(payload.end_page_id));
  if (payload.return_md !== undefined) form.append('return_md', String(payload.return_md));
  if (payload.return_middle_json !== undefined) form.append('return_middle_json', String(payload.return_middle_json));
  if (payload.return_model_output !== undefined) form.append('return_model_output', String(payload.return_model_output));
  if (payload.return_content_list !== undefined) form.append('return_content_list', String(payload.return_content_list));
  if (payload.return_images !== undefined) form.append('return_images', String(payload.return_images));
  if (payload.return_orig_pdf !== undefined) form.append('return_orig_pdf', String(payload.return_orig_pdf));
  if (payload.return_html !== undefined) form.append('return_html', String(payload.return_html));
  if (payload.return_docx !== undefined) form.append('return_docx', String(payload.return_docx));
  if (payload.return_latex !== undefined) form.append('return_latex', String(payload.return_latex));

  const response = await client.post('/tasks', form, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
  return response.data;
}

export async function fetchTasks() {
  const response = await client.get('/tasks');
  return response.data;
}

export async function fetchTask(taskId: string, includeContent = true) {
  const response = await client.get(`/tasks/${taskId}`, {
    params: { include_content: includeContent }
  });
  return response.data;
}

export function getArtifactUrl(taskId: string, relativePath: string) {
  const base = resolveApiBase() ?? '';
  const formatted = relativePath.replace(/^\//, '');
  return appendScopeParams(`${base}/tasks/${taskId}/artifacts/${formatted}`);
}

export function getArtifactDataUrl(taskId: string, relativePath: string) {
  const base = resolveApiBase() ?? '';
  const formatted = relativePath.replace(/^\//, '');
  const encoded = encodeURIComponent(formatted);
  return appendScopeParams(`${base}/tasks/${taskId}/artifact-bytes?path=${encoded}`);
}

export async function retryTask(taskId: string) {
  const response = await client.post(`/tasks/${taskId}/retry`);
  return response.data;
}

export interface MineruSettings {
  backend: string;
  parse_method: string;
  model_source: string | null;
  device_mode: string | null;
  virtual_vram: number | null;
  server_url: string | null;
  default_language: string;
}

export async function fetchSettings(): Promise<MineruSettings> {
  const response = await client.get('/settings');
  return response.data;
}
