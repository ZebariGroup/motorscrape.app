export function PlowTruck() {
  return (
    <svg viewBox="0 0 200 100" width="100%" height="100%" style={{ overflow: 'visible' }}>
      <defs>
        <style>
          {`
            @keyframes wheel-spin {
              from { transform: rotate(0deg); }
              to { transform: rotate(360deg); }
            }
            @keyframes truck-bounce {
              0%, 100% { transform: translateY(0); }
              50% { transform: translateY(1px); }
            }
            @keyframes plow-sweep {
              0%, 100% { transform: rotate(0deg); }
              50% { transform: rotate(-3deg); }
            }
            @keyframes snow-fly {
              0% { transform: translate(0, 0) scale(1); opacity: 0.9; }
              100% { transform: translate(15px, -10px) scale(1.2); opacity: 0; }
            }
            .wheel { transform-origin: center; animation: wheel-spin 1s linear infinite; }
            .truck-body { animation: truck-bounce 0.5s ease-in-out infinite; }
            .plow-blade { transform-origin: 160px 85px; animation: plow-sweep 2s ease-in-out infinite; }
            .snow-particle { animation: snow-fly 0.8s linear infinite; }
          `}
        </style>
      </defs>

      {/* Snow pile in front of plow */}
      <g className="snow-pile">
        <path d="M 170 90 Q 185 90 190 75 Q 195 60 180 50 Q 165 40 150 60 Z" fill="#e2e8f0" opacity="0.9" />
        <path d="M 160 95 Q 175 95 185 85 Q 195 75 180 65 Q 165 55 140 75 Z" fill="#f8fafc" opacity="0.9" />
        <circle cx="185" cy="65" r="4" fill="#f8fafc" className="snow-particle" style={{ animationDelay: '0ms' }} />
        <circle cx="175" cy="55" r="3" fill="#e2e8f0" className="snow-particle" style={{ animationDelay: '200ms' }} />
        <circle cx="190" cy="80" r="5" fill="#f8fafc" className="snow-particle" style={{ animationDelay: '400ms' }} />
      </g>
      
      {/* Exhaust smoke */}
      <circle cx="20" cy="30" r="8" fill="#cbd5e1" opacity="0.6" className="animate-pulse" />
      <circle cx="10" cy="15" r="12" fill="#cbd5e1" opacity="0.4" className="animate-pulse" style={{ animationDelay: '200ms' }} />
      <circle cx="0" cy="0" r="16" fill="#cbd5e1" opacity="0.2" className="animate-pulse" style={{ animationDelay: '400ms' }} />

      <g className="truck-body">
        {/* Truck Bed / Salt Spreader */}
        <path d="M 30 45 L 80 45 L 85 80 L 30 80 Z" fill="#475569" />
        <path d="M 35 35 L 75 35 L 80 45 L 30 45 Z" fill="#334155" />
        <polygon points="40,20 70,20 75,35 35,35" fill="#64748b" />
        
        {/* Exhaust pipe */}
        <rect x="25" y="40" width="6" height="40" fill="#94a3b8" />
        <rect x="23" y="35" width="10" height="5" fill="#64748b" />

        {/* Cab */}
        <path d="M 80 40 L 120 40 L 135 60 L 140 80 L 80 80 Z" fill="#eab308" />
        <path d="M 80 40 L 120 40 L 135 60 L 80 60 Z" fill="#facc15" />
        
        {/* Window */}
        <path d="M 85 45 L 115 45 L 125 58 L 85 58 Z" fill="#bae6fd" />
        <path d="M 110 45 L 115 45 L 125 58 L 115 58 Z" fill="#7dd3fc" /> {/* Window reflection */}

        {/* Beacon */}
        <path d="M 95 35 L 105 35 L 103 40 L 97 40 Z" fill="#f59e0b" />
        <circle cx="100" cy="35" r="4" fill="#fbbf24" className="animate-pulse" />

        {/* Chassis/Bumper */}
        <rect x="20" y="75" width="125" height="8" rx="4" fill="#1e293b" />
        
        {/* Headlight */}
        <rect x="135" y="65" width="6" height="8" rx="2" fill="#fef08a" />
        <path d="M 141 69 L 160 55 L 160 83 Z" fill="#fef08a" opacity="0.4" />

        {/* Plow Mount & Arm */}
        <rect x="140" y="75" width="15" height="6" fill="#334155" />
        <polygon points="150,78 165,65 168,68 150,82" fill="#eab308" />

        {/* Plow Blade */}
        <g className="plow-blade">
          <path d="M 160 85 Q 165 60 175 45 L 180 48 Q 170 65 168 90 Z" fill="#94a3b8" />
          <path d="M 158 85 Q 163 60 173 45 L 175 45 Q 165 60 160 85 Z" fill="#cbd5e1" />
        </g>
      </g>

      {/* Wheels */}
      {/* Rear Wheel */}
      <g style={{ transformOrigin: '50px 85px' }} className="wheel">
        <circle cx="50" cy="85" r="14" fill="#0f172a" />
        <circle cx="50" cy="85" r="8" fill="#cbd5e1" />
        <circle cx="50" cy="85" r="3" fill="#475569" />
        {/* Treads/Spokes for rotation effect */}
        <rect x="48" y="73" width="4" height="24" fill="#475569" />
        <rect x="38" y="83" width="24" height="4" fill="#475569" />
      </g>
      
      {/* Front Wheel */}
      <g style={{ transformOrigin: '115px 85px' }} className="wheel">
        <circle cx="115" cy="85" r="14" fill="#0f172a" />
        <circle cx="115" cy="85" r="8" fill="#cbd5e1" />
        <circle cx="115" cy="85" r="3" fill="#475569" />
        {/* Treads/Spokes for rotation effect */}
        <rect x="113" y="73" width="4" height="24" fill="#475569" />
        <rect x="103" y="83" width="24" height="4" fill="#475569" />
      </g>
    </svg>
  );
}
