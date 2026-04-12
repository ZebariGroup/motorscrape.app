"use client";

export type SearchTab = {
  id: string;
  label: string;
  running: boolean;
  listingCount: number;
};

type SearchTabBarProps = {
  tabs: SearchTab[];
  activeTabId: string;
  onTabSelect: (id: string) => void;
  onTabClose: (id: string) => void;
  onAddTab: () => void;
  maxTabs: number;
  isPaidUser: boolean;
};

export function SearchTabBar({
  tabs,
  activeTabId,
  onTabSelect,
  onTabClose,
  onAddTab,
  maxTabs,
  isPaidUser,
}: SearchTabBarProps) {
  const canAddTab = isPaidUser && tabs.length < maxTabs;

  return (
    <div className="flex items-stretch border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950 overflow-x-auto">
      <div className="flex min-w-0 items-stretch gap-0">
        {tabs.map((tab, index) => {
          const isActive = tab.id === activeTabId;
          return (
            <div
              key={tab.id}
              className={`group relative flex min-w-0 max-w-[200px] shrink-0 items-center gap-1.5 border-r border-zinc-200 px-3 py-2 text-sm dark:border-zinc-800 ${
                isActive
                  ? "bg-white text-zinc-900 dark:bg-zinc-950 dark:text-zinc-50"
                  : "bg-zinc-50 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-700 dark:bg-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
              } cursor-pointer select-none`}
              onClick={() => onTabSelect(tab.id)}
              role="tab"
              aria-selected={isActive}
            >
              {/* Active indicator bar */}
              {isActive && (
                <span className="absolute inset-x-0 bottom-0 h-0.5 bg-emerald-500" />
              )}

              {/* Running pulse dot */}
              {tab.running ? (
                <span className="relative flex h-2 w-2 shrink-0">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                </span>
              ) : tab.listingCount > 0 ? (
                <span className="flex h-2 w-2 shrink-0 rounded-full bg-emerald-500/40" />
              ) : (
                <span className="flex h-2 w-2 shrink-0 rounded-full bg-zinc-300 dark:bg-zinc-700" />
              )}

              {/* Label */}
              <span className="min-w-0 truncate font-medium leading-none">
                {tab.label || `Search ${index + 1}`}
              </span>

              {/* Listing count badge */}
              {tab.listingCount > 0 && !tab.running && (
                <span className="shrink-0 rounded-full bg-zinc-200 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-zinc-600 dark:bg-zinc-700 dark:text-zinc-300">
                  {tab.listingCount}
                </span>
              )}

              {/* Close button — only shown if more than one tab */}
              {tabs.length > 1 && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onTabClose(tab.id);
                  }}
                  className="ml-0.5 shrink-0 rounded p-0.5 opacity-0 transition-opacity hover:bg-zinc-200 hover:text-zinc-800 group-hover:opacity-100 dark:hover:bg-zinc-700 dark:hover:text-zinc-100"
                  aria-label={`Close ${tab.label || `Search ${index + 1}`}`}
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 16 16"
                    fill="currentColor"
                    className="h-3 w-3"
                  >
                    <path d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z" />
                  </svg>
                </button>
              )}
            </div>
          );
        })}
      </div>

      {/* Add tab button */}
      {canAddTab ? (
        <button
          type="button"
          onClick={onAddTab}
          title="Open new search tab"
          className="flex shrink-0 items-center gap-1 px-3 py-2 text-sm text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-700 dark:text-zinc-500 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 16 16"
            fill="currentColor"
            className="h-4 w-4"
          >
            <path d="M8.75 3.75a.75.75 0 0 0-1.5 0v3.5h-3.5a.75.75 0 0 0 0 1.5h3.5v3.5a.75.75 0 0 0 1.5 0v-3.5h3.5a.75.75 0 0 0 0-1.5h-3.5v-3.5Z" />
          </svg>
          <span className="hidden sm:inline text-xs font-medium">New Search</span>
        </button>
      ) : isPaidUser && tabs.length >= maxTabs ? (
        <div
          title={`Maximum ${maxTabs} simultaneous searches on your plan`}
          className="flex shrink-0 items-center gap-1 px-3 py-2 text-xs text-zinc-300 dark:text-zinc-600 cursor-not-allowed"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 16 16"
            fill="currentColor"
            className="h-4 w-4"
          >
            <path d="M8.75 3.75a.75.75 0 0 0-1.5 0v3.5h-3.5a.75.75 0 0 0 0 1.5h3.5v3.5a.75.75 0 0 0 1.5 0v-3.5h3.5a.75.75 0 0 0 0-1.5h-3.5v-3.5Z" />
          </svg>
          <span className="hidden sm:inline">{maxTabs} max</span>
        </div>
      ) : null}
    </div>
  );
}
