export function Boat() {
  return (
    <svg viewBox="0 0 200 100" width="100%" height="100%" style={{ overflow: 'visible' }}>
      <defs>
        <style>
          {`
            @keyframes boat-bob {
              0%, 100% { transform: translateY(0) rotate(0deg); }
              50% { transform: translateY(3px) rotate(-1deg); }
            }
            @keyframes wake-splash {
              0% { transform: translate(0, 0) scale(1); opacity: 0.8; }
              100% { transform: translate(-20px, -5px) scale(1.5); opacity: 0; }
            }
            .boat-body { animation: boat-bob 2s ease-in-out infinite; transform-origin: center; }
            .wake { animation: wake-splash 1s linear infinite; }
          `}
        </style>
      </defs>

      {/* Water wake */}
      <path d="M 10 90 Q 30 85 50 90 Q 70 95 90 90" fill="none" stroke="#38bdf8" strokeWidth="3" strokeLinecap="round" className="wake" />
      <path d="M 0 85 Q 20 80 40 85" fill="none" stroke="#7dd3fc" strokeWidth="2" strokeLinecap="round" className="wake" style={{ animationDelay: '300ms' }} />
      <path d="M 140 90 Q 160 85 180 90" fill="none" stroke="#38bdf8" strokeWidth="3" strokeLinecap="round" />

      <g className="boat-body">
        {/* Outboard Motor */}
        <rect x="25" y="55" width="15" height="25" fill="#1e293b" />
        <path d="M 20 50 L 45 50 L 40 60 L 25 60 Z" fill="#334155" />
        <rect x="30" y="75" width="5" height="15" fill="#475569" />
        {/* Propeller */}
        <path d="M 25 85 L 30 95 L 35 85 Z" fill="#94a3b8" />

        {/* Hull */}
        <path d="M 40 50 L 140 50 Q 170 50 180 65 L 160 85 L 40 85 Z" fill="#0284c7" />
        <path d="M 40 50 L 140 50 Q 170 50 180 65 L 160 70 L 40 70 Z" fill="#38bdf8" />
        
        {/* Stripe */}
        <path d="M 40 75 L 155 75 L 150 80 L 40 80 Z" fill="#ffffff" />

        {/* Windshield */}
        <path d="M 100 50 L 120 35 L 130 50 Z" fill="#bae6fd" opacity="0.8" />
        
        {/* Console / Seats */}
        <rect x="80" y="45" width="20" height="5" fill="#1e293b" />
        <rect x="60" y="40" width="15" height="10" fill="#f8fafc" />
        
        {/* Driver */}
        <circle cx="90" cy="35" r="7" fill="#fca5a5" />
        <path d="M 85 45 Q 90 40 95 45 Z" fill="#ef4444" />
      </g>
    </svg>
  );
}
