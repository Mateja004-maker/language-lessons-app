<script setup>
import PageHeader from '@/components/PageHeader.vue'
import { onMounted, ref, computed } from 'vue'
import { api } from '@/services/api'
import { QuillEditor } from '@vueup/vue-quill'
import '@vueup/vue-quill/dist/vue-quill.snow.css'

const role = computed(() => localStorage.getItem('user_role') || '')

const lessons = ref([])
const languages = ref([])
const quillEditor = ref(null)


const loading = ref(false)
const error = ref('')
const msg = ref('')
const editingLessonId = ref(null)

// filter tabele po predmetu (predmeti iz /api/subjects: ADMIN sve, nastavnik svoje).
// Lekcija je vezana za predmet preko language_id (isti id kao predmet - ista pretpostavka kao u backendu).
const subjects = ref([])
const selectedSubject = ref('')
const filteredLessons = computed(() =>
  selectedSubject.value
    ? lessons.value.filter(l => Number(l.language_id) === Number(selectedSubject.value))
    : lessons.value
)

async function loadSubjects() {
  try {
    const { data } = await api.get('/subjects')
    subjects.value = data
  } catch (e) {
    subjects.value = []
  }
}

const form = ref({
  language_id: '',
  title: '',
  content: '',
  tips: '',
  important_info: ''
})
const toolbarOptions = {
  container: [
    [{ header: [1, 2, 3, false] }],
    ['bold', 'italic', 'underline', 'strike'],
    [{ align: [] }],
    [{ list: 'ordered' }, { list: 'bullet' }],
    [{ color: [] }, { background: [] }],
    ['blockquote', 'code-block'],
    ['link', 'image'],
    ['clean']
  ],
  handlers: {
    image: imageHandler
  }
}

async function imageHandler() {
  const input = document.createElement('input')
  input.setAttribute('type', 'file')
  input.setAttribute('accept', 'image/png,image/jpeg,image/jpg,image/webp')
  input.click()

  input.onchange = async () => {
    const file = input.files?.[0]
    if (!file) return

    const formData = new FormData()
    formData.append('image', file)

    try {
      const { data } = await api.post('/lesson-images', formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      })

      const editor = quillEditor.value?.getQuill()
      const range = editor.getSelection(true)

      editor.insertEmbed(
        range.index,
        'image',
        `http://127.0.0.1:5000${data.image_url}`
      )

      editor.setSelection(range.index + 1)
    } catch (e) {
      error.value = e?.response?.data?.error || 'Otpremanje slike nije uspelo.'
    }
  }
}

async function loadAll() {
  error.value = ''
  msg.value = ''
  loading.value = true
  try {
    const [lessonsRes, langsRes] = await Promise.all([
      api.get('/lessons'),
      api.get('/languages')
    ])
    lessons.value = lessonsRes.data
    languages.value = langsRes.data
  } catch (e) {
    error.value = e?.response?.data?.error || 'Učitavanje podataka nije uspelo.'
  } finally {
    loading.value = false
  }
}

async function createLesson() {
  error.value = ''
  msg.value = ''

  if (!form.value.language_id || !form.value.title.trim() || !form.value.content) {
    error.value = 'Popuni predmet, naslov i sadržaj.'
    return
  }

  try {
    await api.post('/lessons', {
      language_id: Number(form.value.language_id),
      title: form.value.title.trim(),
      content: form.value.content,
      tips: form.value.tips.trim(),
      important_info: form.value.important_info.trim()
    })
    msg.value = 'Lekcija je dodata.'
    form.value.title = ''
    form.value.content = ''
    form.value.tips = ''
    form.value.important_info = ''
    await loadAll()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Dodavanje lekcije nije uspelo.'
  }
}

function startEdit(lesson) {
  editingLessonId.value = lesson.id

  form.value.language_id = lesson.language_id
  form.value.title = lesson.title
  form.value.content = lesson.content
  form.value.tips = lesson.tips || ''
  form.value.important_info = lesson.important_info || ''

  window.scrollTo({
    top: 0,
    behavior: 'smooth'
  })
}

function cancelEdit() {
  editingLessonId.value = null

  form.value.language_id = ''
  form.value.title = ''
  form.value.content = ''
  form.value.tips = ''
  form.value.important_info = ''
}

async function updateLesson() {
  error.value = ''
  msg.value = ''

  if (!form.value.language_id || !form.value.title.trim() || !form.value.content) {
    error.value = 'Popuni predmet, naslov i sadržaj.'
    return
  }

  try {
    await api.put(`/lessons/${editingLessonId.value}`, {
      language_id: Number(form.value.language_id),
      title: form.value.title.trim(),
      content: form.value.content,
      tips: form.value.tips.trim(),
      important_info: form.value.important_info.trim()
    })

    msg.value = 'Lekcija je izmenjena.'
    cancelEdit()
    await loadAll()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Izmena lekcije nije uspela.'
  }
}

async function removeLesson(id) {
  error.value = ''
  msg.value = ''
  try {
    await api.delete(`/lessons/${id}`)
    msg.value = 'Lekcija je obrisana.'
    await loadAll()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Brisanje lekcije nije uspelo.'
  }
}

onMounted(() => {
  loadAll()
  loadSubjects()
})
</script>

<template>
  <div class="container py-4">
    <PageHeader title="Uređivanje lekcija" />

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>

    <div class="row g-3">
      <!-- FORM -->
      <div class="col-12">
        <div class="card shadow-sm">
          <div class="card-body">
            <h5 class="card-title mb-3">
              {{ editingLessonId ? 'Izmena lekcije' : 'Nova lekcija' }}
            </h5>

            <div class="mb-3">
              <label class="form-label">Predmet</label>
              <select v-model="form.language_id" class="form-select">
                <option value="" disabled>Izaberi predmet...</option>
                <option v-for="l in languages" :key="l.id" :value="l.id">
                  {{ l.code }} — {{ l.name }}
                </option>
              </select>
            </div>

            <div class="mb-3">
              <label class="form-label">Naslov</label>
              <input v-model="form.title" class="form-control" placeholder="Npr. Pozdravi" />
            </div>

            <div class="mb-3">
              <label class="form-label">Sadržaj</label>
              <QuillEditor
                ref="quillEditor"
                v-model:content="form.content"
                content-type="html"
                theme="snow"
                :toolbar="toolbarOptions"
                placeholder="Upiši sadržaj lekcije..."
              />
            </div>
            <div class="row g-3 mb-3">
              <div class="col-12 col-md-6">
                <div class="info-box tips-box">
                  <label class="form-label">Saveti</label>
                  <textarea
                    v-model="form.tips"
                    class="form-control"
                    rows="4"
                    placeholder="Korisni saveti, prečice ili primeri..."
                  ></textarea>
                </div>
              </div>

              <div class="col-12 col-md-6">
                <div class="info-box important-box">
                  <label class="form-label">Važne informacije</label>
                  <textarea
                    v-model="form.important_info"
                    class="form-control"
                    rows="4"
                    placeholder="Ključna pravila, upozorenja ili važne napomene..."
                  ></textarea>
                </div>
              </div>
            </div>

           <div class="d-flex gap-2">
            <button
              v-if="!editingLessonId"
              class="btn btn-primary w-100"
              :disabled="loading"
              @click="createLesson"
            >
              Dodaj lekciju
            </button>

            <button
              v-else
              class="btn btn-primary w-100"
              :disabled="loading"
              @click="updateLesson"
            >
              Sačuvaj izmene
            </button>

            <button
              v-if="editingLessonId"
              class="btn btn-outline-secondary"
              type="button"
              @click="cancelEdit"
            >
              Otkaži
            </button>
          </div>
      
          </div>
        </div>
      </div>

      <!-- LIST -->
      <div class="col-12">
        <div class="card shadow-sm">
          <div class="card-body">
            <!-- filter neposredno iznad tabele -->
            <div class="table-toolbar">
              <h5 class="card-title m-0">Sve lekcije</h5>
              <select v-model="selectedSubject" class="form-select" aria-label="Predmet">
                <option value="">Svi predmeti</option>
                <option v-for="s in subjects" :key="s.id" :value="s.id">{{ s.name }}</option>
              </select>
            </div>

            <div v-if="loading" class="text-muted">Učitavanje...</div>

            <div v-else-if="filteredLessons.length === 0" class="text-muted">
              Nema lekcija.
            </div>

            <div v-else class="table-responsive">
              <table class="table table-sm align-middle">
                <thead class="table-light">
                  <tr>
                    <th>ID</th>
                    <th>Predmet</th>
                    <th>Naslov</th>
                    <th class="text-end">Akcije</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(l, index) in filteredLessons" :key="l.id">
                    <td>{{ index + 1 }}</td>
                    <td><span class="badge text-bg-light border">{{ l.language_code }}</span></td>
                    <td class="fw-semibold">{{ l.title }}</td>
                    <td class="text-end">
                      <button
                        class="btn btn-outline-secondary btn-sm me-2"
                        @click="startEdit(l)"
                      >
                        Izmeni
                      </button>

                      <button
                        class="btn btn-outline-danger btn-sm"
                        @click="removeLesson(l.id)"
                      >
                        Obriši
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>

              
              
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.container {
  max-width: 1100px;
}
.info-box {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  padding: 16px;
  background: var(--app-surface);
}

/* bez obojenih ivica: razlika samo u svetloj pozadini */
.tips-box {
  background: var(--app-primary-soft);
}

.important-box {
  background: var(--app-danger-soft);
}
:deep(.ql-toolbar) {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius) var(--app-radius) 0 0;
  background: var(--app-bg);
  padding: 12px;
}

:deep(.ql-container) {
  border: 1px solid var(--app-border);
  border-top: none;
  border-radius: 0 0 var(--app-radius) var(--app-radius);
  min-height: 280px;
  font-size: 16px;
}

:deep(.ql-editor) {
  min-height: 280px;
  line-height: 1.7;
  padding: 20px;
}

:deep(.ql-editor.ql-blank::before) {
  color: var(--app-text-muted);
  font-style: normal;
}
</style>