<script setup>
import PageHeader from '@/components/PageHeader.vue'
import { onMounted, ref } from 'vue'
import { api } from '@/services/api'

const languages = ref([])
const code = ref('')
const name = ref('')
const error = ref('')
const msg = ref('')
const loading = ref(false)

async function load() {
  error.value = ''
  loading.value = true
  try {
    const { data } = await api.get('/languages')
    languages.value = data
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da učitam jezike.'
  } finally {
    loading.value = false
  }
}

async function addLanguage() {
  error.value = ''
  msg.value = ''

  if (!code.value.trim() || !name.value.trim()) {
    error.value = 'Popuni code i name.'
    return
  }

  try {
    await api.post('/languages', {
      code: code.value.trim(),
      name: name.value.trim()
    })
    code.value = ''
    name.value = ''
    msg.value = 'Jezik dodat.'
    await load()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da dodam jezik.'
  }
}

async function deleteLanguage(lang) {
  error.value = ''
  msg.value = ''

  const confirmed = confirm(
    `Da li sigurno želiš da obrišeš jezik "${lang.name}" (${lang.code})?`
  )
  if (!confirmed) return

  try {
    await api.delete(`/languages/${lang.id}`)
    msg.value = 'Jezik je obrisan.'
    await load()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da obrišem jezik.'
  }
}

onMounted(load)
</script>

<template>
  
  <div class="container py-4">
    <PageHeader title="Admin: Languages">
      <button class="btn btn-outline-secondary" :disabled="loading" @click="load">
        Refresh
      </button>
    </PageHeader>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>

    <div class="section-card section-padding">
      <div class="card-body">
        <h5 class="card-title mb-3">Add language</h5>

        <div class="row g-2 align-items-end">
          <div class="col-12 col-md-3">
            <label class="form-label">Code</label>
            <input v-model="code" class="form-control" placeholder="en" />
          </div>

          <div class="col-12 col-md-5">
            <label class="form-label">Name</label>
            <input v-model="name" class="form-control" placeholder="English" />
          </div>

          <div class="col-12 col-md-2">
            <button class="btn btn-primary w-100" @click="addLanguage">Add</button>
          </div>
        </div>
      </div>
    </div>

    <div class="card shadow-sm">
      <div class="card-body">
        <h5 class="card-title mb-3">Languages</h5>

        <div v-if="loading" class="text-muted">Loading...</div>

        <div v-else class="table-responsive">
          <table class="table table-hover align-middle">
            <thead class="table-light">
              <tr>
                <th>ID</th>
                <th>Code</th>
                <th>Name</th>
                <th class="text-end">Actions</th>
              </tr>
            </thead>

            <tbody>
              <tr v-for="l in languages" :key="l.id">
                <td>{{ l.id }}</td>
                <td><span class="badge text-bg-light border">{{ l.code }}</span></td>
                <td class="fw-semibold">{{ l.name }}</td>
                <td class="text-end">
                  <button
                    class="btn btn-outline-danger btn-sm"
                    @click="deleteLanguage(l)"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            </tbody>
          </table>

          <div class="text-muted small">
            Jezik može da se obriše samo ako nema lekcije povezane sa njim.
          </div>
        </div>
      </div>
    </div>
  </div>
</template>