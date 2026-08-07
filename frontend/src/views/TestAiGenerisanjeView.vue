<template>
  <div class="container py-4">
    <h4>Test: AI generisanje sličnog pitanja</h4>
    <p class="text-muted">Privremeni test-ekran za /api/questions/:id/generate-similar. Nije linkovan u navbar-u.</p>

    <div class="card shadow-sm mb-3">
      <div class="card-body">
        <label class="form-label">ID postojećeg pitanja (exam_questions.id)</label>
        <input
          v-model="questionId"
          type="number"
          class="form-control mb-3"
          placeholder="npr. 60"
        />
        <button class="btn btn-primary" :disabled="loading || !questionId" @click="generate">
          {{ loading ? 'Generišem...' : 'Generiši slično pitanje' }}
        </button>
      </div>
    </div>

    <div v-if="status !== null" class="card shadow-sm">
      <div class="card-body">
        <p class="mb-2"><strong>Status:</strong> {{ status }}</p>
        <pre class="bg-light p-3 border rounded" style="white-space: pre-wrap;">{{ responseText }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { api } from '@/services/api'

const questionId = ref('')
const status = ref(null)
const responseText = ref('')
const loading = ref(false)

async function generate() {
  loading.value = true
  status.value = null
  responseText.value = ''
  try {
    const res = await api.post(`/questions/${questionId.value}/generate-similar`)
    status.value = res.status
    responseText.value = JSON.stringify(res.data, null, 2)
  } catch (e) {
    if (e.response) {
      status.value = e.response.status
      responseText.value = JSON.stringify(e.response.data, null, 2)
    } else {
      status.value = 'network error'
      responseText.value = String(e)
    }
  } finally {
    loading.value = false
  }
}
</script>
