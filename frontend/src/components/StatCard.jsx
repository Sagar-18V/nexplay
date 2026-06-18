export default function StatCard({ title, value, delta, deltaType = 'up', icon }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{title}</div>
      <div className="stat-value">{value}</div>
      {delta && (
        <div className={`stat-delta ${deltaType}`}>
          <span>{deltaType === 'up' ? '↑' : deltaType === 'down' ? '↓' : '•'}</span>
          <span>{delta}</span>
        </div>
      )}
    </div>
  )
}
