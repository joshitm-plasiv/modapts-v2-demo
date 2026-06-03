import React, { useState, useReducer, useCallback } from 'react'
import SettingsPanel from './components/SettingsPanel'
import InputBar from './components/InputBar'
import ResultsTable from './components/ResultsTable'

const STORAGE_KEY_CORRECTIONS = 'modapts_corrections'
const STORAGE_KEY_ACCEPTED = 'modapts_accepted'
const STORAGE_KEY_RESULTS = 'modapts_results'

function loadFromStorage(key) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function saveToStorage(key, data) {
  try { localStorage.setItem(key, JSON.stringify(data)) } catch {}
}

// Diff two results (before/after a single fact-override) for in-place highlighting.
// Matches steps by event_index + position; flags changed code/native, added/removed steps,
// and the total delta. Used only for single overrides (sweep handles multi-value).
function computeDiff(before, after) {
  const key = (s, i) => `${s.event_index == null ? 'x' : s.event_index}:${i}`
  const beforeMap = {}
  ;(before.steps || []).forEach((s, i) => { beforeMap[key(s, i)] = s })
  const stepFlags = (after.steps || []).map((s, i) => {
    const b = beforeMap[key(s, i)]
    if (!b) return { status: 'added' }
    if (b.code !== s.code || b.native !== s.native) {
      return { status: 'changed', oldCode: b.code, oldNative: b.native }
    }
    return { status: 'same' }
  })
  const beforeSecs = before.total_seconds ?? null
  const afterSecs = after.total_seconds ?? null
  const delta = (beforeSecs != null && afterSecs != null) ? +(afterSecs - beforeSecs).toFixed(3) : null
  return { stepFlags, beforeSecs, afterSecs, delta }
}

function resultsReducer(state, action) {
  let next
  switch (action.type) {
    case 'add':
      next = [{ id: Date.now(), input: action.input, result: action.result, expanded: true }, ...state]
      break
    case 'toggle':
      next = state.map(r => r.id === action.id ? { ...r, expanded: !r.expanded } : r)
      break
    case 'update_result':
      // a fresh classification/override/reinterpret clears any open sweep panel.
      // If action.diffFrom is set (single fact-override), compute a per-step diff to highlight.
      next = state.map(r => {
        if (r.id !== action.id) return r
        const diff = action.diffFrom ? computeDiff(action.diffFrom, action.result) : null
        return { ...r, result: action.result, sweep: null, diff }
      })
      break
    case 'set_sweep':
      next = state.map(r => r.id === action.id ? { ...r, sweep: action.sweep } : r)
      break
    case 'clear_sweep':
      next = state.map(r => r.id === action.id ? { ...r, sweep: null } : r)
      break
    case 'clear':
      next = []
      break
    default:
      return state
  }
  saveToStorage(STORAGE_KEY_RESULTS, next)
  return next
}

export default function App() {
  const [settings, setSettings] = useState({
    standard: 'MTM-UAS',
    provider: 'anthropic',
    model: 'claude-sonnet-4-6',
    apiKey: '',
  })
  const [showSettings, setShowSettings] = useState(true)
  const [results, dispatch] = useReducer(resultsReducer, [], () => loadFromStorage(STORAGE_KEY_RESULTS))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const corrections = loadFromStorage(STORAGE_KEY_CORRECTIONS)
  const isConfigured = settings.apiKey && settings.provider && settings.model

  const classify = useCallback(async (input) => {
    if (!isConfigured) {
      setError('Enter your API key in settings first')
      setShowSettings(true)
      return
    }
    setError(null)
    setLoading(true)
    try {
      const res = await fetch('/api/classify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input,
          standard: settings.standard,
          provider: settings.provider,
          model: settings.model,
          api_key: settings.apiKey,
          corrections,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
      dispatch({ type: 'add', input, result: data })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [settings, isConfigured, corrections])

  const submitCodeEdit = useCallback(async (resultId, stepIndex, originalInput, originalCode, newCode, why) => {
    setError(null)
    try {
      const res = await fetch('/api/feedback?path=code_edit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          original_input: originalInput,
          original_code: originalCode,
          corrected_code: newCode,
          why,
          provider: settings.provider,
          model: settings.model,
          api_key: settings.apiKey,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
      return data
    } catch (e) {
      setError(e.message)
      return null
    }
  }, [settings])

  const completeCodeEdit = useCallback((originalInput, originalCode, correctedCode, why, clarifyQ, clarifyA) => {
    const record = {
      type: 'code_edit',
      timestamp: new Date().toISOString(),
      original_input: originalInput,
      original_code: originalCode,
      corrected_code: correctedCode,
      why,
      clarifying_question: clarifyQ || null,
      operator_answer: clarifyA || null,
      few_shot_text: `Input: '${originalInput}'\nOriginal: ${originalCode} → Corrected: ${correctedCode}\nReason: ${[why, clarifyA].filter(Boolean).join(', ')}`,
    }
    const updated = [...corrections, record]
    saveToStorage(STORAGE_KEY_CORRECTIONS, updated)
  }, [corrections])

  const submitReinterpret = useCallback(async (resultId, originalInput, originalInterp, correctedInterp) => {
    setError(null)
    try {
      const res = await fetch('/api/feedback?path=reinterpret', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          corrected_interpretation: correctedInterp,
          standard: settings.standard,
          provider: settings.provider,
          model: settings.model,
          api_key: settings.apiKey,
          corrections,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)

      // Store interpretation correction
      const record = {
        type: 'interpretation_edit',
        timestamp: new Date().toISOString(),
        original_input: originalInput,
        original_interpretation: originalInterp,
        corrected_interpretation: correctedInterp,
        few_shot_text: `Input: '${originalInput}'\nOriginal interpretation: '${originalInterp}'\nCorrect interpretation: '${correctedInterp}'`,
      }
      saveToStorage(STORAGE_KEY_CORRECTIONS, [...corrections, record])

      dispatch({ type: 'update_result', id: resultId, result: data })
    } catch (e) {
      setError(e.message)
    }
  }, [settings, corrections])

  const acceptResult = useCallback((originalInput, result) => {
    const record = {
      type: 'accepted',
      timestamp: new Date().toISOString(),
      original_input: originalInput,
      ...result,
    }
    const accepted = loadFromStorage(STORAGE_KEY_ACCEPTED)
    saveToStorage(STORAGE_KEY_ACCEPTED, [...accepted, record])
  }, [])

  // Sensing-ambiguity resolution: re-classify with the operator's answer.
  const resolveClarification = useCallback(async (resultId, originalInput, question, answer) => {
    setError(null)
    setLoading(true)
    try {
      const res = await fetch('/api/classify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input: originalInput,
          standard: settings.standard,
          provider: settings.provider,
          model: settings.model,
          api_key: settings.apiKey,
          corrections,
          clarification: { question, answer },
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
      dispatch({ type: 'update_result', id: resultId, result: data })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [settings, corrections])

  // Per-step fact correction: operator overrides an inferred fact (distance, weight,
  // fit) on the source event. Deterministic — patches the event, re-runs (all four if ALL).
  const submitFactOverride = useCallback(async (resultId, originalInput, eventIndex, patch) => {
    if (eventIndex == null) return
    setError(null)
    setLoading(true)
    // capture the current result for this row to diff against the override result
    const prior = results.find(r => r.id === resultId)
    const diffFrom = prior && !prior.result.compare ? prior.result : null
    try {
      const fact_overrides = []
      fact_overrides[eventIndex] = patch
      const res = await fetch('/api/classify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input: originalInput,
          standard: settings.standard,
          provider: settings.provider,
          model: settings.model,
          api_key: settings.apiKey,
          corrections,
          fact_overrides,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
      dispatch({ type: 'update_result', id: resultId, result: data, diffFrom })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [settings, corrections])

  // Multi-value sweep: one fact varied across N values, all engines, one interpretation.
  // Transient — does NOT overwrite the stored result; opens a what-if panel beside it.
  const submitSweep = useCallback(async (resultId, originalInput, eventIndex, field, values) => {
    if (eventIndex == null || !values.length) return
    setError(null)
    setLoading(true)
    try {
      const res = await fetch('/api/classify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input: originalInput,
          standard: 'SWEEP',
          event_index: eventIndex,
          field,
          values,
          provider: settings.provider,
          model: settings.model,
          api_key: settings.apiKey,
          corrections,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
      dispatch({ type: 'set_sweep', id: resultId, sweep: data })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [settings, corrections])

  return (
    <>
      <header className="header">
        <h1>PMTS<span>/v3</span></h1>
        <div className="header-right">
          {results.length > 0 && (
            <button
              className="settings-toggle"
              onClick={() => { if (confirm('Clear all classification history?')) dispatch({ type: 'clear' }) }}
            >
              Clear history
            </button>
          )}
          {corrections.length > 0 && (
            <span className="corrections-badge">{corrections.length} correction{corrections.length !== 1 ? 's' : ''}</span>
          )}
          <button
            className={`settings-toggle ${showSettings ? 'active' : ''}`}
            onClick={() => setShowSettings(!showSettings)}
          >
            {showSettings ? '▾ Settings' : '▸ Settings'}
          </button>
        </div>
      </header>

      {showSettings && (
        <SettingsPanel settings={settings} onChange={setSettings} />
      )}

      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="loading-bar" />}

      <InputBar onSubmit={classify} disabled={loading} />

      <ResultsTable
        results={results}
        onToggle={(id) => dispatch({ type: 'toggle', id })}
        onCodeEdit={submitCodeEdit}
        onCodeEditComplete={completeCodeEdit}
        onReinterpret={submitReinterpret}
        onAccept={acceptResult}
        onResolveClarification={resolveClarification}
        onFactOverride={submitFactOverride}
        onSweep={submitSweep}
        onClearSweep={(id) => dispatch({ type: 'clear_sweep', id })}
      />
    </>
  )
}
