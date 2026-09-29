import axios from 'axios'

export const api = axios.create({
    baseURL: '/api'
}) // Frontend sve zahteve salje na /api(/api ne mora da se pise u svaku api rutu u frontendu)


console.log('API FILE LOADED')

// Dodaj JWT token u svaki zahtev (ako postoji)
api.interceptors.request.use((config) => {
    const token = localStorage.getItem('access_token')
    if (token) config.headers.Authorization = `Bearer ${token}`
    return config
})

// Ako backend vrati 401, izbaci usera na login
api.interceptors.response.use(
    (res) => res,
    (err) => {
        if (err?.response?.status === 401) {
            localStorage.removeItem('access_token')
            localStorage.removeItem('user_role')
            // hard redirect da bude jednostavno
            window.location.href = '/login'
        }
        return Promise.reject(err)
    }
)

// =========================
// EXAMS API
// =========================

export const getExams = () => api.get('/exams')

export const createExam = (data) => api.post('/exams', data)

export const getExamDetails = (id) => api.get(`/exams/${id}`)

export const addExamQuestion = (examId, data) =>
  api.post(`/exams/${examId}/questions`, data)

// Postojece pitanje iz banke u test (exam_test_questions); 409 ako je vec u
// testu, 400 ako je iz drugog predmeta.
export const assignBankQuestionToExam = (examId, questionId, orderNo) =>
  api.post(`/exams/${examId}/questions/${questionId}`, { order_no: orderNo })

// Uklanja pitanje samo iz ovog testa - pitanje ostaje u banci.
export const removeQuestionFromExam = (examId, questionId) =>
  api.delete(`/exams/${examId}/questions/${questionId}`)

export const addQuestionAnswer = (questionId, data) =>
  api.post(`/questions/${questionId}/answers`, data)

export const getQuestionAnswers = (questionId) =>
  api.get(`/questions/${questionId}/answers`)

export const deleteQuestion = (id) => api.delete(`/questions/${id}`)

export const deleteAnswer = (id) => api.delete(`/answers/${id}`)

export const updateQuestion = (id, data) =>
  api.put(`/questions/${id}`, data)

export const updateAnswer = (id, data) =>
  api.put(`/answers/${id}`, data)

export const publishExam = (id) =>
  api.put(`/exams/${id}/publish`)

export const deleteExam = (id) => api.delete(`/exams/${id}`)

export const submitExam = (examId, data) =>
  api.post(`/exams/${examId}/submit`, data)

export const getExamResults = (examId) =>
  api.get(`/exams/${examId}/results`)

export const getMyResults = () =>
  api.get('/my-results')

export const getMyResultDetail = (attemptId) =>
  api.get(`/my-results/${attemptId}`)


export const exportExamResults = (examId) =>
  api.get(`/exams/${examId}/results/export`, {
    responseType: 'blob'
  })

// =========================
// SUBJECTS / AREAS / QUESTION BANK API
// =========================

export const getSubjects = () => api.get('/subjects')

export const getAreas = (subjectId) =>
  api.get(`/subjects/${subjectId}/areas`)

export const addArea = (subjectId, data) =>
  api.post(`/subjects/${subjectId}/areas`, data)

export const getBankQuestions = (subjectId, areaId) =>
  api.get(`/subjects/${subjectId}/questions`, {
    params: areaId ? { area_id: areaId } : {}
  })

export const addBankQuestion = (subjectId, data) =>
  api.post(`/subjects/${subjectId}/questions`, data)

// =========================
// AI ARTIFACTS API
// =========================

export const getAiArtifacts = (status = 'predlog') =>
  api.get('/ai/artifacts', { params: { status } })

export const getAiArtifact = (id) =>
  api.get(`/ai/artifacts/${id}`)

export const reviewAiArtifact = (id, data) =>
  api.post(`/ai/artifacts/${id}/review`, data)

// Mistral je privremeno blokiran (429, limit 0 zahteva/min) - dugme je
// skriveno na ekranima za generisanje; backend ga i dalje podržava.
export const MISTRAL_ENABLED = false

export const generateSimilarQuestion = (questionId, provider) =>
  api.post(`/questions/${questionId}/generate-similar`, null, {
    params: { provider }
  })

// =========================
// AI OBJASNJENJA API (Andrejev modul)
// =========================

// mode: 'mode_a' | 'mode_b'; evaluationBatchId je opcion (bez njega run je
// razvojna proba) - axios izostavlja undefined parametre.
export const generateExplanation = (questionId, mode, provider, evaluationBatchId) =>
  api.post(`/questions/${questionId}/generate-explanation`, null, {
    params: { mode, provider, evaluation_batch_id: evaluationBatchId }
  })

export const getExplanationArtifacts = (status = 'predlog') =>
  api.get('/ai-artifacts/explanation', { params: { status } })

export const getExplanationArtifact = (id) =>
  api.get(`/ai-artifacts/explanation/${id}`)

// data: { action: 'approve' | 'edit' | 'reject', scores, edited_text, rejection_reason }
// edited_text mora biti JSON string istog oblika kao original
// ({"explanation": ...} ili {"solution": ..., "explanation": ...}) - studentska
// ruta ga parsira sa json.loads.
export const reviewExplanationArtifact = (id, data) =>
  api.post(`/ai-artifacts/explanation/${id}/review`, data)

export const getQuestionExplanation = (questionId, mode) =>
  api.get(`/questions/${questionId}/explanation`, { params: { mode } })

// scores: [{ dimension_key, score, comment? }] za sve STUDENT dimenzije
export const rateExplanationArtifact = (id, scores) =>
  api.post(`/ai-artifacts/explanation/${id}/rate`, { scores })
