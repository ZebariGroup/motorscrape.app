import { useState, useRef, useEffect } from "react";

export function MultiModelSelect({
  models,
  selectedModels,
  onChange,
  disabled,
  allowAnyModel,
}: {
  models: readonly string[];
  selectedModels: string[];
  onChange: (models: string[]) => void;
  disabled: boolean;
  allowAnyModel: boolean;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handlePointerDownOutside = (e: PointerEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDownOutside, true);
    return () => document.removeEventListener("pointerdown", handlePointerDownOutside, true);
  }, []);

  const toggleModel = (m: string) => {
    if (selectedModels.includes(m)) {
      onChange(selectedModels.filter((x) => x !== m));
    } else {
      if (selectedModels.length >= 5) return;
      onChange([...selectedModels, m]);
    }
  };

  const displayText =
    selectedModels.length === 0
      ? allowAnyModel
        ? "Any model"
        : "Select models (up to 5)"
      : selectedModels.join(", ");

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        disabled={disabled || models.length === 0}
        onClick={() => setIsOpen(!isOpen)}
        className="flex min-h-11 w-full items-center justify-between rounded-lg border border-zinc-300 bg-white px-3 py-2 text-left text-base text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-0 sm:text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
      >
        <span className="truncate">{models.length === 0 ? "Select make first" : displayText}</span>
        <svg
          className="ml-2 h-4 w-4 shrink-0 text-zinc-500"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && models.length > 0 && (
        <div className="absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-lg border border-zinc-200 bg-white py-1 shadow-lg dark:border-zinc-700 dark:bg-zinc-800">
          {allowAnyModel && (
            <label className="flex min-h-11 cursor-pointer items-center px-3 py-2 hover:bg-zinc-100 sm:min-h-0 dark:hover:bg-zinc-700">
              <input
                type="checkbox"
                className="rounded border-zinc-300 text-emerald-600 focus:ring-emerald-500"
                checked={selectedModels.length === 0}
                onChange={() => {
                  onChange([]);
                  setIsOpen(false);
                }}
              />
              <span className="ml-2 text-sm text-zinc-900 dark:text-zinc-100">Any model</span>
            </label>
          )}
          {models.map((m) => {
            const isSelected = selectedModels.includes(m);
            const isDisabled = !isSelected && selectedModels.length >= 5;
            return (
              <label
                key={m}
                className={`flex min-h-11 items-center px-3 py-2 sm:min-h-0 ${
                  isDisabled ? "cursor-not-allowed opacity-50" : "cursor-pointer hover:bg-zinc-100 dark:hover:bg-zinc-700"
                }`}
              >
                <input
                  type="checkbox"
                  className="rounded border-zinc-300 text-emerald-600 focus:ring-emerald-500"
                  checked={isSelected}
                  disabled={isDisabled}
                  onChange={() => toggleModel(m)}
                />
                <span className="ml-2 text-sm text-zinc-900 dark:text-zinc-100">{m}</span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}
