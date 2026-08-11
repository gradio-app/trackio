"""Pure sweep logic: config validation, parameter distributions, and trial
suggestion. No I/O — storage and transport live in sqlite_storage.py and
sweep_agent.py."""

import hashlib
import itertools
import json
import math
import secrets
import warnings

import numpy as np

SWEEP_ID_ENV = "TRACKIO_SWEEP_ID"
SWEEP_TRIAL_ID_ENV = "TRACKIO_SWEEP_TRIAL_ID"
SWEEP_PARAMS_ENV = "TRACKIO_SWEEP_PARAMS"
SWEEP_PROJECT_ENV = "TRACKIO_SWEEP_PROJECT"

SWEEP_METHODS = ("grid", "random")
FUTURE_SWEEP_METHODS = ("bayes",)

SWEEP_STATES = ("running", "paused", "finished", "stopped", "cancelled")
TERMINAL_SWEEP_STATES = ("finished", "stopped", "cancelled")
SWEEP_STATE_TRANSITIONS = {
    "running": {"paused", "finished", "stopped", "cancelled"},
    "paused": {"running", "finished", "stopped", "cancelled"},
    "finished": set(),
    "stopped": set(),
    "cancelled": set(),
}

TRIAL_STATES = ("assigned", "running", "finished", "failed", "pruned")
TERMINAL_TRIAL_STATES = ("finished", "failed", "pruned")

GRID_COMPATIBLE_DISTRIBUTIONS = (
    "constant",
    "categorical",
    "int_uniform",
    "q_uniform",
)

DISTRIBUTIONS = (
    "constant",
    "categorical",
    "categorical_w_probabilities",
    "int_uniform",
    "uniform",
    "q_uniform",
    "log_uniform",
    "log_uniform_values",
    "q_log_uniform",
    "q_log_uniform_values",
    "inv_log_uniform",
    "inv_log_uniform_values",
    "normal",
    "q_normal",
    "log_normal",
    "q_log_normal",
    "beta",
    "q_beta",
)


class SweepConfigError(ValueError):
    pass


def generate_sweep_id() -> str:
    return secrets.token_hex(4)


def can_transition_sweep_state(current: str, new: str) -> bool:
    return new in SWEEP_STATE_TRANSITIONS.get(current, set())


def param_hash(params: dict) -> str:
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def infer_distribution(spec: dict, path: str) -> str:
    if "distribution" in spec:
        distribution = spec["distribution"]
        if distribution not in DISTRIBUTIONS:
            raise SweepConfigError(
                f"Parameter '{path}': unknown distribution '{distribution}'. "
                f"Valid distributions: {', '.join(DISTRIBUTIONS)}"
            )
        return distribution
    if "values" in spec and "probabilities" in spec:
        return "categorical_w_probabilities"
    if "values" in spec:
        return "categorical"
    if "value" in spec:
        return "constant"
    if "min" in spec and "max" in spec:
        if isinstance(spec["min"], int) and isinstance(spec["max"], int):
            return "int_uniform"
        return "uniform"
    raise SweepConfigError(
        f"Parameter '{path}' must define one of: 'value', 'values', "
        "'min'/'max', 'distribution', or nested 'parameters'."
    )


def _validate_bounds(spec: dict, path: str, positive: bool = False):
    for key in ("min", "max"):
        if key not in spec:
            raise SweepConfigError(f"Parameter '{path}' requires '{key}'.")
        if not isinstance(spec[key], (int, float)) or isinstance(spec[key], bool):
            raise SweepConfigError(f"Parameter '{path}': '{key}' must be a number.")
    if spec["min"] > spec["max"]:
        raise SweepConfigError(f"Parameter '{path}': 'min' must be <= 'max'.")
    if positive and spec["min"] <= 0:
        raise SweepConfigError(f"Parameter '{path}': 'min' must be > 0.")


def _validate_param_spec(spec: dict, path: str):
    distribution = infer_distribution(spec, path)
    if distribution == "constant":
        if "value" not in spec:
            raise SweepConfigError(f"Parameter '{path}' requires 'value'.")
    elif distribution in ("categorical", "categorical_w_probabilities"):
        values = spec.get("values")
        if not isinstance(values, list) or not values:
            raise SweepConfigError(
                f"Parameter '{path}' requires a non-empty 'values' list."
            )
        if distribution == "categorical_w_probabilities":
            probabilities = spec.get("probabilities")
            if not isinstance(probabilities, list) or len(probabilities) != len(values):
                raise SweepConfigError(
                    f"Parameter '{path}': 'probabilities' must be a list the "
                    "same length as 'values'."
                )
            if not math.isclose(sum(probabilities), 1.0, rel_tol=1e-6):
                raise SweepConfigError(
                    f"Parameter '{path}': 'probabilities' must sum to 1."
                )
    elif distribution == "int_uniform":
        _validate_bounds(spec, path)
        if not isinstance(spec["min"], int) or not isinstance(spec["max"], int):
            raise SweepConfigError(
                f"Parameter '{path}': int_uniform requires integer 'min'/'max'."
            )
    elif distribution in (
        "uniform",
        "q_uniform",
        "log_uniform",
        "q_log_uniform",
        "inv_log_uniform",
    ):
        _validate_bounds(spec, path)
    elif distribution in (
        "log_uniform_values",
        "q_log_uniform_values",
        "inv_log_uniform_values",
    ):
        _validate_bounds(spec, path, positive=True)
    elif distribution in ("normal", "q_normal", "log_normal", "q_log_normal"):
        for key in ("mu", "sigma"):
            if key in spec and (
                not isinstance(spec[key], (int, float)) or isinstance(spec[key], bool)
            ):
                raise SweepConfigError(f"Parameter '{path}': '{key}' must be a number.")
        if spec.get("sigma", 1.0) <= 0:
            raise SweepConfigError(f"Parameter '{path}': 'sigma' must be > 0.")
    elif distribution in ("beta", "q_beta"):
        for key in ("a", "b"):
            if spec.get(key, 1.0) <= 0:
                raise SweepConfigError(f"Parameter '{path}': '{key}' must be > 0.")
    if "q" in spec and spec["q"] <= 0:
        raise SweepConfigError(f"Parameter '{path}': 'q' must be > 0.")


def flatten_parameters(parameters: dict, prefix: str = "") -> dict[str, dict]:
    """Flattens nested `parameters` blocks to dotted paths -> leaf specs."""
    flat = {}
    for name, spec in parameters.items():
        if not isinstance(spec, dict):
            spec = {"value": spec}
        path = f"{prefix}{name}"
        if "parameters" in spec:
            nested = spec["parameters"]
            if not isinstance(nested, dict) or not nested:
                raise SweepConfigError(
                    f"Parameter '{path}': nested 'parameters' must be a non-empty dict."
                )
            flat.update(flatten_parameters(nested, prefix=f"{path}."))
        else:
            flat[path] = spec
    return flat


def unflatten_params(flat_params: dict) -> dict:
    nested: dict = {}
    for path, value in flat_params.items():
        parts = path.split(".")
        node = nested
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return nested


def validate_sweep_config(config: dict) -> dict:
    """Validates a wandb-schema sweep config and returns a normalized copy."""
    if not isinstance(config, dict):
        raise SweepConfigError("Sweep config must be a dict.")
    config = dict(config)

    method = config.get("method")
    if method in FUTURE_SWEEP_METHODS:
        raise SweepConfigError(
            f"Sweep method '{method}' is not supported yet by trackio. "
            f"Supported methods: {', '.join(SWEEP_METHODS)}."
        )
    if method not in SWEEP_METHODS:
        raise SweepConfigError(
            f"Sweep config requires 'method' set to one of: {', '.join(SWEEP_METHODS)}."
        )

    parameters = config.get("parameters")
    if not isinstance(parameters, dict) or not parameters:
        raise SweepConfigError("Sweep config requires a non-empty 'parameters' dict.")
    flat_specs = flatten_parameters(parameters)
    for path, spec in flat_specs.items():
        _validate_param_spec(spec, path)
        if method == "grid":
            distribution = infer_distribution(spec, path)
            if distribution not in GRID_COMPATIBLE_DISTRIBUTIONS:
                raise SweepConfigError(
                    f"Parameter '{path}': distribution '{distribution}' is not "
                    "compatible with method 'grid'. Grid search requires "
                    "discrete parameters (value, values, int_uniform, or "
                    "q_uniform)."
                )

    metric = config.get("metric")
    if metric is not None:
        if not isinstance(metric, dict) or "name" not in metric:
            raise SweepConfigError("'metric' must be a dict with a 'name' key.")
        goal = metric.get("goal", "minimize")
        if goal not in ("minimize", "maximize"):
            raise SweepConfigError("'metric.goal' must be 'minimize' or 'maximize'.")
        config["metric"] = {**metric, "goal": goal}

    run_cap = config.get("run_cap")
    if run_cap is not None and (not isinstance(run_cap, int) or run_cap <= 0):
        raise SweepConfigError("'run_cap' must be a positive integer.")

    if "early_terminate" in config:
        warnings.warn(
            "Sweep config contains 'early_terminate', which trackio does not "
            "support yet. Trials will NOT be pruned early.",
            stacklevel=2,
        )

    return config


def _quantize(value: float, q: float) -> float:
    return round(value / q) * q


def sample_parameter(spec: dict, path: str, rng: np.random.Generator):
    distribution = infer_distribution(spec, path)
    q = spec.get("q", 1.0)
    mu = spec.get("mu", 0.0)
    sigma = spec.get("sigma", 1.0)

    if distribution == "constant":
        return spec["value"]
    if distribution == "categorical":
        return spec["values"][int(rng.integers(len(spec["values"])))]
    if distribution == "categorical_w_probabilities":
        index = rng.choice(len(spec["values"]), p=spec["probabilities"])
        return spec["values"][int(index)]
    if distribution == "int_uniform":
        return int(rng.integers(spec["min"], spec["max"] + 1))
    if distribution == "uniform":
        return float(rng.uniform(spec["min"], spec["max"]))
    if distribution == "q_uniform":
        return _quantize(rng.uniform(spec["min"], spec["max"]), q)
    if distribution == "log_uniform":
        return float(np.exp(rng.uniform(spec["min"], spec["max"])))
    if distribution == "log_uniform_values":
        return float(np.exp(rng.uniform(np.log(spec["min"]), np.log(spec["max"]))))
    if distribution == "q_log_uniform":
        return _quantize(np.exp(rng.uniform(spec["min"], spec["max"])), q)
    if distribution == "q_log_uniform_values":
        return _quantize(
            np.exp(rng.uniform(np.log(spec["min"]), np.log(spec["max"]))), q
        )
    if distribution == "inv_log_uniform":
        return float(1.0 / np.exp(rng.uniform(spec["min"], spec["max"])))
    if distribution == "inv_log_uniform_values":
        low = np.log(1.0 / spec["max"])
        high = np.log(1.0 / spec["min"])
        return float(1.0 / np.exp(rng.uniform(low, high)))
    if distribution == "normal":
        return float(rng.normal(mu, sigma))
    if distribution == "q_normal":
        return _quantize(rng.normal(mu, sigma), q)
    if distribution == "log_normal":
        return float(np.exp(rng.normal(mu, sigma)))
    if distribution == "q_log_normal":
        return _quantize(np.exp(rng.normal(mu, sigma)), q)
    if distribution == "beta":
        return float(rng.beta(spec.get("a", 1.0), spec.get("b", 1.0)))
    if distribution == "q_beta":
        return _quantize(rng.beta(spec.get("a", 1.0), spec.get("b", 1.0)), q)
    raise SweepConfigError(f"Parameter '{path}': unhandled distribution.")


def grid_values(spec: dict, path: str) -> list:
    distribution = infer_distribution(spec, path)
    if distribution == "constant":
        return [spec["value"]]
    if distribution == "categorical":
        return list(spec["values"])
    if distribution == "int_uniform":
        return list(range(spec["min"], spec["max"] + 1))
    if distribution == "q_uniform":
        q = spec.get("q", 1.0)
        values = []
        step = 0
        while True:
            value = spec["min"] + step * q
            if value > spec["max"] + 1e-9:
                break
            values.append(_quantize(value, q))
            step += 1
        return values
    raise SweepConfigError(
        f"Parameter '{path}': distribution '{distribution}' is not compatible "
        "with method 'grid'."
    )


class GridSuggester:
    def __init__(self, config: dict):
        self.config = config
        flat_specs = flatten_parameters(config["parameters"])
        self.paths = sorted(flat_specs)
        self.value_lists = [grid_values(flat_specs[path], path) for path in self.paths]

    def suggest(
        self, trials: list[dict], rng: np.random.Generator | None = None
    ) -> dict | None:
        seen = {
            trial.get("param_hash") or param_hash(trial["params"]) for trial in trials
        }
        combinations = itertools.product(*self.value_lists)
        if self.config.get("randomize_order") and rng is not None:
            combinations = list(combinations)
            rng.shuffle(combinations)
        for combination in combinations:
            flat_params = dict(zip(self.paths, combination))
            params = unflatten_params(flat_params)
            if param_hash(params) not in seen:
                return params
        return None


class RandomSuggester:
    def __init__(self, config: dict):
        self.config = config
        self.flat_specs = flatten_parameters(config["parameters"])

    def suggest(
        self, trials: list[dict], rng: np.random.Generator | None = None
    ) -> dict | None:
        rng = rng if rng is not None else np.random.default_rng()
        flat_params = {
            path: sample_parameter(spec, path, rng)
            for path, spec in sorted(self.flat_specs.items())
        }
        return unflatten_params(flat_params)


SUGGESTERS = {
    "grid": GridSuggester,
    "random": RandomSuggester,
}


def next_trial(
    config: dict, trials: list[dict], rng: np.random.Generator | None = None
) -> dict | None:
    """Returns the next parameter set for a sweep, or None if the sweep is
    exhausted (grid) or has hit its run_cap."""
    run_cap = config.get("run_cap")
    if run_cap is not None and len(trials) >= run_cap:
        return None
    suggester = SUGGESTERS[config["method"]](config)
    return suggester.suggest(trials, rng=rng)
