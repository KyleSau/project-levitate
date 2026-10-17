// Artificial horizon + heading from the recorded Euler angles (Z-Y-X, display only).
export function AttitudeIndicator({ roll, pitch, yaw }: { roll: number; pitch: number; yaw: number }) {
  const R = 46;
  const pxPerDeg = 1.6;
  return (
    <svg viewBox="-50 -50 100 112" className="attitude">
      <defs>
        <clipPath id="ai-clip"><circle r={R} /></clipPath>
      </defs>
      <g clipPath="url(#ai-clip)">
        {/* FLU body frame: +roll = right side down -> horizon turns counter-clockwise; +pitch about +y (left) = nose down */}
        <g transform={`rotate(${-roll}) translate(0 ${-pitch * pxPerDeg})`}>
          <rect x={-200} y={-200} width={400} height={200} fill="#1f4f7a" />
          <rect x={-200} y={0} width={400} height={200} fill="#5a3d22" />
          <line x1={-200} x2={200} y1={0} y2={0} stroke="#fff" strokeWidth={0.8} />
          {[-20, -10, 10, 20].map((d) => (
            <g key={d}>
              <line x1={-10} x2={10} y1={d * pxPerDeg} y2={d * pxPerDeg} stroke="#fff" strokeWidth={0.5} />
              <text x={13} y={d * pxPerDeg + 2} fontSize={5} fill="#fff">{-d}</text>
            </g>
          ))}
        </g>
      </g>
      <circle r={R} fill="none" stroke="#5d6b7a" strokeWidth={1.2} />
      <path d="M-22 0 L-8 0 L-4 4 L0 0 L4 4 L8 0 L22 0" fill="none" stroke="#ffe066" strokeWidth={1.6} />
      <text x={0} y={58} fontSize={7} textAnchor="middle" fill="#9fb3c8">
        roll {roll.toFixed(1)}° · pitch {pitch.toFixed(1)}° · yaw {yaw.toFixed(1)}°
      </text>
    </svg>
  );
}
