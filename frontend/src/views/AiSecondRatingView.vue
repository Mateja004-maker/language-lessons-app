<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getSecondRatingArtifact, submitSecondRating } from '@/services/api'

// Režim "samo ocena": ista rubrika kao pri pregledu, bez dugmadi za odluku.
// Ruta ne vraća model, status/odluku, izmenu ni tuđe ocene.
const route = useRoute()
const router = useRouter()
const artifactId = route.params.id

const artifact = ref(null)
const loading = ref(false)
const error = ref('')
const scores = reactive({})
const comment = ref('')
const difficulty = ref('')
const bloomLevel = ref('')
const submitting = ref(false)
const submitError = ref('')

const DIFFICULTY_OPTIONS = [
  { value: 'lako', label: 'Lako' },
  { value: 'srednje', label: 'Srednje' },
  { value: 'tesko', label: 'Teško' }
]
const BLOOM_OPTIONS = [
  { value: 'pamcenje', label: 'Pamćenje' },
  { value: 'razumevanje', label: 'Razumevanje' },
  { value: 'primena', label: 'Primena' },
  { value: 'analiza', label: 'Analiza' },
  { value: 'vrednovanje', label: 'Vrednovanje' },
  { value: 'stvaranje', label: 'Stvaranje' }
]
const SIMILAR_SOURCE_LABELS = { source: 'izvorno pitanje', bank: 'pitanje iz banke', artifact: 'drugi AI predlog' }

const allScored = computed(() =>
  !!artifact.value?.rubric_criteria?.length &&
  artifact.value.rubric_criteria.every((c) => scores[c.id] !== null && scores[c.id] !== undefined)
)
const labelsOk = computed(() => !artifact.value?.labels_required || (!!difficulty.value && !!bloomLevel.value))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await getSecondRatingArtifact(artifactId)
    artifact.value = data
    for (const criterion of data.rubric_criteria || []) scores[criterion.id] = null
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da učitam predlog.'
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (submitting.value) return
  submitError.value = ''
  submitting.value = true
  try {
    await submitSecondRating(artifactId, {
      scores: Object.entries(scores).map(([id, score]) => ({ rubric_definition_id: Number(id), score })),
      comment: comment.value.trim() || undefined,
      difficulty: difficulty.value || undefined,
      bloom_level: bloomLevel.value || undefined
    })
    router.push({ path: '/ai/druga-ocena', query: { sacuvano: artifactId } })
  } catch (e) {
    submitError.value = e?.response?.data?.error || 'Ne mogu da sačuvam ocenu.'
    submitting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="container py-4">
    <button class="btn btn-outline-secondary btn-sm mb-3" @click="router.push('/ai/druga-ocena')">
      <i class="fa-solid fa-arrow-left me-2"></i>
      Nazad na listu
    </button>

    <div v-if="loading" class="d-flex align-items-center gap-2 text-muted">
      <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
      Učitavanje...
    </div>

    <div v-else-if="error" class="alert alert-warning">{{ error }}</div>

    <div v-else-if="artifact">
      <h2 class="page-title mb-2">Druga ocena predloga #{{ artifact.id }}</h2>
      <div class="d-flex flex-wrap align-items-center gap-2 mb-4">
        <span class="badge bg-dark">{{ artifact.subject_name || 'Nepoznat predmet' }}</span>
        <span v-if="artifact.area_name" class="badge bg-secondary">{{ artifact.area_name }}</span>
        <span class="badge bg-info text-dark">{{ artifact.question_type === 'mc' ? 'MC' : 'Otvoreno pitanje' }}</span>
        <span class="badge bg-light text-dark border">samo ocena, bez odluke</span>
      </div>

      <div class="row g-3 mb-4">
        <div class="col-12 col-lg-6">
          <div class="card shadow-sm h-100">
            <div class="card-header bg-white">Originalno pitanje</div>
            <div class="card-body">
              <ol v-if="artifact.input_questions?.length" class="mb-0 ps-3">
                <li v-for="q in artifact.input_questions" :key="q.id" class="mb-1">{{ q.question_text }}</li>
              </ol>
              <p v-else class="mb-3">{{ artifact.source_question_text }}</p>
              <div v-for="(a, idx) in (artifact.input_questions?.length ? [] : artifact.source_answers)" :key="idx"
                   class="d-flex justify-content-between align-items-center border rounded p-2 mb-2">
                <span>{{ a.answer_text }}</span>
                <span v-if="a.is_correct" class="badge bg-success">Tačan</span>
              </div>
            </div>
          </div>
        </div>
        <div class="col-12 col-lg-6">
          <div class="card shadow-sm h-100 border-primary">
            <div class="card-header bg-primary bg-opacity-10">AI predlog</div>
            <div class="card-body">
              <p class="mb-3">{{ artifact.original_text?.question_text }}</p>
              <div v-for="(a, idx) in artifact.original_text?.answers || []" :key="idx"
                   class="d-flex justify-content-between align-items-center border rounded p-2 mb-2">
                <span>{{ a.answer_text }}</span>
                <span v-if="a.is_correct" class="badge bg-success">Tačan</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="artifact.max_similarity !== undefined" class="card shadow-sm mb-4"
           :class="artifact.possible_duplicate ? 'border-warning' : ''">
        <div class="card-header bg-white">
          Najsličnije postojeće pitanje
          <span class="text-muted small ms-2">
            {{ Math.round(artifact.max_similarity * 100) }} % -
            {{ SIMILAR_SOURCE_LABELS[artifact.similar_source] || artifact.similar_source }}
            <template v-if="artifact.similar_question_id">#{{ artifact.similar_question_id }}</template>
          </span>
        </div>
        <div class="card-body">{{ artifact.similar_question_text || '—' }}</div>
      </div>

      <div class="card shadow-sm mb-4">
        <div class="card-header bg-white">Ocena po kriterijumima rubrike</div>
        <div class="card-body">
          <div v-for="criterion in artifact.rubric_criteria" :key="criterion.id"
               class="d-flex flex-wrap justify-content-between align-items-center gap-2 border-bottom py-3">
            <div class="fw-semibold">{{ criterion.dimension_label }}</div>
            <div class="btn-group" role="group">
              <template v-for="n in (criterion.scale_max - criterion.scale_min + 1)" :key="n">
                <input type="radio" class="btn-check"
                       :id="`sr-${criterion.id}-${criterion.scale_min + n - 1}`"
                       :name="`sr-${criterion.id}`"
                       :checked="scores[criterion.id] === criterion.scale_min + n - 1"
                       @change="scores[criterion.id] = criterion.scale_min + n - 1" />
                <label class="btn btn-outline-primary" :for="`sr-${criterion.id}-${criterion.scale_min + n - 1}`">
                  {{ criterion.scale_min + n - 1 }}
                </label>
              </template>
            </div>
          </div>

          <div v-if="artifact.labels_required" class="row g-3 mt-1">
            <div class="col-12 col-md-6">
              <label class="form-label" for="sr-difficulty">Težina</label>
              <select id="sr-difficulty" v-model="difficulty" class="form-select" :disabled="submitting">
                <option value="">Izaberi...</option>
                <option v-for="o in DIFFICULTY_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </div>
            <div class="col-12 col-md-6">
              <label class="form-label" for="sr-bloom">Nivo Blumove taksonomije</label>
              <select id="sr-bloom" v-model="bloomLevel" class="form-select" :disabled="submitting">
                <option value="">Izaberi...</option>
                <option v-for="o in BLOOM_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </div>
          </div>

          <div class="mt-3">
            <label class="form-label">Komentar (opciono)</label>
            <textarea v-model="comment" class="form-control" rows="3"></textarea>
          </div>
        </div>
      </div>

      <div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
      <div v-if="!allScored || !labelsOk" class="text-muted small mb-2">
        Oceni sve kriterijume{{ artifact.labels_required ? ' i izaberi težinu i nivo' : '' }} da bi sačuvao ocenu.
      </div>
      <button class="btn btn-primary" :disabled="!allScored || !labelsOk || submitting" @click="submit">
        <span v-if="submitting" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
        {{ submitting ? 'Čuvam...' : 'Sačuvaj ocenu' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.page-title {
  font-size: 2rem;
  font-weight: 800;
}
</style>
