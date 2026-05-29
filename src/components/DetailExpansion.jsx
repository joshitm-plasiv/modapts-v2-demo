import React, { useState } from 'react'

// 44 MODAPTS codes for dropdown
const ALL_CODES = [
  'M1','M2','M3','M4','M5','M7',
  'G0','G1','G3',
  'P0','P2','P5',
  'R2','R3',
  'D3',
  'E2','E4',
  'N3','N6',
  'W5','W2.36','W7.75',
  'F3',
  'C3','C4',
  'B17',
  'S30',
  'X4',
  'J2',
  'V3',
  'U0.5','U1','U2','U3',
  'L0','L1','L2',
  'H4','H5','H6','H7','H21','H26','H35',
]

export default function DetailExpansion({ resultId, input, result, onCodeEdit, onCodeEditComplete, onReinterpret, onAccept, onResolveClarification }) {
  // Interpretation editing (Path B)
  const [editingInterp, setEditingInterp] = useState(false)
  const [interpText, setInterpText] = useState(result.interpreted_action)

  // Sensing-ambiguity clarification (Instruction 6)
  const [clarifyResponse, setClarifyResponse] = useState('')

  // Code editing (Path A)
  const [editingStep, setEditingStep] = useState(null) // step index
  const [selectedCode, setSelectedCode] = useState('')
  const [whyText, setWhyText] = useState('')
  const [feedbackPhase, setFeedbackPhase] = useState(null) // null | 'why' | 'clarify'
  const [clarifyData, setClarifyData] = useState(null)
  const [clarifyAnswer, setClarifyAnswer] = useState('')
  const [feedbackLoading, setFeedbackLoading] = useState(false)

  // ── Path B: Interpretation edit ──
  const handleInterpSubmit = () => {
    const trimmed = interpText.trim()
    if (trimmed && trimmed !== result.interpreted_action) {
      onReinterpret(resultId, input, result.interpreted_action, trimmed)
    }
    setEditingInterp(false)
  }

  const handleInterpCancel = () => {
    setInterpText(result.interpreted_action)
    setEditingInterp(false)
  }

  // ── Path A: Code edit ──
  const startCodeEdit = (stepIndex) => {
    setEditingStep(stepIndex)
    setSelectedCode(result.steps[stepIndex].code)
    setWhyText('')
    setFeedbackPhase('why')
    setClarifyData(null)
    setClarifyAnswer('')
  }

  const cancelCodeEdit = () => {
    setEditingStep(null)
    setFeedbackPhase(null)
    setClarifyData(null)
  }

  const submitWhy = async () => {
    const step = result.steps[editingStep]
    if (selectedCode === step.code) {
      cancelCodeEdit()
      return
    }

    if (!whyText.trim()) {
      // Store without Call 2
      onCodeEditComplete(input, step.code, selectedCode, '', '', '')
      cancelCodeEdit()
      return
    }

    setFeedbackLoading(true)
    const data = await onCodeEdit(resultId, editingStep, input, step.code, selectedCode, whyText)
    setFeedbackLoading(false)

    if (data && data.clarifying_question) {
      setClarifyData(data)
      setFeedbackPhase('clarify')
    } else {
      // No clarifying question returned — store and close
      onCodeEditComplete(input, step.code, selectedCode, whyText, '', '')
      cancelCodeEdit()
    }
  }

  const submitClarify = () => {
    const step = result.steps[editingStep]
    onCodeEditComplete(
      input, step.code, selectedCode, whyText,
      clarifyData?.clarifying_question || '',
      clarifyAnswer
    )
    cancelCodeEdit()
  }

  // ── Sensing-ambiguity clarification view ──
  // When the LLM requested clarification, show only the question + answer box.
  if (result.needs_clarification) {
    return (
      <div className="detail-panel">
        <div className="feedback-inline" style={{ marginTop: 0 }}>
          <label>Clarification needed before coding</label>
          <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: '0 0 10px' }}>
            {result.clarifying_question}
          </p>
          <input
            type="text"
            value={clarifyResponse}
            onChange={e => setClarifyResponse(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && clarifyResponse.trim()) {
                onResolveClarification(resultId, input, result.clarifying_question, clarifyResponse.trim())
              }
            }}
            placeholder="Answer in your own words… e.g. 'I touch it to check' or 'there's a temperature gauge'"
            autoFocus
          />
          <div className="feedback-actions">
            <button
              className="btn-sm primary"
              onClick={() => onResolveClarification(resultId, input, result.clarifying_question, clarifyResponse.trim())}
              disabled={!clarifyResponse.trim()}
            >
              Submit answer
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="detail-panel">
      {/* Interpreted action */}
      <div className="detail-interpreted">
        <label>Interpreted</label>
        {editingInterp ? (
          <>
            <input
              type="text"
              value={interpText}
              onChange={e => setInterpText(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleInterpSubmit()}
              autoFocus
            />
            <button className="btn-sm primary" onClick={handleInterpSubmit}>Apply</button>
            <button className="btn-sm ghost" onClick={handleInterpCancel}>Cancel</button>
          </>
        ) : (
          <span className="detail-interpreted-text" onClick={() => setEditingInterp(true)}>
            {result.interpreted_action}
          </span>
        )}
      </div>

      {/* Steps table */}
      <table className="steps-table">
        <thead>
          <tr>
            <th className="col-motion">Motion</th>
            <th className="col-code">Code</th>
            <th className="col-mods">MODs</th>
            <th className="col-assumption">Assumption</th>
          </tr>
        </thead>
        <tbody>
          {result.steps.map((step, i) => (
            <tr key={i}>
              <td className="col-motion">{step.motion}</td>
              <td className="col-code">
                {editingStep === i ? (
                  <select
                    className="code-select"
                    value={selectedCode}
                    onChange={e => setSelectedCode(e.target.value)}
                  >
                    {ALL_CODES.map(c => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                ) : (
                  <span className="code-cell" onClick={() => startCodeEdit(i)}>
                    {step.code || '?'}
                  </span>
                )}
              </td>
              <td className="col-mods" style={{ fontFamily: 'var(--mono)', textAlign: 'right' }}>
                {step.mods != null ? (step.mods === Math.floor(step.mods) ? step.mods : step.mods) : '—'}
              </td>
              <td className="col-assumption">{step.assumption || ''}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Path A feedback inline */}
      {editingStep !== null && feedbackPhase === 'why' && (
        <div className="feedback-inline">
          <label>Why is {selectedCode} correct instead of {result.steps[editingStep].code}?</label>
          <textarea
            rows={2}
            value={whyText}
            onChange={e => setWhyText(e.target.value)}
            placeholder="Optional: explain the correction…"
          />
          <div className="feedback-actions">
            <button className="btn-sm ghost" onClick={cancelCodeEdit}>Cancel</button>
            <button className="btn-sm primary" onClick={submitWhy} disabled={feedbackLoading}>
              {feedbackLoading ? 'Analyzing…' : 'Submit'}
            </button>
          </div>
        </div>
      )}

      {editingStep !== null && feedbackPhase === 'clarify' && clarifyData && (
        <div className="feedback-inline">
          <label>{clarifyData.clarifying_question}</label>
          <input
            type="text"
            value={clarifyAnswer}
            onChange={e => setClarifyAnswer(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && submitClarify()}
            placeholder="Your answer…"
            autoFocus
          />
          <div className="feedback-actions">
            <button className="btn-sm ghost" onClick={() => { submitClarify() }}>Skip</button>
            <button className="btn-sm primary" onClick={submitClarify}>Submit</button>
          </div>
        </div>
      )}

      {/* Accept button — only when no edit in progress */}
      {editingStep === null && !editingInterp && (
        <div style={{ marginTop: 12, display: 'flex', justifyContent: 'flex-end' }}>
          <button
            className="btn-sm ghost"
            onClick={() => onAccept(input, result)}
            style={{ fontSize: 11 }}
          >
            ✓ Accept classification
          </button>
        </div>
      )}
    </div>
  )
}
