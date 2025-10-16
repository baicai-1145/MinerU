<template>
  <div class="pdf-viewer" ref="container"></div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch, onBeforeUnmount } from 'vue';
import * as pdfjsLib from 'pdfjs-dist';
import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import 'pdfjs-dist/web/pdf_viewer.css';

pdfjsLib.GlobalWorkerOptions.workerSrc = workerSrc;

const props = defineProps<{
  url?: string | null;
  data?: Uint8Array | null;
}>();

const container = ref<HTMLDivElement | null>(null);
let cleanupFns: Array<() => void> = [];

function cleanup() {
  cleanupFns.forEach(fn => {
    try {
      fn();
    } catch (err) {
      console.warn('Failed to cleanup pdf task', err);
    }
  });
  cleanupFns = [];
  if (container.value) {
    container.value.innerHTML = '';
  }
}

async function renderPdf() {
  cleanup();
  if (!container.value) {
    return;
  }

  const source =
    props.data && props.data.byteLength
      ? { data: props.data }
      : props.url
        ? { url: props.url, withCredentials: false }
        : null;

  if (!source) {
    return;
  }

  const loadingTask = pdfjsLib.getDocument(source as any);
  cleanupFns.push(() => loadingTask.destroy());

  const pdf = await loadingTask.promise;
  const pages = pdf.numPages;

  const root = container.value;
  root.innerHTML = '';

  const scroller = document.createElement('div');
  scroller.className = 'pdf-scroller';
  root.appendChild(scroller);

  for (let pageNumber = 1; pageNumber <= pages; pageNumber += 1) {
    const pageContainer = document.createElement('div');
    pageContainer.className = 'pdf-page';
    scroller.appendChild(pageContainer);

    const canvas = document.createElement('canvas');
    pageContainer.appendChild(canvas);
    const context = canvas.getContext('2d');
    if (!context) continue;

    const page = await pdf.getPage(pageNumber);
    const viewport = page.getViewport({ scale: 1.5 });
    const outputScale = window.devicePixelRatio || 1;
    canvas.width = Math.floor(viewport.width * outputScale);
    canvas.height = Math.floor(viewport.height * outputScale);
    canvas.style.width = '100%';
    canvas.style.height = 'auto';
    const renderContext = {
      canvasContext: context,
      transform: [outputScale, 0, 0, outputScale, 0, 0],
      viewport,
    };
    const renderTask = page.render(renderContext as any);
    cleanupFns.push(() => renderTask.cancel());
    try {
      await renderTask.promise;
    } catch (err) {
      if ((err as any)?.name !== 'RenderingCancelledException') {
        console.warn('PDF render error', err);
      }
    }
  }

  root.dispatchEvent(new CustomEvent('pdf-rendered', { bubbles: true }));
}

watch(
  () => [props.url, props.data],
  () => {
    renderPdf().catch(err => console.warn('Failed to render PDF', err));
  },
  { immediate: true }
);

onMounted(() => {
  renderPdf().catch(err => console.warn('Failed to render PDF', err));
});

onBeforeUnmount(() => {
  cleanup();
});
</script>

<style scoped>
.pdf-viewer {
  width: 100%;
  height: 100%;
}

.pdf-scroller {
  width: 100%;
  height: 100%;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.pdf-page {
  display: flex;
  justify-content: center;
  background: var(--bg-elevated);
  border-radius: 0.75rem;
  padding: 0.75rem;
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.18);
}

.pdf-page canvas {
  width: 100%;
  height: auto;
  border-radius: 0.75rem;
}
</style>
