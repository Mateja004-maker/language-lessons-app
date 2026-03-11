<script setup>
import { onMounted, ref } from 'vue'
import { api } from '@/services/api'

const role = localStorage.getItem('user_role')

const languages = ref([])
const lessons = ref([])
const error = ref('')
const msg = ref('')

const form = ref({
  language_id: '',
  level: 'A1',
  title: '',
  content_html: '',
  order_no: 1
})

async function loadAll() {
  const [langRes, lessonsRes] = await Promise.all([
    api.get('/languages'),
    api.get('/lessons')
  ])
  languages.value = langRes.data
  lessons.value = lessonsRes.data
}

async function createLesson() {
  error.value = ''
  msg.value = ''
  try {
    await api.post('/lessons', {
      language_id: Number(form.value.language_id),
      level: form.value.level,
      title: form.value.title,
      content_html: form.value.content_html,
      order_no: Number(form.value.order_no)
    })
    msg.value = 'Lekcija dodata.'
    form.value.title = ''
    form.value.content_html = ''
    await loadAll()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne može da doda lekciju'
  }
}

async function deleteLesson(id) {
  error.value = ''
  msg.value = ''
  try {
    await api.delete(`/lessons/${id}`)
    msg.value = 'Lekcija obrisana.'
    await loadAll()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne može da obriše lekciju'
  }
}

onMounted(loadAll)
</script>

<template>
  <div style="max-width:1000px;margin:30px auto;">
    <h2>Manage Lessons</h2>
    <p>Role: <b>{{ role }}</b></p>

    <div style="border:1px solid #ddd;padding:12px;border-radius:10px;">
      <h3>New lesson</h3>

      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div>
          <label>Language</label><br />
          <select v-model="form.language_id">
            <option value="" disabled>Choose...</option>
            <option v-for="l in languages" :key="l.id" :value="l.id">
              {{ l.code }} — {{ l.name }}
            </option>
          </select>
        </div>

        <div>
          <label>Level</label><br />
          <select v-model="form.level">
            <option>A1</option><option>A2</option><option>B1</option><option>B2</option><option>C1</option><option>C2</option>
          </select>
        </div>

        <div>
          <label>Order</label><br />
          <input type="number" v-model="form.order_no" />
        </div>
      </div>

      <div style="margin-top:10px;">
        <label>Title</label><br />
        <input style="width:100%" v-model="form.title" />
      </div>

      <div style="margin-top:10px;">
        <label>Content (HTML)</label><br />
        <textarea style="width:100%;min-height:140px;" v-model="form.content_html"></textarea>
      </div>

      <button style="margin-top:10px;" @click="createLesson">Create</button>

      <p v-if="msg" style="color:green">{{ msg }}</p>
      <p v-if="error" style="color:#b00020">{{ error }}</p>
    </div>

    <h3 style="margin-top:18px;">Existing lessons</h3>
    <ul>
      <li v-for="x in lessons" :key="x.id">
        <b>{{ x.language_code }}</b> {{ x.level }} — {{ x.title }}
        <button style="margin-left:10px;" @click="deleteLesson(x.id)">Delete</button>
      </li>
    </ul>
  </div>
</template>