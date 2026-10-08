<script setup>
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

const form = ref({
  language_id: '',
  level: 'A1',
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
      error.value = e?.response?.data?.error || 'Failed to upload image.'
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
    error.value = e?.response?.data?.error || 'Failed to load data.'
  } finally {
    loading.value = false
  }
}

async function createLesson() {
  error.value = ''
  msg.value = ''

  if (!form.value.language_id || !form.value.title.trim() || !form.value.content) {
    error.value = 'Please fill in the language, title, and content.'
    return
  }

  try {
    await api.post('/lessons', {
      language_id: Number(form.value.language_id),
      level: form.value.level,
      title: form.value.title.trim(),
      content: form.value.content,
      tips: form.value.tips.trim(),
      important_info: form.value.important_info.trim()
    })
    msg.value = 'Lesson added successfully.'
    form.value.title = ''
    form.value.content = ''
    form.value.tips = ''
    form.value.important_info = ''
    await loadAll()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Failed to add the lesson.'
  }
}

function startEdit(lesson) {
  editingLessonId.value = lesson.id

  form.value.language_id = lesson.language_id
  form.value.level = lesson.level
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
  form.value.level = 'A1'
  form.value.title = ''
  form.value.content = ''
  form.value.tips = ''
  form.value.important_info = ''
}

async function updateLesson() {
  error.value = ''
  msg.value = ''

  if (!form.value.language_id || !form.value.title.trim() || !form.value.content) {
    error.value = 'Please fill in the language, title, and content.'
    return
  }

  try {
    await api.put(`/lessons/${editingLessonId.value}`, {
      language_id: Number(form.value.language_id),
      level: form.value.level,
      title: form.value.title.trim(),
      content: form.value.content,
      tips: form.value.tips.trim(),
      important_info: form.value.important_info.trim()
    })

    msg.value = 'Lesson updated successfully.'
    cancelEdit()
    await loadAll()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Failed to update the lesson.'
  }
}

async function removeLesson(id) {
  error.value = ''
  msg.value = ''
  try {
    await api.delete(`/lessons/${id}`)
    msg.value = 'Lesson deleted successfully.'
    await loadAll()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Failed to delete the lesson.'
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="container py-4">
    <div class="d-flex align-items-center justify-content-between mb-3">
      <h2 class="page-title mb-4">Manage Lessons</h2>
      <span v-if="role" class="badge text-bg-secondary">Role: {{ role }}</span>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>

    <div class="row g-3">
      <!-- FORM -->
      <div class="col-12">
        <div class="card shadow-sm">
          <div class="card-body">
            <h5 class="card-title mb-3">
              {{ editingLessonId ? 'Edit lesson' : 'Create lesson' }}
            </h5>

            <div class="mb-3">
              <label class="form-label">Language</label>
              <select v-model="form.language_id" class="form-select">
                <option value="" disabled>Select language...</option>
                <option v-for="l in languages" :key="l.id" :value="l.id">
                  {{ l.code }} — {{ l.name }}
                </option>
              </select>
            </div>

            <div class="mb-3">
              <label class="form-label">Level</label>
              <select v-model="form.level" class="form-select">
                <option>A1</option><option>A2</option><option>B1</option><option>B2</option><option>C1</option><option>C2</option>
              </select>
            </div>

            <div class="mb-3">
              <label class="form-label">Title</label>
              <input v-model="form.title" class="form-control" placeholder="Greetings" />
            </div>

            <div class="mb-3">
              <label class="form-label">Content</label>
              <QuillEditor
                ref="quillEditor"
                v-model:content="form.content"
                content-type="html"
                theme="snow"
                :toolbar="toolbarOptions"
                placeholder="Write lesson content here..."
              />
            </div>
            <div class="row g-3 mb-3">
              <div class="col-12 col-md-6">
                <div class="info-box tips-box">
                  <label class="form-label">Tips & Tricks</label>
                  <textarea
                    v-model="form.tips"
                    class="form-control"
                    rows="4"
                    placeholder="Add useful tips, shortcuts, or examples..."
                  ></textarea>
                </div>
              </div>

              <div class="col-12 col-md-6">
                <div class="info-box important-box">
                  <label class="form-label">Important Information</label>
                  <textarea
                    v-model="form.important_info"
                    class="form-control"
                    rows="4"
                    placeholder="Add key rules, warnings, or important notes..."
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
              Add lesson
            </button>

            <button
              v-else
              class="btn btn-success w-100"
              :disabled="loading"
              @click="updateLesson"
            >
              Save changes
            </button>

            <button
              v-if="editingLessonId"
              class="btn btn-outline-secondary"
              type="button"
              @click="cancelEdit"
            >
              Cancel
            </button>
          </div>
      
          </div>
        </div>
      </div>

      <!-- LIST -->
      <div class="col-12">
        <div class="card shadow-sm">
          <div class="card-body">
            <div class="d-flex align-items-center justify-content-between mb-2">
              <h5 class="card-title m-0">All lessons</h5>
              <button class="btn btn-outline-secondary btn-sm" :disabled="loading" @click="loadAll">
                Refresh
              </button>
            </div>

            <div v-if="loading" class="text-muted">Loading...</div>

            <div v-else-if="lessons.length === 0" class="text-muted">
              No lessons yet.
            </div>

            <div v-else class="table-responsive">
              <table class="table table-sm align-middle">
                <thead class="table-light">
                  <tr>
                    <th>ID</th>
                    <th>Lang</th>
                    <th>Level</th>
                    <th>Title</th>
                    <th class="text-end">Action</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(l, index) in lessons" :key="l.id">
                    <td>{{ index + 1 }}</td>
                    <td><span class="badge text-bg-light border">{{ l.language_code }}</span></td>
                    <td><span class="badge text-bg-primary">{{ l.level }}</span></td>
                    <td class="fw-semibold">{{ l.title }}</td>
                    <td class="text-end">
                      <button
                        class="btn btn-outline-primary btn-sm me-2"
                        @click="startEdit(l)"
                      >
                        Edit
                      </button>

                      <button
                        class="btn btn-outline-danger btn-sm"
                        @click="removeLesson(l.id)"
                      >
                        Delete
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
.page-title {
  font-size: 2rem;
  font-weight: 800;
  color: var(--app-text);
  border-bottom: 2px solid var(--app-border);
  padding-bottom: 0.75rem;
}
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