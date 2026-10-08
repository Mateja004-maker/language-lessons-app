<script>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getExamDetails,
  getAreas,
  getBankQuestions,
  assignBankQuestionToExam,
  removeQuestionFromExam,
  publishExam,
  generateSimilarFromExam,
  getEvaluationBatches,
  MISTRAL_ENABLED
} from '@/services/api'

export default {
  setup() {
    const route = useRoute()
    const router = useRouter()

    const exam = ref(null)
    const loading = ref(true)

    // Pitanja iz banke predmeta ovog testa (dodavanje postojecih pitanja u test)
    const areas = ref([])
    const selectedAreaId = ref('')
    const bankQuestions = ref([])
    const bankLoading = ref(false)
    const bankError = ref('')
    const selectedBankIds = ref([])

    const areaNameById = computed(() =>
      Object.fromEntries(areas.value.map(a => [a.id, a.name]))
    )

    const examQuestionIds = computed(() =>
      new Set((exam.value?.questions || []).map(q => q.id))
    )

    // Test podrzava samo pitanja sa ponudjenim odgovorima (ExamTakeView nudi
    // samo izbor odgovora, a canPublish trazi bar 2 odgovora po pitanju).
    const availableBankQuestions = computed(() =>
      bankQuestions.value.filter(q => q.answer_count >= 2 && !examQuestionIds.value.has(q.id))
    )

    const hiddenOpenCount = computed(() =>
      bankQuestions.value.filter(q => q.answer_count < 2 && !examQuestionIds.value.has(q.id)).length
    )

    const loadAreas = async () => {
      const res = await getAreas(exam.value.subject_id)
      areas.value = res.data
    }

    const loadBank = async () => {
      bankError.value = ''
      bankLoading.value = true
      try {
        const res = await getBankQuestions(exam.value.subject_id, selectedAreaId.value || undefined)
        bankQuestions.value = res.data
      } catch (err) {
        bankError.value = err.response?.data?.error || 'Ne mogu da učitam banku pitanja.'
      } finally {
        bankLoading.value = false
      }
    }

    const onAreaChange = async () => {
      selectedBankIds.value = []
      addErrors.value = {}
      addSummary.value = ''
      await loadBank()
    }

    const adding = ref(false)
    // question_id -> { text, error } za pitanja koja nisu dodata
    const addErrors = ref({})
    const addSummary = ref('')

    // Greske za pitanja koja vise nisu u listi (npr. 409 - u medjuvremenu su
    // vec u testu), pa ne mogu da se prikazu pored pitanja.
    const hiddenAddErrors = computed(() => {
      const visible = new Set(availableBankQuestions.value.map(q => q.id))
      return Object.entries(addErrors.value)
        .filter(([id]) => !visible.has(Number(id)))
        .map(([id, e]) => ({ id, ...e }))
    })

    // Pitanja se dodaju redom (ne paralelno), da order_no ide max+1, max+2, ...
    // redom kojim su prikazana; greska jednog pitanja ne prekida ostala.
    const addSelectedToExam = async () => {
      if (adding.value || !selectedBankIds.value.length) return
      adding.value = true
      addErrors.value = {}
      addSummary.value = ''

      const selected = availableBankQuestions.value.filter(q => selectedBankIds.value.includes(q.id))
      let nextOrder = Math.max(0, ...exam.value.questions.map(q => q.order_no || 0)) + 1
      let added = 0
      const errors = {}

      for (const q of selected) {
        try {
          await assignBankQuestionToExam(route.params.id, q.id, nextOrder)
          nextOrder += 1
          added += 1
        } catch (err) {
          errors[q.id] = {
            text: q.question_text,
            error: err.response?.data?.error || 'Greška pri dodavanju'
          }
        }
      }

      try {
        await loadExam()
      } finally {
        selectedBankIds.value = []
        addErrors.value = errors
        addSummary.value = `Dodato ${added} od ${selected.length} pitanja.`
        adding.value = false
      }
    }

    const loadBankSection = async () => {
      if (!exam.value?.subject_id || exam.value.is_published) return
      try {
        await loadAreas()
      } catch (err) {
        bankError.value = err.response?.data?.error || 'Ne mogu da učitam oblasti.'
      }
      await loadBank()
    }

    const canPublish = computed(() => {
      if (!exam.value) return false
      if (!exam.value.questions.length) return false

      return exam.value.questions.every(q =>
        q.answers.length >= 2 && q.answers.some(a => a.is_correct)
      )
    })

    const loadExam = async () => {
      const res = await getExamDetails(route.params.id)
      exam.value = res.data
      loading.value = false
    }


    // Uklanja pitanje samo iz ovog testa - pitanje ostaje u banci (i vraca se
    // u listu za dodavanje). Ranije je ovde bio deleteQuestion, koji je za
    // pitanje vezano za test uvek vracao 409, pa dugme nije radilo.
    const removeQuestion = async (id) => {
      try {
        await removeQuestionFromExam(route.params.id, id)
      } catch (err) {
        alert(err.response?.data?.error || 'Error removing question from exam')
      }
      await loadExam()
    }

    // AI: K novih pitanja na osnovu svih pitanja ovog testa (tačka J)
    const genProvider = ref('groq')
    const genK = ref(3)
    const genBatchId = ref(null)
    const evaluationBatches = ref([])
    const generatingSet = ref(false)
    const genResult = ref(null)
    const genError = ref('')

    const loadEvaluationBatches = async () => {
      try {
        const { data } = await getEvaluationBatches()
        evaluationBatches.value = data || []
        genBatchId.value = evaluationBatches.value.length ? evaluationBatches.value[0].id : null
      } catch {
        evaluationBatches.value = []
      }
    }

    const generateFromExam = async () => {
      genError.value = ''
      genResult.value = null
      generatingSet.value = true
      try {
        const { data } = await generateSimilarFromExam(route.params.id, genProvider.value, Number(genK.value), genBatchId.value)
        genResult.value = data
      } catch (err) {
        genError.value = err.response?.data?.details || err.response?.data?.error || 'Ne mogu da pokrenem generisanje.'
      } finally {
        generatingSet.value = false
      }
    }

    const publish = async () => {
      try {
        await publishExam(route.params.id)
        alert('Exam published!')
        router.push('/exams')
      } catch (err) {
        alert(err.response?.data?.error || 'Error publishing exam')
      }
    }

    onMounted(async () => {
      await loadExam()
      await loadBankSection()
      await loadEvaluationBatches()
    })

    return {
      exam,
      loading,
      areas,
      selectedAreaId,
      bankLoading,
      bankError,
      selectedBankIds,
      areaNameById,
      availableBankQuestions,
      hiddenOpenCount,
      onAreaChange,
      adding,
      addErrors,
      addSummary,
      hiddenAddErrors,
      addSelectedToExam,
      removeQuestion,
      publish,
      canPublish,
      MISTRAL_ENABLED,
      genProvider,
      genK,
      genBatchId,
      evaluationBatches,
      generatingSet,
      genResult,
      genError,
      generateFromExam
    }
  }
}
</script>

<template>
  <div class="container py-4">
    <div v-if="loading">Loading...</div>

    <div v-else>
      <div class="page-header">
        <h1 class="page-title">{{ exam.title }}</h1>

        <span
          class="badge status-badge"
          :class="exam.is_published ? 'bg-success' : 'bg-secondary'"
        >
          <i
            class="me-1"
            :class="exam.is_published ? 'fa-solid fa-check' : 'fa-solid fa-pen-to-square'"
          ></i>
          {{ exam.is_published ? 'Published' : 'Draft' }}
        </span>
      </div>

      <div class="card shadow-sm mb-4">
        <div class="card-body">
          <h5 class="mb-3">
            <i class="fa-solid fa-wand-magic-sparkles me-2"></i>
            AI: generiši slična pitanja iz ovog testa
          </h5>
          <p class="text-muted small">
            Model dobija sva pitanja testa ({{ exam.questions?.length || 0 }}) i predlaže K novih. Predlozi idu na
            pregled (AI predlozi), ne u test.
          </p>
          <div class="row g-2 align-items-end">
            <div class="col-12 col-md-3">
              <label class="form-label" for="gen-set-provider">Model</label>
              <select id="gen-set-provider" v-model="genProvider" class="form-select" :disabled="generatingSet">
                <option value="groq">groq</option>
                <option value="gemini">gemini</option>
                <option v-if="MISTRAL_ENABLED" value="mistral">mistral</option>
                <option value="openrouter">openrouter</option>
              </select>
            </div>
            <div class="col-6 col-md-2">
              <label class="form-label" for="gen-set-k">Broj (K)</label>
              <input id="gen-set-k" v-model="genK" type="number" min="1" max="10" class="form-control" :disabled="generatingSet" />
            </div>
            <div class="col-12 col-md-4">
              <label class="form-label" for="gen-set-batch">Serija (opciono)</label>
              <select id="gen-set-batch" v-model="genBatchId" class="form-select" :disabled="generatingSet">
                <option :value="null">Bez serije (razvojna proba)</option>
                <option v-for="b in evaluationBatches" :key="b.id" :value="b.id">#{{ b.id }} {{ b.name }}</option>
              </select>
            </div>
            <div class="col-12 col-md-3">
              <button class="btn btn-outline-secondary w-100" :disabled="generatingSet || !exam.questions?.length" @click="generateFromExam">
                <span v-if="generatingSet" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
                {{ generatingSet ? 'Generišem...' : 'Generiši' }}
              </button>
            </div>
          </div>
          <div v-if="genError" class="alert alert-danger mt-3 mb-0">{{ genError }}</div>
          <div v-if="genResult" class="alert alert-success mt-3 mb-0">
            Napravljeno predloga: {{ genResult.accepted }} od {{ genResult.requested }}
            <template v-if="genResult.rejected">(odbijeno neispravnih: {{ genResult.rejected }})</template>.
            <router-link to="/ai/predlozi" class="ms-1">Idi na AI predloge</router-link>
          </div>
        </div>
      </div>

      <div v-if="exam.is_published" class="alert alert-secondary mb-4">
        <i class="fa-solid fa-lock me-2"></i>
        Test je objavljen - pitanja se više ne dodaju niti uklanjaju.
      </div>

      <div v-else class="card shadow-sm mb-4">
        <div class="card-body">
          <h5 class="mb-3">
            <i class="fa-solid fa-database me-2"></i>
            Dodaj pitanja iz banke
            <span v-if="exam.subject_name" class="badge bg-light text-dark border ms-2">{{ exam.subject_name }}</span>
          </h5>

          <div v-if="!exam.subject_id" class="alert alert-warning mb-0">
            Test nema predmet, pa nema ni banke pitanja.
          </div>

          <template v-else>
            <div class="mb-3">
              <label class="form-label">Oblast</label>
              <select v-model="selectedAreaId" class="form-select" @change="onAreaChange">
                <option value="">Sve oblasti</option>
                <option v-for="area in areas" :key="area.id" :value="area.id">
                  {{ area.name }}
                </option>
              </select>
            </div>

            <div v-if="bankError" class="alert alert-danger">{{ bankError }}</div>

            <div
              v-if="addSummary"
              class="alert"
              :class="Object.keys(addErrors).length ? 'alert-warning' : 'alert-success'"
            >
              {{ addSummary }}
              <ul v-if="hiddenAddErrors.length" class="mb-0 mt-1 small">
                <li v-for="e in hiddenAddErrors" :key="e.id">{{ e.text }} - {{ e.error }}</li>
              </ul>
            </div>

            <div v-if="bankLoading" class="d-flex align-items-center gap-2 text-muted">
              <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
              Učitavanje...
            </div>

            <div v-else-if="!availableBankQuestions.length" class="text-muted">
              Nema pitanja u banci koja mogu da se dodaju u ovaj test.
            </div>

            <div v-else>
              <div
                v-for="q in availableBankQuestions"
                :key="q.id"
                class="form-check border rounded p-2 ps-5 mb-2"
              >
                <input
                  :id="`bank-q-${q.id}`"
                  v-model="selectedBankIds"
                  :value="q.id"
                  :disabled="adding"
                  type="checkbox"
                  class="form-check-input"
                />
                <label :for="`bank-q-${q.id}`" class="form-check-label w-100">
                  {{ q.question_text }}
                  <span class="d-inline-flex flex-wrap gap-1 ms-2">
                    <span v-if="q.area_id" class="badge bg-secondary">{{ areaNameById[q.area_id] || 'Oblast' }}</span>
                    <span class="badge bg-dark">{{ q.points }} pts</span>
                    <span class="badge bg-light text-dark border">{{ q.answer_count }} odgovora</span>
                  </span>
                </label>
                <div v-if="addErrors[q.id]" class="small text-danger mt-1">
                  <i class="fa-solid fa-circle-exclamation me-1"></i>
                  Nije dodato: {{ addErrors[q.id].error }}
                </div>
              </div>
            </div>

            <div v-if="hiddenOpenCount" class="form-text mt-2">
              {{ hiddenOpenCount }} pitanja bez ponuđenih odgovora nije prikazano - test podržava samo pitanja sa ponuđenim odgovorima.
            </div>

            <button
              class="btn btn-primary mt-3"
              :disabled="!selectedBankIds.length || adding"
              @click="addSelectedToExam"
            >
              <span v-if="adding" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
              <i v-else class="fa-solid fa-plus me-2"></i>
              {{ adding ? 'Dodajem...' : `Dodaj izabrana pitanja u test (${selectedBankIds.length})` }}
            </button>
          </template>
        </div>
      </div>

      <div
        v-for="q in exam.questions"
        :key="q.id"
        class="card shadow-sm mb-3"
      >
        <div class="card-body">
          <!-- Pitanje u testu je samo za citanje; izmena teksta/poena/odgovora
               ide iskljucivo preko banke (/predmeti). -->
          <div class="d-flex justify-content-between">
            <h5 class="fw-bold">
              <i class="fa-solid fa-circle-question me-2"></i>
              {{ q.question_text }}
            </h5>

            <span class="badge bg-dark">{{ q.points }} pts</span>
          </div>

          <div class="mt-3">
            <div
              v-for="a in q.answers"
              :key="a.id"
              class="border rounded p-2 mb-2"
            >
              <i class="fa-solid fa-angle-right me-2 text-muted"></i>
              {{ a.answer_text }}

              <span v-if="a.is_correct" class="badge bg-success ms-2">
                <i class="fa-solid fa-check me-1"></i>
                Correct
              </span>
            </div>
          </div>

          <button
            v-if="!exam.is_published"
            @click="removeQuestion(q.id)"
            class="btn btn-sm btn-outline-danger mt-2"
          >
            <i class="fa-solid fa-xmark me-1"></i>
            Ukloni iz testa
          </button>
        </div>
      </div>

      <div class="mt-4">
        <button
          class="btn btn-primary w-100"
          :disabled="!canPublish || exam.is_published"
          @click="publish"
        >
          <i class="fa-solid fa-upload me-2"></i>
          Publish Exam
        </button>

        <div v-if="!canPublish" class="text-muted small mt-2">
          Add at least 1 question with 2 answers and 1 correct answer to publish.
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
</style>