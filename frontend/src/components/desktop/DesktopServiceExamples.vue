<template>
  <aside class="service-examples" aria-label="远程服务地址示例">
    <div class="service-examples-heading">
      <span>地址示例</span>
      <small>仅供参考，客户环境请填写自己的地址</small>
    </div>
    <div class="service-example-list">
      <div v-for="example in examples" :key="example.title" class="service-example">
        <span class="service-example-dot" :class="example.tone" aria-hidden="true" />
        <div class="service-example-body">
          <div class="service-example-title">
            <strong>{{ example.title }}</strong>
            <span class="service-example-capability">{{ example.capability }}</span>
          </div>
          <code>{{ example.url }}</code>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
interface ServiceExample {
  title: string
  capability: string
  url: string
  tone: 'blue' | 'teal'
}

const examples: ServiceExample[] = [
  {
    title: '完整 Control Plane',
    capability: 'Builder + Code',
    url: 'https://om-demo.dfy.definesys.cn',
    tone: 'blue',
  },
  {
    title: '独立 aPaaS Builder',
    capability: '仅 Builder',
    url: 'https://om-demo.dfy.definesys.cn/builder-standalone',
    tone: 'teal',
  },
]
</script>

<style scoped>
.service-examples {
  margin-top: 12px;
  padding: 11px 12px 12px;
  border: 1px solid color-mix(in srgb, var(--line, #e5e6eb) 78%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--surface-2, #f7f8fa) 70%, transparent);
}

.service-examples-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  color: var(--text-2, #4e5969);
  font-size: 11px;
  line-height: 16px;
}

.service-examples-heading span {
  font-weight: 650;
}

.service-examples-heading small {
  color: var(--text-3, #86909c);
  font-size: 10px;
}

.service-example-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 8px;
}

.service-example {
  min-width: 0;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 9px 10px;
  border: 1px solid var(--line, #e5e6eb);
  border-radius: 6px;
  background: var(--surface, #fff);
}

.service-example-dot {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  margin-top: 4px;
  border-radius: 50%;
}

.service-example-dot.blue { background: #3b82f6; }
.service-example-dot.teal { background: #0f9f9a; }

.service-example-body {
  min-width: 0;
  flex: 1 1 auto;
}

.service-example-title {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
  color: var(--text, #1f2329);
  font-size: 12px;
  line-height: 17px;
}

.service-example-title strong {
  min-width: 0;
  overflow-wrap: anywhere;
  font-weight: 600;
}

.service-example-capability {
  flex: 0 0 auto;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--surface-2, #f2f3f5);
  color: var(--text-3, #86909c);
  font-size: 10px;
  line-height: 15px;
}

.service-example code {
  display: block;
  margin-top: 3px;
  max-width: 100%;
  color: var(--text-3, #86909c);
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 10px;
  line-height: 15px;
  overflow-wrap: anywhere;
  word-break: break-word;
  white-space: normal;
}

@media (max-width: 620px) {
  .service-examples-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 1px;
  }

  .service-example-list {
    grid-template-columns: 1fr;
  }
}
</style>
