<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getSubjects,
  getAreas,
  addArea,
  getBankQuestions,
  addBankQuestion,
  addQuestionAnswer,
  getQuestionAnswers,
  updateQuestion,
  deleteQuestion,
  generateSimilarQuestion,
  generateExplanation,
  getEvaluationBatches,
  MISTRAL_ENABLED
} from '@/services/api'

const route = useRoute()
const router = useRouter()
const subjectId = computed(() => Number(route.params.subjectId))

const subjectName = ref('')
const areas = ref([])
const loading = ref(false)
const error = ref('')

const showAddArea = ref(false)
const newAreaName = ref('')
const addAreaError = ref('')
const addingArea = ref(false)

const expandedAreaId = ref(null)
const questionsByArea = reactive({})
const questionsLoading = reactive({})
const questionsError = reactive({})

const showQuestionModal = ref(false)
const modalAreaId = ref(null)
const newQuestionText = ref('')
const newQuestionPoints = ref(1)
const questionModalError = ref('')
const savingQuestion = ref(false)

const questionType = ref('open')
const mcAnswers = ref([{ text: '' }, { text: '' }])
const correctIndex = ref(0)

const showEditModal = ref(false)
const editQuestionId = ref(null)
const editAreaId = ref(null)
const editQuestionText = ref('')
const editQuestionPoints = ref(1)
const editModalError = ref('')
const savingEdit = ref(false)
const editExistingAnswers = ref([])
const editAnswersLoading = ref(false)

const showGenerateModal = ref(false)
const generateQuestion = ref(null)
const generateProvider = ref('groq')
const generateError = ref('')
const generating = ref(false)
const generateBatchId = ref(null)

const showExplainModal = ref(false)
const explainQuestion = ref(null)
const explainMode = ref('mode_a')
const explainProvider = ref('groq')
const explainError = ref('')
const explaining = ref(false)
const explainResult = ref(null)
const explainBatchId = ref(null)

// Evaluacione serije (oznaka eksperimenta). Ruta ih vraca od najnovije, pa je
// podrazumevano izabrana poslednje napravljena; null = bez serije (razvojna proba).
const evaluationBatches = ref([])
const batchesLoading = ref(false)

async function loadEvaluationBatches() {
  batchesLoading.value = true
  try {
    const { data } = await getEvaluationBatches()
    evaluationBatches.value = data || []
  } catch {
    evaluationBatches.value = []
  } finally {
    batchesLoading.value = false
  }
  return evaluationBatches.value.length ? evaluationBatches.value[0].id : null
}

async function loadSubjectName() {
  try {
    const { data } = await getSubjects()
    const found = data.find((s) => s.id === subjectId.value)
    subjectName.value = found ? found.name : ''
  } catch (e) {
    subjectName.value = ''
  }
}

async function loadAreas() {
  error.value = ''
  loading.value = true
  try {
    const { data } = await getAreas(subjectId.value)
    areas.value = data
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da učitam oblasti.'
  } finally {
    loading.value = false
  }
}

function toggleAddArea() {
  showAddArea.value = !showAddArea.value
  addAreaError.value = ''
  newAreaName.value = ''
}

async function submitNewArea() {
  addAreaError.value = ''
  if (!newAreaName.value.trim()) {
    addAreaError.value = 'Naziv oblasti je obavezan.'
    return
  }

  addingArea.value = true
  try {
    await addArea(subjectId.value, { name: newAreaName.value.trim() })
    newAreaName.value = ''
    showAddArea.value = false
    await loadAreas()
  } catch (e) {
    addAreaError.value = e?.response?.data?.error || 'Ne mogu da dodam oblast.'
  } finally {
    addingArea.value = false
  }
}

async function loadQuestionsForArea(areaId) {
  questionsError[areaId] = ''
  questionsLoading[areaId] = true
  try {
    const { data } = await getBankQuestions(subjectId.value, areaId)
    questionsByArea[areaId] = data
  } catch (e) {
    questionsError[areaId] = e?.response?.data?.error || 'Ne mogu da učitam pitanja.'
  } finally {
    questionsLoading[areaId] = false
  }
}

async function toggleArea(area) {
  if (expandedAreaId.value === area.id) {
    expandedAreaId.value = null
    return
  }

  expandedAreaId.value = area.id
  if (!questionsByArea[area.id]) {
    await loadQuestionsForArea(area.id)
  }
}

function questionTypeLabel(question) {
  return question.answer_count > 0
    ? `MC (${question.answer_count} odgovora)`
    : 'Otvoreno pitanje'
}

function openQuestionModal(area) {
  modalAreaId.value = area.id
  newQuestionText.value = ''
  newQuestionPoints.value = 1
  questionModalError.value = ''
  questionType.value = 'open'
  mcAnswers.value = [{ text: '' }, { text: '' }]
  correctIndex.value = 0
  showQuestionModal.value = true
}

function closeQuestionModal() {
  showQuestionModal.value = false
}

function addAnswerRow() {
  mcAnswers.value.push({ text: '' })
}

function removeAnswerRow(index) {
  if (mcAnswers.value.length <= 2) return
  mcAnswers.value.splice(index, 1)
  if (correctIndex.value >= mcAnswers.value.length) {
    correctIndex.value = 0
  }
}

async function submitNewQuestion() {
  questionModalError.value = ''

  if (!newQuestionText.value.trim()) {
    questionModalError.value = 'Tekst pitanja je obavezan.'
    return
  }

  let answersToSave = []
  if (questionType.value === 'mc') {
    answersToSave = mcAnswers.value
      .map((a, idx) => ({ text: a.text.trim(), isCorrect: idx === correctIndex.value }))
      .filter((a) => a.text)

    if (answersToSave.length < 2) {
      questionModalError.value = 'MC pitanje mora imati bar 2 popunjena odgovora.'
      return
    }
    if (!answersToSave.some((a) => a.isCorrect)) {
      questionModalError.value = 'Izaberi tačan odgovor (ne sme biti prazan red).'
      return
    }
  }

  savingQuestion.value = true
  try {
    const { data } = await addBankQuestion(subjectId.value, {
      question_text: newQuestionText.value.trim(),
      points: newQuestionPoints.value,
      area_id: modalAreaId.value
    })

    if (questionType.value === 'mc') {
      for (const a of answersToSave) {
        await addQuestionAnswer(data.question_id, {
          answer_text: a.text,
          is_correct: a.isCorrect ? 1 : 0
        })
      }
    }

    showQuestionModal.value = false
    await loadQuestionsForArea(modalAreaId.value)
  } catch (e) {
    questionModalError.value = e?.response?.data?.error || 'Ne mogu da sačuvam pitanje.'
  } finally {
    savingQuestion.value = false
  }
}

async function openEditModal(area, question) {
  editQuestionId.value = question.id
  editAreaId.value = area.id
  editQuestionText.value = question.question_text
  editQuestionPoints.value = question.points
  editModalError.value = ''
  editExistingAnswers.value = []
  showEditModal.value = true

  if (question.answer_count > 0) {
    editAnswersLoading.value = true
    try {
      const { data } = await getQuestionAnswers(question.id)
      editExistingAnswers.value = data
    } catch (e) {
      editModalError.value = e?.response?.data?.error || 'Ne mogu da učitam odgovore.'
    } finally {
      editAnswersLoading.value = false
    }
  }
}

function closeEditModal() {
  showEditModal.value = false
}

async function submitEditQuestion() {
  editModalError.value = ''

  if (!editQuestionText.value.trim()) {
    editModalError.value = 'Tekst pitanja je obavezan.'
    return
  }

  savingEdit.value = true
  try {
    await updateQuestion(editQuestionId.value, {
      question_text: editQuestionText.value.trim(),
      points: editQuestionPoints.value
    })

    showEditModal.value = false
    await loadQuestionsForArea(editAreaId.value)
  } catch (e) {
    editModalError.value = e?.response?.data?.error || 'Ne mogu da sačuvam izmene.'
  } finally {
    savingEdit.value = false
  }
}

async function removeQuestion(area, question) {
  const confirmed = confirm('Da li si sigurna da želiš da obrišeš ovo pitanje?')
  if (!confirmed) return

  questionsError[area.id] = ''
  try {
    await deleteQuestion(question.id)
    await loadQuestionsForArea(area.id)
  } catch (e) {
    questionsError[area.id] = e?.response?.data?.error || 'Ne mogu da obrišem pitanje.'
  }
}

async function openGenerateModal(question) {
  generateQuestion.value = question
  generateProvider.value = 'groq'
  generateError.value = ''
  generateBatchId.value = null
  showGenerateModal.value = true
  generateBatchId.value = await loadEvaluationBatches()
}

function closeGenerateModal() {
  if (generating.value) return
  showGenerateModal.value = false
}

async function submitGenerate() {
  generateError.value = ''
  generating.value = true
  try {
    const { data } = await generateSimilarQuestion(generateQuestion.value.id, generateProvider.value, generateBatchId.value)
    showGenerateModal.value = false
    router.push(`/ai/predlozi/${data.artifact_id}`)
  } catch (e) {
    generateError.value = e?.response?.data?.details || e?.response?.data?.error || 'Ne mogu da pokrenem generisanje.'
  } finally {
    generating.value = false
  }
}

// Objasnjenje ima smisla samo kad postoji poznato tacno resenje (rezim A):
// MC pitanje (tacan odgovor iz exam_answers) ili pitanje sa reference_solution.
function canExplain(question) {
  return question.answer_count > 0 || question.has_reference_solution
}

// Rezim B (model sam pise Python resenje) backend odbija za MC pitanja.
function isMcQuestion(question) {
  return question?.answer_count > 0
}

async function openExplainModal(question) {
  explainQuestion.value = question
  explainMode.value = 'mode_a'
  explainProvider.value = 'groq'
  explainError.value = ''
  explainResult.value = null
  explainBatchId.value = null
  showExplainModal.value = true
  explainBatchId.value = await loadEvaluationBatches()
}

function closeExplainModal() {
  if (explaining.value) return
  showExplainModal.value = false
}

async function submitExplain() {
  explainError.value = ''
  explainResult.value = null
  explaining.value = true
  try {
    const { data } = await generateExplanation(explainQuestion.value.id, explainMode.value, explainProvider.value, explainBatchId.value)
    explainResult.value = data
  } catch (e) {
    explainError.value = e?.response?.data?.details || e?.response?.data?.error || 'Ne mogu da pokrenem generisanje objašnjenja.'
  } finally {
    explaining.value = false
  }
}

onMounted(() => {
  loadSubjectName()
  loadAreas()
})
</script>

<template>
  <div class="container py-4">
    <div class="d-flex align-items-center justify-content-between mb-4">
      <h2 class="page-title mb-0">
        Oblasti<span v-if="subjectName"> - {{ subjectName }}</span>
      </h2>

      <button class="btn btn-primary" @click="toggleAddArea">
        <i class="fa-solid fa-plus me-2"></i>
        Dodaj oblast
      </button>
    </div>

    <div v-if="showAddArea" class="card shadow-sm mb-4">
      <div class="card-body">
        <div v-if="addAreaError" class="alert alert-danger">{{ addAreaError }}</div>

        <div class="row g-2 align-items-end">
          <div class="col-12 col-md-8">
            <label class="form-label">Naziv oblasti</label>
            <input v-model="newAreaName" class="form-control" placeholder="npr. Sintaksa" />
          </div>
          <div class="col-12 col-md-4">
            <button class="btn btn-success w-100" :disabled="addingArea" @click="submitNewArea">
              <i class="fa-solid fa-check me-2"></i>
              Sačuvaj
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="loading">Učitavanje...</div>

    <div v-else-if="!areas.length" class="text-muted">
      Nema još nijedne oblasti za ovaj predmet.
    </div>

    <div v-else>
      <div v-for="area in areas" :key="area.id" class="card shadow-sm mb-3">
        <div class="card-body">
          <div class="d-flex align-items-center justify-content-between">
            <h5 class="card-title mb-0 area-name" @click="toggleArea(area)">
              <i class="fa-solid fa-layer-group me-2"></i>
              {{ area.name }}
              <i
                class="fa-solid ms-2 text-muted small"
                :class="expandedAreaId === area.id ? 'fa-chevron-up' : 'fa-chevron-down'"
              ></i>
            </h5>

            <button class="btn btn-outline-primary btn-sm" @click="openQuestionModal(area)">
              <i class="fa-solid fa-plus me-1"></i>
              Dodaj pitanje
            </button>
          </div>

          <div v-if="expandedAreaId === area.id" class="mt-3 border-top pt-3">
            <div v-if="questionsError[area.id]" class="alert alert-danger">
              {{ questionsError[area.id] }}
            </div>

            <div v-if="questionsLoading[area.id]" class="text-muted">Učitavanje pitanja...</div>

            <div v-else-if="!questionsByArea[area.id]?.length" class="text-muted">
              Nema još nijedno pitanje u ovoj oblasti.
            </div>

            <div
              v-for="q in questionsByArea[area.id]"
              :key="q.id"
              class="d-flex justify-content-between align-items-center border rounded p-2 mb-2 flex-wrap gap-2"
            >
              <div>
                <i class="fa-solid fa-circle-question me-2 text-muted"></i>
                {{ q.question_text }}
              </div>
              <div class="d-flex align-items-center gap-2">
                <span class="badge bg-dark">{{ q.points }} pts</span>
                <span class="badge bg-secondary">{{ questionTypeLabel(q) }}</span>
                <button class="btn btn-outline-info btn-sm" @click="openGenerateModal(q)">
                  <i class="fa-solid fa-wand-magic-sparkles me-1"></i>
                  Generiši slično
                </button>
                <button v-if="canExplain(q)" class="btn btn-outline-success btn-sm" @click="openExplainModal(q)">
                  <i class="fa-solid fa-lightbulb me-1"></i>
                  Generiši objašnjenje
                </button>
                <button class="btn btn-outline-warning btn-sm" @click="openEditModal(area, q)">
                  <i class="fa-solid fa-pen me-1"></i>
                  Izmeni
                </button>
                <button class="btn btn-outline-danger btn-sm" @click="removeQuestion(area, q)">
                  <i class="fa-solid fa-trash me-1"></i>
                  Obriši
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="showQuestionModal" class="question-modal-backdrop" @click.self="closeQuestionModal">
      <div class="question-modal-card">
        <h5 class="mb-3">
          <i class="fa-solid fa-circle-plus me-2"></i>
          Dodaj pitanje
        </h5>

        <div v-if="questionModalError" class="alert alert-danger">{{ questionModalError }}</div>

        <div class="mb-2">
          <label class="form-label">Tekst pitanja</label>
          <textarea v-model="newQuestionText" class="form-control" rows="3"></textarea>
        </div>

        <div class="mb-3">
          <label class="form-label">Poeni</label>
          <input v-model="newQuestionPoints" type="number" min="1" class="form-control" />
        </div>

        <div class="mb-3">
          <label class="form-label d-block">Tip pitanja</label>
          <div class="form-check form-check-inline">
            <input
              id="type-open"
              v-model="questionType"
              class="form-check-input"
              type="radio"
              value="open"
            />
            <label class="form-check-label" for="type-open">Otvoreno</label>
          </div>
          <div class="form-check form-check-inline">
            <input
              id="type-mc"
              v-model="questionType"
              class="form-check-input"
              type="radio"
              value="mc"
            />
            <label class="form-check-label" for="type-mc">Višestruki izbor (MC)</label>
          </div>
        </div>

        <div v-if="questionType === 'mc'" class="mb-3">
          <label class="form-label">Odgovori (izaberi tačan)</label>

          <div
            v-for="(answer, index) in mcAnswers"
            :key="index"
            class="d-flex align-items-center gap-2 mb-2"
          >
            <input
              type="radio"
              class="form-check-input mt-0"
              :checked="correctIndex === index"
              @change="correctIndex = index"
            />
            <input
              v-model="answer.text"
              class="form-control"
              :placeholder="`Odgovor ${index + 1}`"
            />
            <button
              class="btn btn-outline-danger btn-sm"
              :disabled="mcAnswers.length <= 2"
              @click="removeAnswerRow(index)"
            >
              <i class="fa-solid fa-xmark"></i>
            </button>
          </div>

          <button class="btn btn-outline-secondary btn-sm" @click="addAnswerRow">
            <i class="fa-solid fa-plus me-1"></i>
            Dodaj odgovor
          </button>
        </div>

        <div class="d-flex justify-content-end gap-2">
          <button class="btn btn-secondary" @click="closeQuestionModal">Otkaži</button>
          <button class="btn btn-success" :disabled="savingQuestion" @click="submitNewQuestion">
            <i class="fa-solid fa-check me-2"></i>
            Sačuvaj
          </button>
        </div>
      </div>
    </div>

    <div v-if="showEditModal" class="question-modal-backdrop" @click.self="closeEditModal">
      <div class="question-modal-card">
        <h5 class="mb-3">
          <i class="fa-solid fa-pen me-2"></i>
          Izmeni pitanje
        </h5>

        <div v-if="editModalError" class="alert alert-danger">{{ editModalError }}</div>

        <div class="mb-2">
          <label class="form-label">Tekst pitanja</label>
          <textarea v-model="editQuestionText" class="form-control" rows="3"></textarea>
        </div>

        <div class="mb-3">
          <label class="form-label">Poeni</label>
          <input v-model="editQuestionPoints" type="number" min="1" class="form-control" />
        </div>

        <div v-if="editAnswersLoading" class="text-muted mb-3">Učitavanje odgovora...</div>

        <div v-else-if="editExistingAnswers.length" class="mb-3">
          <label class="form-label d-block">Postojeći odgovori (samo za pregled)</label>
          <div
            v-for="a in editExistingAnswers"
            :key="a.id"
            class="d-flex justify-content-between align-items-center border rounded p-2 mb-1"
          >
            <span>{{ a.answer_text }}</span>
            <span v-if="a.is_correct" class="badge bg-success">Tačan</span>
          </div>
          <div class="text-muted small">
            Izmena odgovora nije još podržana u ovom ekranu.
          </div>
        </div>

        <div class="d-flex justify-content-end gap-2">
          <button class="btn btn-secondary" @click="closeEditModal">Otkaži</button>
          <button class="btn btn-success" :disabled="savingEdit" @click="submitEditQuestion">
            <i class="fa-solid fa-check me-2"></i>
            Sačuvaj
          </button>
        </div>
      </div>
    </div>

    <div v-if="showGenerateModal" class="question-modal-backdrop" @click.self="closeGenerateModal">
      <div class="question-modal-card">
        <h5 class="mb-3">
          <i class="fa-solid fa-wand-magic-sparkles me-2"></i>
          Generiši slično pitanje
        </h5>

        <p class="text-muted small mb-3">
          Na osnovu pitanja: "{{ generateQuestion?.question_text }}"
        </p>

        <div v-if="generateError" class="alert alert-danger">{{ generateError }}</div>

        <div class="mb-3">
          <label class="form-label d-block">Model</label>
          <div class="btn-group" role="group">
            <input type="radio" class="btn-check" id="gen-provider-groq" value="groq" v-model="generateProvider" />
            <label class="btn btn-outline-secondary" for="gen-provider-groq">groq</label>

            <input type="radio" class="btn-check" id="gen-provider-gemini" value="gemini" v-model="generateProvider" />
            <label class="btn btn-outline-secondary" for="gen-provider-gemini">gemini</label>

            <template v-if="MISTRAL_ENABLED">
              <input type="radio" class="btn-check" id="gen-provider-mistral" value="mistral" v-model="generateProvider" />
              <label class="btn btn-outline-secondary" for="gen-provider-mistral">mistral</label>
            </template>

            <input type="radio" class="btn-check" id="gen-provider-openrouter" value="openrouter" v-model="generateProvider" />
            <label class="btn btn-outline-secondary" for="gen-provider-openrouter">openrouter</label>
          </div>
        </div>

        <div class="mb-3">
          <label class="form-label" for="gen-batch">Serija (opciono)</label>
          <select id="gen-batch" v-model="generateBatchId" class="form-select" :disabled="generating">
            <option :value="null">Bez serije (razvojna proba)</option>
            <option v-for="b in evaluationBatches" :key="b.id" :value="b.id">
              #{{ b.id }} {{ b.name }}{{ b.is_final ? ' (finalna)' : '' }}
            </option>
          </select>
        </div>

        <div class="d-flex justify-content-end gap-2">
          <button class="btn btn-secondary" :disabled="generating" @click="closeGenerateModal">
            Otkaži
          </button>
          <button class="btn btn-primary" :disabled="generating || batchesLoading" @click="submitGenerate">
            <span v-if="generating" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
            <i v-else class="fa-solid fa-wand-magic-sparkles me-2"></i>
            {{ generating ? 'Generišem...' : 'Generiši' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="showExplainModal" class="question-modal-backdrop" @click.self="closeExplainModal">
      <div class="question-modal-card">
        <h5 class="mb-3">
          <i class="fa-solid fa-lightbulb me-2"></i>
          Generiši objašnjenje
        </h5>

        <p class="text-muted small mb-3">
          Pitanje: "{{ explainQuestion?.question_text }}"
        </p>

        <div v-if="explainError" class="alert alert-danger">{{ explainError }}</div>

        <div v-if="explainResult" class="alert alert-success">
          Predlog objašnjenja #{{ explainResult.artifact_id }} je sačuvan i čeka pregled nastavnika.
          <div v-if="explainResult.mode === 'mode_b'" class="small mt-1">
            Mehanička provera rešenja:
            <strong v-if="explainResult.accuracy_check_passed === 1">prošla</strong>
            <strong v-else-if="explainResult.accuracy_check_passed === 0">nije prošla</strong>
            <strong v-else>nije izvršena (nema test primera)</strong>
          </div>
        </div>

        <template v-else>
          <div class="mb-3">
            <label class="form-label d-block">Režim</label>
            <div class="btn-group" role="group">
              <input type="radio" class="btn-check" id="exp-mode-a" value="mode_a" v-model="explainMode" />
              <label class="btn btn-outline-secondary" for="exp-mode-a">A: uz poznato rešenje</label>

              <input
                type="radio"
                class="btn-check"
                id="exp-mode-b"
                value="mode_b"
                v-model="explainMode"
                :disabled="isMcQuestion(explainQuestion)"
              />
              <label class="btn btn-outline-secondary" for="exp-mode-b">B: model rešava sam</label>
            </div>
            <div v-if="isMcQuestion(explainQuestion)" class="form-text">
              Režim B nije dostupan za pitanja sa ponuđenim odgovorima.
            </div>
            <div v-else-if="explainMode === 'mode_b'" class="form-text">
              U režimu B rešenje modela se automatski izvršava nad test primerima pitanja.
            </div>
          </div>

          <div class="mb-3">
            <label class="form-label d-block">Model</label>
            <div class="btn-group" role="group">
              <input type="radio" class="btn-check" id="exp-provider-groq" value="groq" v-model="explainProvider" />
              <label class="btn btn-outline-secondary" for="exp-provider-groq">groq</label>

              <input type="radio" class="btn-check" id="exp-provider-gemini" value="gemini" v-model="explainProvider" />
              <label class="btn btn-outline-secondary" for="exp-provider-gemini">gemini</label>

              <template v-if="MISTRAL_ENABLED">
                <input type="radio" class="btn-check" id="exp-provider-mistral" value="mistral" v-model="explainProvider" />
                <label class="btn btn-outline-secondary" for="exp-provider-mistral">mistral</label>
              </template>

              <input type="radio" class="btn-check" id="exp-provider-openrouter" value="openrouter" v-model="explainProvider" />
              <label class="btn btn-outline-secondary" for="exp-provider-openrouter">openrouter</label>
            </div>
          </div>

          <div class="mb-3">
            <label class="form-label" for="exp-batch">Serija (opciono)</label>
            <select id="exp-batch" v-model="explainBatchId" class="form-select" :disabled="explaining">
              <option :value="null">Bez serije (razvojna proba)</option>
              <option v-for="b in evaluationBatches" :key="b.id" :value="b.id">
                #{{ b.id }} {{ b.name }}{{ b.is_final ? ' (finalna)' : '' }}
              </option>
            </select>
          </div>
        </template>

        <div class="d-flex justify-content-end gap-2">
          <button class="btn btn-secondary" :disabled="explaining" @click="closeExplainModal">
            {{ explainResult ? 'Zatvori' : 'Otkaži' }}
          </button>
          <button v-if="!explainResult" class="btn btn-primary" :disabled="explaining || batchesLoading" @click="submitExplain">
            <span v-if="explaining" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
            <i v-else class="fa-solid fa-lightbulb me-2"></i>
            {{ explaining ? 'Generišem...' : 'Generiši' }}
          </button>
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

.area-name {
  cursor: pointer;
}

.question-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1050;
}

.question-modal-card {
  background: #fff;
  border-radius: 12px;
  padding: 1.5rem;
  width: 100%;
  max-width: 520px;
  max-height: 85vh;
  overflow-y: auto;
}
</style>