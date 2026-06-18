const STATE_CONFIG = {
  CLOSED:    { cls: 'cb-green', badge: 'badge badge-green' },
  HALF_OPEN: { cls: 'cb-amber', badge: 'badge badge-amber' },
  OPEN:      { cls: 'cb-red',   badge: 'badge badge-red'   },
}

export default function GatewayCard({ gateway }) {
  const { name, state, successRate, failures, extra } = gateway
  const cfg = STATE_CONFIG[state] ?? STATE_CONFIG.CLOSED

  return (
    <div className={`cb-card ${cfg.cls}`}>
      <div className="cb-top">
        <div className="cb-name">{name}</div>
        <span className={cfg.badge}>{state.replace('_', '-')}</span>
      </div>
      {successRate !== undefined && (
        <div className="cb-metric">
          Success rate: <span>{successRate}%</span>
        </div>
      )}
      {failures !== undefined && (
        <div className="cb-metric">
          Failures (5m): <span>{failures}</span>
        </div>
      )}
      {extra && (
        <div className="cb-metric" style={{ color: state === 'OPEN' ? 'var(--red)' : undefined }}>
          {extra}
        </div>
      )}
    </div>
  )
}
