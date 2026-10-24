// Pomocne funkcije za AI objasnjenja (Andrejev modul) - bez zavisnosti od Vue-a,
// da mogu da se testiraju zasebno.
//
// Predlog objasnjenja (ai_generated_artifacts.original_text / edited_text) je
// JSON string:
//   mode_a: {"explanation": "..."}
//   mode_b: {"solution": "...", "explanation": "..."}
// Studentska ruta ga parsira sa json.loads, pa edited_text MORA biti JSON
// string istog oblika - inace pada prikaz studentu.

export function parseProposal(text) {
  if (typeof text !== 'string') return null
  try {
    const value = JSON.parse(text)
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null
  } catch {
    return null
  }
}

// Vraca { text } (JSON string spreman za edited_text) ili { error }.
// MC predlog iz rezima B ({"selected_option", "explanation"}): pozivalac prosledjuje
// selectedOption iz originala; prenosi se nepromenjen, menja se samo objasnjenje.
export function buildEditedText(mode, fields = {}) {
  const { explanation, solution, selectedOption } = fields
  const exp = typeof explanation === 'string' ? explanation.trim() : ''
  if (!exp) return { error: 'Objašnjenje ne sme biti prazno.' }

  const isMc = mode === 'mode_b' && 'selectedOption' in fields
  const payload = {}
  if (isMc) {
    // isti kriterijum kao backend (int(selected_option), bool odbijen)
    const isNumber = (typeof selectedOption === 'number' || typeof selectedOption === 'string')
      && String(selectedOption).trim() !== '' && Number.isInteger(Number(selectedOption))
    if (!isNumber) {
      return { error: 'Nedostaje izabrana opcija iz originalnog predloga.' }
    }
    payload.selected_option = selectedOption
  } else if (mode === 'mode_b') {
    // resenje se ne trimuje (uvlacenje je deo koda), samo se proverava da nije prazno
    if (typeof solution !== 'string' || !solution.trim()) {
      return { error: 'Rešenje ne sme biti prazno.' }
    }
    payload.solution = solution
  }
  payload.explanation = exp

  const text = JSON.stringify(payload)
  const back = parseProposal(text)
  const expectedKeys = isMc
    ? ['explanation', 'selected_option']
    : mode === 'mode_b' ? ['explanation', 'solution'] : ['explanation']
  if (!back || JSON.stringify(Object.keys(back).sort()) !== JSON.stringify(expectedKeys)) {
    return { error: 'Izmena nije u ispravnom obliku.' }
  }
  return { text }
}

// accuracy_check_details je JSON lista rezultata po test primeru (programski
// zadaci), JSON objekat sa selected_option (MC pitanja u rezimu B), ili obican
// tekst (npr. "Nema definisanih test primera ..." ili "Nevalidan izbor...").
// Vraca { rows } ili { message }.
export function parseAccuracyDetails(text) {
  if (typeof text !== 'string' || !text.trim()) return { message: null }
  try {
    const value = JSON.parse(text)
    if (Array.isArray(value)) return { rows: value }
    if (value && typeof value === 'object' && 'selected_option' in value) {
      const correctAnswer = value.correct_answer ?? 'nepoznat'
      return {
        message: `Izabran odgovor: '${value.selected_answer}', tačan odgovor: '${correctAnswer}'`
      }
    }
  } catch {
    // nije JSON - prikazuje se kao tekst
  }
  return { message: text }
}

// Backend salje datum kao "Mon, 28 Sep 2026 17:35:44 GMT", ali je u bazi
// lokalno vreme bez zone - zato UTC getteri, da se prikaze tacno vreme iz baze.
export function formatDbDate(value) {
  const d = new Date(value)
  if (!value || Number.isNaN(d.getTime())) return value || ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getUTCDate())}.${pad(d.getUTCMonth() + 1)}.${d.getUTCFullYear()}. ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
}
