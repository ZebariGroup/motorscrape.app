export function RaceCar() {
  return (
    <svg viewBox="0 0 200 100" width="100%" height="100%" style={{ overflow: 'visible' }}>
      <defs>
        <style>
          {`
            @keyframes wheel-spin {
              from { transform: rotate(0deg); }
              to { transform: rotate(360deg); }
            }
            @keyframes car-bounce {
              0%, 100% { transform: translateY(0); }
              50% { transform: translateY(1px); }
            }
            .wheel { transform-origin: center; animation: wheel-spin 0.5s linear infinite; }
            .car-body { animation: car-bounce 0.3s ease-in-out infinite; }
          `}
        </style>
      </defs>

      {/* Exhaust flames */}
      <path d="M 20 70 L 5 65 L 15 75 L 0 80 L 20 80 Z" fill="#f97316" className="animate-pulse" />
      <path d="M 20 72 L 10 70 L 15 75 L 8 78 L 20 78 Z" fill="#fef08a" className="animate-pulse" style={{ animationDelay: '100ms' }} />

      <g className="car-body">
        {/* Rear Wing */}
        <rect x="25" y="45" width="5" height="20" fill="#1e293b" />
        <path d="M 15 40 L 45 40 L 45 45 L 15 45 Z" fill="#dc2626" />
        
        {/* Main Body */}
        <path d="M 20 75 L 170 75 L 160 60 L 110 50 L 70 50 L 40 60 Z" fill="#ef4444" />
        
        {/* Cockpit */}
        <path d="M 70 50 L 110 50 L 100 35 L 80 35 Z" fill="#bae6fd" />
        <path d="M 80 35 L 100 35 L 95 35 L 85 35 Z" fill="#7dd3fc" /> {/* Reflection */}
        
        {/* Racing Stripe */}
        <path d="M 30 65 L 165 65 L 155 60 L 35 60 Z" fill="#ffffff" />
        
        {/* Number Circle */}
        <circle cx="90" cy="65" r="8" fill="#ffffff" />
        <text x="90" y="69" fontSize="10" fontWeight="bold" fill="#000000" textAnchor="middle">8</text>
      </g>

      {/* Rear Wheel */}
      <g style={{ transformOrigin: '50px 75px' }} className="wheel">
        <circle cx="50" cy="75" r="14" fill="#0f172a" />
        <circle cx="50" cy="75" r="6" fill="#fbbf24" />
        <circle cx="50" cy="75" r="2" fill="#000000" />
        <rect x="48" y="63" width="4" height="24" fill="#fbbf24" />
        <rect x="38" y="73" width="24" height="4" fill="#fbbf24" />
      </g>
      
      {/* Front Wheel */}
      <g style={{ transformOrigin: '140px 75px' }} className="wheel">
        <circle cx="140" cy="75" r="14" fill="#0f172a" />
        <circle cx="140" cy="75" r="6" fill="#fbbf24" />
        <circle cx="140" cy="75" r="2" fill="#000000" />
        <rect x="138" y="63" width="4" height="24" fill="#fbbf24" />
        <rect x="128" y="73" width="24" height="4" fill="#fbbf24" />
      </g>
    </svg>
  );
}
