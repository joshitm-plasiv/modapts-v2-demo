import React from 'react'
import DetailExpansion from './DetailExpansion'

export default function ResultsTable({ results, onToggle, onCodeEdit, onCodeEditComplete, onReinterpret, onAccept, onResolveClarification }) {
  if (results.length === 0) {
    return <div className="results-empty">No classifications yet. Type an operator task above.</div>
  }

  const unitLabel = (r) => {
    // EngineResult carries `unit` ("MOD"|"TMU"); legacy MODAPTS V2 has no unit -> seconds only.
    if (r.result.needs_clarification) return '—'
    const native = r.result.total_native
    const unit = r.result.unit
    return (native != null && unit)
      ? `${native} ${unit} · ${r.result.total_seconds}s`
      : `${r.result.total_seconds}s`
  }

  return (
    <div>
      {results.map(r => (
        <div key={r.id} className="result-row">
          <div className="result-summary" onClick={() => onToggle(r.id)}>
            <div className="result-input">
              {r.result.standard && <span className="result-standard">{r.result.standard}</span>}
              {r.input}
            </div>
            {r.result.needs_clarification ? (
              <div className="result-codes" style={{ color: 'var(--warning)' }}>clarify needed</div>
            ) : (
              <div className="result-codes">{r.result.code_sequence}</div>
            )}
            <div className="result-time">{unitLabel(r)}</div>
          </div>
          {r.expanded && (
            <DetailExpansion
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
