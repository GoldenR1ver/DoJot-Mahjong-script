"""
DoJot 参数贝叶斯优化器（GPR + EI）

最低可用目标：
1) 读取导出的 gameData
2) 使用历史样本拟合高斯过程
3) 生成一套新的可导入参数（与 defaultParameter.importable.json 对齐）

结构优化（耦合感知）：
- 可选 parameter_coupling.json：同组参数在局部搜索时施加「相关扰动」，减少乘法耦合维独立探索产生的非物理组合。
- ARD Matern 核：各维独立 length_scale，缓解量纲与敏感度差异。
- 可选锚点正则：在 EI 上惩罚偏离模板（初版参数）过远的点，抑制小样本下的野点。
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
from scipy.stats import norm
from sklearn.exceptions import ConvergenceWarning
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel as C
from sklearn.gaussian_process.kernels import Matern

# sklearn 拟合时常报收敛警告；小样本高维下可忽略
warnings.filterwarnings("ignore", category=ConvergenceWarning)


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


def resolve_coupling_groups(
    specs: List[ParameterSpec], coupling_path: Path | None
) -> Tuple[List[List[int]], Dict[str, Any] | None]:
    """
    将 parameter_coupling.json 中的参数名解析为 specs 的下标列表。
    返回 (groups, meta)；groups 中每个子列表为一组耦合维度；空 coupling_path 时 groups 为空。
    """
    if coupling_path is None or not coupling_path.is_file():
        return [], None

    data = read_json(coupling_path)
    name_to_index = {s.name: i for i, s in enumerate(specs)}
    groups: List[List[int]] = []
    seen_names: set[str] = set()
    dup: List[str] = []

    for g in data.get("groups", []):
        idxs: List[int] = []
        for pname in g.get("params", []):
            if pname in seen_names:
                dup.append(pname)
            seen_names.add(pname)
            if pname not in name_to_index:
                raise ValueError(f"耦合配置中的参数名在 defaultParameter.json 中不存在: {pname}")
            idxs.append(name_to_index[pname])
        if idxs:
            groups.append(idxs)

    if dup:
        raise ValueError(f"耦合配置中重复出现的参数: {sorted(set(dup))}")

    all_names = set(name_to_index.keys())
    ungrouped = sorted(all_names - seen_names)
    meta = {
        "version": data.get("version"),
        "description": data.get("description"),
        "n_groups": len(groups),
        "n_grouped_dims": sum(len(g) for g in groups),
        "n_ungrouped": len(ungrouped),
        "ungrouped_params": ungrouped,
    }
    return groups, meta


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

    def mutate_around_coupled(
        self,
        base: np.ndarray,
        rng: np.random.Generator,
        groups: Sequence[Sequence[int]],
        scale_group: float = 0.09,
        scale_independent: float = 0.028,
    ) -> np.ndarray:
        """
        耦合局部搜索：每个 group 共享一个高斯增量；未出现在任何 group 中的下标各自独立一步。
        最后对所有维加一小独立噪声。
        """
        x = base.astype(float).copy()
        dim = x.shape[0]
        covered = np.zeros(dim, dtype=bool)

        for g in groups:
            delta = float(rng.normal(loc=0.0, scale=scale_group))
            for i in g:
                x[i] += delta
                covered[i] = True

        for i in range(dim):
            if not covered[i]:
                x[i] += float(rng.normal(loc=0.0, scale=scale_group))

        x += rng.normal(loc=0.0, scale=scale_independent, size=dim)
        return np.clip(x, 0.0, 1.0)


def _build_ard_kernel(n_features: int) -> Any:
    """ARD：每维独立 length_scale（与标量 length_scale_bounds 组合，兼容 sklearn 约束写法）。"""
    return C(1.0, (1e-3, 1e3)) * Matern(
        length_scale=np.ones(n_features, dtype=float),
        length_scale_bounds=(1e-2, 1e2),
        nu=2.5,
    )


class BayesianOptimizer:
    def __init__(
        self,
        codec: ParameterCodec,
        random_state: int = 42,
        xi: float = 0.01,
        coupling_groups: List[List[int]] | None = None,
        anchor_vector: np.ndarray | None = None,
        anchor_weight: float = 0.0,
        use_ard: bool = True,
    ):
        self.codec = codec
        self.xi = xi
        self.rng = np.random.default_rng(random_state)
        self.coupling_groups = coupling_groups or []
        self.anchor_vector = anchor_vector
        self.anchor_weight = float(anchor_weight)
        n_dim = len(codec.specs)
        kernel = _build_ard_kernel(n_dim) if use_ard and n_dim > 0 else C(1.0, (1e-3, 1e3)) * Matern(length_scale=1.0, nu=2.5)
        self.gp = GaussianProcessRegressor(
            kernel=kernel,
            alpha=1e-4,
            normalize_y=True,
            n_restarts_optimizer=min(12, max(4, n_dim // 8)),
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
        ei = np.maximum(ei, 0.0)

        if self.anchor_vector is not None and self.anchor_weight > 0.0:
            diff = candidates - self.anchor_vector.reshape(1, -1)
            dist2 = np.mean(diff**2, axis=1)
            ei = ei - self.anchor_weight * dist2
        return ei

    def propose_next(
        self,
        n_candidates: int = 4000,
        block_mutation_ratio: float = 0.55,
        scale_group: float = 0.09,
        scale_independent: float = 0.028,
        scale_legacy: float = 0.12,
    ) -> np.ndarray:
        if self.X is None or self.y is None or len(self.X) < 3:
            return self.codec.random_vector(self.rng)

        n_c = max(200, n_candidates)
        half = max(100, n_c // 2)
        candidates: List[np.ndarray] = []

        for _ in range(half):
            candidates.append(self.codec.random_vector(self.rng))

        top_k = min(5, len(self.y))
        top_idx = np.argsort(self.y)[-top_k:]
        per_top = max(20, n_c // (2 * top_k))

        for idx in top_idx:
            base = self.X[idx]
            for _ in range(per_top):
                if self.coupling_groups and self.rng.random() < block_mutation_ratio:
                    candidates.append(
                        self.codec.mutate_around_coupled(
                            base,
                            self.rng,
                            self.coupling_groups,
                            scale_group=scale_group,
                            scale_independent=scale_independent,
                        )
                    )
                else:
                    candidates.append(self.codec.mutate_around(base, self.rng, scale=scale_legacy))

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
    p = argparse.ArgumentParser(description="DoJot Bayesian Optimizer (coupling-aware GPR + EI)")
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
        help="可导入参数模板文件（亦用作锚点编码）",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("Optimizer/suggestedParameter.importable.json"),
        help="输出的新参数文件",
    )
    p.add_argument("--seed", type=int, default=42, help="随机种子")
    p.add_argument("--candidates", type=int, default=4000, help="EI 候选点数量")
    p.add_argument(
        "--coupling",
        type=Path,
        default=Path("Optimizer/parameter_coupling.json"),
        help="参数耦合分组 JSON；与 --no-coupling 互斥",
    )
    p.add_argument(
        "--no-coupling",
        action="store_true",
        help="不使用耦合分组（退化为独立维度局部搜索）",
    )
    p.add_argument(
        "--block-mutation-ratio",
        type=float,
        default=0.55,
        help="从历史最优附近采样时，使用「分组相关扰动」的比例（0~1）",
    )
    p.add_argument(
        "--anchor-weight",
        type=float,
        default=0.0,
        help="锚点正则强度：EI 减去该系数 × 与模板参数（归一化空间）均方偏离；默认 0 保持旧行为，小样本建议 0.1~0.2",
    )
    p.add_argument(
        "--no-ard",
        action="store_true",
        help="不使用 ARD 核（退化为各向同性 Matern）",
    )
    p.add_argument(
        "--scale-group",
        type=float,
        default=0.09,
        help="耦合块内共享扰动标准差（归一化坐标）",
    )
    p.add_argument(
        "--scale-independent",
        type=float,
        default=0.028,
        help="耦合变异后每维独立噪声标准差",
    )
    return p


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass

    args = build_parser().parse_args()

    spec_tree = read_json(args.param_spec)
    specs = flatten_parameter_spec(spec_tree)
    if not specs:
        raise RuntimeError("未从参数定义中解析到任何可优化参数。")

    coupling_path: Path | None = None
    groups: List[List[int]] = []
    coupling_meta: Dict[str, Any] | None = None
    if args.no_coupling:
        coupling_meta = {"disabled": True, "reason": "--no-coupling"}
    else:
        coupling_path = args.coupling
        if coupling_path.is_file():
            groups, coupling_meta = resolve_coupling_groups(specs, coupling_path)
        else:
            print(f"警告: 未找到耦合文件 {coupling_path}，局部搜索退化为独立维度扰动。", file=sys.stderr)
            groups, coupling_meta = [], {"missing_file": str(coupling_path)}

    template = read_json(args.template)
    codec = ParameterCodec(specs)
    X, y, skipped = load_dataset(args.game_data, codec, template)

    anchor_vec = codec.encode(template) if args.anchor_weight > 0 else None

    optimizer = BayesianOptimizer(
        codec=codec,
        random_state=args.seed,
        xi=0.01,
        coupling_groups=groups,
        anchor_vector=anchor_vec,
        anchor_weight=args.anchor_weight,
        use_ard=not args.no_ard,
    )
    optimizer.fit(X, y)
    x_next = optimizer.propose_next(
        n_candidates=args.candidates,
        block_mutation_ratio=args.block_mutation_ratio,
        scale_group=args.scale_group,
        scale_independent=args.scale_independent,
    )
    proposed_patch = codec.decode(x_next)

    final_params = merge_on_template(template, proposed_patch)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(final_params, f, indent=2, ensure_ascii=False)

    best_idx = int(np.argmax(y))
    best_seen = codec.decode(X[best_idx])
    report: Dict[str, Any] = {
        "samples_used": int(len(X)),
        "samples_skipped": int(skipped),
        "best_historical_score": float(y[best_idx]),
        "best_historical_params_subset": best_seen,
        "suggested_params_subset": proposed_patch,
        "output_file": str(args.out),
        "optimizer": {
            "ard_kernel": not args.no_ard,
            "anchor_weight": args.anchor_weight,
            "block_mutation_ratio": args.block_mutation_ratio,
            "coupling_file": str(coupling_path) if coupling_path else None,
            "coupling_meta": coupling_meta,
        },
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
