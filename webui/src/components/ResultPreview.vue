<template>
  <div class="preview">
    <div class="tab-bar">
      <nav class="tabs">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          :class="['tab', { active: activeTab === tab.key }]"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </nav>
      <button
        v-if="(pdfUrl || imageList.length) && activeTab === 'markdown'"
        class="split-toggle"
        @click="toggleSplit"
      >
        {{ splitMode ? '退出双栏预览' : '双栏预览' }}
      </button>
    </div>

    <div class="tab-content" v-if="activeTab === 'markdown'">
      <template v-if="splitMode">
        <div class="split-container">
          <div class="pdf-pane">
            <template v-if="pdfLoading">
              <p class="empty">PDF 加载中…</p>
            </template>
            <template v-else-if="pdfError">
              <p class="empty">{{ pdfError }}</p>
            </template>
            <template v-else-if="pdfData">
              <PdfViewer :data="pdfData" />
            </template>
            <template v-else-if="imageList.length">
              <div class="image-stack">
                <img
                  v-for="image in imageList"
                  :key="image.path"
                  :src="image.url"
                  :alt="image.name"
                  loading="lazy"
                  decoding="async"
                />
              </div>
            </template>
            <p v-else class="empty">未找到预览 PDF，可在输出配置中勾选留存原始 PDF。</p>
          </div>
          <div class="markdown-pane">
            <div v-if="markdownHtml" class="markdown" v-html="markdownHtml" />
            <p v-else class="empty">暂未生成 Markdown 内容。</p>
          </div>
        </div>
      </template>
      <template v-else>
        <div v-if="markdownHtml" class="markdown" v-html="markdownHtml" />
        <p v-else class="empty">暂未生成 Markdown 内容。</p>
      </template>
    </div>

    <div class="tab-content" v-else-if="activeTab === 'contentList'">
      <JsonViewer v-if="contentList" :value="contentList" label="content_list" />
      <p v-else class="empty">暂无 Content List。</p>
    </div>

    <div class="tab-content" v-else-if="activeTab === 'middleJson'">
      <JsonViewer v-if="middleJson" :value="middleJson" label="middle_json" />
      <p v-else class="empty">暂无 middle.json。</p>
    </div>

    <div class="tab-content" v-else-if="activeTab === 'modelOutput'">
      <JsonViewer v-if="modelOutput" :value="modelOutput" label="model_output" />
      <p v-else class="empty">暂无模型原始输出。</p>
    </div>

    <div class="tab-content" v-else-if="activeTab === 'images'">
      <div v-if="imageList.length" class="image-grid">
        <figure v-for="image in imageList" :key="image.path" class="image-card">
          <img :src="image.url" :alt="image.name" loading="lazy" decoding="async" />
          <figcaption>{{ image.name }}</figcaption>
        </figure>
      </div>
      <p v-else class="empty">暂无图片输出。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue';
import MarkdownIt from 'markdown-it';
import MarkdownItContainer from 'markdown-it-container';
import MarkdownItHighlight from 'markdown-it-highlightjs';
import MarkdownItMathjax from 'markdown-it-mathjax3';
import MarkdownItMultiMdTable from 'markdown-it-multimd-table';
import hljs from 'highlight.js';
import 'highlight.js/styles/github-dark.css';
import 'katex/dist/katex.min.css';
import type { TaskDetail } from '@/stores/taskStore';
import { getArtifactUrl, getArtifactDataUrl } from '@/services/api';
import JsonViewer from './JsonViewer.vue';
import PdfViewer from './PdfViewer.vue';

const pdfDataCache = new Map<string, Uint8Array>();

type TabKey = 'markdown' | 'contentList' | 'middleJson' | 'modelOutput' | 'images';

const props = defineProps<{
  task: TaskDetail | null;
}>();

const md = new MarkdownIt({
  html: true,
  linkify: true,
  breaks: true,
  highlight(code: string, lang?: string) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(code, { language: lang, ignoreIllegals: true }).value}</code></pre>`;
      } catch (err) {
        console.warn('highlight failed', err);
      }
    }
    const safe = MarkdownIt().utils.escapeHtml(code);
    return `<pre class="hljs"><code>${safe}</code></pre>`;
  },
});

md.use(MarkdownItHighlight, { auto: true, code: true });
md.use(MarkdownItMathjax, {
  tex: {
    inlineMath: [['$', '$'], ['\\(', '\\)']],
    displayMath: [['$$', '$$'], ['\\[', '\\]']],
  },
});
md.use(MarkdownItMultiMdTable, {
  multiline: true,
  rowspan: true,
  headerless: true,
});
['info', 'warning', 'success', 'tip'].forEach(type => md.use(MarkdownItContainer, type));
const activeTab = ref<TabKey>('markdown');

const firstDocument = computed(() => props.task?.documents?.[0] as any | undefined);
const docDirectory = computed(() => firstDocument.value?.directory as string | undefined);
const pdfRelativePath = computed(() => {
  const doc = firstDocument.value;
  if (!doc) return null;
  const files = Array.isArray(doc.files) ? (doc.files as Array<any>) : [];

  const preferredTypes = ['origin_pdf', 'layout_pdf'];
  for (const type of preferredTypes) {
    const match = files.find(file => file.type === type && file.exists && typeof file.path === 'string');
    if (match) {
      return match.path as string;
    }
  }

  const generic = files.find(file => typeof file.path === 'string' && file.path.endsWith('.pdf') && file.exists);
  return generic?.path ?? null;
});

const markdownHtml = computed(() => {
  const content = firstDocument.value?.markdown ?? '';
  if (!content) return '';
  const rewritten = rewriteImageLinks(content);
  return md.render(rewritten);
});

const contentList = computed(() => firstDocument.value?.content_list ?? null);
const middleJson = computed(() => firstDocument.value?.middle_json ?? null);
const modelOutput = computed(() => firstDocument.value?.model_output ?? null);
const pdfUrl = computed(() => {
  if (!pdfRelativePath.value || !props.task?.task_id) {
    return null;
  }
  return getArtifactUrl(props.task.task_id, resolveArtifactPath(pdfRelativePath.value));
});

const pdfDataUrl = computed(() => {
  if (!pdfRelativePath.value || !props.task?.task_id) {
    return null;
  }
  return getArtifactDataUrl(props.task.task_id, resolveArtifactPath(pdfRelativePath.value));
});

const pdfData = ref<Uint8Array | null>(null);
const pdfLoading = ref(false);
const pdfError = ref<string | null>(null);
let pdfAbortController: AbortController | null = null;

const imageList = computed(() => {
  if (!props.task?.task_id) {
    return [];
  }

  const taskId = props.task.task_id;
  if (firstDocument.value?.images) {
    return (firstDocument.value.images as any[])
      .filter(item => item.exists)
      .map(item => ({
        name: item.name,
        path: resolveArtifactPath(item.path),
        url: getArtifactUrl(taskId, resolveArtifactPath(item.path)),
      }));
  }

  const markdown = firstDocument.value?.markdown ?? '';
  const matches = Array.from(markdown.matchAll(/!\[[^\]]*\]\((?:\.\/)?(images\/[\w\-.\/%]+)\)/g)) as RegExpMatchArray[];
  const uniquePaths = Array.from(new Set(matches.map(match => match[1])));
  return uniquePaths.map(path => ({
    name: path.split('/').pop() ?? path,
    path: resolveArtifactPath(path),
    url: getArtifactUrl(taskId, resolveArtifactPath(path)),
  }));
});

function cancelPdfFetch() {
  if (pdfAbortController) {
    pdfAbortController.abort();
    pdfAbortController = null;
  }
}

async function loadPdf() {
  const url = pdfDataUrl.value;
  if (!splitMode.value || !url) {
    cancelPdfFetch();
    pdfLoading.value = false;
    if (!splitMode.value) {
      pdfData.value = null;
    }
    return;
  }

  if (pdfDataCache.has(url)) {
    const cached = pdfDataCache.get(url)!;
    pdfData.value = new Uint8Array(cached);
    pdfError.value = null;
    pdfLoading.value = false;
    return;
  }

  cancelPdfFetch();
  const controller = new AbortController();
  pdfAbortController = controller;
  pdfLoading.value = true;
  pdfError.value = null;
  pdfData.value = null;

  try {
    const response = await fetch(url, { credentials: 'include', signal: controller.signal });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const buffer = await response.arrayBuffer();
    if (controller.signal.aborted) {
      return;
    }
    const bytes = new Uint8Array(buffer);
    pdfDataCache.set(url, bytes);
    pdfData.value = new Uint8Array(bytes);
    pdfError.value = null;
  } catch (error) {
    if ((error as any)?.name === 'AbortError') {
      return;
    }
    console.warn('Failed to fetch PDF', error);
    pdfError.value = 'PDF 加载失败，请稍后重试';
    pdfData.value = null;
  } finally {
    if (pdfAbortController === controller) {
      pdfLoading.value = false;
      pdfAbortController = null;
    }
  }
}

watch(
  () => props.task?.task_id,
  () => {
    activeTab.value = 'markdown';
    cancelPdfFetch();
    pdfData.value = null;
    pdfError.value = null;
    pdfLoading.value = false;
  }
);

const tabs = computed((): Array<{ key: TabKey; label: string }> => [
  { key: 'markdown', label: 'Markdown' },
  { key: 'contentList', label: contentList.value ? 'Content List' : 'Content List (空)' },
  { key: 'middleJson', label: middleJson.value ? 'Middle JSON' : 'Middle JSON (空)' },
  { key: 'modelOutput', label: modelOutput.value ? 'Model Output' : 'Model Output (空)' },
  { key: 'images', label: imageList.value.length ? `图片 (${imageList.value.length})` : '图片' },
]);

function rewriteImageLinks(markdownText: string): string {
  if (!props.task?.task_id) {
    return markdownText;
  }
  const taskId = props.task.task_id;
  const pattern = /!\[([^\]]*)\]\((?:\.\/)?(images\/[\w\-.\/%]+)\)/g;
  return markdownText.replace(pattern, (_match, alt: string, relPath: string) => {
    const url = getArtifactUrl(taskId, resolveArtifactPath(relPath));
    return `![${alt}](${url})`;
  });
}

function resolveArtifactPath(relativePath: string): string {
  const normalized = relativePath.replace(/^\.\//, '');
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

const splitMode = ref(false);

function toggleSplit() {
  splitMode.value = !splitMode.value;
}

watch(splitMode, value => {
  if (value) {
    void loadPdf();
  } else {
    cancelPdfFetch();
    pdfLoading.value = false;
    pdfError.value = null;
    pdfData.value = null;
  }
});

watch(activeTab, tab => {
  if (tab === 'markdown' && splitMode.value) {
    void loadPdf();
  }
});

watch(
  () => props.task?.task_id,
  () => {
    splitMode.value = false;
    cancelPdfFetch();
    pdfData.value = null;
    pdfError.value = null;
    pdfLoading.value = false;
  }
);

watch(pdfDataUrl, () => {
  if (splitMode.value) {
    void loadPdf();
  } else {
    cancelPdfFetch();
    pdfData.value = null;
    pdfError.value = null;
    pdfLoading.value = false;
  }
});

onBeforeUnmount(() => {
  cancelPdfFetch();
});

</script>

<style scoped>
.tab-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.tabs {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.tab {
  padding: 0.5rem 1.25rem;
  border: 1px solid var(--border-color);
  background: transparent;
  color: var(--text-primary);
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease;
}

.tab:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.tab.active {
  background: var(--accent);
  color: var(--accent-text);
  border-color: var(--accent);
}

.tab-content {
  border: 1px solid var(--border-color);
  border-radius: 0.75rem;
  background: var(--bg-hover);
  padding: 1rem 1.25rem;
  min-height: 220px;
}

.split-toggle {
  border-radius: 999px;
  border: 1px solid var(--border-color);
  background: transparent;
  color: var(--text-primary);
  padding: 0.45rem 1rem;
  cursor: pointer;
}

.split-toggle:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.split-container {
  display: flex;
  gap: 1rem;
  height: 70vh;
  width: 100%;
  max-width: 100%;
}

.pdf-pane,
.markdown-pane {
  flex: 1 1 0;
  overflow: auto;
  padding: 0.75rem;
  border: 1px solid var(--border-color);
  border-radius: 0.75rem;
  background: var(--bg-elevated);
  min-width: 0;
}

.image-stack {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.image-stack img {
  width: 100%;
  border-radius: 0.75rem;
  background: #0a0a0a;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.2);
}

.markdown :deep(h1),
.markdown :deep(h2),
.markdown :deep(h3) {
  color: var(--text-primary);
  margin-top: 1.2em;
}

.markdown :deep(img) {
  display: block;
  width: 100%;
  height: auto;
  border-radius: 0.75rem;
  margin: 0.75rem 0;
}

.markdown :deep(p),
.markdown :deep(li) {
  color: var(--text-primary);
  line-height: 1.6;
}

.markdown :deep(code) {
  background: rgba(255, 255, 255, 0.1);
  padding: 0.1rem 0.4rem;
  border-radius: 0.4rem;
}

.markdown :deep(a) {
  color: var(--info);
  text-decoration: underline;
}

.markdown :deep(pre) {
  background: #111;
  border-radius: 0.75rem;
  padding: 1rem;
  overflow-x: auto;
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.02);
}

.markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 1rem 0;
  font-size: 0.85rem;
}

.markdown :deep(th),
.markdown :deep(td) {
  border: 1px solid rgba(255, 255, 255, 0.1);
  padding: 0.6rem;
  text-align: left;
}

.markdown :deep(blockquote) {
  margin: 0.5rem 0;
  padding-left: 1rem;
  border-left: 3px solid var(--accent);
  color: var(--text-muted);
}

.json-block {
  margin: 0;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.85rem;
  color: var(--text-muted);
  white-space: pre-wrap;
  line-height: 1.6;
}

.image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 1rem;
}

.image-card {
  background: rgba(255, 255, 255, 0.04);
  border-radius: 0.75rem;
  padding: 0.75rem;
  border: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.image-card img {
  width: 100%;
  border-radius: 0.5rem;
  display: block;
  object-fit: contain;
  background: #0a0a0a;
  max-height: 280px;
}

.image-card figcaption {
  margin-top: 0.5rem;
  font-size: 0.8rem;
  color: var(--text-muted);
  text-align: center;
}

.empty {
  color: var(--text-muted);
  text-align: center;
}
</style>
