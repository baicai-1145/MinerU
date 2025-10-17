<template>
  <div class="task-detail" v-if="currentTask">
    <header class="task-detail__header">
      <div>
        <h2>任务详情</h2>
        <p class="subtitle">
          {{ currentTask.task_id }} · {{ statusLabel(currentTask.status) }} · 更新时间 {{ formatTime(currentTask.updated_at) }}
        </p>
      </div>
      <div class="actions">
        <button @click="$emit('refresh', currentTask.task_id)">刷新</button>
        <button v-if="currentTask.status === 'failed'" class="warn" @click="$emit('retry', currentTask.task_id)">
          重新解析
        </button>
        <div class="download-wrapper" ref="downloadMenuRef">
          <button class="download" :disabled="isDownloading" @click.stop="toggleDownloadMenu">
            {{ isDownloading ? '准备中…' : '下载结果' }}
          </button>
          <div v-if="showDownloadMenu" class="download-menu" @click.stop>
            <button @click="handleDownload('latex')" :disabled="!canDownloadLatex || isDownloading">
              <span class="icon">Σ</span>
              <span>Latex</span>
            </button>
            <button @click="handleDownload('html')" :disabled="!canDownloadHtml || isDownloading">
              <span class="icon">&lt;/&gt;</span>
              <span>HTML</span>
            </button>
            <button @click="handleDownload('docx')" :disabled="!canDownloadDocx || isDownloading">
              <span class="icon">D</span>
              <span>DOCX</span>
            </button>
            <button @click="handleDownload('json')" :disabled="!canDownloadJson || isDownloading">
              <span class="icon">{…}</span>
              <span>JSON</span>
            </button>
            <button @click="handleDownload('markdown')" :disabled="!canDownloadMarkdown || isDownloading">
              <span class="icon">M</span>
              <span>Markdown</span>
            </button>
          </div>
        </div>
      </div>
    </header>

    <section class="section">
      <h3>结果预览</h3>
      <ResultPreview :task="currentTask" />
    </section>

    <section class="section">
      <h3>实时日志</h3>
      <LogViewer :lines="currentTask.logs" />
    </section>

    <section class="section" v-if="downloadList.length">
      <h3>输出文件</h3>
      <ul class="doc-list">
        <li v-for="file in downloadList" :key="file.path">
          <a :href="file.url" target="_blank" rel="noopener">{{ file.name }}</a>
          <span class="doc-path">{{ file.path }}</span>
        </li>
      </ul>
    </section>

    <section class="section">
      <h3>基础参数</h3>
      <pre class="json-block">{{ pretty(currentTask.params) }}</pre>
    </section>
  </div>
  <p v-else class="empty">请选择左侧任务查看详情</p>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue';
import { useTaskStore } from '@/stores/taskStore';
import { useUiStore } from '@/stores/uiStore';
import LogViewer from './LogViewer.vue';
import ResultPreview from './ResultPreview.vue';
import { getArtifactUrl } from '@/services/api';
import JSZip from 'jszip';
import { saveAs } from 'file-saver';

defineEmits<{
  (e: 'refresh', taskId: string): void;
  (e: 'retry', taskId: string): void;
}>();

const taskStore = useTaskStore();
const uiStore = useUiStore();

const currentTask = computed(() => {
  const id = taskStore.currentTaskId;
  if (!id) return null;
  return taskStore.details[id] ?? null;
});

const firstDocument = computed(() => currentTask.value?.documents?.[0] as any | null);
const docDirectory = computed(() => firstDocument.value?.directory as string | undefined);
const docName = computed(() => sanitizeFileName(firstDocument.value?.name || currentTask.value?.task_id || 'document'));
const docBaseName = computed(() => docName.value.replace(/\.[^.]+$/, ''));
const markdownContent = computed(() => firstDocument.value?.markdown ?? '');
const middleJson = computed(() => firstDocument.value?.middle_json ?? null);
const contentListJson = computed(() => firstDocument.value?.content_list ?? null);
const modelOutputJson = computed(() => firstDocument.value?.model_output ?? null);

type ArtifactFile = {
  name: string;
  path: string;
  type?: string;
};

const artifactFiles = computed<ArtifactFile[]>(() => {
  const doc = firstDocument.value as any;
  const files = Array.isArray(doc?.files) ? doc.files : [];
  return files
    .filter((file: any) => file && file.exists && file.path)
    .map((file: any) => ({
      name: file.name ?? (file.path ? String(file.path).split('/').pop() : 'artifact'),
      path: resolveArtifactPath(file.path),
      type: file.type,
    }));
});

const downloadList = computed(() => {
  const task = currentTask.value;
  if (!task) return [];
  return artifactFiles.value.map(file => ({
    ...file,
    url: getArtifactUrl(task.task_id, file.path),
  }));
});

const htmlArtifact = computed(() => artifactFiles.value.find(file => file.type === 'html') ?? null);
const docxArtifact = computed(() => artifactFiles.value.find(file => file.type === 'docx') ?? null);
const latexArtifact = computed(() => artifactFiles.value.find(file => file.type === 'latex_package') ?? null);

const imageEntries = computed(() => {
  const taskId = currentTask.value?.task_id;
  if (!taskId) return [];

  if (firstDocument.value?.images) {
    return (firstDocument.value.images as any[])
      .filter(item => item.exists)
      .map(item => ({
        name: item.name || (item.path ? item.path.split('/').pop() : 'image.jpg'),
        path: resolveArtifactPath(item.path)
      }));
  }

  const markdown = markdownContent.value || '';
  const matches = Array.from(markdown.matchAll(/!\[[^\]]*]\((?:\.\/)?(images\/[\w\-.\/%]+)\)/g)) as RegExpMatchArray[];
  const unique = Array.from(new Set(matches.map(match => match[1])));
  return unique.map(path => ({
    name: path.split('/').pop() ?? path,
    path: resolveArtifactPath(path)
  }));
});

const canDownloadMarkdown = computed(() => Boolean(markdownContent.value));
const canDownloadJson = computed(() => Boolean(middleJson.value || contentListJson.value || modelOutputJson.value));
const canDownloadHtml = computed(() => Boolean(htmlArtifact.value));
const canDownloadDocx = computed(() => Boolean(docxArtifact.value));
const canDownloadLatex = computed(() => Boolean(latexArtifact.value));

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

function pretty(value: unknown) {
  return JSON.stringify(value, null, 2);
}

const showDownloadMenu = ref(false);
const isDownloading = ref(false);
const downloadMenuRef = ref<HTMLDivElement | null>(null);

function toggleDownloadMenu() {
  if (isDownloading.value) return;
  showDownloadMenu.value = !showDownloadMenu.value;
}

function closeDownloadMenu() {
  showDownloadMenu.value = false;
}

function handleClickOutside(event: MouseEvent) {
  if (!showDownloadMenu.value) return;
  const target = event.target as Node;
  if (downloadMenuRef.value && !downloadMenuRef.value.contains(target)) {
    closeDownloadMenu();
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside);
});

onBeforeUnmount(() => {
  document.removeEventListener('click', handleClickOutside);
});

type DownloadFormat = 'markdown' | 'html' | 'docx' | 'json' | 'latex';

async function handleDownload(format: DownloadFormat) {
  if (isDownloading.value) return;
  if (!currentTask.value) return;

  try {
    isDownloading.value = true;
    if (format === 'markdown') {
      await downloadMarkdownPackage();
    } else if (format === 'html') {
      await downloadHtmlFile();
    } else if (format === 'docx') {
      await downloadDocxFile();
    } else if (format === 'json') {
      await downloadJsonBundle();
    } else if (format === 'latex') {
      await downloadLatexFile();
    }
    closeDownloadMenu();
  } catch (error) {
    console.error(error);
    uiStore.setError('下载失败，请稍后重试');
  } finally {
    isDownloading.value = false;
  }
}

function resolveArtifactPath(relativePath: string): string {
  const normalized = (relativePath ?? '').replace(/^\.\//, '');
  if (normalized.startsWith('artifacts/')) {
    return normalized;
  }
  const dir = docDirectory.value;
  if (!dir) {
    return normalized;
  }
  const trimmedDir = dir.replace(/^\.\//, '').replace(/\/$/, '');
  if (!trimmedDir) {
    return normalized;
  }
  if (normalized.startsWith(trimmedDir)) {
    return normalized;
  }
  return `${trimmedDir}/${normalized}`;
}

async function fetchArtifactBlob(path: string): Promise<Blob> {
  if (!currentTask.value) {
    throw new Error('任务未找到');
  }
  const url = getArtifactUrl(currentTask.value.task_id, path);
  const response = await fetch(url, { credentials: 'include' });
  if (!response.ok) {
    throw new Error(`拉取资源失败: ${response.status}`);
  }
  return response.blob();
}

async function downloadMarkdownPackage() {
  if (!canDownloadMarkdown.value) {
    uiStore.setError('没有可用的 Markdown 内容');
    return;
  }
  const zip = new JSZip();
  zip.file(`${docBaseName.value}.md`, markdownContent.value);
  if (imageEntries.value.length) {
    const folder = zip.folder('images');
    for (const image of imageEntries.value) {
      try {
        const blob = await fetchImageBlob(image.path);
        folder?.file(image.name, blob);
      } catch (error) {
        console.warn('下载图片失败', image.path, error);
      }
    }
  }
  const content = await zip.generateAsync({ type: 'blob' });
  saveAs(content, `${docName.value}_markdown.zip`);
}

async function downloadHtmlFile() {
  const artifact = htmlArtifact.value;
  if (!artifact) {
    uiStore.setError('后端未提供 HTML 文件');
    return;
  }
  const blob = await fetchArtifactBlob(artifact.path);
  saveAs(blob, artifact.name || `${docBaseName.value}.html`);
}

async function downloadDocxFile() {
  const artifact = docxArtifact.value;
  if (!artifact) {
    uiStore.setError('后端未提供 DOCX 文件');
    return;
  }
  const blob = await fetchArtifactBlob(artifact.path);
  saveAs(blob, artifact.name || `${docBaseName.value}.docx`);
}

async function downloadJsonBundle() {
  if (!canDownloadJson.value) {
    uiStore.setError('没有可用的 JSON 数据');
    return;
  }
  const zip = new JSZip();
  if (middleJson.value) {
    zip.file(`${docBaseName.value}_middle.json`, JSON.stringify(middleJson.value, null, 2));
  }
  if (contentListJson.value) {
    zip.file(`${docBaseName.value}_content_list.json`, JSON.stringify(contentListJson.value, null, 2));
  }
  if (modelOutputJson.value) {
    zip.file(`${docBaseName.value}_model_output.json`, JSON.stringify(modelOutputJson.value, null, 2));
  }
  const blob = await zip.generateAsync({ type: 'blob' });
  saveAs(blob, `${docBaseName.value}_json.zip`);
}

async function downloadLatexFile() {
  const artifact = latexArtifact.value;
  if (!artifact) {
    uiStore.setError('后端未提供 LaTeX 文件');
    return;
  }
  const blob = await fetchArtifactBlob(artifact.path);
  saveAs(blob, artifact.name || `${docBaseName.value}_latex.zip`);
}

function sanitizeFileName(name: string): string {
  return name.replace(/[^a-zA-Z0-9._-]/g, '_');
}

async function fetchImageBlob(src: string): Promise<Blob> {
  if (src.startsWith('data:')) {
    const response = await fetch(src);
    return response.blob();
  }

  const taskId = currentTask.value?.task_id;
  if (!taskId) {
    throw new Error('任务未找到');
  }

  // try artifact path resolution first
  const isAbsolute = /^https?:\/\//i.test(src);
  if (!isAbsolute) {
    const artifactPath = resolveArtifactPath(src);
    return fetchArtifactBlob(artifactPath);
  }

  const artifactMatch = src.match(/\/tasks\/([^/]+)\/artifacts\/(.+)$/);
  if (artifactMatch) {
    const [, remoteTaskId, encodedPath] = artifactMatch;
    if (!remoteTaskId || remoteTaskId !== taskId) {
      const response = await fetch(src, { credentials: 'include' });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.blob();
    }
    const artifactPath = decodeURIComponent(encodedPath);
    return fetchArtifactBlob(artifactPath);
  }

  const response = await fetch(src, { credentials: 'include' });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.blob();
}

</script>

<style scoped>
.task-detail {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.task-detail__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
}

.task-detail__header h2 {
  margin: 0;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.subtitle {
  margin: 0.25rem 0 0;
  color: var(--text-muted);
  font-size: 0.85rem;
}

.actions {
  display: flex;
  gap: 0.75rem;
  align-items: center;
}

.actions button {
  padding: 0.5rem 1rem;
  border-radius: 999px;
  border: 1px solid var(--border-color);
  background: transparent;
  color: var(--text-primary);
  cursor: pointer;
}

.actions button.download {
  background: var(--accent);
  color: var(--accent-text);
  border: none;
}

.actions button.download:disabled {
  opacity: 0.75;
  cursor: wait;
}

.download-wrapper {
  position: relative;
}

.download-menu {
  position: absolute;
  right: 0;
  top: calc(100% + 0.5rem);
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: 0.75rem;
  box-shadow: var(--card-shadow);
  display: flex;
  flex-direction: column;
  padding: 0.5rem 0;
  min-width: 160px;
  z-index: 10;
}

.download-menu button {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.55rem 1rem;
  background: transparent;
  border: none;
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
}

.download-menu button:hover:not(:disabled) {
  background: var(--bg-hover);
}

.download-menu button:disabled {
  cursor: not-allowed;
  color: var(--text-muted);
}

.download-menu .icon {
  font-weight: 600;
  width: 1.5rem;
  text-align: center;
}

.actions button.warn {
  border-color: var(--danger);
  color: var(--danger);
}

.actions button.warn:hover {
  background: var(--danger);
  color: #fff;
}

.section {
  background: var(--bg-hover);
  border: 1px solid var(--border-color);
  border-radius: 0.75rem;
  padding: 1rem 1.25rem;
}

.section h3 {
  margin: 0 0 0.75rem;
  font-size: 0.95rem;
  color: var(--text-primary);
}

.json-block {
  margin: 0;
  white-space: pre-wrap;
  font-size: 0.85rem;
  line-height: 1.5;
  color: var(--text-muted);
}

.doc-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.doc-path {
  display: block;
  color: var(--text-muted);
  font-size: 0.8rem;
}

.empty {
  text-align: center;
  color: var(--text-muted);
}
</style>
