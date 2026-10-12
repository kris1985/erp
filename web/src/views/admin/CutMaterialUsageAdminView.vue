<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">裁断用料</h1>
      </div>
    </header>
    <div class="admin-card">
      <CutMaterialUsagePanel :show-title="false" />
    </div>
  </div>
</template>

<script setup lang="ts">
import CutMaterialUsagePanel from '@/views/admin/CutMaterialUsagePanel.vue'
</script>
