<script setup>
// Zajedničko zaglavlje stranice: naslov levo, filteri i glavno dugme desno (slot),
// tanka linija ispod preko cele širine. Bez podnaslova. Stil: .page-header u main.css.
defineProps({
  title: { type: String, required: true }
})
</script>

<template>
  <div class="page-header">
    <h1 class="page-title">{{ title }}</h1>
    <div v-if="$slots.default" class="page-header-actions">
      <slot />
    </div>
  </div>
</template>
