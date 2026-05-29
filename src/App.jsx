import React, { useState, useReducer, useCallback } from 'react'
import SettingsPanel from './components/SettingsPanel'
import InputBar from './components/InputBar'
import ResultsTable from './components/ResultsTable'

const STORAGE_KEY_CORRECTIONS = 'modapts_corrections'
const STORAGE_KEY_ACCEPTED = 'modapts_accepted'

function loadFromStorage(key) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function saveToStorage(key, data) {
  try { localStorage.setItem(key, JSON.stringify(data)) } catch {}
}

function resultsReducer(state, action) {
  switch (action.type) {
    case 'add':
      return [{ id: Date.now(), input: action.input, result: action.result, expanded: true }, ...state]
    case 'toggle':
      return state.map(r => r.id === action.id ? { ...r, expanded: !r.expanded } : r)
    case 'update_result':
      return state.map(r => r.id === action.id ? { ...r, result: action.result } : r)
    default:
      return state
  }
}

export default function App() {
  const [settings, setSettings] = useState({
    provider: 'anthropic',
    model: 'claude-sonnet-4-20250514',
    apiKey: '',
  })
  const [showSettings, setShowSettings] = useState(true)
  const [results, dispatch] = useReducer(resultsReducer, [])
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

  return (
    <>
      <header className="header">
        <h1>MODAPTS<span>/v2</span></h1>
        <div className="header-right">
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
      />
    </>
  )
}
