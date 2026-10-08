<template>
  <div class="container mt-4 mb-5">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h2 class="page-title mb-4">Exams</h2>

      <router-link
        v-if="role === 'ADMIN' || role === 'TEACHER'"
        to="/exams/create"
        class="btn btn-primary"
      >
        Create Exam
      </router-link>
    </div>

    <div v-if="loading" class="card border-0 shadow-sm">
      <div class="card-body">Loading...</div>
    </div>

    <div v-else>
      <div v-if="exams.length === 0" class="section-card section-padding text-center text-muted mb-4">
        <AppIllustration kind="clipboard" class="mb-2" />
        <div>Nema dostupnih testova.</div>
      </div>

      <!-- ADMIN SUBJECT FILTER -->
      <div v-if="role === 'ADMIN'" class="card border-0 shadow-sm mb-4">
        <div class="card-body">
          <label class="form-label fw-semibold">Filter by subject</label>
          <select v-model="selectedSubject" class="form-select">
            <option value="">All subjects</option>
            <option
              v-for="subject in subjects"
              :key="subject"
              :value="subject"
            >
              {{ subject }}
            </option>
          </select>
        </div>
      </div>

      <!-- STUDENT VIEW -->
      <template v-if="role === 'STUDENT'">
        <section v-if="pendingExams.length > 0" class="mb-4">
          <h4 class="section-title mb-3">Available Exams</h4>

          <div class="row g-3">
            <div
              class="col-md-6 col-lg-4"
              v-for="exam in pendingExams"
              :key="exam.id"
            >
              <div class="card h-100 border-0 shadow-sm">
                <div class="card-body">
                  <h5 class="fw-bold fs-4 mb-2">{{ exam.title }}</h5>

                  <div class="mb-2">
                    <span v-if="exam.exam_mode" class="badge bg-dark me-1">
                      Exam mode
                    </span>
                    <span class="badge bg-light text-dark border">
                      {{ exam.subject_name }}
                    </span>
                    <span class="badge bg-light text-dark border ms-1">
                      {{ exam.level }}
                    </span>
                  </div>

                  <div class="small text-muted">
                    <div><strong>Duration:</strong> {{ exam.duration_minutes }} min</div>

                    <div v-if="exam.open_at">
                      <strong>From:</strong> {{ formatDate(exam.open_at) }}
                    </div>

                    <div v-if="exam.close_at">
                      <strong>Until:</strong> {{ formatDate(exam.close_at) }}
                    </div>
                  </div>
                </div>

                <div class="card-footer bg-white border-0">
                  <router-link
                    :to="'/exams/' + exam.id + '/take'"
                    class="btn btn-success w-100"
                  >
                    Take Exam
                  </router-link>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section v-if="completedExams.length > 0">
          <h4 class="section-title mb-3">Completed Exams</h4>

          <div class="row g-3">
            <div
              class="col-md-6 col-lg-4"
              v-for="exam in completedExams"
              :key="exam.id"
            >
              <div class="card h-100 border-0 shadow-sm">
                <div class="card-body">
                  <div class="d-flex justify-content-between">
                    <h5 class="fw-bold fs-4 mb-2">{{ exam.title }}</h5>
                    <span class="badge bg-success status-badge">Completed</span>
                  </div>

                  <div class="mb-2">
                    <span class="badge bg-light text-dark border">
                      {{ exam.subject_name }}
                    </span>
                    <span class="badge bg-light text-dark border ms-1">
                      {{ exam.level }}
                    </span>
                  </div>

                  <div class="small text-muted mb-2">
                    <strong>Score:</strong>
                    {{ exam.score }} / {{ exam.total_points }}
                  </div>

                  <span
                    class="badge"
                    :class="isPassed(exam) ? 'bg-success' : 'bg-danger'"
                  >
                    {{ isPassed(exam) ? 'Passed' : 'Failed' }}
                  </span>
                </div>

                <div class="card-footer bg-white border-0">
                  <router-link to="/my-results" class="btn btn-outline-dark w-100">
                    View Result
                  </router-link>
                </div>
              </div>
            </div>
          </div>
        </section>
      </template>

      <!-- ADMIN / TEACHER VIEW -->
      <template v-else>
        <section v-if="publishedExams.length > 0" class="mb-4">
          <h4 class="section-title mb-3">Published Exams</h4>

          <div class="row g-3">
            <div
              class="col-md-6 col-lg-4"
              v-for="exam in publishedExams"
              :key="exam.id"
            >
              <div class="card h-100 border-0 shadow-sm">
                <div class="card-body">
                  <div class="d-flex justify-content-between">
                    <h5 class="fw-bold fs-4 mb-2">{{ exam.title }}</h5>
                    <span class="badge bg-success status-badge">Published</span>
                  </div>

                  <div class="mb-2">
                    <span class="badge bg-light text-dark border">
                      {{ exam.subject_name }}
                    </span>
                    <span class="badge bg-light text-dark border ms-1">
                      {{ exam.level }}
                    </span>
                  </div>

                  <div class="small text-muted">
                    <div><strong>Duration:</strong> {{ exam.duration_minutes }} min</div>
                  </div>
                </div>

                <div class="card-footer bg-white border-0 d-flex gap-2">
                  <router-link
                    :to="'/exams/' + exam.id + '/results'"
                    class="btn btn-outline-dark w-100"
                  >
                    Results
                  </router-link>

                  <button
                    class="btn btn-outline-danger w-100"
                    @click="deleteExamClick(exam)"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section v-if="draftExams.length > 0">
          <h4 class="section-title mb-3">Drafts</h4>

          <div class="row g-3">
            <div
              class="col-md-6 col-lg-4"
              v-for="exam in draftExams"
              :key="exam.id"
            >
              <div class="card h-100 border-0 shadow-sm">
                <div class="card-body">
                  <div class="d-flex justify-content-between">
                    <h5 class="fw-bold fs-4 mb-2">{{ exam.title }}</h5>
                    <span class="badge bg-secondary status-badge">Draft</span>
                  </div>

                  <div class="mb-2">
                    <span class="badge bg-light text-dark border">
                      {{ exam.subject_name }}
                    </span>
                    <span class="badge bg-light text-dark border ms-1">
                      {{ exam.level }}
                    </span>
                  </div>

                  <div class="small text-muted">
                    <div><strong>Duration:</strong> {{ exam.duration_minutes }} min</div>
                  </div>
                </div>

                <div class="card-footer bg-white border-0 d-flex gap-2">
                  <router-link
                    :to="'/exams/' + exam.id"
                    class="btn btn-outline-primary w-100"
                  >
                    Manage
                  </router-link>
                  <button
                    class="btn btn-outline-danger w-100"
                    @click="deleteExamClick(exam)"
                  >
                    Delete
                  </button>

                  <!-- <router-link
                    :to="'/exams/' + exam.id + '/results'"
                    class="btn btn-outline-dark w-100"
                  >
                    Results
                  </router-link> -->
                </div>
              </div>
            </div>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>

<script>
import { getExams, deleteExam } from '@/services/api'
import AppIllustration from '@/components/AppIllustration.vue'

export default {
  components: { AppIllustration },
  data() {
    return {
      exams: [],
      loading: true,
      role: localStorage.getItem('user_role'),
      selectedSubject: ''
    }
  },

  computed: {
    filteredExams() {
      if (this.role !== 'ADMIN' || !this.selectedSubject) {
        return this.exams
      }

      return this.exams.filter(e => e.subject_name === this.selectedSubject)
    },

    subjects() {
      return [...new Set(this.exams.map(e => e.subject_name).filter(Boolean))]
    },

    pendingExams() {
      return this.exams.filter(e => !e.attempt_id)
    },

    completedExams() {
      return this.exams.filter(e => e.attempt_id)
    },

    publishedExams() {
      return this.filteredExams.filter(e => e.is_published)
    },

    draftExams() {
      return this.filteredExams.filter(e => !e.is_published)
    }
  },

  methods: {
    formatDate(dateString) {
      return new Date(dateString).toLocaleString()
    },

    isPassed(exam) {
      return exam.total_points > 0 && exam.score >= exam.total_points * 0.5
    },
    async deleteExamClick(exam) {
      if (!confirm(`Da li sigurno želiš da obrišeš test "${exam.title}"?`)) {
        return
      }

      try {
        await deleteExam(exam.id)
        this.exams = this.exams.filter(e => e.id !== exam.id)
      } catch (err) {
        console.error(err)
        alert(err.response?.data?.error || 'Ne mogu da obrišem test.')
      }
    }
  },

  async mounted() {
    try {
      const res = await getExams()
      this.exams = res.data
    } catch (err) {
      console.error(err)
      alert('Failed to load exams')
    } finally {
      this.loading = false
    }
  }
}
</script>

<style scoped>
.page-title {
  font-size: 2rem;
  font-weight: 800;
  color: var(--app-text);
  border-bottom: 2px solid var(--app-border);
  padding-bottom: 0.75rem;
}

.section-title {
  font-size: 1.45rem;
  font-weight: 750;
  color: var(--app-text);
  margin-top: 1.5rem;
}

.status-badge {
  width: 95px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  padding: 0;
}
</style>