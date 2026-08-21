"""Pure sweep logic: config validation, parameter distributions, and trial
suggestion. No I/O — storage and transport live in sqlite_storage.py and
sweep_agent.py."""

import hashlib
import itertools
import json
import math
import os
import re
import secrets
import sys
import warnings

import numpy as np

SWEEP_ID_ENV = "TRACKIO_SWEEP_ID"
SWEEP_TRIAL_ID_ENV = "TRACKIO_SWEEP_TRIAL_ID"
SWEEP_PARAMS_ENV = "TRACKIO_SWEEP_PARAMS"
SWEEP_PROJECT_ENV = "TRACKIO_SWEEP_PROJECT"
SWEEP_METRIC_ENV = "TRACKIO_SWEEP_METRIC_NAME"

SWEEP_METHODS = ("grid", "random", "bayes")

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

DEFAULT_COMMAND = ["${env}", "${interpreter}", "${program}", "${args}"]

ARGS_MACROS = (
    "${args}",
    "${args_no_boolean_flags}",
    "${args_no_hyphens}",
    "${args_json}",
)

_ENVVAR_MACRO_RE = re.compile(r"\$\{envvar:([A-Za-z_][A-Za-z0-9_]*)\}")

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


def _validate_q_bounds(spec: dict, path: str, lo: float, hi: float):
    q = spec.get("q", 1.0)
    if math.ceil(lo / q - 1e-9) > math.floor(hi / q + 1e-9):
        raise SweepConfigError(
            f"Parameter '{path}': no multiple of q={q} lies within [{lo}, {hi}]."
        )


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
            if any(
                not isinstance(p, (int, float)) or isinstance(p, bool) or p < 0
                for p in probabilities
            ):
                raise SweepConfigError(
                    f"Parameter '{path}': 'probabilities' must be non-negative numbers."
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
        if distribution == "q_uniform":
            _validate_q_bounds(spec, path, spec["min"], spec["max"])
        elif distribution == "q_log_uniform":
            _validate_q_bounds(spec, path, math.exp(spec["min"]), math.exp(spec["max"]))
    elif distribution in (
        "log_uniform_values",
        "q_log_uniform_values",
        "inv_log_uniform_values",
    ):
        _validate_bounds(spec, path, positive=True)
        if distribution == "q_log_uniform_values":
            _validate_q_bounds(spec, path, spec["min"], spec["max"])
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
            nested_flat = flatten_parameters(nested, prefix=f"{path}.")
            for nested_path in nested_flat:
                if nested_path in flat:
                    raise SweepConfigError(
                        f"Parameter '{nested_path}' is defined more than once "
                        "(a dotted name collides with a nested 'parameters' block)."
                    )
            flat.update(nested_flat)
        else:
            if path in flat:
                raise SweepConfigError(
                    f"Parameter '{path}' is defined more than once "
                    "(a dotted name collides with a nested 'parameters' block)."
                )
            flat[path] = spec
    return flat


def nested_param_paths(parameters: dict) -> set[str]:
    """The dotted paths in `flatten_parameters(parameters)` that came from
    nested `parameters` blocks (as opposed to literal dots in a name)."""
    paths: set[str] = set()
    for name, spec in parameters.items():
        if (
            isinstance(spec, dict)
            and "parameters" in spec
            and isinstance(spec["parameters"], dict)
            and spec["parameters"]
        ):
            paths.update(flatten_parameters({name: spec}))
    return paths


def unflatten_params(flat_params: dict, nested_paths: set[str] | None = None) -> dict:
    """Rebuilds a nested params dict from dotted paths. Only the paths in
    `nested_paths` (those produced by nested `parameters` blocks) are re-nested;
    other keys are kept flat even if they contain literal dots, matching how
    the user named them. `nested_paths=None` re-nests every dotted path."""
    nested: dict = {}
    for path, value in flat_params.items():
        if nested_paths is not None and path not in nested_paths:
            if isinstance(nested.get(path), dict):
                raise SweepConfigError(
                    f"Parameter '{path}' conflicts with a nested 'parameters' block."
                )
            nested[path] = value
            continue
        parts = path.split(".")
        node = nested
        for index, part in enumerate(parts[:-1]):
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise SweepConfigError(
                    f"Parameter '{'.'.join(parts[: index + 1])}' is both a "
                    "value and a nested block."
                )
        if isinstance(node.get(parts[-1]), dict):
            raise SweepConfigError(
                f"Parameter '{path}' is both a value and a nested block."
            )
        node[parts[-1]] = value
    return nested


def flatten_params(params: dict, prefix: str = "") -> dict:
    """Flattens a nested params dict (parameter values, not specs) to dotted
    paths, mirroring flatten_parameters."""
    flat = {}
    for key, value in params.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten_params(value, prefix=f"{path}."))
        else:
            flat[path] = value
    return flat


def is_command_sweep(config: dict) -> bool:
    return bool(config.get("program") or config.get("command"))


def _format_arg_value(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, int, float)) or value is None:
        return str(value)
    return json.dumps(value)


def _expand_args_macro(macro: str, params: dict, flat_params: dict) -> list[str]:
    items = sorted(flat_params.items())
    if macro == "${args}":
        return [f"--{key}={_format_arg_value(value)}" for key, value in items]
    if macro == "${args_no_boolean_flags}":
        args = []
        for key, value in items:
            if value is True:
                args.append(f"--{key}")
            elif value is False:
                continue
            else:
                args.append(f"--{key}={_format_arg_value(value)}")
        return args
    if macro == "${args_no_hyphens}":
        return [f"{key}={_format_arg_value(value)}" for key, value in items]
    if macro == "${args_json}":
        return [json.dumps(params, sort_keys=True)]
    raise SweepConfigError(f"Unknown args macro '{macro}'.")


def expand_command(
    config: dict, params: dict, environ: dict | None = None
) -> list[str]:
    """Expands a command-mode sweep's `command` template (or the wandb default
    command) into an argv list for one trial's params. Pure: pass `environ` to
    override os.environ for ${envvar:NAME} macros."""
    environ = dict(os.environ) if environ is None else environ
    program = config.get("program")
    command = config.get("command")
    if command is None:
        if program is None:
            raise SweepConfigError(
                "Command-mode sweeps require 'program' (or an explicit 'command')."
            )
        command = DEFAULT_COMMAND
    flat_params = flatten_params(params)
    argv = []
    for token in command:
        if token in ARGS_MACROS:
            argv.extend(_expand_args_macro(token, params, flat_params))
            continue
        for macro in ARGS_MACROS:
            if macro in token:
                raise SweepConfigError(
                    f"Macro '{macro}' must be a whole command token, not part "
                    f"of '{token}'."
                )
        if token == "${env}":
            if sys.platform != "win32":
                argv.append("/usr/bin/env")
            continue
        expanded = token.replace(
            "${env}", "" if sys.platform == "win32" else "/usr/bin/env"
        )
        expanded = expanded.replace("${interpreter}", sys.executable)
        if "${program}" in expanded:
            if program is None:
                raise SweepConfigError(
                    "'command' references ${program} but no 'program' is set."
                )
            expanded = expanded.replace("${program}", program)

        def _envvar(match: re.Match) -> str:
            name = match.group(1)
            if name not in environ:
                warnings.warn(
                    f"Sweep command references ${{envvar:{name}}} but it is "
                    "not set; expanding to an empty string.",
                    stacklevel=2,
                )
                return ""
            return environ[name]

        expanded = _ENVVAR_MACRO_RE.sub(_envvar, expanded)
        argv.append(expanded)
    return argv


def validate_sweep_config(config: dict) -> dict:
    """Validates a wandb-schema sweep config and returns a normalized copy."""
    if not isinstance(config, dict):
        raise SweepConfigError("Sweep config must be a dict.")
    config = dict(config)

    method = config.get("method")
    if method not in SWEEP_METHODS:
        raise SweepConfigError(
            f"Sweep config requires 'method' set to one of: {', '.join(SWEEP_METHODS)}."
        )

    parameters = config.get("parameters")
    if not isinstance(parameters, dict) or not parameters:
        raise SweepConfigError("Sweep config requires a non-empty 'parameters' dict.")
    flat_specs = flatten_parameters(parameters)
    unflatten_params(dict.fromkeys(flat_specs), nested_param_paths(parameters))
    grid_size = 1
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
            grid_size *= grid_cardinality(spec, path)
            if grid_size > MAX_GRID_CARDINALITY:
                raise SweepConfigError(
                    f"Grid sweep has more than {MAX_GRID_CARDINALITY:,} "
                    "parameter combinations; use method 'random' or 'bayes' "
                    "for a search space this large."
                )

    metric = config.get("metric")
    if metric is not None:
        if not isinstance(metric, dict) or "name" not in metric:
            raise SweepConfigError("'metric' must be a dict with a 'name' key.")
        goal = metric.get("goal", "minimize")
        if goal not in ("minimize", "maximize"):
            raise SweepConfigError("'metric.goal' must be 'minimize' or 'maximize'.")
        target = metric.get("target")
        if target is not None and (
            not isinstance(target, (int, float)) or isinstance(target, bool)
        ):
            raise SweepConfigError("'metric.target' must be a number.")
        config["metric"] = {**metric, "goal": goal}

    if method == "bayes" and not (config.get("metric") or {}).get("name"):
        raise SweepConfigError(
            "Sweep method 'bayes' requires 'metric' with a 'name' so trial "
            "results can guide the search."
        )

    run_cap = config.get("run_cap")
    if run_cap is not None and (not isinstance(run_cap, int) or run_cap <= 0):
        raise SweepConfigError("'run_cap' must be a positive integer.")

    program = config.get("program")
    if program is not None and not isinstance(program, str):
        raise SweepConfigError("'program' must be a string.")
    command = config.get("command")
    if command is not None:
        if not isinstance(command, list) or not all(
            isinstance(token, str) for token in command
        ):
            raise SweepConfigError("'command' must be a list of strings.")
        if program is None and any("${program}" in token for token in command):
            raise SweepConfigError(
                "'command' references ${program} but no 'program' is set."
            )

    if "early_terminate" in config:
        warnings.warn(
            "Sweep config contains 'early_terminate', which trackio does not "
            "support yet. Trials will NOT be pruned early.",
            stacklevel=2,
        )

    return config


def target_met(config: dict, trials: list[dict]) -> bool:
    """Whether any finished trial's metric value meets `metric.target`."""
    metric = config.get("metric") or {}
    target = metric.get("target")
    if target is None:
        return False
    maximize = metric.get("goal") == "maximize"
    for trial in trials:
        value = trial.get("metric_value")
        if trial.get("state") != "finished" or value is None:
            continue
        if value >= target if maximize else value <= target:
            return True
    return False


def _quantize(
    value: float, q: float, lo: float | None = None, hi: float | None = None
) -> float:
    """Round `value` to the nearest multiple of `q`, kept within the declared
    bounds: without clamping, rounding can land one step outside [lo, hi]."""
    k = round(value / q)
    if lo is not None:
        k = max(k, math.ceil(lo / q - 1e-9))
    if hi is not None:
        k = min(k, math.floor(hi / q + 1e-9))
    return k * q


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
        probabilities = np.asarray(spec["probabilities"], dtype=float)
        index = rng.choice(len(spec["values"]), p=probabilities / probabilities.sum())
        return spec["values"][int(index)]
    if distribution == "int_uniform":
        return int(rng.integers(spec["min"], spec["max"] + 1))
    if distribution == "uniform":
        return float(rng.uniform(spec["min"], spec["max"]))
    if distribution == "q_uniform":
        return _quantize(
            rng.uniform(spec["min"], spec["max"]), q, lo=spec["min"], hi=spec["max"]
        )
    if distribution == "log_uniform":
        return float(np.exp(rng.uniform(spec["min"], spec["max"])))
    if distribution == "log_uniform_values":
        return float(np.exp(rng.uniform(np.log(spec["min"]), np.log(spec["max"]))))
    if distribution == "q_log_uniform":
        return _quantize(
            np.exp(rng.uniform(spec["min"], spec["max"])),
            q,
            lo=math.exp(spec["min"]),
            hi=math.exp(spec["max"]),
        )
    if distribution == "q_log_uniform_values":
        return _quantize(
            np.exp(rng.uniform(np.log(spec["min"]), np.log(spec["max"]))),
            q,
            lo=spec["min"],
            hi=spec["max"],
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


MAX_GRID_CARDINALITY = 100_000


def grid_cardinality(spec: dict, path: str) -> int:
    """Number of grid values for a spec, computed without materializing them."""
    distribution = infer_distribution(spec, path)
    if distribution == "constant":
        return 1
    if distribution == "categorical":
        return len(spec["values"])
    if distribution == "int_uniform":
        return spec["max"] - spec["min"] + 1
    if distribution == "q_uniform":
        q = spec.get("q", 1.0)
        k_lo = math.ceil(spec["min"] / q - 1e-9)
        k_hi = math.floor(spec["max"] / q + 1e-9)
        return max(0, k_hi - k_lo + 1)
    raise SweepConfigError(
        f"Parameter '{path}': distribution '{distribution}' is not compatible "
        "with method 'grid'."
    )


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
        k_lo = math.ceil(spec["min"] / q - 1e-9)
        k_hi = math.floor(spec["max"] / q + 1e-9)
        if k_lo > k_hi:
            raise SweepConfigError(
                f"Parameter '{path}': no multiple of q={q} lies within "
                f"[{spec['min']}, {spec['max']}]."
            )
        return [k * q for k in range(k_lo, k_hi + 1)]
    raise SweepConfigError(
        f"Parameter '{path}': distribution '{distribution}' is not compatible "
        "with method 'grid'."
    )


class GridSuggester:
    def __init__(self, config: dict):
        self.config = config
        flat_specs = flatten_parameters(config["parameters"])
        self.nested_paths = nested_param_paths(config["parameters"])
        self.paths = sorted(flat_specs)
        self.value_lists = [grid_values(flat_specs[path], path) for path in self.paths]

    def suggest(
        self, trials: list[dict], rng: np.random.Generator | None = None
    ) -> dict | None:
        seen = {
            trial.get("param_hash") or param_hash(trial["params"]) for trial in trials
        }
        combinations = itertools.product(*self.value_lists)
        if self.config.get("randomize_order"):
            rng = rng if rng is not None else np.random.default_rng()
            combinations = list(combinations)
            rng.shuffle(combinations)
        for combination in combinations:
            flat_params = dict(zip(self.paths, combination))
            params = unflatten_params(flat_params, self.nested_paths)
            if param_hash(params) not in seen:
                return params
        return None


class RandomSuggester:
    def __init__(self, config: dict):
        self.config = config
        self.flat_specs = flatten_parameters(config["parameters"])
        self.nested_paths = nested_param_paths(config["parameters"])

    def suggest(
        self, trials: list[dict], rng: np.random.Generator | None = None
    ) -> dict | None:
        rng = rng if rng is not None else np.random.default_rng()
        flat_params = {
            path: sample_parameter(spec, path, rng)
            for path, spec in sorted(self.flat_specs.items())
        }
        return unflatten_params(flat_params, self.nested_paths)


def _bayes_suggester(config: dict):
    from trackio.sweep_bayes import BayesSuggester  # noqa: PLC0415

    return BayesSuggester(config)


SUGGESTERS = {
    "grid": GridSuggester,
    "random": RandomSuggester,
    "bayes": _bayes_suggester,
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
