<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getAiArtifacts } from '@/services/api'

const router = useRouter()

const artifacts = ref([])
const loading = ref(false)
const error = ref('')

function questionTypeLabel(artifact) {
  return artifact.question_type === 'mc' ? 'MC' : 'Otvoreno pitanje'
}

async function loadArtifacts() {
  error.value = ''
  loading.value = true
  try {
    const { data } = await getAiArtifacts('predlog')
    artifacts.value = data
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da učitam AI predloge.'
  } finally {
    loading.value = false
  }
}

function openArtifact(artifact) {
  router.push(`/ai/predlozi/${artifact.id}`)
}

onMounted(loadArtifacts)
</script>

<template>
  <div class="container py-4">
    <h2 class="page-title mb-4">AI predlozi</h2>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-if="loading" class="d-flex align-items-center gap-2 text-muted">
      <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
      Učitavanje...
    </div>

    <div v-else-if="!artifacts.length" class="empty-state text-muted text-center py-5">
      <i class="fa-solid fa-inbox fa-2x mb-3 d-block"></i>
      Nema predloga na čekanju.
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
              <i class="fa-solid fa-wand-magic-sparkles me-2 text-muted"></i>
              {{ artifact.original_text?.question_text }}
            </div>
          </div>

          <div class="d-flex flex-wrap align-items-center gap-2 mt-2">
            <span class="badge bg-dark">{{ artifact.subject_name || 'Nepoznat predmet' }}</span>
            <span v-if="artifact.area_name" class="badge bg-secondary">{{ artifact.area_name }}</span>
            <span class="badge bg-info text-dark">{{ questionTypeLabel(artifact) }}</span>
            <!-- Slepo ocenjivanje: model se ne prikazuje dok je predlog u statusu 'predlog' -->
            <span v-if="artifact.status !== 'predlog' && artifact.model_name" class="badge bg-light text-dark border">{{ artifact.provider }} / {{ artifact.model_name }}</span>
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