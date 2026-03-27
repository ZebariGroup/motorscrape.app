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
    models: ["Integra", "MDX", "RDX", "TLX", "ZDX"],
  },
  {
    make: "Alfa Romeo",
    models: ["Giulia", "Stelvio", "Tonale"],
  },
  {
    make: "Audi",
    models: ["A3", "A4", "A5", "A6", "A7", "e-tron GT", "Q3", "Q4 e-tron", "Q5", "Q7", "Q8", "RS 5", "RS 6 Avant", "RS Q8", "S3", "S4", "S5", "SQ5"],
  },
  {
    make: "BMW",
    models: ["2 Series", "3 Series", "4 Series", "5 Series", "7 Series", "8 Series", "i4", "i5", "i7", "iX", "M2", "M3", "M4", "M5", "X1", "X2", "X3", "X4", "X5", "X6", "X7", "XM", "Z4"],
  },
  {
    make: "Buick",
    models: ["Enclave", "Encore GX", "Envista"],
  },
  {
    make: "Cadillac",
    models: ["CT4", "CT5", "Escalade", "LYRIQ", "OPTIQ", "XT4", "XT5", "XT6"],
  },
  {
    make: "Chevrolet",
    models: ["Blazer", "Blazer EV", "Camaro", "Colorado", "Corvette", "Equinox", "Equinox EV", "Express", "Malibu", "Silverado 1500", "Silverado HD", "Suburban", "Tahoe", "Trailblazer", "Traverse", "Trax"],
  },
  {
    make: "Chrysler",
    models: ["Pacifica", "Voyager"],
  },
  {
    make: "Dodge",
    models: ["Charger", "Challenger", "Durango", "Hornet"],
  },
  {
    make: "Ford",
    models: ["Bronco", "Bronco Sport", "Escape", "Expedition", "Explorer", "F-150", "F-150 Lightning", "Maverick", "Mustang", "Mustang Mach-E", "Ranger", "Super Duty", "Transit"],
  },
  {
    make: "Genesis",
    models: ["G70", "G80", "G90", "GV60", "GV70", "GV80"],
  },
  {
    make: "GMC",
    models: ["Acadia", "Canyon", "HUMMER EV", "Savana", "Sierra 1500", "Sierra HD", "Terrain", "Yukon"],
  },
  {
    make: "Honda",
    models: ["Accord", "Civic", "CR-V", "HR-V", "Odyssey", "Passport", "Pilot", "Prologue", "Ridgeline"],
  },
  {
    make: "Hyundai",
    models: ["Elantra", "IONIQ 5", "IONIQ 6", "Kona", "Palisade", "Santa Cruz", "Santa Fe", "Sonata", "Tucson", "Venue"],
  },
  {
    make: "INFINITI",
    models: ["Q50", "QX50", "QX55", "QX60", "QX80"],
  },
  {
    make: "Jaguar",
    models: ["F-PACE", "F-TYPE", "I-PACE"],
  },
  {
    make: "Jeep",
    models: ["Compass", "Gladiator", "Grand Cherokee", "Grand Wagoneer", "Wrangler", "Wagoneer"],
  },
  {
    make: "Kia",
    models: ["Carnival", "EV6", "EV9", "Forte", "K5", "Niro", "Seltos", "Sorento", "Soul", "Sportage", "Telluride"],
  },
  {
    make: "Land Rover",
    models: ["Defender", "Discovery", "Discovery Sport", "Range Rover", "Range Rover Evoque", "Range Rover Sport", "Range Rover Velar"],
  },
  {
    make: "Lexus",
    models: ["ES", "GX", "IS", "LC", "LS", "LX", "NX", "RX", "RZ", "TX", "UX"],
  },
  {
    make: "Lincoln",
    models: ["Aviator", "Corsair", "Nautilus", "Navigator"],
  },
  {
    make: "Lucid",
    models: ["Air", "Gravity"],
  },
  {
    make: "Maserati",
    models: ["Ghibli", "Grecale", "GranTurismo", "Levante", "MC20", "Quattroporte"],
  },
  {
    make: "Mazda",
    models: ["CX-30", "CX-5", "CX-50", "CX-70", "CX-90", "Mazda3", "MX-5 Miata"],
  },
  {
    make: "Mercedes-Benz",
    models: ["C-Class", "CLA", "CLE", "E-Class", "EQS", "EQS SUV", "G-Class", "GLA", "GLB", "GLE", "GLS", "S-Class", "Sprinter"],
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
    models: ["Altima", "Ariya", "Armada", "Frontier", "Kicks", "LEAF", "Murano", "Pathfinder", "Rogue", "Sentra", "Titan", "Versa", "Z"],
  },
  {
    make: "Polestar",
    models: ["Polestar 2", "Polestar 3", "Polestar 4"],
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
    make: "Subaru",
    models: ["Ascent", "BRZ", "Crosstrek", "Forester", "Impreza", "Legacy", "Outback", "Solterra", "WRX"],
  },
  {
    make: "Tesla",
    models: ["Cybertruck", "Model 3", "Model S", "Model X", "Model Y"],
  },
  {
    make: "Toyota",
    models: ["4Runner", "bZ4X", "Camry", "Corolla", "Corolla Cross", "Crown", "GR86", "Grand Highlander", "Highlander", "Land Cruiser", "Prius", "RAV4", "Sequoia", "Sienna", "Tacoma", "Tundra", "Venza"],
  },
  {
    make: "Volkswagen",
    models: ["Atlas", "Atlas Cross Sport", "Golf GTI", "Golf R", "ID.4", "Jetta", "Taos", "Tiguan"],
  },
  {
    make: "Volvo",
    models: ["C40 Recharge", "EX30", "EX90", "S60", "S90", "V60 Cross Country", "V90 Cross Country", "XC40", "XC60", "XC90"],
  },
] as const;

const VEHICLE_CATALOG_BY_CATEGORY: Record<VehicleCategory, readonly { make: string; models: readonly string[] }[]> = {
  car: CAR_CATALOG,
  motorcycle: [],
  boat: [],
  other: [],
};

export function getMakesForCategory(category: VehicleCategory): readonly string[] {
  return VEHICLE_CATALOG_BY_CATEGORY[category].map((entry) => entry.make);
}

export function getModelsForMake(category: VehicleCategory, make: string): readonly string[] {
  return VEHICLE_CATALOG_BY_CATEGORY[category].find((entry) => entry.make === make)?.models ?? [];
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
