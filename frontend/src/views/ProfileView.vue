<script setup>
import PageHeader from '@/components/PageHeader.vue'
import { onMounted, ref, computed } from 'vue'
import { api } from '@/services/api'

const profile = ref(null)
const subjects = ref([])
const display_name = ref('')
const error = ref('')
const msg = ref('')
const loading = ref(false)

const languageLabel = computed(() => {
  if (!profile.value) return ''

  if (profile.value.role === 'TEACHER') {
    return 'Predmeti koje predaješ'
  }

  if (profile.value.role === 'STUDENT') {
    return 'Predmeti koje pratiš'
  }

  return 'Predmeti'
})

const subjectNames = computed(() => {
  if (!profile.value?.subjects || !subjects.value.length) return ''
  return profile.value.subjects
    .map(id => subjects.value.find(s => s.id === id)?.name)
    .filter(Boolean)
    .join(', ')
})

const selectedImage = ref(null)
const previewImage = ref('')

async function loadProfile() {
  error.value = ''
  msg.value = ''
  loading.value = true

  try {
    const [profileRes, subjectsRes] = await Promise.all([
      api.get('/profile'),
      api.get('/subjects')
    ])

    profile.value = profileRes.data
    display_name.value = profileRes.data.display_name || ''
    subjects.value = subjectsRes.data
  } catch (e) {
    error.value = e?.response?.data?.error || 'Učitavanje profila nije uspelo.'
  } finally {
    loading.value = false
  }
}

async function saveProfile() {
  error.value = ''
  msg.value = ''

  try {
    await api.put('/profile', {
      display_name: display_name.value,
      learning_language_id: profile.value.learning_language_id || null
    })
    msg.value = 'Profil je sačuvan.'
    await loadProfile()
    window.location.reload()
    
  } catch (e) {
    error.value = e?.response?.data?.error || 'Čuvanje profila nije uspelo.'
  }
}
function onImageChange(event) {
  const file = event.target.files[0]

  if (!file) return

  selectedImage.value = file
  previewImage.value = URL.createObjectURL(file)
}

async function uploadProfileImage() {
  error.value = ''
  msg.value = ''

  if (!selectedImage.value) {
    error.value = 'Prvo izaberi sliku.'
    return
  }

  try {
    const formData = new FormData()
    formData.append('image', selectedImage.value)

    await api.post('/profile/image', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })

    msg.value = 'Profilna slika je sačuvana.'
    await loadProfile()
    window.location.reload()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Čuvanje profilne slike nije uspelo.'
  }
}

onMounted(loadProfile)
</script>

<template>
  <div class="container py-4">

    <PageHeader title="Moj profil" />

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>

    <div v-if="loading" class="text-muted">Učitavanje...</div>

    <div v-if="profile" class="section-card section-padding">
      <div class="text-center mb-4">
        <img
          :src="previewImage || (profile.profile_image ? `http://127.0.0.1:5000${profile.profile_image}` : 'https://via.placeholder.com/120')"
          alt="Profilna slika"
          class="profile-image"
        />

        <div class="mt-3">
          <input
            type="file"
            class="form-control"
            accept="image/png, image/jpeg, image/jpg, image/webp"
            @change="onImageChange"
          />
        </div>

        <button
          class="btn btn-outline-secondary mt-3"
          type="button"
          @click="uploadProfileImage"
        >
          Sačuvaj profilnu sliku
        </button>
      </div>

      <div class="row g-3">

        <div class="col-md-6">
          <label class="form-label">Email</label>
          <input class="form-control" :value="profile.email" disabled />
        </div>

        <div class="col-md-6">
          <label class="form-label">Uloga</label>

          <div>
            <span v-if="profile.role === 'ADMIN'" class="badge badge-soft fs-6">Administrator</span>
            <span v-else-if="profile.role === 'TEACHER'" class="badge badge-soft fs-6">Nastavnik</span>
            <span v-else class="badge badge-soft fs-6">Student</span>
          </div>
        </div>

        <div class="col-md-6">
          <label class="form-label">Ime i prezime</label>
          <input v-model="display_name" class="form-control" />
        </div>

        <div v-if="profile.role !== 'ADMIN'" class="col-md-6">
          <label class="form-label">{{ languageLabel }}</label>
          <input
            class="form-control"
            :value="subjectNames || 'Nije izabran nijedan predmet'"
            disabled
          />
          <small class="text-muted">
            Predmete dodeljuje administrator (ili ih biraš pri prvoj prijavi).
          </small>
        </div>

      </div>

      <div class="mt-4 text-end">
        <button class="btn btn-primary px-4" @click="saveProfile">
          Sačuvaj izmene
        </button>
      </div>

    </div>

  </div>
</template>

<style scoped>
.profile-image {
  width: 120px;
  height: 120px;
  border-radius: 50%;
  object-fit: cover;
  border: 4px solid var(--app-border);
}
</style>