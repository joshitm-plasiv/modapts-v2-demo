import React from 'react'
import DetailExpansion from './DetailExpansion'

export default function ResultsTable({ results, onToggle, onCodeEdit, onCodeEditComplete, onReinterpret, onAccept, onResolveClarification }) {
  if (results.length === 0) {
    return <div className="results-empty">No classifications yet. Type an operator task above.</div>
  }

  const unitLabel = (r) => {
    if (r.needs_clarification) return '—'
    const native = r.total_native
    const unit = r.unit
    return (native != null && unit) ? `${native} ${unit} · ${r.total_seconds}s` : `${r.total_seconds}s`
  }

  return (
    <div>
      {results.map(r => (
        <div key={r.id} className="result-row">
          <div className="result-summary" onClick={() => onToggle(r.id)}>
            <div className="result-input">
              {r.result.compare && <span className="result-standard">COMPARE</span>}
              {!r.result.compare && r.result.standard && <span className="result-standard">{r.result.standard}</span>}
              {r.input}
            </div>
            {r.result.compare ? (
              <div className="result-codes" style={{ color: 'var(--text-secondary)' }}>
                {r.result.needs_clarification ? 'clarify needed' : `${r.result.results.length} standards`}
              </div>
            ) : r.result.needs_clarification ? (
              <div className="result-codes" style={{ color: 'var(--warning)' }}>clarify needed</div>
            ) : (
              <div className="result-codes">{r.result.code_sequence}</div>
            )}
            <div className="result-time">
              {r.result.compare ? '' : unitLabel(r.result)}
            </div>
          </div>
          {r.expanded && (
            r.result.compare
              ? <CompareDetail
                  resultId={r.id}
                  input={r.input}
                  result={r.result}
                  unitLabel={unitLabel}
                  onCodeEdit={onCodeEdit}
                  onCodeEditComplete={onCodeEditComplete}
                  onReinterpret={onReinterpret}
                  onAccept={onAccept}
                  onResolveClarification={onResolveClarification}
                />
              : <DetailExpansion
                  resultId={r.id}
                  input={r.input}
                  result={r.result}
                  onCodeEdit={onCodeEdit}
                  onCodeEditComplete={onCodeEditComplete}
                  onReinterpret={onReinterpret}
                  onAccept={onAccept}
                  onResolveClarification={onResolveClarification}
                />
          )}
        </div>
      ))}
    </div>
  )
}

// Compare view: one interpretation, all engines. Each row expands into its full
// per-step audit + feedback (DetailExpansion). Reinterpret re-runs ALL standards
// (shared facts), so it's handled at the compare level, not per row.
function CompareDetail({ resultId, input, result, unitLabel, onCodeEdit, onCodeEditComplete, onReinterpret, onAccept, onResolveClarification }) {
  const [openStd, setOpenStd] = React.useState(null)

  if (result.needs_clarification) {
    // Clarification is shared across all standards — answer once, re-run all four.
    const q = (result.clarifying_questions && result.clarifying_questions[0]) || result.clarifying_question || 'Clarification needed.'
    return (
      <div className="detail-panel">
        <ClarifyAll resultId={resultId} input={input} question={q} onResolveClarification={onResolveClarification} questions={result.clarifying_questions} />
      </div>
    )
  }

  return (
    <div className="detail-panel">
      {/* Shared interpretation — editing it re-runs ALL standards (active standard = ALL) */}
      <SharedInterpreted resultId={resultId} input={input} result={result} onReinterpret={onReinterpret} />

      <table className="steps-table compare-table">
        <thead>
          <tr>
            <th className="col-motion">Standard</th>
            <th>Code sequence</th>
            <th className="col-mods">Native</th>
            <th className="col-mods">Seconds</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {result.results.map((r, i) => (
            <React.Fragment key={i}>
              <tr>
                <td className="col-motion"><span className="result-standard">{r.standard}</span></td>
                <td style={{ fontFamily: 'var(--mono)', fontSize: 13, fontWeight: 500, color: 'var(--accent)' }}>{r.code_sequence}</td>
                <td className="col-mods" style={{ fontFamily: 'var(--mono)', textAlign: 'right' }}>
                  {r.total_native != null ? `${r.total_native} ${r.unit}` : '—'}
                </td>
                <td className="col-mods" style={{ fontFamily: 'var(--mono)', textAlign: 'right', fontWeight: 700, color: 'var(--success)' }}>
                  {r.total_seconds}s
                </td>
                <td style={{ textAlign: 'right' }}>
                  <button className="btn-sm ghost" onClick={() => setOpenStd(openStd === i ? null : i)}>
                    {openStd === i ? '▾ detail' : '▸ detail'}
                  </button>
                </td>
              </tr>
              {openStd === i && (
                <tr>
                  <td colSpan={5} style={{ padding: 0, background: 'var(--bg-secondary)' }}>
                    {/* Full audit trail + per-standard code edits. resultId is composed so
                        a code edit knows which standard it came from. Reinterpret is hidden
                        here (handled once at compare level — see SharedInterpreted). */}
                    <DetailExpansion
                      resultId={`${resultId}:${r.standard}`}
                      input={input}
                      result={r}
                      onCodeEdit={onCodeEdit}
                      onCodeEditComplete={onCodeEditComplete}
                      onReinterpret={() => {}}  /* disabled per-row; reinterpret is global in compare */
                      onAccept={onAccept}
                      onResolveClarification={onResolveClarification}
                      hideInterpreted
                    />
                  </td>
                </tr>
              )}
            </React.Fragment>
          ))}
        </tbody>
      </table>
      <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 10 }}>
        Same interpreted task, four standards. Totals differ by method; ordering within an equal
        total is cosmetic. Open “detail” on any row for its motion-by-motion codes, rules, and edits.
        Editing the interpretation above re-runs all four.
      </p>
    </div>
  )
}

// Shared interpreted line for compare mode — edit re-runs all standards.
function SharedInterpreted({ resultId, input, result, onReinterpret }) {
  const [editing, setEditing] = React.useState(false)
  const [text, setText] = React.useState(result.interpreted_action)
  const submit = () => {
    const t = text.trim()
    if (t && t !== result.interpreted_action) onReinterpret(resultId, input, result.interpreted_action, t)
    setEditing(false)
  }
  return (
    <div className="detail-interpreted">
      <label>Interpreted</label>
      {editing ? (
        <>
          <input type="text" value={text} onChange={e => setText(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && submit()} autoFocus />
          <button className="btn-sm primary" onClick={submit}>Apply to all</button>
          <button className="btn-sm ghost" onClick={() => { setText(result.interpreted_action); setEditing(false) }}>Cancel</button>
        </>
      ) : (
        <span className="detail-interpreted-text" onClick={() => setEditing(true)} title="Edit interpretation — re-runs all standards">
          {result.interpreted_action}
        </span>
      )}
    </div>
  )
}

function ClarifyAll({ resultId, input, question, questions, onResolveClarification }) {
  const [answer, setAnswer] = React.useState('')
  const list = (questions && questions.length) ? questions : [question]
  return (
    <div className="feedback-inline" style={{ marginTop: 0 }}>
      <label>Clarification needed (shared across all standards)</label>
      {list.map((q, i) => (
        <p key={i} style={{ fontSize: 13, color: 'var(--text-secondary)', margin: '0 0 10px' }}>{q}</p>
      ))}
      <input type="text" value={answer} onChange={e => setAnswer(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && answer.trim()) onResolveClarification(resultId, input, question, answer.trim()) }}
        placeholder="Answer once — all four standards re-run…" autoFocus />
      <div className="feedback-actions">
        <button className="btn-sm primary" disabled={!answer.trim()}
          onClick={() => onResolveClarification(resultId, input, question, answer.trim())}>Submit to all</button>
      </div>
    </div>
  )
}
