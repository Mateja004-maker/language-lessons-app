<script setup>
import { onMounted, ref } from 'vue'
import { api } from '@/services/api'

const languages = ref([])
const users = ref([])

const email = ref('')
const password = ref('')
const display_name = ref('')
const role = ref('STUDENT')
const learning_language_id = ref('')

const error = ref('')
const msg = ref('')
const loading = ref(false)

const currentRole = localStorage.getItem('user_role')

async function loadLanguages() {
  const { data } = await api.get('/languages')
  languages.value = data
}

async function loadUsers() {
  const { data } = await api.get('/users')
  users.value = data
}

async function loadAll() {
  error.value = ''
  loading.value = true
  try {
    await Promise.all([loadLanguages(), loadUsers()])
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da učitam podatke.'
  } finally {
    loading.value = false
  }
}

async function createUser() {
  error.value = ''
  msg.value = ''

  if (!email.value.trim() || !password.value.trim()) {
    error.value = 'Email i password su obavezni.'
    return
  }

  try {
    await api.post('/users', {
      email: email.value.trim(),
      password: password.value.trim(),
      display_name: display_name.value.trim(),
      role: role.value,
      learning_language_id: learning_language_id.value || null
    })

    email.value = ''
    password.value = ''
    display_name.value = ''
    role.value = 'STUDENT'
    learning_language_id.value = ''

    msg.value = 'Korisnik uspešno kreiran.'
    await loadAll()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da kreiram korisnika.'
  }
}

async function deleteUser(user) {
  error.value = ''
  msg.value = ''

  const confirmed = confirm(
    `Da li sigurno želiš da obrišeš korisnika ${user.email}?`
  )
  if (!confirmed) return

  try {
    await api.delete(`/users/${user.id}`)
    msg.value = 'Korisnik je obrisan.'
    await loadUsers()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da obrišem korisnika.'
  }
}
async function approveUser(user) {
  error.value = ''
  msg.value = ''

  try {
    await api.patch(`/users/${user.id}/approve`)
    msg.value = 'Korisnik je odobren.'
    await loadUsers()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da odobrim korisnika.'
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="container py-4">

    <div class="page-header">
      <div class="page-title">Users</div>
      <div class="page-subtitle">
        Kreiranje i upravljanje studentima i nastavnicima
      </div>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>
    <div v-if="loading" class="text-muted">Loading...</div>

    <div class="section-card section-padding mb-4">
      <h5 class="mb-3">Create User</h5>

      <div class="row g-3">
        <div class="col-md-6">
          <label class="form-label">Display name</label>
          <input v-model="display_name" class="form-control" />
        </div>

        <div class="col-md-6">
          <label class="form-label">Email</label>
          <input v-model="email" class="form-control" />
        </div>

        <div class="col-md-6">
          <label class="form-label">Password</label>
          <input v-model="password" type="password" class="form-control" />
        </div>

        <div class="col-md-3">
          <label class="form-label">Role</label>
          <select v-model="role" class="form-select">
            <option value="STUDENT">STUDENT</option>
            <option value="TEACHER">TEACHER</option>
          </select>
        </div>

        <div class="col-md-3">
          <label class="form-label">Language</label>
          <select v-model="learning_language_id" class="form-select">
            <option value="">-- Select --</option>
            <option v-for="l in languages" :key="l.id" :value="l.id">
              {{ l.name }}
            </option>
          </select>
        </div>
      </div>

      <div class="mt-4 text-end">
        <button class="btn btn-primary px-4" @click="createUser">
          Create User
        </button>
      </div>
    </div>

    <div class="section-card section-padding">
      <div class="d-flex justify-content-between align-items-center mb-3">
        <h5 class="m-0">All Users</h5>
        <button class="btn btn-outline-secondary btn-sm" @click="loadUsers">
          Refresh
        </button>
      </div>

      <div class="table-responsive">
        <table class="table table-hover align-middle">
          <thead class="table-light">
            <tr>
              <th>ID</th>
              <th>Name</th>
              <th>Email</th>
              <th>Role</th>
              <th>Language</th>
              <th>Status</th>
              <th class="text-end">Actions</th>
            </tr>
          </thead>

          <tbody>
            <tr v-for="u in users" :key="u.id">
              <td>{{ u.id }}</td>
              <td>{{ u.display_name || '-' }}</td>
              <td>{{ u.email }}</td>
              <td>
                <span v-if="u.role === 'ADMIN'" class="badge text-bg-danger">ADMIN</span>
                <span v-else-if="u.role === 'TEACHER'" class="badge text-bg-warning">TEACHER</span>
                <span v-else class="badge text-bg-success">STUDENT</span>
              </td>
              <td>{{ u.learning_language_name || '-' }}</td>
              <td>
                <span v-if="u.is_active == 1" class="badge text-bg-success">
                  Approved
                </span>

                <span v-else class="badge text-bg-secondary">
                  Pending
                </span>
              </td>
              <td class="text-end">
                <div class="d-flex justify-content-end gap-2">
                  <button
                    v-if="u.is_active != 1 && u.role !== 'ADMIN'"
                    class="btn btn-outline-success btn-sm"
                    @click="approveUser(u)"
                  >
                    Approve
                  </button>

                  <button
                    v-if="u.role !== 'ADMIN'"
                    class="btn btn-outline-danger btn-sm"
                    @click="deleteUser(u)"
                  >
                    Delete
                  </button>

                  <span v-if="u.role === 'ADMIN'" class="text-muted small">
                    Protected
                  </span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

  </div>
</template>