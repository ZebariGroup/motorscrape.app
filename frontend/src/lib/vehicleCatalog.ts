import type { MarketRegion } from "@/lib/marketRegion";

export type VehicleCategory = "car" | "motorcycle" | "boat" | "other";

export const VEHICLE_CATEGORY_OPTIONS: Array<{ value: VehicleCategory; label: string }> = [
  { value: "car", label: "Cars and trucks" },
  { value: "motorcycle", label: "Motorcycles" },
  { value: "boat", label: "Boats" },
  { value: "other", label: "Other motor vehicles" },
];

function enabledCategorySet(): Set<VehicleCategory> {
  const raw = process.env.NEXT_PUBLIC_ENABLED_VEHICLE_CATEGORIES?.trim() || "car";
  const enabled = raw
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter((value): value is VehicleCategory =>
      value === "car" || value === "motorcycle" || value === "boat" || value === "other",
    );
  return new Set(enabled.length > 0 ? enabled : ["car"]);
}

const ENABLED_CATEGORY_SET = enabledCategorySet();
export const ENABLED_VEHICLE_CATEGORY_OPTIONS = VEHICLE_CATEGORY_OPTIONS.filter((option) =>
  ENABLED_CATEGORY_SET.has(option.value),
);

const CAR_CATALOG = [
  {
    make: "Acura",
    models: ["CL", "ILX", "Integra", "Legend", "MDX", "RDX", "RLX", "RSX", "TLX", "TSX", "Vigor", "ZDX"],
  },
  {
    make: "Alfa Romeo",
    models: ["Giulia", "Stelvio", "Tonale"],
  },
  {
    make: "Aston Martin",
    models: ["DB11", "DB12", "DBS", "DBX", "Vantage"],
  },
  {
    make: "Audi",
    models: ["A3", "A4", "A5", "A6", "A7", "A8", "Cabriolet", "Q3", "Q4 e-tron", "Q5", "Q7", "Q8", "R8", "RS 5", "RS 6 Avant", "RS Q8", "S3", "S4", "S5", "SQ5", "TT", "allroad", "e-tron GT"],
  },
  {
    make: "BMW",
    models: ["2 Series", "3 Series", "4 Series", "5 Series", "6 Series", "7 Series", "8 Series", "M2", "M3", "M4", "M5", "X1", "X2", "X3", "X4", "X5", "X6", "X7", "XM", "Z3", "Z4", "Z8", "i3", "i4", "i5", "i7", "i8", "iX"],
  },
  {
    make: "Bentley",
    models: ["Bentayga", "Continental GT", "Flying Spur"],
  },
  {
    make: "Bugatti",
    models: ["Chiron", "Veyron"],
  },
  {
    make: "Buick",
    models: ["Cascada", "Century", "Enclave", "Encore", "Encore GX", "Envista", "LaCrosse", "LeSabre", "Lucerne", "Park Avenue", "Regal", "Rendezvous", "Verano"],
  },
  {
    make: "Cadillac",
    models: ["ATS", "CT4", "CT5", "CTS", "DTS", "DeVille", "ELR", "Escalade", "LYRIQ", "OPTIQ", "SRX", "STS", "Seville", "XLR", "XT4", "XT5", "XT6", "XTS"],
  },
  {
    make: "Chevrolet",
    models: ["Astro", "Avalanche", "Aveo", "Blazer", "Blazer EV", "Bolt EUV", "Bolt EV", "Camaro", "Cavalier", "Cobalt", "Colorado", "Corvette", "Cruze", "Equinox", "Equinox EV", "Express", "HHR", "Impala", "Lumina", "Malibu", "Monte Carlo", "SS", "SSR", "Silverado 1500", "Silverado HD", "Sonic", "Spark", "Suburban", "Tahoe", "Tracker", "Trailblazer", "Traverse", "Trax", "Uplander", "Venture", "Volt"],
  },
  {
    make: "Chrysler",
    models: ["200", "300", "300M", "Aspen", "Concorde", "Crossfire", "PT Cruiser", "Pacifica", "Sebring", "Town & Country", "Voyager"],
  },
  {
    make: "Daewoo",
    models: ["Lanos", "Leganza", "Nubira"],
  },
  {
    make: "Datsun",
    models: ["240Z", "260Z", "280Z", "280ZX"],
  },
  {
    make: "DeLorean",
    models: ["DMC-12"],
  },
  {
    make: "Dodge",
    models: ["Avenger", "Caliber", "Caravan", "Challenger", "Charger", "Dart", "Durango", "Grand Caravan", "Hornet", "Intrepid", "Journey", "Magnum", "Neon", "Nitro", "Stratus", "Viper"],
  },
  {
    make: "Eagle",
    models: ["Talon", "Vision"],
  },
  {
    make: "Ferrari",
    models: ["296 GTB", "488 GTB", "812 Superfast", "F8 Tributo", "Portofino", "Roma", "SF90 Stradale"],
  },
  {
    make: "Fiat",
    models: ["124 Spider", "500", "500L", "500X"],
  },
  {
    make: "Fisker",
    models: ["Karma", "Ocean"],
  },
  {
    make: "Ford",
    models: ["Aerostar", "Bronco", "Bronco Sport", "C-MAX", "Crown Victoria", "E-Series", "EcoSport", "Edge", "Escape", "Escort", "Excursion", "Expedition", "Explorer", "F-150", "F-150 Lightning", "Fiesta", "Five Hundred", "Flex", "Focus", "Freestar", "Fusion", "Maverick", "Mustang", "Mustang Mach-E", "Ranger", "Super Duty", "Taurus", "Thunderbird", "Transit", "Windstar"],
  },
  {
    make: "Genesis",
    models: ["G70", "G80", "G90", "GV60", "GV70", "GV80"],
  },
  {
    make: "Geo",
    models: ["Metro", "Prizm", "Tracker"],
  },
  {
    make: "GMC",
    models: ["Acadia", "Canyon", "HUMMER EV", "Savana", "Sierra 1500", "Sierra HD", "Terrain", "Yukon"],
  },
  {
    make: "Honda",
    models: ["Accord", "CR-V", "CR-Z", "Civic", "Clarity", "Crosstour", "Element", "Fit", "HR-V", "Insight", "Odyssey", "Passport", "Pilot", "Prelude", "Prologue", "Ridgeline", "S2000"],
  },
  {
    make: "Hummer",
    models: ["H1", "H2", "H3"],
  },
  {
    make: "Hyundai",
    models: ["Accent", "Azera", "Elantra", "Entourage", "Equus", "Genesis Coupe", "IONIQ 5", "IONIQ 6", "Ioniq", "Kona", "Palisade", "Santa Cruz", "Santa Fe", "Santa Fe Sport", "Sonata", "Tiburon", "Tucson", "Veloster", "Venue", "Veracruz"],
  },
  {
    make: "INFINITI",
    models: ["Q50", "QX50", "QX55", "QX60", "QX80"],
  },
  {
    make: "Ineos",
    models: ["Grenadier"],
  },
  {
    make: "Isuzu",
    models: ["Amigo", "Ascender", "Axiom", "Rodeo", "Trooper"],
  },
  {
    make: "Jaguar",
    models: ["F-PACE", "F-TYPE", "I-PACE"],
  },
  {
    make: "Jeep",
    models: ["Cherokee", "Commander", "Compass", "Gladiator", "Grand Cherokee", "Grand Wagoneer", "Liberty", "Patriot", "Renegade", "Wagoneer", "Wrangler"],
  },
  {
    make: "Karma",
    models: ["GS-6", "Revero"],
  },
  {
    make: "Kia",
    models: ["Amanti", "Borrego", "Cadenza", "Carnival", "EV6", "EV9", "Forte", "K5", "K900", "Niro", "Optima", "Rio", "Rondo", "Sedona", "Seltos", "Sephia", "Sorento", "Soul", "Spectra", "Sportage", "Stinger", "Telluride"],
  },
  {
    make: "Lamborghini",
    models: ["Aventador", "Huracan", "Urus"],
  },
  {
    make: "Land Rover",
    models: ["Defender", "Discovery", "Discovery Sport", "Range Rover", "Range Rover Evoque", "Range Rover Sport", "Range Rover Velar"],
  },
  {
    make: "Lexus",
    models: ["CT", "ES", "GS", "GX", "HS", "IS", "LC", "LS", "LX", "NX", "RX", "RZ", "SC", "TX", "UX"],
  },
  {
    make: "Lincoln",
    models: ["Aviator", "Corsair", "Nautilus", "Navigator"],
  },
  {
    make: "Lotus",
    models: ["Emira", "Evora", "Exige"],
  },
  {
    make: "Lucid",
    models: ["Air", "Gravity"],
  },
  {
    make: "Maserati",
    models: ["Ghibli", "GranTurismo", "Grecale", "Levante", "MC20", "Quattroporte"],
  },
  {
    make: "Maybach",
    models: ["57", "62"],
  },
  {
    make: "Mazda",
    models: ["B-Series", "CX-3", "CX-30", "CX-5", "CX-50", "CX-7", "CX-70", "CX-9", "CX-90", "MPV", "MX-5 Miata", "Mazda2", "Mazda3", "Mazda5", "Mazda6", "Protege", "RX-8", "Tribute"],
  },
  {
    make: "McLaren",
    models: ["570S", "600LT", "720S", "Artura", "GT"],
  },
  {
    make: "Mercedes-Benz",
    models: ["C-Class", "CLA", "CLE", "E-Class", "EQS", "EQS SUV", "G-Class", "GLA", "GLB", "GLE", "GLS", "S-Class", "Sprinter"],
  },
  {
    make: "Mercury",
    models: ["Cougar", "Grand Marquis", "Mariner", "Milan", "Mountaineer", "Sable"],
  },
  {
    make: "MINI",
    models: ["Clubman", "Convertible", "Countryman", "Hardtop"],
  },
  {
    make: "Mitsubishi",
    models: ["Eclipse Cross", "Mirage", "Outlander", "Outlander PHEV", "Outlander Sport"],
  },
  {
    make: "Nissan",
    models: ["350Z", "370Z", "Altima", "Ariya", "Armada", "Cube", "Frontier", "Juke", "Kicks", "LEAF", "Maxima", "Murano", "NV", "NV200", "Pathfinder", "Quest", "Rogue", "Rogue Select", "Rogue Sport", "Sentra", "Titan", "Versa", "Xterra", "Z"],
  },
  {
    make: "Oldsmobile",
    models: ["Alero", "Aurora", "Bravada", "Intrigue", "Silhouette"],
  },
  {
    make: "Plymouth",
    models: ["Breeze", "Neon", "Prowler", "Voyager"],
  },
  {
    make: "Polestar",
    models: ["Polestar 2", "Polestar 3", "Polestar 4"],
  },
  {
    make: "Pontiac",
    models: ["Aztek", "Bonneville", "G5", "G6", "G8", "GTO", "Grand Am", "Grand Prix", "Montana", "Solstice", "Sunfire", "Vibe"],
  },
  {
    make: "Porsche",
    models: ["718 Boxster", "718 Cayman", "911", "Cayenne", "Macan", "Panamera", "Taycan"],
  },
  {
    make: "Ram",
    models: ["1500", "2500", "3500", "ProMaster"],
  },
  {
    make: "Rivian",
    models: ["R1S", "R1T"],
  },
  {
    make: "Rolls-Royce",
    models: ["Cullinan", "Dawn", "Ghost", "Phantom", "Wraith"],
  },
  {
    make: "Saab",
    models: ["9-2X", "9-3", "9-4X", "9-5"],
  },
  {
    make: "Saturn",
    models: ["Aura", "Ion", "L-Series", "Outlook", "Relay", "S-Series", "Sky", "Vue"],
  },
  {
    make: "Scion",
    models: ["FR-S", "iA", "iM", "iQ", "tC", "xA", "xB", "xD"],
  },
  {
    make: "Smart",
    models: ["EQ fortwo", "fortwo"],
  },
  {
    make: "Subaru",
    models: ["Ascent", "B9 Tribeca", "BRZ", "Baja", "Crosstrek", "Forester", "Impreza", "Legacy", "Outback", "Solterra", "Tribeca", "WRX", "XV Crosstrek"],
  },
  {
    make: "Suzuki",
    models: ["Aerio", "Equator", "Forenza", "Grand Vitara", "Kizashi", "Reno", "SX4", "XL7"],
  },
  {
    make: "Tesla",
    models: ["Cybertruck", "Model 3", "Model S", "Model X", "Model Y"],
  },
  {
    make: "Toyota",
    models: ["4Runner", "Avalon", "C-HR", "Camry", "Celica", "Corolla", "Corolla Cross", "Crown", "Echo", "FJ Cruiser", "GR86", "Grand Highlander", "Highlander", "Land Cruiser", "MR2", "Matrix", "Prius", "RAV4", "Sequoia", "Sienna", "Supra", "Tacoma", "Tercel", "Tundra", "Venza", "Yaris", "Yaris iA", "bZ4X"],
  },
  {
    make: "Volkswagen",
    models: ["Atlas", "Atlas Cross Sport", "Beetle", "CC", "Cabrio", "Eos", "EuroVan", "Golf", "Golf Alltrack", "Golf GTI", "Golf R", "Golf SportWagen", "ID.4", "Jetta", "Passat", "Phaeton", "R32", "Rabbit", "Routan", "Taos", "Tiguan", "Touareg"],
  },
  {
    make: "Volvo",
    models: ["C30", "C40 Recharge", "C70", "EX30", "EX90", "S40", "S60", "S70", "S80", "V40", "V50", "V60 Cross Country", "V70", "V90 Cross Country", "XC40", "XC60", "XC90"],
  },
] as const;

const MOTORCYCLE_CATALOG = [
  {
    make: "BMW Motorrad",
    models: ["C 400 GT", "F 800 GS", "F 900 GS", "F 900 R", "M 1000 RR", "R 12", "R 1300 GS", "R 18", "S 1000 RR", "S 1000 XR"],
  },
  {
    make: "Can-Am",
    models: ["Canyon", "Ryker", "Ryker Rally", "Spyder F3", "Spyder RT", "Spyder Sea-to-Sky"],
  },
  {
    make: "Ducati",
    models: ["DesertX", "Diavel V4", "Hypermotard 698 Mono", "Monster", "Multistrada V4", "Panigale V2", "Panigale V4", "Scrambler Icon", "Streetfighter V2", "Streetfighter V4", "Supersport 950"],
  },
  {
    make: "Harley-Davidson",
    models: ["Breakout", "Fat Boy", "Heritage Classic", "Low Rider S", "Nightster", "Pan America 1250 ST", "Road Glide", "Road King Special", "Sportster S", "Street Bob", "Street Glide"],
  },
  {
    make: "Honda",
    models: [
      "Africa Twin",
      "CB500F",
      "CB650R",
      "CBR500R",
      "CBR650R",
      "CRF110F",
      "CRF300L",
      "FourTrax Foreman",
      "FourTrax Rancher",
      "FourTrax Recon",
      "FourTrax Rubicon",
      "Gold Wing",
      "Pioneer 520",
      "Pioneer 700",
      "Pioneer 1000",
      "Rebel 500",
      "Rebel 1100",
      "Shadow Phantom",
      "Talon 1000",
      "Transalp",
    ],
  },
  {
    make: "Arctic Cat",
    models: ["Alterra 600", "Alterra 700", "Blast M", "M 858", "Riot 600", "ZR 600", "Wildcat XX"],
  },
  {
    make: "CFMOTO",
    models: ["CForce 500", "CForce 600", "CForce 1000", "Ibex 450", "Ibex 800", "UForce 1000", "ZForce 950"],
  },
  {
    make: "Indian Motorcycle",
    models: ["101 Scout", "Chief Bobber", "Challenger", "Chieftain", "FTR", "Pursuit", "Roadmaster", "Scout", "Scout Bobber", "Scout Sixty", "Sport Chief"],
  },
  {
    make: "Kawasaki",
    models: ["Eliminator", "KLR650", "Ninja 500", "Ninja 650", "Ninja ZX-4RR", "Ninja ZX-6R", "Versys 650", "Vulcan S", "Z500", "Z650", "Z900"],
  },
  {
    make: "KTM",
    models: ["1290 Super Duke R EVO", "250 Duke", "390 Adventure", "390 Duke", "690 Enduro R", "790 Duke", "890 Adventure", "890 Duke R", "RC 390", "Super Adventure S", "Supermoto R"],
  },
  {
    make: "Polaris",
    models: ["General 1000", "Ranger 1000", "Ranger XP 1000", "RZR Pro XP", "RZR Turbo R", "Sportsman 570", "Sportsman XP 1000", "Xpedition ADV"],
  },
  {
    make: "Sea-Doo",
    models: ["FishPro Sport", "GTI 130", "GTI SE 170", "GTR 230", "RXP-X 325", "Spark Trixx", "Wake 170"],
  },
  {
    make: "Ski-Doo",
    models: ["Backcountry", "Expedition", "MXZ Adrenaline", "Renegade Adrenaline", "Summit Adrenaline", "Summit X", "Tundra LE"],
  },
  {
    make: "Slingshot",
    models: ["Slingshot S", "Slingshot SL", "Slingshot R"],
  },
  {
    make: "Suzuki",
    models: ["DR-Z4S", "GSX-8R", "GSX-8S", "GSX-R600", "GSX-R750", "GSX-S1000", "Hayabusa", "Katana", "SV650", "V-Strom 650", "V-Strom 800"],
  },
  {
    make: "Triumph",
    models: ["Bonneville Bobber", "Bonneville T100", "Bonneville T120", "Daytona 660", "Rocket 3", "Scrambler 1200", "Speed Triple 1200 RS", "Speed Twin 900", "Street Triple 765", "Tiger 900", "Trident 660"],
  },
  {
    make: "Yamaha",
    models: ["Bolt R-Spec", "MT-03", "MT-07", "MT-09", "Tenere 700", "Tracer 9", "XSR700", "XSR900", "YZF-R3", "YZF-R7", "YZF-R9"],
  },
] as const;

const BOAT_CATALOG = [
  {
    make: "Axis",
    models: ["A20", "A225", "A245", "T220", "T235", "T250"],
  },
  {
    make: "Bayliner",
    models: ["Ciera 8", "DX2000", "DX2050", "M15", "M17", "M19", "T18", "T20", "T22CC", "VR4", "VR5"],
  },
  {
    make: "Barletta",
    models: ["Aria", "Cabrio", "Corsa", "Lusso", "Leggera", "Reserve"],
  },
  {
    make: "Bennington",
    models: ["20 SVL", "21 SSB", "22 SXSR", "23 LSB", "24 LXSB", "24 RX Sport", "25 QX Sport"],
  },
  {
    make: "Boston Whaler",
    models: ["170 Montauk", "190 Montauk", "210 Vantage", "230 Outrage", "240 Vantage", "280 Dauntless"],
  },
  {
    make: "Chaparral",
    models: ["19 SSi", "21 Surf", "21 SSi", "23 Surf", "23 SSi", "247 SSX", "250 OSX", "267 SSX", "30 Surf"],
  },
  {
    make: "Chris Craft",
    models: ["Calypso 24", "Calypso 30", "Catalina 30", "Launch 25 GT", "Launch 28 GT", "Sportster 25"],
  },
  {
    make: "Cobalt",
    models: ["A29", "CS23", "R4", "R6", "R8", "R30"],
  },
  {
    make: "Crestliner",
    models: ["1650 Fish Hawk", "1750 Fish Hawk", "1850 Super Hawk", "MX 19", "VT 17", "XF 189"],
  },
  {
    make: "Four Winns",
    models: ["H1", "H2", "H4", "HD3", "HD5", "TH36"],
  },
  {
    make: "Godfrey",
    models: ["AquaPatio 235UL", "Monaco 235SB", "Sweetwater 2286 SB", "Sweetwater 2486 SFL", "Xperience 2086 CX", "Xperience 2286 SBX"],
  },
  {
    make: "Hurricane",
    models: ["185 SS", "188 OB", "201 OB", "217 SD", "231 OB", "2600"],
  },
  {
    make: "Key West Boats",
    models: ["1720CC", "188BR", "203FS", "219FS", "239FS", "263FS"],
  },
  {
    make: "Lund",
    models: ["1650 Angler", "1875 Crossover XS", "1875 Impact XS", "1875 Pro-V Bass XS", "1975 Tyee", "2025 Impact XS", "2075 Pro-V Bass XS"],
  },
  {
    make: "Malibu",
    models: ["20 VTX", "21 LX", "21 MLX", "22 LSV", "23 LSV", "23 MXZ", "24 MXZ", "25 LSV", "M220", "M230", "M240"],
  },
  {
    make: "Manitou",
    models: ["Aurora LE", "Cruise 22", "Explore 24", "LX 25", "XT 25", "X-Plode 25"],
  },
  {
    make: "MasterCraft",
    models: ["NXT20", "NXT22", "NXT24", "ProStar", "X22", "X24", "XStar", "XT22", "XT23"],
  },
  {
    make: "Moomba",
    models: ["Craz", "Kaiyen", "Makai", "Max", "Mojo", "Tykon"],
  },
  {
    make: "Monterey",
    models: ["218SS", "255SS", "275SS", "298SS", "M-225", "M-45"],
  },
  {
    make: "Nautique",
    models: ["G21", "G23", "GS20", "GS22", "S23", "S25"],
  },
  {
    make: "Premier",
    models: ["230 Solaris", "230 Sunsation", "250 Intrigue", "250 Solaris", "290 Grand Majestic", "Boundary Waters 231"],
  },
  {
    make: "Ranger Boats",
    models: ["2080MS Angler", "620FS Pro", "621FS Pro", "RT178", "RT188", "VS1660 SC", "VS1682 WT", "Z175", "Z185", "Z520R"],
  },
  {
    make: "Regal",
    models: ["26 XO", "33 XO", "36 XO", "LS2", "LX4", "LX6"],
  },
  {
    make: "Robalo",
    models: ["160", "200ES", "202EX", "222EX", "226 Cayman", "R317"],
  },
  {
    make: "Sea Ray",
    models: ["SDX 250", "SDX 270", "SLX 260", "SLX 280", "SPX 190", "SPX 210", "SPX 230", "Sundancer 320", "Sundancer 370"],
  },
  {
    make: "Starcraft",
    models: ["EX 20 C", "LX 20 R", "SVX 171 OB", "SVX 191 OB", "SVX 211 OB", "MX 25 L"],
  },
  {
    make: "Sylvan",
    models: ["L-3 DLZ", "Mirage 820", "Mirage X3", "S3 CRS", "X1", "X3 CLZ"],
  },
  {
    make: "Tracker",
    models: ["Bass Tracker Classic XL", "Grizzly 1648", "Guide V-16 SC", "Pro Guide V-175 Combo", "Pro Team 175 TXW", "Pro Team 190 TX", "Targa V-18 Combo"],
  },
  {
    make: "Yamaha Boats",
    models: ["195S", "222XD", "252SD", "252XE", "255XD", "AR190", "AR220", "AR250", "SX190", "SX220"],
  },
] as const;

/** Extra model lines common in EU/UK; merged into US rows for `marketRegion === "eu"`. */
const EU_EXTRA_MODELS_BY_MAKE: Record<string, readonly string[]> = {
  BMW: [
    "1 Series",
    "2 Series Gran Tourer",
    "2 Series Active Tourer",
    "iX1",
    "iX2",
    "X2",
  ],
  Audi: ["A1", "Q2", "e-tron", "e-tron Sportback"],
  "Mercedes-Benz": ["EQA", "EQB", "EQC", "EQV", "T-Class", "Citan", "CLA Shooting Brake"],
  Volkswagen: [
    "ID.3",
    "ID.5",
    "ID.7",
    "Passat",
    "Polo",
    "T-Cross",
    "T-Roc",
    "Touran",
    "Arteon",
    "California",
  ],
  Toyota: ["Aygo X", "bZ4X", "C-HR", "Proace", "Proace City"],
  Ford: ["Puma", "Kuga", "Focus", "Mondeo", "Tourneo", "Ranger Raptor"],
  Hyundai: ["Bayon", "i10", "i20", "i30", "IONIQ", "IONIQ 5 N"],
  Kia: ["Ceed", "Picanto", "Stonic", "XCeed", "EV3"],
  Nissan: ["Juke", "Qashqai", "X-Trail", "Townstar", "Primastar"],
  Honda: ["e:Ny1", "Jazz", "ZR-V", "HR-V"],
  Mazda: ["2", "CX-3", "MX-30"],
  Subaru: ["Crosstrek", "Levorg"],
  Volvo: ["EX40", "EC40"],
  MINI: ["Aceman", "Cooper", "Cooper Electric"],
  Porsche: ["Taycan Cross Turismo", "718 Spyder"],
  "Land Rover": ["Range Rover SV", "Defender Octa"],
  Fiat: ["500e", "600e", "Panda", "Tipo"],
  Smart: ["#1", "#3"],
};

/** Brands and lines primarily marketed in Europe; merged into the car catalog for EU. */
const EU_ONLY_CAR_BRANDS: readonly { make: string; models: readonly string[] }[] = [
  { make: "Abarth", models: ["500e", "595", "695"] },
  { make: "Alpine", models: ["A110", "A290"] },
  { make: "Citroën", models: ["C3", "C4", "C5 Aircross", "ë-C4", "Berlingo", "SpaceTourer", "Ami"] },
  { make: "Cupra", models: ["Born", "Formentor", "Leon", "Tavascan", "Terramar", "Ateca"] },
  { make: "Dacia", models: ["Duster", "Sandero", "Jogger", "Spring", "Bigster"] },
  { make: "DS", models: ["DS 3", "DS 4", "DS 7", "DS 9"] },
  { make: "Lancia", models: ["Ypsilon"] },
  { make: "MG", models: ["MG3", "MG4", "MG5", "ZS", "HS", "Cyberster"] },
  { make: "Opel", models: ["Corsa", "Astra", "Mokka", "Grandland", "Combo", "Frontera", "Vivaro"] },
  { make: "Peugeot", models: ["208", "2008", "308", "3008", "408", "5008", "Rifter", "Partner", "e-208", "e-2008"] },
  { make: "Renault", models: ["Clio", "Captur", "Austral", "Rafale", "Mégane", "Scénic", "Kangoo", "Trafic", "Master", "5 E-Tech"] },
  { make: "SEAT", models: ["Ibiza", "Leon", "Ateca", "Tarraco"] },
  { make: "Škoda", models: ["Fabia", "Scala", "Octavia", "Superb", "Kamiq", "Karoq", "Kodiaq", "Enyaq", "Elroq"] },
  { make: "SsangYong", models: ["Torres", "Korando", "Rexton", "Musso"] },
  { make: "Vauxhall", models: ["Corsa", "Astra", "Mokka", "Grandland", "Frontera", "Vivaro", "Combo"] },
];

function mergeEuCarCatalog(): { make: string; models: readonly string[] }[] {
  const byMake = new Map<string, Set<string>>();
  for (const row of CAR_CATALOG) {
    byMake.set(row.make, new Set([...row.models]));
  }
  for (const [make, models] of Object.entries(EU_EXTRA_MODELS_BY_MAKE)) {
    const bucket = byMake.get(make) ?? new Set();
    for (const m of models) bucket.add(m);
    byMake.set(make, bucket);
  }
  for (const row of EU_ONLY_CAR_BRANDS) {
    const bucket = byMake.get(row.make) ?? new Set();
    for (const m of row.models) bucket.add(m);
    byMake.set(row.make, bucket);
  }
  return [...byMake.entries()]
    .map(([make, set]) => ({
      make,
      models: [...set].sort((a, b) => a.localeCompare(b)) as readonly string[],
    }))
    .sort((a, b) => a.make.localeCompare(b.make));
}

const EU_CAR_CATALOG_MERGED: readonly { make: string; models: readonly string[] }[] = mergeEuCarCatalog();

const VEHICLE_CATALOG_BY_CATEGORY: Record<VehicleCategory, readonly { make: string; models: readonly string[] }[]> = {
  car: CAR_CATALOG,
  motorcycle: MOTORCYCLE_CATALOG,
  boat: BOAT_CATALOG,
  other: [],
};

function vehicleCatalogRows(
  category: VehicleCategory,
  marketRegion: MarketRegion,
): readonly { make: string; models: readonly string[] }[] {
  if (category === "car" && marketRegion === "eu") {
    return EU_CAR_CATALOG_MERGED;
  }
  return VEHICLE_CATALOG_BY_CATEGORY[category];
}

export function getMakesForCategory(category: VehicleCategory, marketRegion: MarketRegion = "us"): readonly string[] {
  return vehicleCatalogRows(category, marketRegion).map((entry) => entry.make);
}

export function getMakeGroupsForCategory(
  category: VehicleCategory,
  marketRegion: MarketRegion = "us",
): { current: readonly string[]; discontinued: readonly string[] } {
  const rows = vehicleCatalogRows(category, marketRegion);
  const current: string[] = [];
  const discontinued: string[] = [];

  for (const row of rows) {
    const isDiscontinued = row.models.length === 0 && ((row as any).discontinuedModels?.length ?? 0) > 0;
    if (isDiscontinued) {
      discontinued.push(row.make);
    } else {
      current.push(row.make);
    }
  }

  return { current, discontinued };
}

export function getModelsForMake(
  category: VehicleCategory,
  make: string,
  marketRegion: MarketRegion = "us",
): readonly string[] {
  const row = vehicleCatalogRows(category, marketRegion).find((entry) => entry.make === make);
  if (!row) return [];
  const current = row.models ?? [];
  const discontinued = (row as any).discontinuedModels ?? [];
  return [...current, ...discontinued];
}

export function getModelGroupsForMake(
  category: VehicleCategory,
  make: string,
  marketRegion: MarketRegion = "us",
): { current: readonly string[]; discontinued: readonly string[] } {
  const row = vehicleCatalogRows(category, marketRegion).find((entry) => entry.make === make);
  if (!row) return { current: [], discontinued: [] };
  return {
    current: row.models ?? [],
    discontinued: (row as any).discontinuedModels ?? [],
  };
}

export function categoryUsesCatalog(category: VehicleCategory): boolean {
  return VEHICLE_CATALOG_BY_CATEGORY[category].length > 0;
}

export function vehicleCategoryLabel(category: VehicleCategory): string {
  return VEHICLE_CATEGORY_OPTIONS.find((option) => option.value === category)?.label ?? "Vehicles";
}

export function defaultVehicleCategory(): VehicleCategory {
  return ENABLED_VEHICLE_CATEGORY_OPTIONS[0]?.value ?? "car";
}
