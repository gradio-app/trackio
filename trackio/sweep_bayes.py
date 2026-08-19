"""Bayesian-optimization suggester for sweeps: a numpy-only Gaussian process
(Matern nu=1.5) with Expected Improvement evaluated over candidates sampled
from the parameter priors, mirroring wandb's bayes search engine. Pure, no
I/O, no dependencies beyond numpy."""

import math

import numpy as np

from trackio.sweeps import (
    flatten_parameters,
    flatten_params,
    infer_distribution,
    nested_param_paths,
    sample_parameter,
    unflatten_params,
)

MIN_COMPLETED_TRIALS = 2
NUM_CANDIDATES = 1000
LENGTH_SCALES = (0.1, 0.3, 1.0, 3.0)
BASE_JITTER = 1e-8
MAX_JITTER = 1e-2

_ERF = np.vectorize(math.erf)


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _encode_numeric(spec: dict, distribution: str, value) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.5
    try:
        if distribution in ("int_uniform", "uniform", "q_uniform"):
            low, high = spec["min"], spec["max"]
        elif distribution in ("log_uniform", "q_log_uniform"):
            low, high = spec["min"], spec["max"]
            value = math.log(value)
        elif distribution in ("log_uniform_values", "q_log_uniform_values"):
            low, high = math.log(spec["min"]), math.log(spec["max"])
            value = math.log(value)
        elif distribution == "inv_log_uniform":
            low, high = spec["min"], spec["max"]
            value = math.log(1.0 / value)
        elif distribution == "inv_log_uniform_values":
            low = math.log(1.0 / spec["max"])
            high = math.log(1.0 / spec["min"])
            value = math.log(1.0 / value)
        elif distribution in ("normal", "q_normal"):
            return _normal_cdf((value - spec.get("mu", 0.0)) / spec.get("sigma", 1.0))
        elif distribution in ("log_normal", "q_log_normal"):
            return _normal_cdf(
                (math.log(value) - spec.get("mu", 0.0)) / spec.get("sigma", 1.0)
            )
        elif distribution in ("beta", "q_beta"):
            return min(max(value, 0.0), 1.0)
        else:
            return 0.5
    except (ValueError, ZeroDivisionError):
        return 0.5
    if high <= low:
        return 0.5
    return min(max((value - low) / (high - low), 0.0), 1.0)


class _SpaceEncoder:
    """Maps flat param dicts to points in [0, 1]^d for GP modeling: one-hot
    for categoricals, normalized (log-scaled where appropriate) coordinates
    for numeric distributions, constants dropped."""

    def __init__(self, flat_specs: dict):
        self.columns = []
        for path in sorted(flat_specs):
            spec = flat_specs[path]
            distribution = infer_distribution(spec, path)
            if distribution == "constant":
                continue
            if distribution in ("categorical", "categorical_w_probabilities"):
                self.columns.append((path, spec, distribution, "categorical"))
            else:
                self.columns.append((path, spec, distribution, "numeric"))
        self.dim = sum(
            len(spec["values"]) if kind == "categorical" else 1
            for _, spec, _, kind in self.columns
        )

    def encode(self, flat_params: dict) -> np.ndarray:
        features: list[float] = []
        for path, spec, distribution, kind in self.columns:
            value = flat_params.get(path)
            if kind == "categorical":
                one_hot = [0.0] * len(spec["values"])
                if value in spec["values"]:
                    one_hot[spec["values"].index(value)] = 1.0
                features.extend(one_hot)
            else:
                features.append(_encode_numeric(spec, distribution, value))
        return np.array(features, dtype=float)


def _matern_kernel(a: np.ndarray, b: np.ndarray, length_scale: float) -> np.ndarray:
    squared = (
        np.sum(a**2, axis=1)[:, None] + np.sum(b**2, axis=1)[None, :] - 2.0 * (a @ b.T)
    )
    dists = np.sqrt(np.maximum(squared, 0.0))
    scaled = math.sqrt(3.0) * dists / length_scale
    return (1.0 + scaled) * np.exp(-scaled)


class _GaussianProcess:
    def __init__(self, x: np.ndarray, y: np.ndarray, length_scale: float):
        self.x = x
        self.y = y
        self.length_scale = length_scale
        kernel = _matern_kernel(x, x, length_scale)
        jitter = BASE_JITTER
        while True:
            try:
                self.cholesky = np.linalg.cholesky(kernel + jitter * np.eye(len(x)))
                break
            except np.linalg.LinAlgError:
                jitter *= 10.0
                if jitter > MAX_JITTER:
                    raise
        self.alpha = np.linalg.solve(self.cholesky.T, np.linalg.solve(self.cholesky, y))

    def log_marginal_likelihood(self) -> float:
        return float(
            -0.5 * self.y @ self.alpha
            - np.sum(np.log(np.diag(self.cholesky)))
            - 0.5 * len(self.y) * math.log(2.0 * math.pi)
        )

    def predict(self, x_new: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        k_star = _matern_kernel(x_new, self.x, self.length_scale)
        mean = k_star @ self.alpha
        v = np.linalg.solve(self.cholesky, k_star.T)
        variance = np.maximum(1.0 - np.sum(v**2, axis=0), 1e-12)
        return mean, np.sqrt(variance)


def _fit_gp(x: np.ndarray, y: np.ndarray) -> "_GaussianProcess | None":
    best = None
    best_lml = -math.inf
    for length_scale in LENGTH_SCALES:
        try:
            gp = _GaussianProcess(x, y, length_scale)
        except np.linalg.LinAlgError:
            continue
        lml = gp.log_marginal_likelihood()
        if lml > best_lml:
            best, best_lml = gp, lml
    return best


def _expected_improvement(mean: np.ndarray, std: np.ndarray, best: float) -> np.ndarray:
    z = (best - mean) / std
    cdf = 0.5 * (1.0 + _ERF(z / math.sqrt(2.0)))
    pdf = np.exp(-0.5 * z**2) / math.sqrt(2.0 * math.pi)
    return (best - mean) * cdf + std * pdf


class BayesSuggester:
    def __init__(self, config: dict):
        self.config = config
        self.flat_specs = flatten_parameters(config["parameters"])
        self.nested_paths = nested_param_paths(config["parameters"])
        metric = config.get("metric") or {}
        self.maximize = metric.get("goal") == "maximize"
        self.encoder = _SpaceEncoder(self.flat_specs)

    def _random_flat_params(self, rng: np.random.Generator) -> dict:
        return {
            path: sample_parameter(spec, path, rng)
            for path, spec in sorted(self.flat_specs.items())
        }

    def suggest(
        self, trials: list[dict], rng: np.random.Generator | None = None
    ) -> dict | None:
        rng = rng if rng is not None else np.random.default_rng()
        completed: list[tuple[dict, float]] = []
        imputed: list[dict] = []
        in_flight: list[dict] = []
        for trial in trials:
            state = trial.get("state")
            value = trial.get("metric_value")
            flat = flatten_params(trial["params"])
            if state == "finished" and value is not None:
                completed.append((flat, float(value)))
            elif state in ("failed", "pruned"):
                imputed.append(flat)
            elif state in ("assigned", "running"):
                in_flight.append(flat)

        if len(completed) < MIN_COMPLETED_TRIALS or self.encoder.dim == 0:
            return unflatten_params(self._random_flat_params(rng), self.nested_paths)

        sign = -1.0 if self.maximize else 1.0
        x_rows = [self.encoder.encode(flat) for flat, _ in completed]
        y_values = [sign * value for _, value in completed]
        worst = max(y_values)
        for flat in imputed:
            x_rows.append(self.encoder.encode(flat))
            y_values.append(worst)

        y = np.array(y_values, dtype=float)
        y_mean = float(y.mean())
        y_scale = float(y.std())
        if y_scale == 0.0:
            y_scale = 1.0
        y_norm = (y - y_mean) / y_scale
        x = np.vstack(x_rows)

        gp = _fit_gp(x, y_norm)
        if gp is None:
            return unflatten_params(self._random_flat_params(rng), self.nested_paths)

        if in_flight:
            x_fantasy = np.vstack([self.encoder.encode(flat) for flat in in_flight])
            fantasy_mean, _ = gp.predict(x_fantasy)
            gp = _fit_gp(
                np.vstack([x, x_fantasy]), np.concatenate([y_norm, fantasy_mean])
            )
            if gp is None:
                return unflatten_params(
                    self._random_flat_params(rng), self.nested_paths
                )

        candidates = [self._random_flat_params(rng) for _ in range(NUM_CANDIDATES)]
        x_candidates = np.vstack([self.encoder.encode(c) for c in candidates])
        mean, std = gp.predict(x_candidates)
        best_observed = float(np.min(y_norm[: len(completed)]))
        ei = _expected_improvement(mean, std, best_observed)
        return unflatten_params(candidates[int(np.argmax(ei))], self.nested_paths)
