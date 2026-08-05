<script>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getExamDetails,
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

    onMounted(loadExam)

    return {
      exam,
      loading,
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