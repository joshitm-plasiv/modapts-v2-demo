import React, { useState } from 'react'

// MODAPTS V2 legacy dropdown codes (Path A code-edit for the MODAPTS standard).
// V3 engines (MTM-UAS/MTM-1/BasicMOST) own large code spaces; for those, the code
// cell shows the engine code read-only and correction goes via reinterpret (Path B).
const MODAPTS_CODES = [
  'M1','M2','M3','M4','M5','M7','G0','G1','G3','P0','P2','P5','R2','R3','D3',
  'E2','E4','N3','N6','W5','W2.36','W7.75','F3','C3','C4','B17','S30','X4','J2',
  'V3','U0.5','U1','U2','U3','L0','L1','L2','H4','H5','H6','H7','H21','H26','H35',
]

// Normalize clarification: V3 EngineResult uses `clarifying_questions` (list);
// MODAPTS V2 uses `clarifying_question` (string). Render either.
function clarifyQuestions(result) {
  if (Array.isArray(result.clarifying_questions) && result.clarifying_questions.length) {
    return result.clarifying_questions
  }
  if (result.clarifying_question) return [result.clarifying_question]
  return []
}

export default function DetailExpansion({ resultId, input, result, onCodeEdit, onCodeEditComplete, onReinterpret, onAccept, onResolveClarification, onFactOverride, hideInterpreted }) {
  const [editingInterp, setEditingInterp] = useState(false)
  const [interpText, setInterpText] = useState(result.interpreted_action)
  const [clarifyResponse, setClarifyResponse] = useState('')

  // Per-step fact correction (distance/weight/fit) — patches the source event, re-runs.
  const [factStep, setFactStep] = useState(null)   // step index being corrected
  const [factField, setFactField] = useState('distance_cm')
  const [factValue, setFactValue] = useState('')

  // Path A (code edit) — MODAPTS legacy only
  const [editingStep, setEditingStep] = useState(null)
  const [selectedCode, setSelectedCode] = useState('')
  const [whyText, setWhyText] = useState('')
  const [feedbackPhase, setFeedbackPhase] = useState(null)
  const [clarifyData, setClarifyData] = useState(null)
  const [clarifyAnswer, setClarifyAnswer] = useState('')
  const [feedbackLoading, setFeedbackLoading] = useState(false)

  const isLegacyModapts = (result.standard || 'MODAPTS') === 'MODAPTS'
  const unit = result.unit || 'MOD'

  const handleInterpSubmit = () => {
    const trimmed = interpText.trim()
    if (trimmed && trimmed !== result.interpreted_action) {
      onReinterpret(resultId, input, result.interpreted_action, trimmed)
    }
    setEditingInterp(false)
  }
  const handleInterpCancel = () => { setInterpText(result.interpreted_action); setEditingInterp(false) }

  const submitFact = (step) => {
    if (factValue === '' || step.event_index == null) return
    onFactOverride(resultId, input, step.event_index, { [factField]: factValue })
    setFactStep(null)
  }

  const startCodeEdit = (stepIndex) => {
    if (!isLegacyModapts) return  // V3 engine codes are deterministic; correct via reinterpret
    setEditingStep(stepIndex)
    setSelectedCode(result.steps[stepIndex].code)
    setWhyText(''); setFeedbackPhase('why'); setClarifyData(null); setClarifyAnswer('')
  }
  const cancelCodeEdit = () => { setEditingStep(null); setFeedbackPhase(null); setClarifyData(null) }

  const submitWhy = async () => {
    const step = result.steps[editingStep]
    if (selectedCode === step.code) { cancelCodeEdit(); return }
    if (!whyText.trim()) { onCodeEditComplete(input, step.code, selectedCode, '', '', ''); cancelCodeEdit(); return }
    setFeedbackLoading(true)
    const data = await onCodeEdit(resultId, editingStep, input, step.code, selectedCode, whyText)
    setFeedbackLoading(false)
    if (data && data.clarifying_question) { setClarifyData(data); setFeedbackPhase('clarify') }
    else { onCodeEditComplete(input, step.code, selectedCode, whyText, '', ''); cancelCodeEdit() }
  }
  const submitClarify = () => {
    const step = result.steps[editingStep]
    onCodeEditComplete(input, step.code, selectedCode, whyText, clarifyData?.clarifying_question || '', clarifyAnswer)
    cancelCodeEdit()
  }

  // ── Clarification view (sensing ambiguity) ──
  const questions = clarifyQuestions(result)
  if (result.needs_clarification) {
    const q = questions[0] || 'Clarification needed.'
    return (
      <div className="detail-panel">
        <div className="feedback-inline" style={{ marginTop: 0 }}>
          <label>Clarification needed before coding</label>
          {questions.map((qq, i) => (
            <p key={i} style={{ fontSize: 13, color: 'var(--text-secondary)', margin: '0 0 10px' }}>{qq}</p>
          ))}
          <input
            type="text" value={clarifyResponse}
            onChange={e => setClarifyResponse(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && clarifyResponse.trim()) onResolveClarification(resultId, input, q, clarifyResponse.trim()) }}
            placeholder="Answer in your own words… e.g. 'I touch it to check' or 'there's a gauge'"
            autoFocus
          />
          <div className="feedback-actions">
            <button className="btn-sm primary"
              onClick={() => onResolveClarification(resultId, input, q, clarifyResponse.trim())}
              disabled={!clarifyResponse.trim()}>Submit answer</button>
          </div>
        </div>
      </div>
    )
  }

  const fmtVars = (v) => {
    if (!v || typeof v !== 'object') return ''
    return Object.entries(v)
      .filter(([k]) => k !== 'provenance' && k !== 'flagged')
      .map(([k, val]) => `${k}=${Array.isArray(val) ? `[${val.join(',')}]` : val}`)
      .join('  ')
  }

  return (
    <div className="detail-panel">
      {!hideInterpreted && (
      <div className="detail-interpreted">
        <label>Interpreted</label>
        {editingInterp ? (
          <>
            <input type="text" value={interpText} onChange={e => setInterpText(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleInterpSubmit()} autoFocus />
            <button className="btn-sm primary" onClick={handleInterpSubmit}>Apply</button>
            <button className="btn-sm ghost" onClick={handleInterpCancel}>Cancel</button>
          </>
        ) : (
          <span className="detail-interpreted-text" onClick={() => setEditingInterp(true)}>
            {result.interpreted_action}
          </span>
        )}
      </div>
      )}

      <table className="steps-table">
        <thead>
          <tr>
            <th className="col-motion">Motion</th>
            <th className="col-code">Code</th>
            <th className="col-mods">{unit}</th>
            <th className="col-assumption">Rule / Assumption</th>
          </tr>
        </thead>
        <tbody>
          {result.steps.map((step, i) => {
            const flagged = step.variables && step.variables.flagged
            return (
              <tr key={i}>
                <td className="col-motion">{step.motion}</td>
                <td className="col-code">
                  {editingStep === i ? (
                    <select className="code-select" value={selectedCode} onChange={e => setSelectedCode(e.target.value)}>
                      {MODAPTS_CODES.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                  ) : (
                    <span
                      className="code-cell"
                      onClick={() => startCodeEdit(i)}
                      style={{ cursor: isLegacyModapts ? 'pointer' : 'default',
                               color: flagged ? 'var(--warning)' : undefined }}
                      title={isLegacyModapts ? 'Click to edit (MODAPTS)' : 'Engine code — edit via Interpreted (reinterpret)'}
                    >
                      {step.code || '?'}{flagged ? ' ⚑' : ''}
                    </span>
                  )}
                </td>
                <td className="col-mods" style={{ fontFamily: 'var(--mono)', textAlign: 'right' }}>
                  {step.native != null ? step.native : (step.mods != null ? step.mods : '—')}
                </td>
                <td className="col-assumption">
                  {step.rule && <div className="step-rule">{step.rule}</div>}
                  {fmtVars(step.variables) && <div className="step-vars">{fmtVars(step.variables)}</div>}
                  {step.assumption && <div className="step-assumption">{step.assumption}</div>}
                  {onFactOverride && step.event_index != null && (
                    factStep === i ? (
                      <div className="fact-edit">
                        <select value={factField} onChange={e => setFactField(e.target.value)}>
                          <option value="distance_cm">distance (cm)</option>
                          <option value="object_weight_kg">weight (kg)</option>
                          <option value="placement_accuracy">fit</option>
                        </select>
                        {factField === 'placement_accuracy' ? (
                          <select value={factValue} onChange={e => setFactValue(e.target.value)}>
                            <option value="">—</option>
                            <option value="approximate">approximate</option>
                            <option value="loose">loose</option>
                            <option value="tight">tight</option>
                          </select>
                        ) : (
                          <input type="number" step="any" value={factValue}
                            onChange={e => setFactValue(e.target.value)} placeholder="value"
                            onKeyDown={e => { if (e.key === 'Enter') submitFact(step) }} autoFocus />
                        )}
                        <button className="btn-sm primary" onClick={() => submitFact(step)} disabled={!factValue}>Apply</button>
                        <button className="btn-sm ghost" onClick={() => setFactStep(null)}>Cancel</button>
                      </div>
                    ) : (
                      <button className="fact-edit-trigger" onClick={() => { setFactStep(i); setFactValue('') }}>
                        ✎ correct a fact
                      </button>
                    )
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {editingStep !== null && feedbackPhase === 'why' && (
        <div className="feedback-inline">
          <label>Why is {selectedCode} correct instead of {result.steps[editingStep].code}?</label>
          <textarea rows={2} value={whyText} onChange={e => setWhyText(e.target.value)} placeholder="Optional: explain the correction…" />
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
          <input type="text" value={clarifyAnswer} onChange={e => setClarifyAnswer(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && submitClarify()} placeholder="Your answer…" autoFocus />
          <div className="feedback-actions">
            <button className="btn-sm ghost" onClick={() => submitClarify()}>Skip</button>
            <button className="btn-sm primary" onClick={submitClarify}>Submit</button>
          </div>
        </div>
      )}

      {editingStep === null && !editingInterp && (
        <div style={{ marginTop: 12, display: 'flex', justifyContent: 'flex-end' }}>
          <button className="btn-sm ghost" onClick={() => onAccept(input, result)} style={{ fontSize: 11 }}>
            ✓ Accept classification
          </button>
        </div>
      )}
    </div>
  )
}
