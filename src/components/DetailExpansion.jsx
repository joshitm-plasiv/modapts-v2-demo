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

const FIELD_LABEL = { distance_cm: 'distance (cm)', object_weight_kg: 'weight (kg)', placement_accuracy: 'fit' }

// What-if sensitivity grid: rows = swept values, columns = standards.
// Each cell shows seconds + code_sequence. Transient — not stored as a result.
function SweepGrid({ sweep, onClearSweep }) {
  // column order from the first row (engines sort fastest-first per row; pin a stable
  // column order using the union of standards seen)
  const standards = []
  sweep.rows.forEach(row => row.results.forEach(r => {
    if (!standards.includes(r.standard)) standards.push(r.standard)
  }))
  standards.sort()

  const cell = (row, std) => row.results.find(r => r.standard === std)

  return (
    <div className="sweep-panel">
      <div className="sweep-head">
        <span className="sweep-title">
          What-if: <strong>{FIELD_LABEL[sweep.field] || sweep.field}</strong> swept across {sweep.rows.length} values
        </span>
        {onClearSweep && <button className="btn-sm ghost" onClick={onClearSweep}>Close</button>}
      </div>
      <table className="steps-table sweep-grid">
        <thead>
          <tr>
            <th>{FIELD_LABEL[sweep.field] || sweep.field}</th>
            {standards.map(s => <th key={s} style={{ textAlign: 'left' }}>{s}</th>)}
          </tr>
        </thead>
        <tbody>
          {sweep.rows.map((row, ri) => (
            <tr key={ri} className={row.baseline ? 'sweep-baseline' : ''}>
              <td style={{ fontFamily: 'var(--mono)', fontWeight: 700 }}>
                {row.value}
                {row.baseline && <span className="sweep-baseline-tag"> baseline</span>}
              </td>
              {standards.map(s => {
                const c = cell(row, s)
                return (
                  <td key={s} style={{ verticalAlign: 'top' }}>
                    {c ? (
                      <>
                        <div style={{ fontFamily: 'var(--mono)', fontWeight: 700, color: 'var(--success)' }}>
                          {c.total_seconds}s
                        </div>
                        <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--accent)' }}>
                          {c.code_sequence} <span style={{ color: 'var(--text-muted)' }}>({c.total_native} {c.unit})</span>
                        </div>
                      </>
                    ) : '—'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
        One interpretation, one fact varied — every column is the same task at each value. Exploratory; not saved.
      </p>
    </div>
  )
}

export default function DetailExpansion({ resultId, input, result, onCodeEdit, onCodeEditComplete, onReinterpret, onAccept, onResolveClarification, onFactOverride, onSweep, sweep, onClearSweep, diff, hideInterpreted }) {
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
    if (factValue.trim() === '' || step.event_index == null) return
    // comma list -> 1 value = override (re-run in place); 2+ = sweep (transient grid)
    const parts = factValue.split(',').map(s => s.trim()).filter(Boolean)
    if (parts.length <= 1) {
      onFactOverride(resultId, input, step.event_index, { [factField]: parts[0] })
    } else {
      onSweep(resultId, input, step.event_index, factField, parts)
    }
    setFactStep(null)
  }

  const startCodeEdit = (stepIndex) => {
    if (!isLegacyModapts) return  // V3 engine codes are deterministic; correct via reinterpret
    const s = result.steps && result.steps[stepIndex]
    if (!s) return
    setEditingStep(stepIndex)
    setSelectedCode(s.code)
    setWhyText(''); setFeedbackPhase('why'); setClarifyData(null); setClarifyAnswer('')
  }
  const cancelCodeEdit = () => { setEditingStep(null); setFeedbackPhase(null); setClarifyData(null) }

  const submitWhy = async () => {
    const step = result.steps && result.steps[editingStep]
    if (!step) { cancelCodeEdit(); return }
    if (selectedCode === step.code) { cancelCodeEdit(); return }
    if (!whyText.trim()) { onCodeEditComplete(input, step.code, selectedCode, '', '', ''); cancelCodeEdit(); return }
    setFeedbackLoading(true)
    const data = await onCodeEdit(resultId, editingStep, input, step.code, selectedCode, whyText)
    setFeedbackLoading(false)
    if (data && data.clarifying_question) { setClarifyData(data); setFeedbackPhase('clarify') }
    else { onCodeEditComplete(input, step.code, selectedCode, whyText, '', ''); cancelCodeEdit() }
  }
  const submitClarify = () => {
    const step = result.steps && result.steps[editingStep]
    if (!step) { cancelCodeEdit(); return }
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
          {(result.steps || []).map((step, i) => {
            const flagged = step.variables && step.variables.flagged
            const df = diff && diff.stepFlags ? diff.stepFlags[i] : null
            const rowClass = df && df.status === 'changed' ? 'step-changed'
                           : df && df.status === 'added' ? 'step-added' : ''
            return (
              <tr key={i} className={rowClass}>
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
                      {df && df.status === 'changed' && df.oldCode !== step.code && (
                        <span className="diff-old">{df.oldCode} → </span>
                      )}
                      {step.code || '?'}{flagged ? ' ⚑' : ''}
                    </span>
                  )}
                </td>
                <td className="col-mods" style={{ fontFamily: 'var(--mono)', textAlign: 'right' }}>
                  {df && df.status === 'changed' && df.oldNative !== step.native && (
                    <span className="diff-old">{df.oldNative} → </span>
                  )}
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
                          <input type="text" value={factValue}
                            onChange={e => setFactValue(e.target.value)}
                            placeholder="e.g. 7  or  5, 7, 10, 15"
                            onKeyDown={e => { if (e.key === 'Enter') submitFact(step) }} autoFocus />
                        )}
                        <button className="btn-sm primary" onClick={() => submitFact(step)} disabled={!factValue.trim()}>
                          {factValue.split(',').filter(s => s.trim()).length > 1 ? 'Sweep' : 'Apply'}
                        </button>
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

      {diff && diff.delta != null && diff.delta !== 0 && (
        <div className="diff-total">
          Total: <span className="diff-old">{diff.beforeSecs}s</span> →{' '}
          <strong>{diff.afterSecs}s</strong>{' '}
          <span className={diff.delta > 0 ? 'diff-up' : 'diff-down'}>
            ({diff.delta > 0 ? '▲ +' : '▼ '}{diff.delta}s)
          </span> after fact correction
        </div>
      )}

      {sweep && sweep.rows && sweep.rows.length > 0 && (
        <SweepGrid sweep={sweep} onClearSweep={onClearSweep} />
      )}
      {sweep && sweep.needs_clarification && (
        <div className="feedback-inline" style={{ marginTop: 12 }}>
          <label>Cannot sweep — task needs clarification first</label>
          {(sweep.clarifying_questions || []).map((q, i) => (
            <p key={i} style={{ fontSize: 13, color: 'var(--warning)', margin: '0 0 6px' }}>{q}</p>
          ))}
          {onClearSweep && <div className="feedback-actions"><button className="btn-sm ghost" onClick={onClearSweep}>Dismiss</button></div>}
        </div>
      )}
      {editingStep !== null && feedbackPhase === 'why' && (
        <div className="feedback-inline">
          <label>Why is {selectedCode} correct instead of {result.steps[editingStep]?.code}?</label>
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
