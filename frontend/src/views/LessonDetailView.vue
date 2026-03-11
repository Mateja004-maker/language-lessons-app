<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/services/api'

const route = useRoute()
const lesson = ref(null)
const error = ref('')

onMounted(async () => {
  try {
    const { data } = await api.get(`/lessons/${route.params.id}`)
    lesson.value = data
  } catch (e) {
    error.value = e?.response?.data?.error || 'Failed to load lesson'
  }
})
</script>

<template>
  <div style="max-width:900px;margin:30px auto;">
    <p v-if="error" style="color:#b00020">{{ error }}</p>

    <div v-else-if="lesson">
      <h2>{{ lesson.title }} ({{ lesson.level }})</h2>
      <div v-html="lesson.content_html" style="margin-top:12px;"></div>
    </div>

    <p v-else>Loading...</p>
  </div>
</template>