"use client";

import {
  startTransition,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Motorcycle } from "./Motorcycle";
import { RaceCar } from "./RaceCar";
import { Boat } from "./Boat";
import { Snowmobile } from "./Snowmobile";

type CharacterType = "motorcycle" | "racecar" | "boat" | "snowmobile";

const CHARACTERS: Record<CharacterType, React.FC> = {
  motorcycle: Motorcycle,
  racecar: RaceCar,
  boat: Boat,
  snowmobile: Snowmobile,
};

const OBSTACLES = ["🚧", "🕳️", "🛑", "🪨", "🪵"];

const HIGH_SCORE_KEY = "motorscrape-minigame-highscore";
const FRAME_MS_CAP = 32;
const BASE_SPEED = 250;
const MAX_SPEED = 520;
const GRAVITY = 1680;
const JUMP_VELOCITY = -500;
const MAX_JUMP_HEIGHT = 76;
const JUMP_HOLD_MS = 110;
const JUMP_HOLD_GRAVITY_SCALE = 0.68;
const JUMP_RELEASE_DAMPING = 0.58;
const LANDING_SQUASH_MS = 110;
const GROUND_Y = 0;
const PLAYER_WIDTH = 60;
const PLAYER_HEIGHT = 40;
const PLAYER_HIT_INSET = 6;
const PLAYER_LEFT = 20;
const JUMP_BUFFER_MS = 130;
const SEARCH_DONE_PHRASE = ["YOUR", "SEARCH", "IS", "DONE"] as const;
const WORD_SPAWN_GAP_MS = 400;

type GameObstacle = {
  x: number;
  width: number;
  height: number;
  emoji?: string;
  text?: string;
  accent?: boolean;
};

type PendingWord = { spawnAt: number; text: string };

type DifficultyTuning = {
  speedTarget: number;
  spawnMinMs: number;
  spawnMaxMs: number;
};

function getDifficulty(score: number): DifficultyTuning {
  if (score < 25) return { speedTarget: 250, spawnMinMs: 1350, spawnMaxMs: 1850 };
  if (score < 60) return { speedTarget: 300, spawnMinMs: 1150, spawnMaxMs: 1600 };
  if (score < 110) return { speedTarget: 360, spawnMinMs: 980, spawnMaxMs: 1400 };
  if (score < 175) return { speedTarget: 430, spawnMinMs: 860, spawnMaxMs: 1220 };
  return { speedTarget: 500, spawnMinMs: 760, spawnMaxMs: 1080 };
}

function randomBetween(min: number, max: number) {
  return min + Math.random() * (max - min);
}

interface Props {
  onClose: () => void;
  /** Increments each time a scrape run finishes (running → idle). Drives the in-game “search done” word lane. */
  searchCompletedTick: number;
}

function useDarkModeClass(): boolean {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const el = document.documentElement;
    const read = () => setDark(el.classList.contains("dark"));
    read();
    const obs = new MutationObserver(read);
    obs.observe(el, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);
  return dark;
}

function resizeCanvas(canvas: HTMLCanvasElement, container: HTMLElement) {
  const dpr = Math.min(typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1, 2);
  const w = container.clientWidth;
  const h = container.clientHeight;
  if (w <= 0 || h <= 0) return;
  canvas.width = Math.floor(w * dpr);
  canvas.height = Math.floor(h * dpr);
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
}

function drawScene(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  obstacles: GameObstacle[],
  roadPhase: number,
  parallaxPhase: number,
  scanPhase: number,
  palette: {
    skyTop: string;
    skyBot: string;
    skyline: string;
    road: string;
    roadEdge: string;
    dash: string;
    emojiGround: string;
    accent: string;
    accentGlow: string;
  },
) {
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, palette.skyTop);
  g.addColorStop(1, palette.skyBot);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);

  ctx.save();
  ctx.globalAlpha = 0.35;
  ctx.fillStyle = palette.skyline;
  for (let x = -((parallaxPhase * 0.4) % 100); x < w + 100; x += 72) {
    const seed = Math.abs(Math.sin(x * 0.09)) * 40;
    ctx.fillRect(x, h - 52 - seed, 20, 52 + seed);
  }
  ctx.restore();

  ctx.fillStyle = palette.road;
  ctx.fillRect(0, h - 16, w, 16);
  ctx.fillStyle = palette.roadEdge;
  ctx.fillRect(0, h - 18, w, 2);

  ctx.fillStyle = palette.dash;
  const period = 28;
  const off = roadPhase % period;
  for (let x = -off; x < w + period; x += period) {
    ctx.fillRect(x, h - 26, 14, 3);
  }

  ctx.save();
  ctx.globalAlpha = 0.06;
  ctx.strokeStyle = palette.accent;
  ctx.lineWidth = 1;
  const scanY = (scanPhase * 0.8) % (h + 40);
  ctx.beginPath();
  ctx.moveTo(0, scanY);
  ctx.lineTo(w, scanY + 8);
  ctx.stroke();
  ctx.restore();

  const groundY = h - 16;
  for (const obs of obstacles) {
    const bottom = groundY;
    const top = bottom - obs.height;
    const left = obs.x;

    if (obs.text) {
      ctx.save();
      ctx.font = "bold 18px ui-sans-serif, system-ui, sans-serif";
      ctx.textBaseline = "bottom";
      if (obs.accent) {
        ctx.shadowColor = palette.accentGlow;
        ctx.shadowBlur = 12;
        ctx.fillStyle = palette.accent;
      } else {
        ctx.fillStyle = palette.emojiGround;
      }
      ctx.fillText(obs.text, left + 10, bottom - 6);
      ctx.restore();
      ctx.save();
      ctx.strokeStyle = obs.accent ? palette.accent : palette.roadEdge;
      ctx.globalAlpha = obs.accent ? 0.45 : 0.25;
      ctx.strokeRect(left + 4, top + 2, obs.width - 8, obs.height - 4);
      ctx.restore();
    } else if (obs.emoji) {
      ctx.font = "26px system-ui, sans-serif";
      ctx.textBaseline = "bottom";
      ctx.fillText(obs.emoji, left + 4, bottom - 2);
    }
  }
}

export function ScrapeMiniGame({ onClose, searchCompletedTick }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const playerRef = useRef<HTMLDivElement>(null);
  const isDark = useDarkModeClass();

  const [isPlaying, setIsPlaying] = useState(false);
  const [isGameOver, setIsGameOver] = useState(false);
  const [score, setScore] = useState(0);
  const [highScore, setHighScore] = useState(0);
  const [character, setCharacter] = useState<CharacterType>("motorcycle");
  const [doneBanner, setDoneBanner] = useState(false);

  const palette = useMemo(
    () =>
      isDark
        ? {
            skyTop: "#0c1220",
            skyBot: "#1a1f2e",
            skyline: "#0f172a",
            road: "#18181b",
            roadEdge: "#3f3f46",
            dash: "#52525b",
            emojiGround: "#e4e4e7",
            accent: "#34d399",
            accentGlow: "rgba(52, 211, 153, 0.5)",
          }
        : {
            skyTop: "#ecfdf5",
            skyBot: "#d1fae5",
            skyline: "#a7f3d0",
            road: "#e4e4e7",
            roadEdge: "#a1a1aa",
            dash: "#d4d4d8",
            emojiGround: "#27272a",
            accent: "#059669",
            accentGlow: "rgba(5, 150, 105, 0.35)",
          },
    [isDark],
  );

  const playingRef = useRef(false);
  const gameOverRef = useRef(false);
  const paletteRef = useRef(palette);

  useLayoutEffect(() => {
    paletteRef.current = palette;
  }, [palette]);

  useEffect(() => {
    playingRef.current = isPlaying;
    gameOverRef.current = isGameOver;
  }, [isPlaying, isGameOver]);

  const pendingWordsRef = useRef<PendingWord[]>([]);
  const lastProcessedTickRef = useRef(0);

  const stateRef = useRef({
    playerY: 0,
    playerVelocity: 0,
    jumpBufferMs: 0,
    jumpHeld: false,
    jumpHoldMs: 0,
    landingSquashMs: 0,
    obstacles: [] as GameObstacle[],
    speed: BASE_SPEED,
    score: 0,
    lastObstacleTime: 0,
    nextObstacleDelayMs: 1600,
    lastFrameTime: 0,
    animationFrameId: 0,
    roadPhase: 0,
    parallaxPhase: 0,
    scanPhase: 0,
  });

  useEffect(() => {
    try {
      const raw = localStorage.getItem(HIGH_SCORE_KEY);
      const n = raw != null ? Number.parseInt(raw, 10) : 0;
      if (Number.isFinite(n) && n >= 0) {
        startTransition(() => setHighScore(n));
      }
    } catch {
      /* ignore */
    }
  }, []);

  const scheduleSearchDoneWords = useCallback(() => {
    const base = performance.now() + 500;
    const batch = SEARCH_DONE_PHRASE.map((text, i) => ({
      spawnAt: base + i * WORD_SPAWN_GAP_MS,
      text,
    }));
    pendingWordsRef.current.push(...batch);
    pendingWordsRef.current.sort((a, b) => a.spawnAt - b.spawnAt);
    setDoneBanner(true);
    window.setTimeout(() => setDoneBanner(false), 9000);
  }, []);

  useEffect(() => {
    if (searchCompletedTick <= 0 || searchCompletedTick === lastProcessedTickRef.current) return;
    lastProcessedTickRef.current = searchCompletedTick;
    startTransition(() => {
      scheduleSearchDoneWords();
    });
  }, [searchCompletedTick, scheduleSearchDoneWords]);

  const spawnEmojiObstacle = (canvasW: number) => {
    stateRef.current.obstacles.push({
      x: canvasW,
      width: 36,
      height: 32,
      emoji: OBSTACLES[Math.floor(Math.random() * OBSTACLES.length)],
    });
  };

  const spawnWordObstacle = (canvas: HTMLCanvasElement, text: string) => {
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.font = "bold 18px ui-sans-serif, system-ui, sans-serif";
    const w = Math.ceil(ctx.measureText(text).width) + 20;
    stateRef.current.obstacles.push({
      x: canvas.clientWidth,
      width: w,
      height: 30,
      text,
      accent: true,
    });
  };

  const flushPendingWords = (canvas: HTMLCanvasElement) => {
    const now = performance.now();
    const q = pendingWordsRef.current;
    while (q.length > 0 && q[0].spawnAt + 12_000 < now) {
      q.shift();
    }
    while (q.length > 0 && now >= q[0].spawnAt) {
      const next = q.shift()!;
      spawnWordObstacle(canvas, next.text);
    }
  };

  const gameLoopRef = useRef<() => void>(() => {});

  const doJumpImpulse = useCallback(() => {
    const s = stateRef.current;
    s.playerVelocity = JUMP_VELOCITY;
    s.jumpBufferMs = 0;
    s.jumpHoldMs = 0;
    s.landingSquashMs = 0;
  }, []);

  const releaseJump = useCallback(() => {
    const s = stateRef.current;
    s.jumpHeld = false;
    if (s.playerVelocity < 0) {
      s.playerVelocity *= JUMP_RELEASE_DAMPING;
    }
  }, []);

  const gameLoop = useCallback(() => {
    if (!playingRef.current || gameOverRef.current) return;

    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    if (document.visibilityState === "hidden") {
      stateRef.current.lastFrameTime = performance.now();
      stateRef.current.animationFrameId = requestAnimationFrame(() => gameLoopRef.current());
      return;
    }

    const w = container.clientWidth;
    const h = container.clientHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx || w <= 0 || h <= 0) return;

    const frameNow = performance.now();
    const nowMs = Date.now();
    const state = stateRef.current;
    const dtMs = Math.min(Math.max(frameNow - state.lastFrameTime, 0), FRAME_MS_CAP);
    const dt = dtMs / 1000;
    state.lastFrameTime = frameNow;

    const difficulty = getDifficulty(state.score);
    const speedBlend = Math.min(1, dt * 2.4);
    state.speed += (difficulty.speedTarget - state.speed) * speedBlend;

    state.roadPhase += state.speed * dt;
    state.parallaxPhase += state.speed * 0.22 * dt;
    state.scanPhase += dtMs * 0.06;

    const holdGravityScale =
      state.jumpHeld && state.playerVelocity < 0 && state.jumpHoldMs < JUMP_HOLD_MS
        ? JUMP_HOLD_GRAVITY_SCALE
        : 1;
    state.playerVelocity += GRAVITY * holdGravityScale * dt;
    state.playerY += state.playerVelocity * dt;
    if (state.jumpHeld && state.playerVelocity < 0) {
      state.jumpHoldMs += dtMs;
    }

    if (state.playerY < -MAX_JUMP_HEIGHT) {
      state.playerY = -MAX_JUMP_HEIGHT;
      state.playerVelocity = Math.max(0, state.playerVelocity);
    }

    const wasAirborne = state.playerY < GROUND_Y || state.playerVelocity < 0;
    const onGround = state.playerY >= GROUND_Y;
    if (onGround) {
      state.playerY = GROUND_Y;
      state.playerVelocity = 0;
      state.jumpHoldMs = 0;
      if (wasAirborne) {
        state.landingSquashMs = LANDING_SQUASH_MS;
      }
      if (state.jumpBufferMs > 0) {
        doJumpImpulse();
      }
    } else if (state.jumpBufferMs > 0) {
      state.jumpBufferMs = Math.max(0, state.jumpBufferMs - dtMs);
    }
    state.landingSquashMs = Math.max(0, state.landingSquashMs - dtMs);

    flushPendingWords(canvas);

    if (nowMs - state.lastObstacleTime > state.nextObstacleDelayMs) {
      spawnEmojiObstacle(w);
      state.lastObstacleTime = nowMs;
      state.nextObstacleDelayMs = randomBetween(difficulty.spawnMinMs, difficulty.spawnMaxMs);
      state.speed = Math.min(state.speed, MAX_SPEED);
    }

    let collision = false;
    const inset = PLAYER_HIT_INSET;
    const px = PLAYER_LEFT + inset;
    const pw = PLAYER_WIDTH - inset * 2;
    const ph = PLAYER_HEIGHT - inset * 2;
    const groundCanvasY = h - 16;
    const playerBottomCanvas = groundCanvasY - state.playerY;
    const playerTopCanvas = playerBottomCanvas - ph;
    const playerLeft = px;
    const playerRight = px + pw;

    state.obstacles = state.obstacles.filter((obs) => {
      obs.x -= state.speed * dt;
      const obsLeft = obs.x;
      const obsRight = obs.x + obs.width;
      const obsBottom = groundCanvasY;
      const obsTop = groundCanvasY - obs.height;

      if (
        playerLeft < obsRight &&
        playerRight > obsLeft &&
        playerTopCanvas < obsBottom &&
        playerBottomCanvas > obsTop
      ) {
        collision = true;
      }
      return obs.x + obs.width > -40;
    });

    if (collision) {
      playingRef.current = false;
      gameOverRef.current = true;
      const finalScore = Math.floor(state.score);
      setIsGameOver(true);
      setIsPlaying(false);
      setHighScore((prev) => {
        const next = Math.max(prev, finalScore);
        try {
          localStorage.setItem(HIGH_SCORE_KEY, String(next));
        } catch {
          /* ignore */
        }
        return next;
      });
      drawScene(
        ctx,
        w,
        h,
        state.obstacles,
        state.roadPhase,
        state.parallaxPhase,
        state.scanPhase,
        paletteRef.current,
      );
      return;
    }

    state.score += dt * 9;
    const displayScore = Math.floor(state.score);
    setScore((prev) => (displayScore > prev ? displayScore : prev));

    drawScene(
      ctx,
      w,
      h,
      state.obstacles,
      state.roadPhase,
      state.parallaxPhase,
      state.scanPhase,
      paletteRef.current,
    );

    const playerEl = playerRef.current;
    if (playerEl) {
      const tilt = Math.max(-9, Math.min(9, state.playerVelocity / 85));
      const squatProgress = state.landingSquashMs / LANDING_SQUASH_MS;
      const scaleX = 1 + squatProgress * 0.08;
      const scaleY = 1 - squatProgress * 0.1;
      playerEl.style.transform = `translateY(${state.playerY}px) rotate(${tilt}deg) scaleX(${scaleX}) scaleY(${scaleY})`;
    }

    state.animationFrameId = requestAnimationFrame(() => gameLoopRef.current());
  }, [doJumpImpulse]); // eslint-disable-line react-hooks/exhaustive-deps -- spawn helpers use refs only

  useLayoutEffect(() => {
    gameLoopRef.current = gameLoop;
  }, [gameLoop]);

  const startGame = useCallback(() => {
    playingRef.current = true;
    gameOverRef.current = false;
    setIsPlaying(true);
    setIsGameOver(false);
    setScore(0);
    const now = performance.now();
    stateRef.current = {
      playerY: 0,
      playerVelocity: 0,
      jumpBufferMs: 0,
      jumpHeld: true,
      jumpHoldMs: 0,
      landingSquashMs: 0,
      obstacles: [],
      speed: BASE_SPEED,
      score: 0,
      lastObstacleTime: Date.now(),
      nextObstacleDelayMs: 1600,
      lastFrameTime: now,
      animationFrameId: 0,
      roadPhase: 0,
      parallaxPhase: 0,
      scanPhase: 0,
    };
    gameLoop();
  }, [gameLoop]);

  const pressJump = useCallback(() => {
    if (!playingRef.current || gameOverRef.current) {
      startGame();
      return;
    }
    const s = stateRef.current;
    s.jumpHeld = true;
    const onGroundForJump = s.playerY >= GROUND_Y && s.playerVelocity >= 0;
    if (onGroundForJump) {
      doJumpImpulse();
      return;
    }
    s.jumpBufferMs = JUMP_BUFFER_MS;
  }, [startGame, doJumpImpulse]);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const paintStatic = () => {
      resizeCanvas(canvas, container);
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const cw = container.clientWidth;
      const ch = container.clientHeight;
      if (cw <= 0 || ch <= 0) return;
      const s = stateRef.current;
      drawScene(ctx, cw, ch, [], s.roadPhase, s.parallaxPhase, s.scanPhase, paletteRef.current);
    };

    const ro = new ResizeObserver(paintStatic);
    ro.observe(container);
    paintStatic();
    return () => ro.disconnect();
  }, [palette]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code === "Space" || e.code === "ArrowUp") {
        if (e.repeat) return;
        e.preventDefault();
        pressJump();
      }
    };
    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.code === "Space" || e.code === "ArrowUp") {
        e.preventDefault();
        releaseJump();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, [pressJump, releaseJump]);

  useEffect(() => {
    return () => cancelAnimationFrame(stateRef.current.animationFrameId);
  }, []);

  const CharacterComponent = CHARACTERS[character];

  return (
    <div
      className="relative w-full min-h-[220px] h-56 flex flex-col select-none rounded-xl overflow-hidden border border-emerald-200/60 bg-zinc-50 dark:border-emerald-900/40 dark:bg-zinc-950 shadow-sm"
      onPointerDown={(e) => {
        if (e.pointerType !== "mouse" || e.button === 0) {
          pressJump();
        }
      }}
      onPointerUp={releaseJump}
      onPointerCancel={releaseJump}
      onKeyDown={(e) => {
        if (e.key === " " || e.key === "ArrowUp") {
          if (e.repeat) return;
          e.preventDefault();
          pressJump();
        }
      }}
      onKeyUp={(e) => {
        if (e.key === " " || e.key === "ArrowUp") {
          e.preventDefault();
          releaseJump();
        }
      }}
      role="application"
      aria-label="MotorScrape Run mini-game"
      tabIndex={0}
    >
      <div className="absolute inset-x-0 top-0 z-20 h-px bg-gradient-to-r from-transparent via-emerald-500/40 to-transparent" aria-hidden />

      <div className="relative z-10 flex flex-col gap-1 border-b border-zinc-200/80 bg-white/90 px-3 py-2 dark:border-zinc-800 dark:bg-zinc-950/90">
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-[11px] font-semibold uppercase tracking-widest text-emerald-700 dark:text-emerald-400">
              MotorScrape Run
            </span>
            <span className="truncate text-[10px] text-zinc-500 dark:text-zinc-400">
              Dodge paywalls · jump the scrape lane · HI score saves locally
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <div className="text-xs font-mono font-semibold tabular-nums text-zinc-600 dark:text-zinc-300">
              HI {highScore.toString().padStart(5, "0")} · {score.toString().padStart(5, "0")}
            </div>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onClose();
              }}
              className="rounded-md p-1 text-zinc-400 transition hover:bg-zinc-200 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
              aria-label="Close mini-game"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
                <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
              </svg>
            </button>
          </div>
        </div>
        {doneBanner ? (
          <p className="text-[11px] font-medium text-emerald-700 dark:text-emerald-300">
            Search finished — inventory is ready below. Keep running for a new HI score.
          </p>
        ) : null}
      </div>

      <div ref={containerRef} className="relative min-h-0 flex-1 w-full overflow-hidden">
        {!isPlaying && !isGameOver && (
          <div className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-3 bg-zinc-50/88 px-4 text-center backdrop-blur-[2px] dark:bg-zinc-950/84">
            <span className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">Pick your ride and hit the lane</span>
            <div className="flex flex-wrap items-center justify-center gap-2">
              {(Object.keys(CHARACTERS) as CharacterType[]).map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setCharacter(c);
                  }}
                  className={`rounded-md px-2.5 py-1 text-[11px] font-semibold capitalize transition ${
                    character === c
                      ? "bg-emerald-600 text-white shadow-sm dark:bg-emerald-500"
                      : "bg-white/90 text-zinc-700 hover:bg-zinc-100 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
            <span className="text-xs text-zinc-500 dark:text-zinc-400">Hold jump for a little extra air · release early for a short hop</span>
          </div>
        )}

        {isGameOver && (
          <div className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-3 bg-zinc-50/90 px-4 backdrop-blur-sm dark:bg-zinc-950/85">
            <span className="text-lg font-bold text-zinc-900 dark:text-zinc-50">Wiped out</span>
            <span className="text-center text-xs text-zinc-600 dark:text-zinc-400">
              Space or tap to respawn — listings are still in the results panel.
            </span>
            <div className="flex flex-wrap items-center justify-center gap-2">
              {(Object.keys(CHARACTERS) as CharacterType[]).map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setCharacter(c);
                  }}
                  className={`rounded-md px-2.5 py-1 text-[11px] font-semibold capitalize transition ${
                    character === c
                      ? "bg-emerald-600 text-white shadow-sm dark:bg-emerald-500"
                      : "bg-white/90 text-zinc-700 hover:bg-zinc-100 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>
        )}

        <canvas
          ref={canvasRef}
          className="absolute inset-0 block h-full w-full touch-manipulation"
          aria-hidden
        />

        <div
          ref={playerRef}
          className="pointer-events-none absolute bottom-4 left-5 z-20 h-10 w-[60px] origin-bottom will-change-transform"
          style={{ marginBottom: 0 }}
        >
          <CharacterComponent />
        </div>
      </div>

      <div className="relative z-10 flex h-3 items-center justify-center border-t border-zinc-200 bg-gradient-to-r from-emerald-500/10 via-transparent to-teal-500/10 dark:border-zinc-800" aria-hidden>
        <div className="h-0.5 w-24 rounded-full bg-emerald-500/30 dark:bg-emerald-500/20" />
      </div>
    </div>
  );
}
