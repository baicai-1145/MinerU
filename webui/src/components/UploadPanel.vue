<template>
  <div class="panel">
    <h2 class="panel-title">上传文档</h2>
    <div class="panel-body">
      <label class="upload-box" @dragover.prevent @drop.prevent="onDrop">
        <input ref="inputRef" type="file" multiple accept=".pdf,.png,.jpg,.jpeg" @change="onSelect" />
        <span>拖拽或点击上传 PDF / 图片</span>
      </label>

      <div v-if="files.length" class="file-summary">
        <p class="file-hint">已选择 {{ files.length }} 个文件，点击“开始解析”提交。</p>
        <ul class="file-list">
          <li v-for="file in files" :key="`${file.name}-${file.lastModified}`">
            <span class="file-name">{{ file.name }}</span>
            <span class="file-size">{{ formatSize(file.size) }}</span>
          </li>
        </ul>
      </div>

      <details class="advanced" :open="showAdvanced">
        <summary @click.prevent="toggleAdvanced">
          高级配置
          <span class="summary-hint">{{ showAdvanced ? '（点击折叠）' : '（点击展开）' }}</span>
        </summary>

        <div class="advanced-grid">
          <div class="field">
            <label>语言</label>
            <select v-model="form.language">
              <option v-for="lang in languageOptions" :key="lang" :value="lang">{{ lang }}</option>
            </select>
          </div>

          <div class="field">
            <label>起始页</label>
            <input v-model="form.start_page_id" type="number" min="0" />
          </div>

          <div class="field">
            <label>结束页</label>
            <input v-model="form.end_page_id" type="number" min="0" placeholder="默认到末尾" />
          </div>

          <div class="field field-toggle">
            <label>
              <input type="checkbox" v-model="form.formula_enable" /> 公式识别
            </label>
            <label>
              <input type="checkbox" v-model="form.table_enable" /> 表格识别
            </label>
            <label>
              <input type="checkbox" v-model="form.return_images" /> 输出截图
            </label>
            <label>
              <input type="checkbox" v-model="form.return_orig_pdf" /> 输出原始 PDF
            </label>
          </div>

          <div class="field field-toggle">
            <label>
              <input type="checkbox" v-model="form.return_md" /> 输出 Markdown
            </label>
            <label>
              <input type="checkbox" v-model="form.return_middle_json" /> 输出 middle.json
            </label>
            <label>
              <input type="checkbox" v-model="form.return_content_list" /> 输出 content_list.json
            </label>
            <label>
              <input type="checkbox" v-model="form.return_model_output" /> 输出模型原始文件
            </label>
            <label>
              <input type="checkbox" v-model="form.return_html" /> 输出 HTML
            </label>
            <label>
              <input type="checkbox" v-model="form.return_docx" /> 输出 DOCX
            </label>
            <label>
              <input type="checkbox" v-model="form.return_latex" /> 输出 LaTeX
            </label>
          </div>
        </div>
      </details>

      <div class="actions">
        <button class="primary" :disabled="isUploading" @click="handleSubmit">
          {{ isUploading ? '解析中…' : '开始解析' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useUiStore } from '@/stores/uiStore';
import { fetchSettings } from '@/services/api';
import type { CreateTaskPayload } from '@/services/api';

const uiStore = useUiStore();
const inputRef = ref<HTMLInputElement | null>(null);
const files = ref<File[]>([]);
const showAdvanced = ref(false);

const form = ref({
  backend: 'vlm-http-client',
  parse_method: 'vlm',
  language: 'ch',
  formula_enable: true,
  table_enable: true,
  model_source: 'modelscope',
  device_mode: 'cuda:0',
  virtual_vram: '',
  server_url: 'http://127.0.0.1:30000',
  start_page_id: '0',
  end_page_id: '',
  return_md: true,
  return_middle_json: true,
  return_model_output: true,
  return_content_list: true,
  return_images: false,
  return_orig_pdf: true,
  return_html: true,
  return_docx: true,
  return_latex: true,
});

const languageOptions = ['ch', 'en', 'latin', 'arabic', 'korean', 'japan', 'chinese_cht'];

const emit = defineEmits<{
  (e: 'submit', payload: CreateTaskPayload): void;
}>();

const isUploading = computed(() => uiStore.isUploading);

async function loadSettings() {
  try {
    const data = await fetchSettings();
    form.value.backend = data.backend;
    form.value.parse_method = data.parse_method;
    form.value.model_source = data.model_source ?? '';
    form.value.device_mode = data.device_mode ?? '';
    form.value.virtual_vram = data.virtual_vram !== null ? String(data.virtual_vram) : '';
    form.value.server_url = data.server_url ?? '';
    if (data.default_language) {
      form.value.language = data.default_language;
    }
  } catch (error) {
    console.error(error);
    uiStore.setError('加载服务器配置失败');
  }
}

onMounted(() => {
  loadSettings();
});

function toggleAdvanced() {
  showAdvanced.value = !showAdvanced.value;
}

function onSelect(event: Event) {
  const target = event.target as HTMLInputElement;
  if (target.files) {
    files.value = Array.from(target.files);
  }
}

function onDrop(event: DragEvent) {
  if (event.dataTransfer?.files) {
    files.value = Array.from(event.dataTransfer.files);
  }
}

function handleSubmit() {
  if (!files.value.length) {
    uiStore.setError('请先选择文件');
    return;
  }

  const payload: CreateTaskPayload = {
    files: files.value,
    backend: form.value.backend,
    parse_method: form.value.parse_method,
    formula_enable: form.value.formula_enable,
    table_enable: form.value.table_enable,
    lang_list: form.value.language ? [form.value.language] : undefined,
    model_source: form.value.model_source || undefined,
    device_mode: form.value.device_mode || undefined,
    virtual_vram: form.value.virtual_vram ? Number(form.value.virtual_vram) : undefined,
    server_url: form.value.server_url || undefined,
    start_page_id: form.value.start_page_id !== '' ? Number(form.value.start_page_id) : undefined,
    end_page_id: form.value.end_page_id !== '' ? Number(form.value.end_page_id) : undefined,
    return_md: form.value.return_md,
    return_middle_json: form.value.return_middle_json,
    return_model_output: form.value.return_model_output,
    return_content_list: form.value.return_content_list,
    return_images: form.value.return_images,
    return_orig_pdf: form.value.return_orig_pdf,
    return_html: form.value.return_html,
    return_docx: form.value.return_docx,
    return_latex: form.value.return_latex,
  };

  if (form.value.backend !== 'pipeline') {
    payload.parse_method = 'vlm';
  }

  emit('submit', payload);
  files.value = [];
  if (inputRef.value) {
    inputRef.value.value = '';
  }
}

function formatSize(size: number): string {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}
</script>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.panel-title {
  margin: 0;
  font-size: 1rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.panel-body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.upload-box {
  border: 1px dashed var(--border-strong);
  border-radius: 0.75rem;
  padding: 1.5rem;
  text-align: center;
  color: var(--text-muted);
  background: var(--bg-hover);
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease;
}

.upload-box:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.upload-box input {
  display: none;
}

.file-summary {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--border-color);
  border-radius: 0.75rem;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.file-hint {
  margin: 0;
  color: var(--text-muted);
  font-size: 0.85rem;
}

.file-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.file-list li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.85rem;
  color: var(--text-primary);
}

.file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}

.file-size {
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.advanced {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border-color);
  border-radius: 1rem;
  padding: 1rem;
  color: var(--text-primary);
}

.advanced summary {
  cursor: pointer;
  font-weight: 600;
  letter-spacing: 0.05em;
}

.summary-hint {
  margin-left: 0.5rem;
  color: var(--text-muted);
  font-size: 0.85rem;
}

.advanced-grid {
  margin-top: 1rem;
  display: grid;
  gap: 1rem;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.field select,
.field input {
  padding: 0.6rem;
  border-radius: 0.6rem;
  border: 1px solid var(--border-color);
  background: var(--bg-hover);
  color: var(--text-primary);
}

.field .hint {
  margin: 0;
  font-size: 0.8rem;
  color: var(--text-muted);
}

.field-toggle {
  flex-direction: row;
  flex-wrap: wrap;
  gap: 0.75rem 1.5rem;
}

.field-toggle label {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.85rem;
}

.actions {
  display: flex;
  justify-content: flex-end;
}

.primary {
  padding: 0.75rem 1.5rem;
  border-radius: 999px;
  border: 1px solid var(--accent);
  background: var(--accent);
  color: var(--accent-text);
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
  box-shadow: var(--card-shadow);
}

.primary:hover:not(:disabled) {
  background: var(--accent-hover);
  transform: translateY(-1px);
}

.primary:disabled {
  cursor: not-allowed;
  opacity: 0.6;
  filter: grayscale(0.2);
}
</style>
