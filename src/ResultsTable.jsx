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
              ? <CompareDetail result={r.result} unitLabel={unitLabel} />
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

// Compare view: one interpretation, all engines side by side, sorted fastest-first.
function CompareDetail({ result, unitLabel }) {
  if (result.needs_clarification) {
    return (
      <div className="detail-panel">
        <p style={{ fontSize: 13, color: 'var(--warning)', margin: 0 }}>
          The task needs clarification before any standard can code it. Re-enter with the missing
          detail (sensing method, distance, weight) — clarification is shared across all standards.
        </p>
      </div>
    )
  }
  return (
    <div className="detail-panel">
      <div className="detail-interpreted">
        <label>Interpreted</label>
        <span className="detail-interpreted-text" style={{ cursor: 'default' }}>{result.interpreted_action}</span>
      </div>
      <table className="steps-table compare-table">
        <thead>
          <tr>
            <th className="col-motion">Standard</th>
            <th>Code sequence</th>
            <th className="col-mods">Native</th>
            <th className="col-mods">Seconds</th>
          </tr>
        </thead>
        <tbody>
          {result.results.map((r, i) => (
            <tr key={i}>
              <td className="col-motion"><span className="result-standard">{r.standard}</span></td>
              <td style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--accent)' }}>{r.code_sequence}</td>
              <td className="col-mods" style={{ fontFamily: 'var(--mono)', textAlign: 'right' }}>
                {r.total_native != null ? `${r.total_native} ${r.unit}` : '—'}
              </td>
              <td className="col-mods" style={{ fontFamily: 'var(--mono)', textAlign: 'right', color: 'var(--success)' }}>
                {r.total_seconds}s
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 10 }}>
        Same interpreted task, four standards. Totals differ by method; ordering within an equal
        total is cosmetic. Per-step detail: re-run with a single standard selected.
      </p>
    </div>
  )
}
