export function Snowmobile() {
  return (
    <svg viewBox="0 0 200 100" width="100%" height="100%" style={{ overflow: 'visible' }}>
      <defs>
        <style>
          {`
            @keyframes sled-bounce {
              0%, 100% { transform: translateY(0) rotate(0deg); }
              50% { transform: translateY(2px) rotate(-1deg); }
            }
            @keyframes snow-spray {
              0% { transform: translate(0, 0) scale(1); opacity: 0.9; }
              100% { transform: translate(-15px, -10px) scale(1.5); opacity: 0; }
            }
            .sled-body { animation: sled-bounce 0.4s ease-in-out infinite; transform-origin: center; }
            .spray { animation: snow-spray 0.6s linear infinite; }
          `}
        </style>
      </defs>

      {/* Snow spray */}
      <circle cx="20" cy="85" r="5" fill="#f8fafc" className="spray" />
      <circle cx="15" cy="80" r="4" fill="#e2e8f0" className="spray" style={{ animationDelay: '150ms' }} />
      <circle cx="25" cy="75" r="6" fill="#f8fafc" className="spray" style={{ animationDelay: '300ms' }} />

      <g className="sled-body">
        {/* Track/Tread */}
        <rect x="30" y="75" width="80" height="10" rx="5" fill="#1e293b" />
        <rect x="35" y="77" width="70" height="6" rx="3" fill="#334155" />
        
        {/* Skis */}
        <path d="M 120 85 L 170 85 Q 180 85 185 75" fill="none" stroke="#94a3b8" strokeWidth="4" strokeLinecap="round" />
        <line x1="130" y1="70" x2="140" y2="85" stroke="#64748b" strokeWidth="4" strokeLinecap="round" />
        <line x1="150" y1="70" x2="160" y2="85" stroke="#64748b" strokeWidth="4" strokeLinecap="round" />

        {/* Main Body */}
        <path d="M 40 70 L 110 70 L 150 50 L 130 35 L 90 40 L 40 50 Z" fill="#10b981" />
        <path d="M 40 70 L 110 70 L 150 50 L 110 50 L 40 60 Z" fill="#059669" />
        
        {/* Seat */}
        <path d="M 40 50 L 90 40 L 85 35 L 35 45 Z" fill="#1f2937" />
        
        {/* Windshield */}
        <path d="M 130 35 L 145 20 L 150 35 Z" fill="#bae6fd" opacity="0.7" />
        
        {/* Handlebars */}
        <path d="M 110 40 L 120 25 L 115 25" fill="none" stroke="#475569" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        
        {/* Headlight */}
        <circle cx="145" cy="45" r="5" fill="#fef08a" />
        <path d="M 150 45 L 180 35 L 180 55 Z" fill="#fef08a" opacity="0.4" />
        
        {/* Rider */}
        <path d="M 70 40 C 70 25, 80 15, 90 25 C 95 30, 90 40, 80 40 Z" fill="#ef4444" />
        <circle cx="85" cy="15" r="8" fill="#1e293b" /> {/* Helmet */}
      </g>
    </svg>
  );
}
