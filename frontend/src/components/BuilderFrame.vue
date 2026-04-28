<template>
  <WorkbenchShell>
    <section class="builder-view">
      <BuilderTopBar :breadcrumbs="breadcrumbs">
        <template v-if="$slots.center" #center>
          <slot name="center" />
        </template>
        <template v-if="$slots.actions" #actions>
          <slot name="actions" />
        </template>
      </BuilderTopBar>
      <slot />
    </section>
  </WorkbenchShell>
</template>

<script setup lang="ts">
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import BuilderTopBar from '@/components/BuilderTopBar.vue'

defineProps<{
  breadcrumbs: Array<{ label: string; to?: string }>
}>()
</script>
