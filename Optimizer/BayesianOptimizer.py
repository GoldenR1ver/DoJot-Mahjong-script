"""
DoJot 参数贝叶斯优化器（GPR + EI）

最低可用目标：
1) 读取导出的 gameData
2) 使用历史样本拟合高斯过程
3) 生成一套新的可导入参数（与 defaultParameter.importable.json 对齐）
"""

from __future__ import annotations

import argparse
import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from scipy.stats import norm
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel as C
from sklearn.gaussian_process.kernels import Matern


@dataclass
class ParameterSpec:
    path: Tuple[str, ...]
    param_type: str
    low: float | None = None
    high: float | None = None
    choices: List[Any] | None = None

    @property
    def name(self) -> str:
        return ".".join(self.path)


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_nested(d: Dict[str, Any], path: Tuple[str, ...]) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            raise KeyError(f"Missing key path: {'.'.join(path)}")
        cur = cur[key]
    return cur


def set_nested(d: Dict[str, Any], path: Tuple[str, ...], value: Any) -> None:
    cur = d
    for key in path[:-1]:
        cur = cur.setdefault(key, {})
    cur[path[-1]] = value


def flatten_parameter_spec(spec_tree: Dict[str, Any], prefix: Tuple[str, ...] = ()) -> List[ParameterSpec]:
    out: List[ParameterSpec] = []
    for key, value in spec_tree.items():
        cur_path = prefix + (key,)
        if isinstance(value, dict) and "type" in value:
            p_type = value["type"]
            out.append(
                ParameterSpec(
                    path=cur_path,
                    param_type=p_type,
                    low=value.get("low"),
                    high=value.get("high"),
                    choices=value.get("choices"),
                )
            )
        elif isinstance(value, dict):
            out.extend(flatten_parameter_spec(value, cur_path))
    return out


class ObjectiveFunction:
    """从 gameData 的 overall_statistics 计算单局质量分。"""

    WEIGHTS = {
        "rank": 0.35,
        "score_rate": 0.15,
        "win_efficiency": 0.20,
        "defense": -0.15,
        "tenpai_quality": 0.15,
    }

    @staticmethod
    def _safe_float(v: Any, default: float = 0.0) -> float:
        try:
            if v is None:
                return default
            return float(v)
        except (TypeError, ValueError):
            return default

    @classmethod
    def from_stats(cls, stats: Dict[str, Any]) -> float:
        final_rank = stats.get("final_ranking", [4])
        final_score = stats.get("final_scores", [0])

        my_rank = int(final_rank[0]) if final_rank else 4
        my_score = cls._safe_float(final_score[0] if final_score else 0.0)

        win_stats = stats.get("win_stats", {})
        deal_in_stats = stats.get("deal_in_stats", {})
        tenpai_stats = stats.get("tenpai_stats", {})

        win_freq = cls._safe_float(win_stats.get("win_frequency", 0.0))
        avg_win_score = cls._safe_float(win_stats.get("average_win_score", 0.0))

        deal_in_freq = cls._safe_float(deal_in_stats.get("deal_in_frequency", 0.0))
        avg_deal_in_score = cls._safe_float(deal_in_stats.get("average_deal_in_score", 0.0))

        tenpai_freq = cls._safe_float(tenpai_stats.get("tenpai_frequency", 0.0))
        expected_han = cls._safe_float(
            tenpai_stats.get("expected_han_stats", {}).get("average_expected_han", 0.0)
        )

        rank_score = (4 - my_rank) * 25.0
        score_rate = my_score / 10000.0
        win_efficiency = win_freq * (avg_win_score / 10000.0)
        defense_penalty = deal_in_freq * (avg_deal_in_score / 10000.0)
        tenpai_quality = tenpai_freq * expected_han

        return (
            rank_score * cls.WEIGHTS["rank"]
            + score_rate * cls.WEIGHTS["score_rate"]
            + win_efficiency * 100.0 * cls.WEIGHTS["win_efficiency"]
            + (-defense_penalty) * 50.0 * cls.WEIGHTS["defense"]
            + tenpai_quality * 5.0 * cls.WEIGHTS["tenpai_quality"]
        )


class ParameterCodec:
    """参数向量化 / 反向解码（与 defaultParameter.json 一致）。"""

    def __init__(self, specs: List[ParameterSpec]):
        self.specs = specs

    @staticmethod
    def _clip01(v: float) -> float:
        return float(max(0.0, min(1.0, v)))

    def encode(self, params: Dict[str, Any]) -> np.ndarray:
        vec: List[float] = []
        for spec in self.specs:
            raw = get_nested(params, spec.path)
            if spec.param_type in ("float", "int"):
                low, high = float(spec.low), float(spec.high)
                if high <= low:
                    vec.append(0.0)
                else:
                    vec.append(self._clip01((float(raw) - low) / (high - low)))
            elif spec.param_type == "categorical":
                choices = spec.choices or []
                if len(choices) <= 1:
                    vec.append(0.0)
                else:
                    idx = choices.index(raw)
                    vec.append(idx / (len(choices) - 1))
            else:
                raise ValueError(f"Unsupported param type: {spec.param_type} ({spec.name})")
        return np.array(vec, dtype=float)

    def decode_value(self, spec: ParameterSpec, normalized_value: float) -> Any:
        n = self._clip01(normalized_value)
        if spec.param_type == "float":
            low, high = float(spec.low), float(spec.high)
            return round(low + n * (high - low), 6)
        if spec.param_type == "int":
            low, high = int(spec.low), int(spec.high)
            val = int(round(low + n * (high - low)))
            return max(low, min(high, val))
        if spec.param_type == "categorical":
            choices = spec.choices or []
            if not choices:
                return None
            if len(choices) == 1:
                return choices[0]
            idx = int(round(n * (len(choices) - 1)))
            idx = max(0, min(len(choices) - 1, idx))
            return choices[idx]
        raise ValueError(f"Unsupported param type: {spec.param_type} ({spec.name})")

    def decode(self, vec: np.ndarray) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for i, spec in enumerate(self.specs):
            value = self.decode_value(spec, float(vec[i]))
            set_nested(out, spec.path, value)
        return out

    def random_vector(self, rng: np.random.Generator) -> np.ndarray:
        return rng.random(len(self.specs))

    def mutate_around(self, base: np.ndarray, rng: np.random.Generator, scale: float = 0.12) -> np.ndarray:
        x = base.copy().astype(float)
        noise = rng.normal(loc=0.0, scale=scale, size=x.shape[0])
        x = np.clip(x + noise, 0.0, 1.0)
        return x


class BayesianOptimizer:
    def __init__(self, codec: ParameterCodec, random_state: int = 42, xi: float = 0.01):
        self.codec = codec
        self.xi = xi
        self.rng = np.random.default_rng(random_state)
        self.gp = GaussianProcessRegressor(
            kernel=C(1.0, (1e-3, 1e3)) * Matern(length_scale=1.0, nu=2.5),
            alpha=1e-5,
            normalize_y=True,
            n_restarts_optimizer=8,
            random_state=random_state,
        )
        self.X: np.ndarray | None = None
        self.y: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        self.X = X
        self.y = y
        if len(X) >= 3:
            self.gp.fit(X, y)

    def expected_improvement(self, candidates: np.ndarray) -> np.ndarray:
        if self.X is None or self.y is None or len(self.X) < 3:
            return np.ones(candidates.shape[0], dtype=float)
        mu, sigma = self.gp.predict(candidates, return_std=True)
        sigma = np.maximum(sigma, 1e-9)
        y_best = float(np.max(self.y))
        imp = mu - y_best - self.xi
        z = imp / sigma
        ei = imp * norm.cdf(z) + sigma * norm.pdf(z)
        return np.maximum(ei, 0.0)

    def propose_next(self, n_candidates: int = 4000) -> np.ndarray:
        # 初始样本不足：随机探索
        if self.X is None or self.y is None or len(self.X) < 3:
            return self.codec.random_vector(self.rng)

        candidates = [self.codec.random_vector(self.rng) for _ in range(max(200, n_candidates // 2))]

        # 在历史最优附近加局部搜索，避免纯随机低效
        top_k = min(5, len(self.y))
        top_idx = np.argsort(self.y)[-top_k:]
        for idx in top_idx:
            base = self.X[idx]
            for _ in range(max(40, n_candidates // (2 * top_k))):
                candidates.append(self.codec.mutate_around(base, self.rng))

        cand = np.vstack(candidates)
        ei = self.expected_improvement(cand)
        return cand[int(np.argmax(ei))]


def load_dataset(
    game_data_path: Path, codec: ParameterCodec, template_params: Dict[str, Any]
) -> Tuple[np.ndarray, np.ndarray, int]:
    payload = read_json(game_data_path)
    records = payload.get("records", [])
    X_list: List[np.ndarray] = []
    y_list: List[float] = []
    skipped = 0

    for rec in records:
        try:
            params_raw = rec["metadata"]["ai_parameters"]
            stats = rec["overall_statistics"]
            params_upper = normalize_keys_upper(params_raw)
            full_params = merge_on_template(template_params, params_upper)
            x = codec.encode(full_params)
            y = ObjectiveFunction.from_stats(stats)
            X_list.append(x)
            y_list.append(y)
        except Exception:
            skipped += 1

    if not X_list:
        raise RuntimeError("没有可用样本：gameData 中未找到可解析的 ai_parameters + overall_statistics")

    return np.vstack(X_list), np.array(y_list, dtype=float), skipped


def merge_on_template(template: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(template)

    def _merge(a: Dict[str, Any], b: Dict[str, Any]) -> None:
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                _merge(a[k], v)
            else:
                a[k] = v

    _merge(out, patch)
    return out


def normalize_keys_upper(obj: Any) -> Any:
    """把参数字典键统一成大写，便于对齐 defaultParameter/importable 结构。"""
    if isinstance(obj, dict):
        return {str(k).upper(): normalize_keys_upper(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_keys_upper(v) for v in obj]
    return obj


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="DoJot Bayesian Optimizer")
    p.add_argument(
        "--game-data",
        type=Path,
        default=Path("GameData/gameData_20260324135920.json"),
        help="导出的 gameData JSON 路径",
    )
    p.add_argument(
        "--param-spec",
        type=Path,
        default=Path("Parameter/defaultParameter.json"),
        help="参数边界定义文件",
    )
    p.add_argument(
        "--template",
        type=Path,
        default=Path("Parameter/defaultParameter.importable.json"),
        help="可导入参数模板文件",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("Optimizer/suggestedParameter.importable.json"),
        help="输出的新参数文件",
    )
    p.add_argument("--seed", type=int, default=42, help="随机种子")
    p.add_argument("--candidates", type=int, default=4000, help="EI 候选点数量")
    return p


def main() -> None:
    args = build_parser().parse_args()

    spec_tree = read_json(args.param_spec)
    specs = flatten_parameter_spec(spec_tree)
    if not specs:
        raise RuntimeError("未从参数定义中解析到任何可优化参数。")

    template = read_json(args.template)
    codec = ParameterCodec(specs)
    X, y, skipped = load_dataset(args.game_data, codec, template)

    optimizer = BayesianOptimizer(codec=codec, random_state=args.seed, xi=0.01)
    optimizer.fit(X, y)
    x_next = optimizer.propose_next(n_candidates=args.candidates)
    proposed_patch = codec.decode(x_next)

    final_params = merge_on_template(template, proposed_patch)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(final_params, f, indent=2, ensure_ascii=False)

    # 输出一份简明报告，方便手动导入
    best_idx = int(np.argmax(y))
    best_seen = codec.decode(X[best_idx])
    report = {
        "samples_used": int(len(X)),
        "samples_skipped": int(skipped),
        "best_historical_score": float(y[best_idx]),
        "best_historical_params_subset": best_seen,
        "suggested_params_subset": proposed_patch,
        "output_file": str(args.out),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
