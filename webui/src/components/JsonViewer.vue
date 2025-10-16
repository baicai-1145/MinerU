<template>
  <div class="json-viewer">
    <JsonNode :value="value" :label="label || 'root'" :depth="0" />
  </div>
</template>

<script lang="ts">
import { defineComponent, h, type VNode, type PropType } from 'vue';

type JsonPrimitive = string | number | boolean | null;
interface JsonArray extends Array<JsonValue> {}
interface JsonObject {
  [key: string]: JsonValue;
}
type JsonValue = JsonPrimitive | JsonArray | JsonObject;

function formatPrimitive(value: Exclude<JsonValue, JsonValue[] | Record<string, JsonValue>>) {
  if (typeof value === 'string') {
    return `"${value}"`;
  }
  if (value === null) {
    return 'null';
  }
  return String(value);
}

const JsonNode = defineComponent({
  name: 'JsonNode',
  props: {
    value: {
      type: null as unknown as PropType<JsonValue>,
      required: true,
    },
    label: {
      type: String,
      default: '',
    },
    depth: {
      type: Number,
      required: true,
    },
  },
  setup(props) {
    const renderChildren = (): VNode[] => {
      const nextDepth = props.depth + 1;
      if (Array.isArray(props.value)) {
        return props.value.map((item, index) =>
          h(JsonNode, {
            value: item as JsonValue,
            label: `[${index}]`,
            depth: nextDepth,
          }),
        );
      }

      if (props.value && typeof props.value === 'object') {
        return Object.entries(props.value as JsonObject).map(([key, val]) =>
          h(JsonNode, {
            value: val,
            label: key,
            depth: nextDepth,
          }),
        );
      }
      return [];
    };

    return (): VNode => {
      const value = props.value as JsonValue;
      const label = props.label || 'value';

      if (Array.isArray(value)) {
        return h(
          'details',
          { open: true, class: ['json-node', `depth-${props.depth}`] },
          [
            h('summary', `${label} · Array(${value.length})`),
            h('div', { class: 'json-children' }, renderChildren()),
          ],
        );
      }

      if (value && typeof value === 'object') {
        const entries = Object.keys(value as JsonObject).length;
        return h(
          'details',
          { open: true, class: ['json-node', `depth-${props.depth}`] },
          [
            h('summary', `${label} · Object(${entries})`),
            h('div', { class: 'json-children' }, renderChildren()),
          ],
        );
      }

      return h(
        'div',
        { class: ['json-leaf', `depth-${props.depth}`] },
        [`${label}: `, h('span', { class: 'json-value' }, formatPrimitive(value as JsonPrimitive))],
      );
    };
  },
});

export default defineComponent({
  name: 'JsonViewer',
  components: { JsonNode },
  props: {
    value: {
      type: null as unknown as PropType<JsonValue>,
      required: true,
    },
    label: {
      type: String,
      default: 'root',
    },
  },
  setup(props) {
    return () => h('div', { class: 'json-viewer-root' }, [h(JsonNode, { value: props.value as JsonValue, label: props.label, depth: 0 })]);
  },
});
</script>

<style scoped>
.json-viewer {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.85rem;
  color: var(--text-primary);
}

details {
  border-left: 2px solid rgba(255, 255, 255, 0.08);
  padding-left: 0.75rem;
  margin-left: 0.5rem;
  margin-bottom: 0.35rem;
}

summary {
  cursor: pointer;
  color: var(--info);
  outline: none;
}

.json-children {
  margin-top: 0.4rem;
  padding-left: 0.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.json-leaf {
  padding-left: 1.25rem;
  color: var(--text-muted);
}

.json-value {
  color: var(--success);
}
</style>
