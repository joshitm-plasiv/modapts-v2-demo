import React from 'react'
import DetailExpansion from './DetailExpansion'

export default function ResultsTable({ results, onToggle, onCodeEdit, onCodeEditComplete, onReinterpret, onAccept }) {
  if (results.length === 0) {
    return <div className="results-empty">No classifications yet. Type an operator task above.</div>
  }

  return (
    <div>
      {results.map(r => (
        <div key={r.id} className="result-row">
          <div className="result-summary" onClick={() => onToggle(r.id)}>
            <div className="result-input">{r.input}</div>
            <div className="result-codes">{r.result.code_sequence}</div>
            <div className="result-time">{r.result.total_seconds}s</div>
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
            />
          )}
        </div>
      ))}
    </div>
  )
}
