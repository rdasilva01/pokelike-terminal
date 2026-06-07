"""
train.py — PPO training entry point for the Pokelike RL shiny hunter.

Usage:
    python train.py                          # 4 envs, stage 1, 500k steps
    python train.py --n-envs 2 --stage 1    # fewer envs for lighter machines
    python train.py --resume models/pokelike_rl_200000_steps  # continue run
"""
import argparse
import sys
from pathlib import Path

# Add repo root to path so rl-trainer modules find the parsers
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv
from stable_baselines3.common.callbacks import CheckpointCallback
from stable_baselines3.common.monitor import Monitor
from sb3_contrib import MaskablePPO

from game_env import PokelikeEnv
from config import (
    N_ENVS, STARTING_STAGE,
    PPO_N_STEPS, PPO_BATCH_SIZE, PPO_N_EPOCHS, PPO_LR, PPO_GAMMA,
    PPO_ENT_COEF, PPO_TOTAL_TIMESTEPS,
)


def make_env(env_idx: int, stage: int, watch: bool = False):
    def _init():
        env = PokelikeEnv(env_idx=env_idx, stage=stage)
        env.runner.start(headless=not (watch and env_idx == 0))
        return Monitor(env)
    return _init


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-envs",  type=int, default=N_ENVS)
    parser.add_argument("--stage",   type=int, default=STARTING_STAGE)
    parser.add_argument("--steps",   type=int, default=PPO_TOTAL_TIMESTEPS)
    parser.add_argument("--resume",  type=str, default=None)
    parser.add_argument("--no-sub",  action="store_true",
                        help="Use DummyVecEnv (single process, easier to debug)")
    parser.add_argument("--watch",   action="store_true",
                        help="Show env 0 in a visible browser window")
    args = parser.parse_args()

    models_dir = Path(__file__).parent / "models"
    logs_dir   = Path(__file__).parent / "logs"
    models_dir.mkdir(exist_ok=True)
    logs_dir.mkdir(exist_ok=True)

    factories = [make_env(i, args.stage, watch=args.watch) for i in range(args.n_envs)]
    VecEnvCls  = DummyVecEnv if args.no_sub else SubprocVecEnv
    envs       = VecEnvCls(factories)

    if args.resume:
        model = MaskablePPO.load(args.resume, env=envs)
        print(f"[train] Resumed from {args.resume}")
    else:
        model = MaskablePPO(
            "MlpPolicy",
            envs,
            verbose=1,
            n_steps=PPO_N_STEPS,
            batch_size=PPO_BATCH_SIZE,
            n_epochs=PPO_N_EPOCHS,
            learning_rate=PPO_LR,
            gamma=PPO_GAMMA,
            ent_coef=PPO_ENT_COEF,
            tensorboard_log=str(logs_dir),
        )

    checkpoint_cb = CheckpointCallback(
        save_freq=max(10_000 // args.n_envs, 1),
        save_path=str(models_dir),
        name_prefix="pokelike_rl",
        verbose=1,
    )

    print(f"[train] Starting: {args.n_envs} env(s), stage {args.stage}, {args.steps:,} steps")
    model.learn(
        total_timesteps=args.steps,
        callback=[checkpoint_cb],
        reset_num_timesteps=(args.resume is None),
    )

    final_path = models_dir / "pokelike_rl_final"
    model.save(final_path)
    print(f"[train] Saved final model → {final_path}")
    envs.close()


if __name__ == "__main__":
    main()
