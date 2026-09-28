<script setup>
import { onMounted, ref } from 'vue'
import { getExplanationArtifacts } from '@/services/api'

const STATUSES = [
  { value: 'predlog', label: 'Na čekanju' },
  { value: 'prihvaceno', label: 'Prihvaćeno' },
  { value: 'prihvaceno_izmena', label: 'Prihvaćeno uz izmenu' },
  { value: 'odbaceno', label: 'Odbačeno' }
]

const status = ref('predlog')
const artifacts = ref([])
const loading = ref(false)
const error = ref('')

function modeLabel(artifact) {
  return artifact.mode === 'mode_b' ? 'Režim B' : 'Režim A'
}

function accuracyBadge(artifact) {
  if (artifact.accuracy_check_passed === 1) return { cls: 'bg-success', text: 'Provera tačnosti: prošla' }
  if (artifact.accuracy_check_passed === 0) return { cls: 'bg-danger', text: 'Provera tačnosti: nije prošla' }
  return { cls: 'bg-warning text-dark', text: 'Provera tačnosti: nije izvršena' }
}

// Backend salje datum kao "Mon, 28 Sep 2026 17:35:44 GMT", ali je u bazi
// lokalno vreme bez zone - zato UTC getteri, da se prikaze tacno vreme iz baze.
function formatDate(value) {
  const d = new Date(value)
  if (!value || Number.isNaN(d.getTime())) return value || ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getUTCDate())}.${pad(d.getUTCMonth() + 1)}.${d.getUTCFullYear()}. ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
}

async function loadArtifacts() {
  error.value = ''
  loading.value = true
  try {
    const { data } = await getExplanationArtifacts(status.value)
    artifacts.value = data
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da učitam AI objašnjenja.'
  } finally {
    loading.value = false
  }
}

onMounted(loadArtifacts)
</script>

<template>
  <div class="container py-4">
    <h2 class="page-title mb-4">AI objašnjenja</h2>

    <div class="btn-group flex-wrap mb-4" role="group">
      <template v-for="s in STATUSES" :key="s.value">
        <input
          type="radio"
          class="btn-check"
          :id="`exp-status-${s.value}`"
          :value="s.value"
          v-model="status"
          @change="loadArtifacts"
        />
        <label class="btn btn-outline-secondary" :for="`exp-status-${s.value}`">{{ s.label }}</label>
      </template>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-if="loading" class="d-flex align-items-center gap-2 text-muted">
      <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
      Učitavanje...
    </div>

    <div v-else-if="!artifacts.length" class="empty-state text-muted text-center py-5">
      <i class="fa-solid fa-inbox fa-2x mb-3 d-block"></i>
      Nema objašnjenja u ovom statusu.
    </div>

    <div v-else>
      <div
        v-for="artifact in artifacts"
        :key="artifact.id"
        class="card shadow-sm mb-3"
      >
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start">
            <div>
              <i class="fa-solid fa-lightbulb me-2 text-muted"></i>
              {{ artifact.question_text || `Pitanje #${artifact.source_question_id}` }}
            </div>
          </div>

          <div class="d-flex flex-wrap align-items-center gap-2 mt-2">
            <span class="badge bg-info text-dark">{{ modeLabel(artifact) }}</span>
            <span
              v-if="artifact.mode === 'mode_b'"
              class="badge"
              :class="accuracyBadge(artifact).cls"
            >
              {{ accuracyBadge(artifact).text }}
            </span>
            <span class="text-muted small">{{ formatDate(artifact.created_at) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-title {
  font-size: 2rem;
  font-weight: 800;
}

.empty-state {
  border: 1px dashed rgba(0, 0, 0, 0.15);
  border-radius: 0.75rem;
}
</style>
