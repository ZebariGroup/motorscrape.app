export function Motorcycle() {
  return (
    <svg viewBox="0 0 200 100" width="100%" height="100%" style={{ overflow: 'visible' }}>
      <defs>
        <style>
          {`
            @keyframes wheel-spin {
              from { transform: rotate(0deg); }
              to { transform: rotate(360deg); }
            }
            @keyframes moto-bounce {
              0%, 100% { transform: translateY(0); }
              50% { transform: translateY(2px); }
            }
            .wheel { transform-origin: center; animation: wheel-spin 0.8s linear infinite; }
            .moto-body { animation: moto-bounce 0.4s ease-in-out infinite; }
          `}
        </style>
      </defs>

      {/* Exhaust smoke */}
      <circle cx="20" cy="70" r="6" fill="#cbd5e1" opacity="0.6" className="animate-pulse" />
      <circle cx="10" cy="65" r="8" fill="#cbd5e1" opacity="0.4" className="animate-pulse" style={{ animationDelay: '200ms' }} />
      
      <g className="moto-body">
        {/* Frame/Body */}
        <path d="M 60 60 L 120 60 L 140 40 L 110 40 Z" fill="#ef4444" />
        <path d="M 70 60 L 100 80 L 120 60 Z" fill="#b91c1c" />
        
        {/* Seat */}
        <path d="M 70 40 L 110 40 L 100 35 L 75 35 Z" fill="#1f2937" />
        
        {/* Handlebars */}
        <path d="M 130 45 L 120 25 L 110 25" fill="none" stroke="#94a3b8" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="110" cy="25" r="4" fill="#0f172a" />
        
        {/* Front Fork */}
        <line x1="140" y1="40" x2="160" y2="80" stroke="#94a3b8" strokeWidth="6" strokeLinecap="round" />
        
        {/* Headlight */}
        <circle cx="145" cy="45" r="6" fill="#fef08a" />
        <path d="M 150 45 L 180 30 L 180 60 Z" fill="#fef08a" opacity="0.4" />
        
        {/* Rider (abstract) */}
        <path d="M 90 35 C 90 20, 100 10, 110 20 C 115 25, 110 35, 100 35 Z" fill="#3b82f6" />
        <circle cx="105" cy="15" r="8" fill="#1e293b" /> {/* Helmet */}
      </g>

      {/* Rear Wheel */}
      <g style={{ transformOrigin: '60px 80px' }} className="wheel">
        <circle cx="60" cy="80" r="16" fill="#0f172a" />
        <circle cx="60" cy="80" r="10" fill="#cbd5e1" />
        <circle cx="60" cy="80" r="4" fill="#475569" />
        <rect x="58" y="66" width="4" height="28" fill="#475569" />
        <rect x="46" y="78" width="28" height="4" fill="#475569" />
      </g>
      
      {/* Front Wheel */}
      <g style={{ transformOrigin: '160px 80px' }} className="wheel">
        <circle cx="160" cy="80" r="16" fill="#0f172a" />
        <circle cx="160" cy="80" r="10" fill="#cbd5e1" />
        <circle cx="160" cy="80" r="4" fill="#475569" />
        <rect x="158" y="66" width="4" height="28" fill="#475569" />
        <rect x="146" y="78" width="28" height="4" fill="#475569" />
      </g>
    </svg>
  );
}
