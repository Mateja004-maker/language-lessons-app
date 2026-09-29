<script>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getExamDetails,
  getAreas,
  getBankQuestions,
  addExamQuestion,
  addQuestionAnswer,
  deleteQuestion,
  deleteAnswer,
  updateQuestion,
  updateAnswer,
  publishExam
} from '@/services/api'

export default {
  setup() {
    const route = useRoute()
    const router = useRouter()

    const exam = ref(null)
    const loading = ref(true)

    const question_text = ref('')
    const points = ref(1)
    const answerText = ref({})
    const correctAnswer = ref({})

    const editingQuestion = ref(null)
    const editQuestionText = ref('')
    const editPoints = ref(1)

    const editingAnswer = ref(null)
    const editAnswerText = ref('')
    const editCorrect = ref(false)

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
      await loadBank()
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

    const submitQuestion = async () => {
      if (!question_text.value.trim()) return

      await addExamQuestion(route.params.id, {
        question_text: question_text.value,
        points: points.value
      })

      question_text.value = ''
      points.value = 1
      await loadExam()
    }

    const submitAnswer = async (questionId) => {
      if (!answerText.value[questionId]?.trim()) return

      await addQuestionAnswer(questionId, {
        answer_text: answerText.value[questionId],
        is_correct: correctAnswer.value[questionId] ? 1 : 0
      })

      answerText.value[questionId] = ''
      correctAnswer.value[questionId] = false
      await loadExam()
    }

    const removeQuestion = async (id) => {
      await deleteQuestion(id)
      await loadExam()
    }

    const removeAnswer = async (id) => {
      await deleteAnswer(id)
      await loadExam()
    }

    const startEditQuestion = (q) => {
      editingQuestion.value = q.id
      editQuestionText.value = q.question_text
      editPoints.value = q.points
    }

    const saveEditQuestion = async (id) => {
      await updateQuestion(id, {
        question_text: editQuestionText.value,
        points: editPoints.value
      })

      editingQuestion.value = null
      await loadExam()
    }

    const startEditAnswer = (a) => {
      editingAnswer.value = a.id
      editAnswerText.value = a.answer_text
      editCorrect.value = a.is_correct
    }

    const saveEditAnswer = async (id) => {
      await updateAnswer(id, {
        answer_text: editAnswerText.value,
        is_correct: editCorrect.value ? 1 : 0
      })

      editingAnswer.value = null
      await loadExam()
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
      question_text,
      points,
      answerText,
      correctAnswer,
      submitQuestion,
      submitAnswer,
      removeQuestion,
      removeAnswer,
      editingQuestion,
      editQuestionText,
      editPoints,
      startEditQuestion,
      saveEditQuestion,
      editingAnswer,
      editAnswerText,
      editCorrect,
      startEditAnswer,
      saveEditAnswer,
      publish,
      canPublish
    }
  }
}
</script>

<template>
  <div class="container mt-4 mb-5">
    <div v-if="loading">Loading...</div>

    <div v-else>
      <div class="mb-4">
        <h2 class="page-title">
          <i class="fa-solid fa-file-lines me-2"></i>
          {{ exam.title }}
        </h2>

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

      <div v-if="exam.is_published" class="alert alert-secondary mb-4">
        <i class="fa-solid fa-lock me-2"></i>
        Test je objavljen - pitanja se više ne dodaju.
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
              </div>
            </div>

            <div v-if="hiddenOpenCount" class="form-text mt-2">
              {{ hiddenOpenCount }} pitanja bez ponuđenih odgovora nije prikazano - test podržava samo pitanja sa ponuđenim odgovorima.
            </div>
          </template>
        </div>
      </div>

      <div class="card shadow-sm mb-4">
        <div class="card-body">
          <h5 class="mb-3">
            <i class="fa-solid fa-circle-plus me-2"></i>
            Add Question
          </h5>

          <input
            v-model="question_text"
            class="form-control mb-2"
            placeholder="Question text"
          />

          <input
            v-model="points"
            type="number"
            class="form-control mb-2"
            placeholder="Points"
          />

          <button @click="submitQuestion" class="btn btn-primary">
            <i class="fa-solid fa-plus me-2"></i>
            Add Question
          </button>
        </div>
      </div>

      <div
        v-for="q in exam.questions"
        :key="q.id"
        class="card shadow-sm mb-3"
      >
        <div class="card-body">
          <div v-if="editingQuestion === q.id">
            <input v-model="editQuestionText" class="form-control mb-2" />
            <input v-model="editPoints" type="number" class="form-control mb-2" />

            <button @click="saveEditQuestion(q.id)" class="btn btn-success btn-sm">
              <i class="fa-solid fa-floppy-disk me-1"></i>
              Save
            </button>
          </div>

          <div v-else>
            <div class="d-flex justify-content-between">
              <h5 class="fw-bold">
                <i class="fa-solid fa-circle-question me-2"></i>
                {{ q.question_text }}
              </h5>

              <span class="badge bg-dark">{{ q.points }} pts</span>
            </div>

            <button @click="startEditQuestion(q)" class="btn btn-sm btn-warning me-2">
              <i class="fa-solid fa-pen me-1"></i>
              Edit
            </button>

            <button @click="removeQuestion(q.id)" class="btn btn-sm btn-danger">
              <i class="fa-solid fa-trash me-1"></i>
              Delete
            </button>
          </div>

          <div class="mt-3">
            <div
              v-for="a in q.answers"
              :key="a.id"
              class="d-flex justify-content-between align-items-center border rounded p-2 mb-2"
            >
              <div>
                <i class="fa-solid fa-angle-right me-2 text-muted"></i>
                {{ a.answer_text }}

                <span v-if="a.is_correct" class="badge bg-success ms-2">
                  <i class="fa-solid fa-check me-1"></i>
                  Correct
                </span>
              </div>

              <div>
                <button @click="startEditAnswer(a)" class="btn btn-sm btn-warning me-1">
                  <i class="fa-solid fa-pen"></i>
                </button>

                <button @click="removeAnswer(a.id)" class="btn btn-sm btn-danger">
                  <i class="fa-solid fa-trash"></i>
                </button>
              </div>
            </div>

            <input
              v-model="answerText[q.id]"
              class="form-control mb-2"
              placeholder="Answer text"
            />

            <div class="form-check mb-2">
              <input
                type="checkbox"
                class="form-check-input"
                v-model="correctAnswer[q.id]"
              />
              <label class="form-check-label">
                Correct answer
              </label>
            </div>

            <button @click="submitAnswer(q.id)" class="btn btn-sm btn-primary">
              <i class="fa-solid fa-plus me-1"></i>
              Add Answer
            </button>
          </div>
        </div>
      </div>

      <div class="mt-4">
        <button
          class="btn btn-success w-100"
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
.page-title {
  font-size: 2.4rem;
  font-weight: 800;
}

.status-badge {
  width: 120px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
}
</style>