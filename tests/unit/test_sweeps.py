import numpy as np
import pytest

from trackio import sweeps
from trackio.sweeps import (
    GridSuggester,
    RandomSuggester,
    SweepConfigError,
    can_transition_sweep_state,
    flatten_parameters,
    grid_values,
    infer_distribution,
    next_trial,
    param_hash,
    sample_parameter,
    unflatten_params,
    validate_sweep_config,
)


def grid_config(**overrides):
    config = {
        "method": "grid",
        "parameters": {
            "lr": {"values": [0.1, 0.01]},
            "batch_size": {"values": [8, 16]},
        },
    }
    config.update(overrides)
    return config


class TestValidateSweepConfig:
    def test_requires_method(self):
        with pytest.raises(SweepConfigError, match="method"):
            validate_sweep_config({"parameters": {"lr": {"values": [1]}}})

    def test_rejects_bayes_with_clear_message(self):
        with pytest.raises(SweepConfigError, match="not supported yet"):
            validate_sweep_config(
                {"method": "bayes", "parameters": {"lr": {"values": [1]}}}
            )

    def test_requires_parameters(self):
        with pytest.raises(SweepConfigError, match="parameters"):
            validate_sweep_config({"method": "grid"})

    def test_grid_rejects_continuous_distributions(self):
        with pytest.raises(SweepConfigError, match="not.*compatible.*grid"):
            validate_sweep_config(
                {"method": "grid", "parameters": {"lr": {"min": 0.1, "max": 0.5}}}
            )

    def test_metric_goal_defaults_to_minimize(self):
        config = validate_sweep_config({**grid_config(), "metric": {"name": "loss"}})
        assert config["metric"]["goal"] == "minimize"

    def test_invalid_metric_goal_rejected(self):
        with pytest.raises(SweepConfigError, match="goal"):
            validate_sweep_config(
                {**grid_config(), "metric": {"name": "loss", "goal": "up"}}
            )

    def test_run_cap_must_be_positive(self):
        with pytest.raises(SweepConfigError, match="run_cap"):
            validate_sweep_config(grid_config(run_cap=0))

    def test_early_terminate_warns(self):
        with pytest.warns(UserWarning, match="early_terminate"):
            validate_sweep_config(
                grid_config(early_terminate={"type": "hyperband", "min_iter": 3})
            )

    def test_probabilities_must_sum_to_one(self):
        with pytest.raises(SweepConfigError, match="probabilities"):
            validate_sweep_config(
                {
                    "method": "random",
                    "parameters": {
                        "opt": {"values": ["a", "b"], "probabilities": [0.9, 0.5]}
                    },
                }
            )


class TestDistributionInference:
    def test_values_infers_categorical(self):
        assert infer_distribution({"values": [1, 2]}, "p") == "categorical"

    def test_value_infers_constant(self):
        assert infer_distribution({"value": 1}, "p") == "constant"

    def test_int_bounds_infer_int_uniform(self):
        assert infer_distribution({"min": 1, "max": 10}, "p") == "int_uniform"

    def test_float_bounds_infer_uniform(self):
        assert infer_distribution({"min": 0.1, "max": 1.0}, "p") == "uniform"

    def test_values_with_probabilities(self):
        spec = {"values": [1, 2], "probabilities": [0.3, 0.7]}
        assert infer_distribution(spec, "p") == "categorical_w_probabilities"

    def test_unknown_distribution_rejected(self):
        with pytest.raises(SweepConfigError, match="unknown distribution"):
            infer_distribution({"distribution": "zipf"}, "p")


class TestSampling:
    def test_seeded_sampling_is_deterministic(self):
        spec = {"distribution": "log_uniform_values", "min": 1e-4, "max": 1e-1}
        first = sample_parameter(spec, "lr", np.random.default_rng(42))
        second = sample_parameter(spec, "lr", np.random.default_rng(42))
        assert first == second

    def test_log_uniform_values_within_bounds(self):
        spec = {"distribution": "log_uniform_values", "min": 1e-4, "max": 1e-1}
        rng = np.random.default_rng(0)
        for _ in range(100):
            value = sample_parameter(spec, "lr", rng)
            assert 1e-4 <= value <= 1e-1

    def test_int_uniform_bounds_inclusive(self):
        spec = {"min": 1, "max": 3}
        rng = np.random.default_rng(0)
        seen = {sample_parameter(spec, "n", rng) for _ in range(200)}
        assert seen == {1, 2, 3}

    def test_q_uniform_quantized(self):
        spec = {"distribution": "q_uniform", "min": 0.0, "max": 1.0, "q": 0.25}
        rng = np.random.default_rng(0)
        for _ in range(50):
            value = sample_parameter(spec, "p", rng)
            assert value in (0.0, 0.25, 0.5, 0.75, 1.0)

    def test_categorical_w_probabilities_respects_weights(self):
        spec = {"values": ["a", "b"], "probabilities": [1.0, 0.0]}
        rng = np.random.default_rng(0)
        assert all(sample_parameter(spec, "p", rng) == "a" for _ in range(20))


class TestGridValues:
    def test_int_uniform_expands_to_range(self):
        assert grid_values({"min": 1, "max": 4}, "p") == [1, 2, 3, 4]

    def test_q_uniform_expands_to_steps(self):
        assert grid_values(
            {"distribution": "q_uniform", "min": 0.0, "max": 1.0, "q": 0.5}, "p"
        ) == [0.0, 0.5, 1.0]

    def test_continuous_rejected(self):
        with pytest.raises(SweepConfigError):
            grid_values({"min": 0.1, "max": 1.0}, "p")


class TestNestedParameters:
    def test_flatten_and_unflatten_roundtrip(self):
        parameters = {
            "optimizer": {
                "parameters": {
                    "name": {"values": ["adam", "sgd"]},
                    "lr": {"values": [0.1]},
                }
            },
            "seed": {"value": 1},
        }
        flat = flatten_parameters(parameters)
        assert set(flat) == {"optimizer.name", "optimizer.lr", "seed"}
        nested = unflatten_params({"optimizer.name": "adam", "seed": 1})
        assert nested == {"optimizer": {"name": "adam"}, "seed": 1}

    def test_grid_over_nested_parameters(self):
        config = validate_sweep_config(
            {
                "method": "grid",
                "parameters": {
                    "optimizer": {"parameters": {"name": {"values": ["adam", "sgd"]}}}
                },
            }
        )
        suggester = GridSuggester(config)
        first = suggester.suggest([])
        assert first["optimizer"]["name"] in ("adam", "sgd")


class TestGridSuggester:
    def test_exhausts_all_combinations_without_repeats(self):
        config = validate_sweep_config(grid_config())
        trials = []
        while True:
            params = GridSuggester(config).suggest(trials)
            if params is None:
                break
            trials.append({"params": params})
        assert len(trials) == 4
        hashes = {param_hash(t["params"]) for t in trials}
        assert len(hashes) == 4

    def test_dedups_against_existing_trials(self):
        config = validate_sweep_config(grid_config())
        existing = [{"params": {"lr": 0.1, "batch_size": 8}}]
        params = GridSuggester(config).suggest(existing)
        assert params != {"lr": 0.1, "batch_size": 8}


class TestRandomSuggester:
    def test_allows_repeated_params_on_small_space(self):
        config = validate_sweep_config(
            {"method": "random", "parameters": {"flag": {"values": [True]}}}
        )
        suggester = RandomSuggester(config)
        trials = []
        for _ in range(5):
            params = suggester.suggest(trials, rng=np.random.default_rng(0))
            assert params == {"flag": True}
            trials.append({"params": params})

    def test_never_returns_none(self):
        config = validate_sweep_config(
            {"method": "random", "parameters": {"lr": {"min": 0.0, "max": 1.0}}}
        )
        trials = [{"params": {"lr": 0.5}}] * 100
        assert RandomSuggester(config).suggest(trials) is not None


class TestNextTrial:
    def test_run_cap_stops_random_sweeps(self):
        config = validate_sweep_config(
            {
                "method": "random",
                "run_cap": 3,
                "parameters": {"lr": {"min": 0.0, "max": 1.0}},
            }
        )
        trials = [{"params": {"lr": 0.5}}] * 3
        assert next_trial(config, trials) is None
        assert next_trial(config, trials[:2]) is not None

    def test_grid_exhaustion_returns_none(self):
        config = validate_sweep_config(
            {"method": "grid", "parameters": {"lr": {"values": [0.1]}}}
        )
        assert next_trial(config, [{"params": {"lr": 0.1}}]) is None


class TestSweepStateMachine:
    def test_running_can_pause_and_terminate(self):
        for new in ("paused", "finished", "stopped", "cancelled"):
            assert can_transition_sweep_state("running", new)

    def test_paused_can_resume(self):
        assert can_transition_sweep_state("paused", "running")

    def test_terminal_states_are_final(self):
        for terminal in sweeps.TERMINAL_SWEEP_STATES:
            for new in sweeps.SWEEP_STATES:
                assert not can_transition_sweep_state(terminal, new)


class TestParamHash:
    def test_stable_under_key_order(self):
        assert param_hash({"a": 1, "b": 2}) == param_hash({"b": 2, "a": 1})

    def test_differs_for_different_values(self):
        assert param_hash({"a": 1}) != param_hash({"a": 2})
