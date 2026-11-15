/** Compact chord box (frets indexed string 1 = high e .. 6 = low E, -1 = muted). */
export function ChordDiagram({ frets }: { frets: number[] }) {
  const f = frets.slice(0, 6)
  const fretted = f.filter(x => x > 0)
  const max = fretted.length ? Math.max(...fretted) : 0
  const base = max > 4 ? Math.min(...fretted) : 1
  const W = 22, H = 20, sx = W / 5, sy = H / 4
  const strings = [5, 4, 3, 2, 1, 0] // draw low E on the left
  return (
    <div className="chord-diagram">
      <svg width={W + 8} height={H + 12} viewBox={`-4 -8 ${W + 8} ${H + 12}`}>
        {base === 1 && <rect x={0} y={-1.6} width={W} height={1.8} fill="#222" />}
        {[0, 1, 2, 3, 4].map(i => <line key={`f${i}`} x1={0} x2={W} y1={i * sy} y2={i * sy} stroke="#444" strokeWidth={0.6} />)}
        {strings.map((_s, i) => <line key={`s${i}`} x1={i * sx} x2={i * sx} y1={0} y2={H} stroke="#444" strokeWidth={0.6} />)}
        {strings.map((s, i) => {
          const v = f[s]
          if (v === undefined || v < 0) return <text key={`m${i}`} x={i * sx} y={-3} fontSize={4.5} textAnchor="middle" fill="#333">×</text>
          if (v === 0) return <circle key={`o${i}`} cx={i * sx} cy={-4} r={1.4} fill="none" stroke="#333" strokeWidth={0.6} />
          const row = v - base
          if (row < 0 || row > 3) return null
          return <circle key={`d${i}`} cx={i * sx} cy={row * sy + sy / 2} r={1.9} fill="#222" />
        })}
      </svg>
      {base > 1 && <span className="chord-fr">fr. {base}</span>}
    </div>
  )
}
