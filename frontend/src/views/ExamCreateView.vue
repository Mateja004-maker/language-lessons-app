<script>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { createExam, api } from '@/services/api'

export default {
  setup() {
    const router = useRouter()

    const title = ref('')
    const description = ref('')
    const subject_id = ref('')
    const level = ref('')
    const duration_minutes = ref(30)
    const allSubjects = ref([])
    const profile = ref(null)
    const open_at = ref('')
    const close_at = ref('')
    const exam_mode = ref(false)

    const role = localStorage.getItem('user_role')

    const isTeacher = computed(() => role === 'TEACHER')
    const isAdmin = computed(() => role === 'ADMIN')

    const teacherSubjects = ref([])

    onMounted(async () => {
      try {
        const profileRes = await api.get('/profile')
        profile.value = profileRes.data

        if (role === 'TEACHER') {
          const subjectsRes = await api.get('/subjects')
          const subjectIds = profileRes.data.subjects || []
          teacherSubjects.value = subjectsRes.data.filter(
            s => subjectIds.includes(s.id)
          )

          if (teacherSubjects.value.length === 1) {
            subject_id.value = teacherSubjects.value[0].id
          }
        }

        // Test pripada predmetu (exams.subject_id) - i ADMIN bira iz subjects
        if (role === 'ADMIN') {
          const res = await api.get('/subjects')
          allSubjects.value = res.data
        }
      } catch (err) {
        console.error(err)
        alert('Error loading exam form')
      }
    })

    const submit = async () => {
      try {
        const res = await createExam({
          title: title.value,
          description: description.value,
          subject_id: subject_id.value,
          level: level.value,
          duration_minutes: duration_minutes.value,
          is_published: 0,
          open_at: open_at.value || null,
          close_at: close_at.value || null,
          exam_mode: exam_mode.value ? 1 : 0
        })

        router.push(`/exams/${res.data.exam_id}`)
      } catch (err) {
        console.error(err)
        alert(err.response?.data?.error || 'Error creating exam')
      }
    }

    return {
      title,
      description,
      subject_id,
      level,
      duration_minutes,
      allSubjects,
      teacherSubjects,
      profile,
      isTeacher,
      isAdmin,
      submit,
      open_at,
      close_at,
      exam_mode
    }
  }
}
</script>

<template>
  <div class="container mt-4 mb-5">
    <h2 class="page-title mb-4">
      <i class="fa-solid fa-file-circle-plus me-2"></i>
      Create Exam
    </h2>

    <div class="card border-0 shadow-sm">
      <div class="card-body">
        <h5 class="section-title mb-3">
          <i class="fa-solid fa-circle-info me-2"></i>
          Basic information
        </h5>

        <div class="mb-3">
          <label class="form-label">
            <i class="fa-solid fa-heading me-1"></i>
            Title
          </label>
          <input v-model="title" class="form-control" />
        </div>

        <div v-if="isAdmin" class="mb-3">
          <label class="form-label">
            <i class="fa-solid fa-book me-1"></i>
            Predmet
          </label>
          <select v-model="subject_id" class="form-select">
            <option value="">Izaberi predmet</option>
            <option v-for="subject in allSubjects" :key="subject.id" :value="subject.id">
              {{ subject.name }}
            </option>
          </select>
        </div>

        <div v-if="isTeacher" class="mb-3">
          <label class="form-label">
            <i class="fa-solid fa-book me-1"></i>
            Predmet
          </label>
          <select v-model="subject_id" class="form-select">
            <option value="">Izaberi predmet</option>
            <option v-for="subject in teacherSubjects" :key="subject.id" :value="subject.id">
              {{ subject.name }}
            </option>
          </select>
          <small class="text-muted">
            Exam se pravi samo za predmete koje predaješ.
          </small>
        </div>

        <div class="row">
          <div class="col-md-6 mb-3">
            <label class="form-label">
              <i class="fa-solid fa-layer-group me-1"></i>
              Level
            </label>
            <select v-model="level" class="form-select">
              <option value="">Select level</option>
              <option>A1</option>
              <option>A2</option>
              <option>B1</option>
              <option>B2</option>
              <option>C1</option>
              <option>C2</option>
            </select>
          </div>

          <div class="col-md-6 mb-3">
            <label class="form-label">
              <i class="fa-solid fa-clock me-1"></i>
              Duration minutes
            </label>
            <input v-model="duration_minutes" type="number" class="form-control" />
          </div>
        </div>

        <hr />

        <h5 class="section-title mb-3">
          <i class="fa-solid fa-calendar-days me-2"></i>
          Schedule and mode
        </h5>

        <div class="row">
          <div class="col-md-6 mb-3">
            <label class="form-label">
              <i class="fa-solid fa-calendar-plus me-1"></i>
              Open at
            </label>
            <input v-model="open_at" type="datetime-local" class="form-control" />
          </div>

          <div class="col-md-6 mb-3">
            <label class="form-label">
              <i class="fa-solid fa-calendar-xmark me-1"></i>
              Close at
            </label>
            <input v-model="close_at" type="datetime-local" class="form-control" />
          </div>
        </div>

        <div class="form-check mb-4">
          <input
            v-model="exam_mode"
            class="form-check-input"
            type="checkbox"
            id="examMode"
          />
          <label class="form-check-label" for="examMode">
            <i class="fa-solid fa-lock me-1"></i>
            Enable exam mode
          </label>
        </div>

        <button class="btn btn-primary px-4" @click="submit">
          <i class="fa-solid fa-plus me-2"></i>
          Create Exam
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-title {
  font-size: 2rem;
  font-weight: 800;
  color: var(--app-text);
  border-bottom: 2px solid var(--app-border);
  padding-bottom: 0.75rem;
}

.section-title {
  font-weight: 700;
  color: var(--app-text);
}
</style>