import React from 'react'

const PROVIDERS = [
  { value: 'anthropic', label: 'Anthropic', defaultModel: 'claude-sonnet-4-6' },
  { value: 'openai', label: 'OpenAI', defaultModel: 'gpt-4o' },
  { value: 'mistral', label: 'Mistral', defaultModel: 'mistral-large-latest' },
]

// Selectable work-measurement standards (mirrors GET /api/classify registry).
const STANDARDS = [
  { value: 'ALL', label: 'All standards (compare)' },
  { value: 'MTM-UAS', label: 'MTM-UAS' },
  { value: 'MTM-1', label: 'MTM-1' },
  { value: 'BasicMOST', label: 'BasicMOST' },
  { value: 'MODAPTS', label: 'MODAPTS' },
]

export default function SettingsPanel({ settings, onChange }) {
  const update = (field, value) => {
    const next = { ...settings, [field]: value }
    if (field === 'provider') {
      const p = PROVIDERS.find(p => p.value === value)
      if (p) next.model = p.defaultModel
    }
    onChange(next)
  }

  const connected = settings.apiKey && settings.provider && settings.model

  return (
    <div className="settings-panel">
      <div className="settings-field">
        <label>Standard</label>
        <select value={settings.standard} onChange={e => update('standard', e.target.value)}>
          {STANDARDS.map(s => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>
      </div>
      <div className="settings-field">
        <label>Provider</label>
        <select value={settings.provider} onChange={e => update('provider', e.target.value)}>
          {PROVIDERS.map(p => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>
      </div>
      <div className="settings-field">
        <label>Model</label>
        <input
          type="text"
          value={settings.model}
          onChange={e => update('model', e.target.value)}
          placeholder="e.g. claude-sonnet-4-6"
        />
      </div>
      <div className="settings-field">
        <label>API Key</label>
        <input
          type="password"
          value={settings.apiKey}
          onChange={e => update('apiKey', e.target.value)}
          placeholder="sk-..."
        />
      </div>
      <div className="settings-status">
        <span className={`status-dot ${connected ? 'connected' : 'disconnected'}`} />
        <span style={{ color: connected ? 'var(--success)' : 'var(--text-muted)' }}>
          {connected ? `${settings.standard} · ${settings.provider} / ${settings.model}` : 'Enter credentials above'}
        </span>
      </div>
    </div>
  )
}
