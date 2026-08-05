<script setup>
import { ref } from 'vue'
import { api } from '@/services/api'

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
    error.value = 'Email and password are required.'
    return
  }

  try {
    await api.post('/auth/register', {
      email: email.value.trim(),
      password: password.value.trim(),
      display_name: display_name.value.trim(),
      role: role.value
    })

    msg.value = 'Registration submitted. Please wait for administrator approval.'

    display_name.value = ''
    email.value = ''
    password.value = ''
    role.value = 'STUDENT'
  } catch (e) {
    error.value = e?.response?.data?.error || 'Registration failed.'
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
              <div class="mb-3 register-hero-icon">
                <i class="fa-solid fa-sparkles"></i>
              </div>

              <h1 class="fw-bold mb-3 register-hero-title">
                Create your learning account.
              </h1>

              <p class="text-muted fs-5 mb-4">
                Register for the platform, wait for administrator approval,
                and then start learning your selected language.
              </p>

              <div class="d-flex gap-3 flex-wrap">
                <span class="badge text-bg-primary px-3 py-2">Students</span>
                <span class="badge text-bg-success px-3 py-2">Teachers</span>
                <span class="badge text-bg-warning px-3 py-2">Admin approval</span>
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
                  Create Account
                </h2>

                <div class="text-muted">
                  Start your language learning journey
                </div>
              </div>

              <div class="alert alert-warning py-2 small">
                <i class="fa-solid fa-circle-info me-2"></i>
                Administrator approval is required before login.
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
                  Full Name
                </label>

                <input
                  v-model="display_name"
                  class="form-control"
                  placeholder="Enter your full name"
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
                  placeholder="Enter your email"
                />
              </div>

              <div class="mb-3">
                <label class="form-label fw-semibold">
                  <i class="fa-solid fa-lock me-1"></i>
                  Password
                </label>

                <input
                  v-model="password"
                  type="password"
                  class="form-control"
                  placeholder="Enter your password"
                />
              </div>

              <div class="mb-4">
                <label class="form-label fw-semibold">
                  <i class="fa-solid fa-user-tag me-1"></i>
                  Account Type
                </label>

                <select v-model="role" class="form-select">
                  <option value="STUDENT">Student</option>
                  <option value="TEACHER">Teacher</option>
                </select>
              </div>

              <button class="btn btn-primary w-100 auth-btn" @click="register">
                <i class="fa-solid fa-user-check me-2"></i>
                Sign Up
              </button>

              <div class="text-center mt-4">
                <RouterLink to="/login">
                  <i class="fa-solid fa-right-to-bracket me-1"></i>
                  Already have an account? Sign in
                </RouterLink>
              </div>
            </div>

            <div class="text-center text-muted small mt-4">
              © {{ new Date().getFullYear() }} Language Lessons
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
  border-radius: 24px;
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

.register-hero-icon {
  font-size: 3rem;
}

.register-hero-title {
  font-size: 3rem;
  line-height: 1.1;
}
</style>