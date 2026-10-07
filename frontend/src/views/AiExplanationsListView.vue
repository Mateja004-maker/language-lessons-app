<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getExplanationArtifacts } from '@/services/api'
import { formatDbDate } from '@/services/explanationHelpers'

const router = useRouter()

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

function openArtifact(artifact) {
  router.push(`/ai/objasnjenja/${artifact.id}`)
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
        class="card shadow-sm mb-3 artifact-card"
        @click="openArtifact(artifact)"
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
            <!-- Slepo ocenjivanje: vreme generisanja se ne prikazuje dok je predlog u statusu 'predlog' -->
            <span v-if="artifact.status !== 'predlog' && artifact.created_at" class="text-muted small">{{ formatDbDate(artifact.created_at) }}</span>
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

.artifact-card {
  cursor: pointer;
  transition: box-shadow 0.15s ease, transform 0.15s ease;
}

.artifact-card:hover {
  box-shadow: 0 0.5rem 1rem rgba(0, 0, 0, 0.1) !important;
  transform: translateY(-1px);
}

.empty-state {
  border: 1px dashed rgba(0, 0, 0, 0.15);
  border-radius: 0.75rem;
}
</style>
