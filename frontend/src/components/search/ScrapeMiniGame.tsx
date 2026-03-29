"use client";

import { useEffect, useRef, useState } from "react";
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

interface Props {
  onClose: () => void;
}

export function ScrapeMiniGame({ onClose }: Props) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isGameOver, setIsGameOver] = useState(false);
  const [score, setScore] = useState(0);
  const [highScore, setHighScore] = useState(0);
  const [character, setCharacter] = useState<CharacterType>("motorcycle");

  // Game state refs (to avoid re-renders during loop)
  const stateRef = useRef({
    playerY: 0,
    playerVelocity: 0,
    isJumping: false,
    obstacles: [] as { x: number; type: string; width: number; height: number }[],
    speed: 5,
    score: 0,
    lastObstacleTime: 0,
    animationFrameId: 0,
  });

  const GRAVITY = 0.6;
  const JUMP_STRENGTH = -12;
  const GROUND_Y = 0; // 0 means on the ground
  const PLAYER_WIDTH = 60;
  const PLAYER_HEIGHT = 40;

  const startGame = () => {
    setIsPlaying(true);
    setIsGameOver(false);
    setScore(0);
    
    stateRef.current = {
      playerY: 0,
      playerVelocity: 0,
      isJumping: false,
      obstacles: [],
      speed: 5,
      score: 0,
      lastObstacleTime: Date.now(),
      animationFrameId: 0,
    };

    gameLoop();
  };

  const jump = () => {
    if (!stateRef.current.isJumping && isPlaying && !isGameOver) {
      stateRef.current.playerVelocity = JUMP_STRENGTH;
      stateRef.current.isJumping = true;
    } else if (!isPlaying || isGameOver) {
      startGame();
    }
  };

  const gameLoop = () => {
    if (!canvasRef.current) return;
    const canvasWidth = canvasRef.current.clientWidth;
    const now = Date.now();
    const state = stateRef.current;

    // Physics
    state.playerVelocity += GRAVITY;
    state.playerY += state.playerVelocity;

    if (state.playerY >= GROUND_Y) {
      state.playerY = GROUND_Y;
      state.playerVelocity = 0;
      state.isJumping = false;
    }

    // Spawn obstacles
    if (now - state.lastObstacleTime > 1500 + Math.random() * 1500) {
      state.obstacles.push({
        x: canvasWidth,
        type: OBSTACLES[Math.floor(Math.random() * OBSTACLES.length)],
        width: 30,
        height: 30,
      });
      state.lastObstacleTime = now;
      // Slightly increase speed over time
      state.speed += 0.1;
    }

    // Move obstacles and check collisions
    let collision = false;
    state.obstacles = state.obstacles.filter((obs) => {
      obs.x -= state.speed;

      // Collision detection (AABB)
      // Player rect: x: 20, y: canvasHeight - 40 - playerY, w: 60, h: 40
      // Obstacle rect: x: obs.x, y: canvasHeight - 30, w: 30, h: 30
      const playerRect = { left: 20, right: 20 + PLAYER_WIDTH, top: -state.playerY - PLAYER_HEIGHT, bottom: -state.playerY };
      const obsRect = { left: obs.x, right: obs.x + obs.width, top: -obs.height, bottom: 0 };

      if (
        playerRect.left < obsRect.right &&
        playerRect.right > obsRect.left &&
        playerRect.top < obsRect.bottom &&
        playerRect.bottom > obsRect.top
      ) {
        collision = true;
      }

      return obs.x + obs.width > 0;
    });

    if (collision) {
      setIsGameOver(true);
      setIsPlaying(false);
      setHighScore((prev) => Math.max(prev, Math.floor(state.score)));
      return; // Stop loop
    }

    // Update score
    state.score += 0.1;
    if (Math.floor(state.score) > score) {
      setScore(Math.floor(state.score));
    }

    // Apply visual updates directly to DOM for performance
    const playerEl = document.getElementById("game-player");
    if (playerEl) {
      playerEl.style.transform = `translateY(${state.playerY}px)`;
    }

    const obstaclesContainer = document.getElementById("game-obstacles");
    if (obstaclesContainer) {
      obstaclesContainer.innerHTML = state.obstacles
        .map(
          (obs) =>
            `<div style="position: absolute; left: ${obs.x}px; bottom: 0; font-size: 24px; line-height: 1;">${obs.type}</div>`
        )
        .join("");
    }

    state.animationFrameId = requestAnimationFrame(gameLoop);
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code === "Space" || e.code === "ArrowUp") {
        e.preventDefault();
        jump();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      cancelAnimationFrame(stateRef.current.animationFrameId);
    };
  }, [isPlaying, isGameOver]);

  const CharacterComponent = CHARACTERS[character];

  return (
    <div className="relative w-full h-48 bg-zinc-50 dark:bg-zinc-900 rounded-xl overflow-hidden border border-zinc-200 dark:border-zinc-800 flex flex-col select-none" onClick={jump}>
      {/* Header */}
      <div className="absolute top-0 left-0 right-0 p-3 flex justify-between items-center z-10">
        <div className="flex gap-2">
          {(Object.keys(CHARACTERS) as CharacterType[]).map((c) => (
            <button
              key={c}
              onClick={(e) => {
                e.stopPropagation();
                setCharacter(c);
              }}
              className={`px-2 py-1 text-xs rounded-md font-medium capitalize transition-colors ${
                character === c
                  ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300"
                  : "bg-zinc-200 text-zinc-600 hover:bg-zinc-300 dark:bg-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-700"
              }`}
            >
              {c}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-4">
          <div className="text-sm font-mono font-semibold text-zinc-600 dark:text-zinc-400">
            HI {highScore.toString().padStart(5, "0")} | {score.toString().padStart(5, "0")}
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onClose();
            }}
            className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 transition"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
              <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
            </svg>
          </button>
        </div>
      </div>

      {/* Game Area */}
      <div ref={canvasRef} className="relative flex-1 w-full overflow-hidden mt-10 border-b-2 border-zinc-300 dark:border-zinc-700">
        {!isPlaying && !isGameOver && (
          <div className="absolute inset-0 flex items-center justify-center z-20">
            <span className="text-zinc-500 dark:text-zinc-400 font-medium animate-pulse">
              Press Space or Tap to Start
            </span>
          </div>
        )}
        
        {isGameOver && (
          <div className="absolute inset-0 flex flex-col items-center justify-center z-20 bg-zinc-50/80 dark:bg-zinc-900/80 backdrop-blur-sm">
            <span className="text-xl font-bold text-zinc-800 dark:text-zinc-200 mb-2">Game Over</span>
            <span className="text-zinc-500 dark:text-zinc-400 font-medium animate-pulse">
              Press Space or Tap to Restart
            </span>
          </div>
        )}

        {/* Player */}
        <div
          id="game-player"
          className="absolute left-5 bottom-0 w-[60px] h-[40px] will-change-transform"
        >
          <CharacterComponent />
        </div>

        {/* Obstacles */}
        <div id="game-obstacles" className="absolute inset-0 pointer-events-none" />
      </div>
      
      {/* Ground decoration */}
      <div className="h-4 bg-zinc-100 dark:bg-zinc-800/50 w-full" />
    </div>
  );
}
