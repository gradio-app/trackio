"""Hyperparameter sweep support for Trackio.

Provides a minimal, wandb-compatible way to define a hyperparameter search
space and run a local grid or random search over it. Each generated
configuration is executed by calling a user-supplied training function; any
`trackio.init()` call made from within that function automatically picks up
the sweep-selected values (merged into `config`) and is grouped under a
shared sweep id, so the resulting runs can be compared side by side in the
dashboard (e.g. by filtering to that group).

This is intentionally scoped to local, in-process orchestration: grid and
random search over a single machine. A hosted sweep controller, distributed
agents, and Bayesian/other advanced search strategies are not implemented
here; see https://github.com/gradio-app/trackio/issues/657 for the broader
feature request.
"""

import itertools
import random
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Literal

from trackio.context_vars import current_sweep_config, current_sweep_id

SweepMethod = Literal["grid", "random"]


@dataclass
class SweepParameter:
    """A single parameter's search space within a sweep.

    Either `values` (a discrete set to choose from) or both `min` and `max`
    (a continuous or integer range, used by random search) must be provided.
    """

    values: list[Any] | None = None
    min: float | None = None
    max: float | None = None
    distribution: Literal["uniform", "int_uniform"] = "uniform"

    def __post_init__(self):
        has_values = self.values is not None
        has_range = self.min is not None or self.max is not None
        if not has_values and not has_range:
            raise ValueError(
                "Each sweep parameter must define either `values` or both "
                "`min` and `max`."
            )
        if has_values and has_range:
            raise ValueError(
                "A sweep parameter cannot define both `values` and a `min`/`max` range."
            )
        if has_range and (self.min is None or self.max is None):
            raise ValueError(
                "A sweep parameter with a range must define both `min` and `max`."
            )
        if has_range and self.min > self.max:
            raise ValueError(
                f"`min` ({self.min}) must be less than or equal to `max` ({self.max})."
            )

    def is_discrete(self) -> bool:
        return self.values is not None

    def sample(self) -> Any:
        if self.values is not None:
            return random.choice(self.values)
        if self.distribution == "int_uniform":
            return random.randint(int(self.min), int(self.max))
        return random.uniform(self.min, self.max)


@dataclass
class SweepConfig:
    parameters: dict[str, SweepParameter]
    method: SweepMethod = "grid"
    name: str | None = None

    @classmethod
    def from_dict(cls, config: "SweepConfig | dict[str, Any]") -> "SweepConfig":
        if isinstance(config, SweepConfig):
            return config
        method = config.get("method", "grid")
        if method not in ("grid", "random"):
            raise ValueError(
                f"Unsupported sweep method {method!r}. Supported methods: 'grid', 'random'."
            )
        raw_parameters = config.get("parameters")
        if not raw_parameters:
            raise ValueError("Sweep config must define a non-empty `parameters` dict.")
        parameters = {}
        for param_name, param_spec in raw_parameters.items():
            if isinstance(param_spec, SweepParameter):
                parameters[param_name] = param_spec
            elif isinstance(param_spec, dict):
                parameters[param_name] = SweepParameter(**param_spec)
            else:
                raise ValueError(
                    f"Sweep parameter '{param_name}' must be a dict like "
                    f"{{'values': [...]}} or {{'min': ..., 'max': ...}}, got {type(param_spec)}."
                )
        return cls(parameters=parameters, method=method, name=config.get("name"))


def _grid_configs(parameters: dict[str, SweepParameter]) -> Iterator[dict[str, Any]]:
    for param_name, param in parameters.items():
        if not param.is_discrete():
            raise ValueError(
                f"Grid search requires discrete `values` for every parameter, but "
                f"'{param_name}' defines a min/max range instead. Use method='random' "
                "for continuous or integer ranges, or provide `values` for a grid search."
            )
    names = list(parameters.keys())
    value_lists = [parameters[name].values for name in names]
    for combo in itertools.product(*value_lists):
        yield dict(zip(names, combo))


def _random_configs(
    parameters: dict[str, SweepParameter], count: int
) -> Iterator[dict[str, Any]]:
    for _ in range(count):
        yield {name: param.sample() for name, param in parameters.items()}


def generate_configs(
    sweep_config: "SweepConfig | dict[str, Any]", count: int | None = None
) -> list[dict[str, Any]]:
    """Materializes the list of hyperparameter configurations a sweep will run.

    Args:
        sweep_config (`SweepConfig` or `dict`):
            A `SweepConfig`, or a dict with `method` (`"grid"` or `"random"`,
            defaults to `"grid"`) and `parameters` (a dict mapping parameter
            name to either `{"values": [...]}` for a discrete set, or
            `{"min": ..., "max": ...}` for a continuous/integer range).
        count (`int`, *optional*):
            Number of configurations to generate. Required when
            `method="random"`. For `method="grid"`, defaults to the full
            cartesian product of `values`; if provided and smaller than the
            full grid, the grid is truncated to the first `count` combinations.

    Returns:
        A list of dicts, each mapping parameter name to its sampled value.
    """
    resolved = SweepConfig.from_dict(sweep_config)

    if resolved.method == "grid":
        configs = list(_grid_configs(resolved.parameters))
        if count is not None:
            configs = configs[:count]
        return configs

    if count is None:
        raise ValueError("`count` is required when method='random'.")
    if count < 1:
        raise ValueError("`count` must be a positive integer.")
    return list(_random_configs(resolved.parameters, count))


def sweep(
    sweep_config: "SweepConfig | dict[str, Any]",
    function: Callable[[], Any],
    count: int | None = None,
    sweep_id: str | None = None,
) -> str:
    """Runs a local hyperparameter sweep by calling `function` once per configuration.

    For each generated configuration, `function` is called with the sweep's
    context set so that any `trackio.init()` call made inside it automatically
    merges the sweep-selected hyperparameters into `config` (overriding any
    matching keys already in that run's `config`) and groups the run under
    the returned sweep id, unless `group` is explicitly passed to that
    `init()` call.

    Args:
        sweep_config (`SweepConfig` or `dict`):
            See [`generate_configs`].
        function (`Callable`):
            A zero-argument callable that runs one training iteration,
            typically calling `trackio.init()`, logging metrics, then
            `run.finish()`.
        count (`int`, *optional*):
            Number of configurations to run. Required when `method="random"`,
            optional for `method="grid"` (caps the grid if provided).
        sweep_id (`str`, *optional*):
            Identifier for this sweep, used as the run group name so results
            can be compared in the dashboard. Defaults to `sweep_config.name`
            if set, otherwise a short generated id.

    Returns:
        The sweep id used to group the runs.

    Example:
        ```python
        import trackio

        def train():
            run = trackio.init(project="my-project")
            lr = run.config["learning_rate"]
            batch_size = run.config["batch_size"]
            # ... train and log metrics ...
            run.finish()

        trackio.sweep(
            {
                "method": "grid",
                "parameters": {
                    "learning_rate": {"values": [1e-2, 1e-3, 1e-4]},
                    "batch_size": {"values": [16, 32, 64]},
                },
            },
            function=train,
        )
        ```
    """
    resolved = SweepConfig.from_dict(sweep_config)
    configs = generate_configs(resolved, count=count)
    if not configs:
        raise ValueError("Sweep produced zero configurations to run.")

    resolved_sweep_id = sweep_id or resolved.name or f"sweep-{uuid.uuid4().hex[:8]}"

    plural = "s" if len(configs) != 1 else ""
    print(
        f"* Starting sweep '{resolved_sweep_id}' ({resolved.method} search, "
        f"{len(configs)} run{plural})"
    )

    for i, run_config in enumerate(configs, start=1):
        print(f"* Sweep run {i}/{len(configs)} [{resolved_sweep_id}]: {run_config}")
        config_token = current_sweep_config.set(run_config)
        id_token = current_sweep_id.set(resolved_sweep_id)
        try:
            function()
        finally:
            current_sweep_config.reset(config_token)
            current_sweep_id.reset(id_token)

    return resolved_sweep_id
