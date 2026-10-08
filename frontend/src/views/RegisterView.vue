<script setup>
import { ref } from 'vue'
import { api } from '@/services/api'
import AppIllustration from '@/components/AppIllustration.vue'

const display_name = ref('')
const email = ref('')
const password = ref('')
const role = ref('STUDENT')

const error = ref('')
const msg = ref('')

async function register() {
  error.value = ''
  msg.value = ''

  if (!email.value.trim() || !password.value.trim()) {
    error.value = 'Email i lozinka su obavezni.'
    return
  }

  try {
    await api.post('/auth/register', {
      email: email.value.trim(),
      password: password.value.trim(),
      display_name: display_name.value.trim(),
      role: role.value
    })

    msg.value = 'Registracija je poslata. Sačekaj odobrenje administratora.'

    display_name.value = ''
    email.value = ''
    password.value = ''
    role.value = 'STUDENT'
  } catch (e) {
    error.value = e?.response?.data?.error || 'Registracija nije uspela.'
  }
}
</script>

<template>
  <div class="container py-5">
    <div class="row justify-content-center align-items-center min-vh-100">
      <div class="col-12 col-lg-10">
        <div class="row g-4 align-items-center">

          <!-- LEFT -->
          <div class="col-lg-6 d-none d-lg-block">
            <div class="pe-4">
              <div class="mb-3">
                <AppIllustration kind="register" :size="200" />
              </div>

              <h1 class="fw-bold mb-3 register-hero-title">
                Napravi nalog.
              </h1>

              <p class="text-muted fs-5 mb-4">
                Registruj se, sačekaj odobrenje administratora, a zatim pristupi
                svojim predmetima, lekcijama i testovima.
              </p>

              <div class="d-flex gap-3 flex-wrap">
                <span class="badge text-bg-primary px-3 py-2">Studenti</span>
                <span class="badge text-bg-success px-3 py-2">Nastavnici</span>
                <span class="badge text-bg-warning px-3 py-2">Odobrenje administratora</span>
              </div>
            </div>
          </div>

          <!-- CARD -->
          <div class="col-12 col-lg-6">
            <div class="section-card section-padding auth-card mx-auto">
              <div class="text-center mb-4">
                <div class="mb-2 auth-icon">
                  <i class="fa-solid fa-user-plus"></i>
                </div>

                <h2 class="fw-bold mb-1">
                  Registracija
                </h2>

                <div class="text-muted">
                  Nalog za studente i nastavnike
                </div>
              </div>

              <div class="alert alert-warning py-2 small">
                <i class="fa-solid fa-circle-info me-2"></i>
                Pre prve prijave nalog mora da odobri administrator.
              </div>

              <div v-if="error" class="alert alert-danger">
                <i class="fa-solid fa-triangle-exclamation me-2"></i>
                {{ error }}
              </div>

              <div v-if="msg" class="alert alert-success">
                <i class="fa-solid fa-circle-check me-2"></i>
                {{ msg }}
              </div>

              <div class="mb-3">
                <label class="form-label fw-semibold">
                  <i class="fa-solid fa-user me-1"></i>
                  Ime i prezime
                </label>

                <input
                  v-model="display_name"
                  class="form-control"
                  placeholder="Unesi ime i prezime"
                />
              </div>

              <div class="mb-3">
                <label class="form-label fw-semibold">
                  <i class="fa-solid fa-envelope me-1"></i>
                  Email
                </label>

                <input
                  v-model="email"
                  type="email"
                  class="form-control"
                  placeholder="Unesi email"
                />
              </div>

              <div class="mb-3">
                <label class="form-label fw-semibold">
                  <i class="fa-solid fa-lock me-1"></i>
                  Lozinka
                </label>

                <input
                  v-model="password"
                  type="password"
                  class="form-control"
                  placeholder="Unesi lozinku"
                />
              </div>

              <div class="mb-4">
                <label class="form-label fw-semibold">
                  <i class="fa-solid fa-user-tag me-1"></i>
                  Vrsta naloga
                </label>

                <select v-model="role" class="form-select">
                  <option value="STUDENT">Student</option>
                  <option value="TEACHER">Nastavnik</option>
                </select>
              </div>

              <button class="btn btn-primary w-100 auth-btn" @click="register">
                <i class="fa-solid fa-user-check me-2"></i>
                Registruj se
              </button>

              <div class="text-center mt-4">
                <RouterLink to="/login">
                  <i class="fa-solid fa-right-to-bracket me-1"></i>
                  Već imaš nalog? Prijavi se
                </RouterLink>
              </div>
            </div>

            <div class="text-center text-muted small mt-4">
              © {{ new Date().getFullYear() }} Onlajn testiranje
            </div>
          </div>

        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-card {
  max-width: 520px;
  border-radius: var(--app-radius);
}

.auth-icon {
  font-size: 2.5rem;
}

.auth-card .form-control,
.auth-card .form-select {
  padding: 12px 14px;
}

.auth-btn {
  padding: 12px;
  font-weight: 700;
}

.register-hero-title {
  font-size: 3rem;
  line-height: 1.1;
}
</style>