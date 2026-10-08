<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getAiArtifact, reviewAiArtifact } from '@/services/api'

const route = useRoute()
const router = useRouter()

const artifactId = route.params.id

const artifact = ref(null)
const loading = ref(false)
const error = ref('')
const errorStatus = ref(null)
// 403 za odlučen predlog iz otvorene serije: ponudi drugu ocenu
const secondRating = ref(false)

const scores = reactive({})
const comment = ref('')

const submitting = ref(false)
const submitError = ref('')

const showEditForm = ref(false)
const editQuestionText = ref('')
const editAnswers = ref([])
const editCorrectIndex = ref(0)

const showRejectForm = ref(false)
const rejectReason = ref('')

// Težina i Blumov nivo (v3 predlog): nastavnik ih bira NE videvši modelove;
// modelove vraća ruta tek posle odluke. Vrednosti su iste kao u backendu.
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
const reviewedDifficulty = ref('')
const reviewedBloom = ref('')

// Mogući duplikat: nastavnik potvrđuje (true) / odbacuje (false) ili ne označava ('')
const reviewedDuplicate = ref('')
const SIMILAR_SOURCE_LABELS = {
  source: 'izvorno pitanje',
  bank: 'pitanje iz banke',
  artifact: 'drugi AI predlog'
}
const hasSimilarity = computed(() => artifact.value?.max_similarity !== undefined)

function labelOf(options, value) {
  return options.find((o) => o.value === value)?.label || '—'
}

const labelsRequired = computed(() => !!artifact.value?.labels_required)
const labelsChosen = computed(() => !!reviewedDifficulty.value && !!reviewedBloom.value)
// Prihvatanje i izmena v3 predloga traže obe oznake; odbacivanje ne
const canAccept = computed(() => allScored.value && (!labelsRequired.value || labelsChosen.value))
const showLabelComparison = computed(() => {
  const a = artifact.value
  return a && a.status !== 'predlog' && (a.model_difficulty || a.reviewed_difficulty)
})

const questionTypeLabel = computed(() => {
  if (!artifact.value) return ''
  return artifact.value.question_type === 'mc' ? 'MC' : 'Otvoreno pitanje'
})

const allScored = computed(() => {
  if (!artifact.value?.rubric_criteria?.length) return false
  return artifact.value.rubric_criteria.every(
    (c) => scores[c.id] !== null && scores[c.id] !== undefined
  )
})

async function loadArtifact() {
  error.value = ''
  errorStatus.value = null
  loading.value = true
  try {
    const { data } = await getAiArtifact(artifactId)
    artifact.value = data
    for (const criterion of data.rubric_criteria || []) {
      scores[criterion.id] = null
    }
  } catch (e) {
    errorStatus.value = e?.response?.status || null
    secondRating.value = !!e?.response?.data?.second_rating
    error.value = e?.response?.data?.error || 'Ne mogu da učitam predlog.'
  } finally {
    loading.value = false
  }
}

function setScore(criterionId, value) {
  scores[criterionId] = value
}

function buildScoresPayload() {
  return Object.entries(scores).map(([rubric_definition_id, score]) => ({
    rubric_definition_id: Number(rubric_definition_id),
    score
  }))
}

function labelsPayload() {
  return {
    reviewed_difficulty: reviewedDifficulty.value || undefined,
    reviewed_bloom_level: reviewedBloom.value || undefined,
    reviewed_duplicate: reviewedDuplicate.value === '' ? undefined : reviewedDuplicate.value === 'da'
  }
}

async function acceptWithoutChange() {
  if (submitting.value) return
  submitError.value = ''
  submitting.value = true
  try {
    await reviewAiArtifact(artifactId, {
      decision: 'prihvaceno',
      comment: comment.value.trim() || undefined,
      scores: buildScoresPayload(),
      ...labelsPayload()
    })
    router.push('/ai/predlozi')
  } catch (e) {
    submitError.value = e?.response?.data?.error || 'Ne mogu da sačuvam pregled.'
    submitting.value = false
  }
}

function openEditForm() {
  submitError.value = ''
  showRejectForm.value = false
  editQuestionText.value = artifact.value.original_text?.question_text || ''
  const answers = artifact.value.original_text?.answers || []
  editAnswers.value = answers.map((a) => ({ text: a.answer_text }))
  editCorrectIndex.value = answers.findIndex((a) => a.is_correct)
  if (editCorrectIndex.value < 0) editCorrectIndex.value = 0
  showEditForm.value = true
}

function cancelEdit() {
  showEditForm.value = false
}

async function acceptWithChange() {
  if (submitting.value) return
  submitError.value = ''
  submitting.value = true
  try {
    const editedText = { question_text: editQuestionText.value.trim() }
    if (artifact.value.question_type === 'mc') {
      editedText.answers = editAnswers.value.map((a, idx) => ({
        answer_text: a.text.trim(),
        is_correct: idx === editCorrectIndex.value
      }))
    }

    await reviewAiArtifact(artifactId, {
      decision: 'prihvaceno_izmena',
      comment: comment.value.trim() || undefined,
      scores: buildScoresPayload(),
      edited_text: editedText,
      ...labelsPayload()
    })
    router.push('/ai/predlozi')
  } catch (e) {
    submitError.value = e?.response?.data?.error || 'Ne mogu da sačuvam pregled.'
    submitting.value = false
  }
}

function openRejectForm() {
  submitError.value = ''
  showEditForm.value = false
  rejectReason.value = ''
  showRejectForm.value = true
}

function cancelReject() {
  showRejectForm.value = false
}

async function reject() {
  if (submitting.value) return
  submitError.value = ''
  submitting.value = true
  try {
    await reviewAiArtifact(artifactId, {
      decision: 'odbaceno',
      comment: comment.value.trim() || undefined,
      scores: buildScoresPayload(),
      rejection_reason: rejectReason.value.trim(),
      ...labelsPayload()
    })
    router.push('/ai/predlozi')
  } catch (e) {
    submitError.value = e?.response?.data?.error || 'Ne mogu da sačuvam pregled.'
    submitting.value = false
  }
}

function goBack() {
  router.push('/ai/predlozi')
}

onMounted(loadArtifact)
</script>

<template>
  <div class="container py-4">
    <button class="btn btn-outline-secondary btn-sm mb-3" @click="goBack">
      <i class="fa-solid fa-arrow-left me-2"></i>
      Nazad na listu
    </button>

    <div v-if="loading" class="d-flex align-items-center gap-2 text-muted">
      <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
      Učitavanje...
    </div>

    <div v-else-if="error && secondRating" class="alert alert-info">
      {{ error }}
      <div class="mt-2">
        <router-link class="btn btn-primary btn-sm" :to="`/ai/druga-ocena/${artifactId}`">Oceni kao drugi ocenjivač</router-link>
      </div>
    </div>

    <div v-else-if="error" class="alert alert-danger">
      <strong v-if="errorStatus">[{{ errorStatus }}]</strong>
      {{ error }}
    </div>

    <div v-else-if="artifact">
      <h2 class="page-title mb-2">AI predlog #{{ artifact.id }}</h2>

      <div class="d-flex flex-wrap align-items-center gap-2 mb-4">
        <span class="badge bg-dark">{{ artifact.subject_name || 'Nepoznat predmet' }}</span>
        <span v-if="artifact.area_name" class="badge bg-secondary">{{ artifact.area_name }}</span>
        <span class="badge bg-info text-dark">{{ questionTypeLabel }}</span>
        <!-- Mogući duplikat (sličnost teksta; ne otkriva model) -->
        <span
          v-if="artifact.possible_duplicate"
          class="badge bg-warning text-dark"
          :title="artifact.similar_source === 'artifact' ? 'Sličan drugom AI predlogu' : 'Sličan pitanju iz banke'"
        >
          <i class="fa-solid fa-clone me-1"></i>
          mogući duplikat ({{ Math.round(artifact.max_similarity * 100) }} % sa {{ artifact.similar_question_id ? '#' + artifact.similar_question_id : 'drugim predlogom' }})
        </span>
        <!-- Slepo ocenjivanje: model i vreme generisanja se ne prikazuju dok je predlog u statusu 'predlog' -->
        <template v-if="artifact.status !== 'predlog'">
          <span v-if="artifact.model_name" class="badge bg-light text-dark border">{{ artifact.provider }} / {{ artifact.model_name }}</span>
          <span v-if="artifact.created_at" class="text-muted small">{{ artifact.created_at }}</span>
        </template>
      </div>

      <div class="row g-3 mb-4">
        <div class="col-12 col-lg-6">
          <div class="card shadow-sm h-100">
            <div class="card-header bg-white">
              <i class="fa-solid fa-file-lines me-2 text-muted"></i>
              Originalno pitanje
            </div>
            <div class="card-body">
              <!-- Predlog iz skupa pitanja testa (tačka J): sva ulazna pitanja -->
              <ol v-if="artifact.input_questions?.length" class="mb-0 ps-3">
                <li v-for="q in artifact.input_questions" :key="q.id" class="mb-1">{{ q.question_text }}</li>
              </ol>
              <p v-else class="mb-3">{{ artifact.source_question_text }}</p>

              <div v-if="artifact.source_answers?.length && !artifact.input_questions?.length">
                <div
                  v-for="(a, idx) in artifact.source_answers"
                  :key="idx"
                  class="d-flex justify-content-between align-items-center border rounded p-2 mb-2"
                >
                  <span>{{ a.answer_text }}</span>
                  <span v-if="a.is_correct" class="badge bg-success">Tačan</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="col-12 col-lg-6">
          <div class="card shadow-sm h-100">
            <div class="card-header bg-primary bg-opacity-10">
              <i class="fa-solid fa-wand-magic-sparkles me-2 text-primary"></i>
              AI predlog
            </div>
            <div class="card-body">
              <p class="mb-3">{{ artifact.original_text?.question_text }}</p>

              <div v-if="artifact.original_text?.answers?.length">
                <div
                  v-for="(a, idx) in artifact.original_text.answers"
                  :key="idx"
                  class="d-flex justify-content-between align-items-center border rounded p-2 mb-2"
                >
                  <span>{{ a.answer_text }}</span>
                  <span v-if="a.is_correct" class="badge bg-success">Tačan</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="hasSimilarity" class="card shadow-sm mb-4" :class="artifact.possible_duplicate ? 'border-warning' : ''">
        <div class="card-header bg-white">
          <i class="fa-solid fa-clone me-2 text-muted"></i>
          Najsličnije postojeće pitanje
          <span class="text-muted small ms-2">
            {{ Math.round(artifact.max_similarity * 100) }} % -
            {{ SIMILAR_SOURCE_LABELS[artifact.similar_source] || artifact.similar_source }}
            <template v-if="artifact.similar_question_id">#{{ artifact.similar_question_id }}</template>
          </span>
        </div>
        <div class="card-body">
          <p class="mb-3">{{ artifact.similar_question_text || '—' }}</p>

          <template v-if="artifact.status === 'predlog'">
            <label class="form-label d-block">Da li je predlog duplikat ovog pitanja?</label>
            <div class="btn-group" role="group">
              <input type="radio" class="btn-check" id="dup-da" value="da" v-model="reviewedDuplicate" :disabled="submitting" />
              <label class="btn btn-outline-primary" for="dup-da">Da, duplikat</label>
              <input type="radio" class="btn-check" id="dup-ne" value="ne" v-model="reviewedDuplicate" :disabled="submitting" />
              <label class="btn btn-outline-secondary" for="dup-ne">Ne</label>
              <input type="radio" class="btn-check" id="dup-none" value="" v-model="reviewedDuplicate" :disabled="submitting" />
              <label class="btn btn-outline-light text-dark border" for="dup-none">Nije označeno</label>
            </div>
            <div class="form-text">Opciono; čuva se uz odluku.</div>
          </template>
          <div v-else-if="artifact.reviewed_duplicate !== undefined" class="small">
            Nastavnik: <strong>{{ artifact.reviewed_duplicate ? 'duplikat' : 'nije duplikat' }}</strong>
          </div>
        </div>
      </div>

      <div class="card shadow-sm mb-4">
        <div class="card-header bg-white">
          <i class="fa-solid fa-list-check me-2 text-muted"></i>
          Ocena po kriterijumima rubrike
        </div>
        <div class="card-body">
          <div
            v-for="criterion in artifact.rubric_criteria"
            :key="criterion.id"
            class="d-flex flex-wrap justify-content-between align-items-center gap-2 border-bottom py-3"
          >
            <div class="fw-semibold">{{ criterion.dimension_label }}</div>

            <div class="btn-group" role="group">
              <template v-for="n in (criterion.scale_max - criterion.scale_min + 1)" :key="n">
                <input
                  type="radio"
                  class="btn-check"
                  :id="`criterion-${criterion.id}-${criterion.scale_min + n - 1}`"
                  :name="`criterion-${criterion.id}`"
                  :checked="scores[criterion.id] === criterion.scale_min + n - 1"
                  @change="setScore(criterion.id, criterion.scale_min + n - 1)"
                />
                <label
                  class="btn btn-outline-primary"
                  :for="`criterion-${criterion.id}-${criterion.scale_min + n - 1}`"
                >
                  {{ criterion.scale_min + n - 1 }}
                </label>
              </template>
            </div>
          </div>

          <div class="mt-3">
            <label class="form-label">Komentar (opciono)</label>
            <textarea v-model="comment" class="form-control" rows="3"></textarea>
          </div>
        </div>
      </div>

      <!-- Slepo ocenjivanje: nastavnik bira težinu i Blumov nivo pre nego što vidi modelove -->
      <div v-if="labelsRequired && artifact.status === 'predlog'" class="card shadow-sm mb-4">
        <div class="card-header bg-white">
          <i class="fa-solid fa-layer-group me-2 text-muted"></i>
          Težina i kognitivni nivo (tvoja procena)
        </div>
        <div class="card-body">
          <div class="row g-3">
            <div class="col-12 col-md-6">
              <label class="form-label" for="reviewed-difficulty">Težina</label>
              <select id="reviewed-difficulty" v-model="reviewedDifficulty" class="form-select" :disabled="submitting">
                <option value="">Izaberi...</option>
                <option v-for="o in DIFFICULTY_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </div>
            <div class="col-12 col-md-6">
              <label class="form-label" for="reviewed-bloom">Nivo Blumove taksonomije</label>
              <select id="reviewed-bloom" v-model="reviewedBloom" class="form-select" :disabled="submitting">
                <option value="">Izaberi...</option>
                <option v-for="o in BLOOM_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </div>
          </div>
          <div class="form-text">
            Obavezno za prihvatanje. Procena modela se prikazuje tek posle odluke.
          </div>
        </div>
      </div>

      <div v-if="showLabelComparison" class="card shadow-sm mb-4">
        <div class="card-header bg-white">
          <i class="fa-solid fa-layer-group me-2 text-muted"></i>
          Težina i kognitivni nivo
        </div>
        <div class="card-body">
          <table class="table table-sm mb-0">
            <thead>
              <tr>
                <th></th>
                <th>Nastavnik</th>
                <th>Model</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th class="fw-semibold">Težina</th>
                <td>{{ labelOf(DIFFICULTY_OPTIONS, artifact.reviewed_difficulty) }}</td>
                <td>{{ labelOf(DIFFICULTY_OPTIONS, artifact.model_difficulty) }}</td>
              </tr>
              <tr>
                <th class="fw-semibold">Blumov nivo</th>
                <td>{{ labelOf(BLOOM_OPTIONS, artifact.reviewed_bloom_level) }}</td>
                <td>{{ labelOf(BLOOM_OPTIONS, artifact.model_bloom_level) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="showEditForm" class="card shadow-sm mb-4">
        <div class="card-header bg-warning bg-opacity-25">
          <i class="fa-solid fa-pen me-2"></i>
          Izmena pitanja pre prihvatanja
        </div>
        <div class="card-body">
          <div class="mb-3">
            <label class="form-label">Tekst pitanja</label>
            <textarea v-model="editQuestionText" class="form-control" rows="3"></textarea>
          </div>

          <div v-if="artifact.question_type === 'mc'" class="mb-2">
            <label class="form-label d-block">Odgovori (izaberi tačan)</label>

            <div
              v-for="(a, idx) in editAnswers"
              :key="idx"
              class="d-flex align-items-center gap-2 mb-2"
            >
              <input
                type="radio"
                class="form-check-input mt-0"
                :checked="editCorrectIndex === idx"
                @change="editCorrectIndex = idx"
              />
              <input v-model="a.text" class="form-control" :placeholder="`Odgovor ${idx + 1}`" />
            </div>
          </div>

          <div class="d-flex gap-2 mt-3">
            <button class="btn btn-secondary btn-sm" :disabled="submitting" @click="cancelEdit">
              Otkaži izmenu
            </button>
          </div>
        </div>
      </div>

      <div v-if="showRejectForm" class="card shadow-sm mb-4">
        <div class="card-header bg-danger bg-opacity-25">
          <i class="fa-solid fa-xmark me-2"></i>
          Razlog odbijanja
        </div>
        <div class="card-body">
          <div class="mb-2">
            <label class="form-label">Zašto se predlog odbija? (obavezno)</label>
            <textarea v-model="rejectReason" class="form-control" rows="3"></textarea>
          </div>

          <div class="d-flex gap-2 mt-3">
            <button class="btn btn-secondary btn-sm" :disabled="submitting" @click="cancelReject">
              Otkaži
            </button>
          </div>
        </div>
      </div>

      <div class="card shadow-sm">
        <div class="card-body">
          <div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

          <div v-if="!allScored" class="text-muted small mb-2">
            Oceni sve kriterijume rubrike da bi mogao da doneseš odluku.
          </div>
          <div v-else-if="!canAccept" class="text-muted small mb-2">
            Izaberi težinu i nivo Blumove taksonomije da bi mogao da prihvatiš predlog.
          </div>

          <div class="d-flex flex-wrap gap-2">
            <button
              class="btn btn-success"
              :disabled="!canAccept || submitting"
              @click="acceptWithoutChange"
            >
              <span v-if="submitting" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
              <i v-else class="fa-solid fa-check me-2"></i>
              {{ submitting ? 'Čuvam...' : 'Prihvati bez izmene' }}
            </button>

            <button
              v-if="!showEditForm"
              class="btn btn-outline-primary"
              :disabled="!canAccept || submitting"
              @click="openEditForm"
            >
              <i class="fa-solid fa-pen me-2"></i>
              Prihvati uz izmenu
            </button>

            <button
              v-else
              class="btn btn-primary"
              :disabled="!canAccept || submitting"
              @click="acceptWithChange"
            >
              <span v-if="submitting" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
              <i v-else class="fa-solid fa-check me-2"></i>
              {{ submitting ? 'Čuvam...' : 'Sačuvaj sa izmenom' }}
            </button>

            <button
              v-if="!showRejectForm"
              class="btn btn-outline-danger"
              :disabled="!allScored || submitting"
              @click="openRejectForm"
            >
              <i class="fa-solid fa-xmark me-2"></i>
              Odbaci
            </button>

            <button
              v-else
              class="btn btn-danger"
              :disabled="!allScored || submitting || !rejectReason.trim()"
              @click="reject"
            >
              <span v-if="submitting" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
              <i v-else class="fa-solid fa-xmark me-2"></i>
              {{ submitting ? 'Čuvam...' : 'Potvrdi odbijanje' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
</style>