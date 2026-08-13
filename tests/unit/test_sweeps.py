import sys

import numpy as np
import pytest

from trackio import sweeps
from trackio.sweeps import (
    GridSuggester,
    RandomSuggester,
    SweepConfigError,
    can_transition_sweep_state,
    expand_command,
    flatten_parameters,
    flatten_params,
    grid_values,
    infer_distribution,
    is_command_sweep,
    next_trial,
    param_hash,
    sample_parameter,
    target_met,
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

    def test_bayes_requires_metric(self):
        with pytest.raises(SweepConfigError, match="bayes.*metric"):
            validate_sweep_config(
                {"method": "bayes", "parameters": {"lr": {"values": [1]}}}
            )
        config = validate_sweep_config(
            {
                "method": "bayes",
                "metric": {"name": "loss"},
                "parameters": {"lr": {"min": 0.001, "max": 0.1}},
            }
        )
        assert config["metric"]["goal"] == "minimize"

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

    def test_metric_target_must_be_number(self):
        with pytest.raises(SweepConfigError, match="target"):
            validate_sweep_config(
                {**grid_config(), "metric": {"name": "loss", "target": "low"}}
            )
        with pytest.raises(SweepConfigError, match="target"):
            validate_sweep_config(
                {**grid_config(), "metric": {"name": "loss", "target": True}}
            )
        config = validate_sweep_config(
            {**grid_config(), "metric": {"name": "loss", "target": 0.1}}
        )
        assert config["metric"]["target"] == 0.1

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

    def test_q_uniform_off_lattice_bounds_match_sampling_support(self):
        spec = {"distribution": "q_uniform", "min": 0.1, "max": 0.5, "q": 0.2}
        values = grid_values(spec, "p")
        assert values == [0.0, 0.2, 0.4]
        assert len(values) == len(set(values))
        rng = np.random.default_rng(0)
        support = set(values)
        for _ in range(200):
            assert sample_parameter(spec, "p", rng) in support

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


class TestCommandConfigValidation:
    def test_program_must_be_string(self):
        with pytest.raises(SweepConfigError, match="program"):
            validate_sweep_config({**grid_config(), "program": ["train.py"]})

    def test_command_must_be_list_of_strings(self):
        with pytest.raises(SweepConfigError, match="command"):
            validate_sweep_config({**grid_config(), "command": "python train.py"})
        with pytest.raises(SweepConfigError, match="command"):
            validate_sweep_config({**grid_config(), "command": ["python", 3]})

    def test_command_referencing_program_requires_program(self):
        with pytest.raises(SweepConfigError, match="program"):
            validate_sweep_config(
                {**grid_config(), "command": ["${interpreter}", "${program}"]}
            )

    def test_is_command_sweep(self):
        assert not is_command_sweep(grid_config())
        assert is_command_sweep({**grid_config(), "program": "train.py"})
        assert is_command_sweep({**grid_config(), "command": ["./train.sh"]})


class TestExpandCommand:
    def test_default_command(self):
        config = {**grid_config(), "program": "train.py"}
        argv = expand_command(config, {"lr": 0.1, "batch_size": 8})
        assert argv == [
            "/usr/bin/env",
            sys.executable,
            "train.py",
            "--batch_size=8",
            "--lr=0.1",
        ]

    def test_requires_program_or_command(self):
        with pytest.raises(SweepConfigError, match="program"):
            expand_command(grid_config(), {"lr": 0.1})

    def test_nested_params_use_dotted_args(self):
        config = {**grid_config(), "program": "train.py"}
        argv = expand_command(config, {"optimizer": {"lr": 0.1, "name": "adam"}})
        assert "--optimizer.lr=0.1" in argv
        assert "--optimizer.name=adam" in argv

    def test_args_no_hyphens(self):
        config = {
            **grid_config(),
            "program": "train.py",
            "command": ["${program}", "${args_no_hyphens}"],
        }
        argv = expand_command(config, {"lr": 0.1})
        assert argv == ["train.py", "lr=0.1"]

    def test_args_no_boolean_flags(self):
        config = {
            **grid_config(),
            "command": ["run.sh", "${args_no_boolean_flags}"],
        }
        argv = expand_command(config, {"augment": True, "debug": False, "lr": 0.1})
        assert argv == ["run.sh", "--augment", "--lr=0.1"]

    def test_boolean_values_in_plain_args(self):
        config = {**grid_config(), "command": ["run.sh", "${args}"]}
        argv = expand_command(config, {"augment": True})
        assert argv == ["run.sh", "--augment=True"]

    def test_args_json(self):
        config = {**grid_config(), "command": ["run.sh", "${args_json}"]}
        params = {"optimizer": {"lr": 0.1}}
        argv = expand_command(config, params)
        assert argv == ["run.sh", '{"optimizer": {"lr": 0.1}}']

    def test_args_macros_must_be_whole_tokens(self):
        config = {**grid_config(), "command": ["run.sh", "--params=${args}"]}
        with pytest.raises(SweepConfigError, match="whole command token"):
            expand_command(config, {"lr": 0.1})

    def test_envvar_macro(self):
        config = {
            **grid_config(),
            "command": ["run.sh", "${envvar:MY_TOKEN}"],
        }
        argv = expand_command(config, {}, environ={"MY_TOKEN": "secret"})
        assert argv == ["run.sh", "secret"]

    def test_missing_envvar_warns_and_expands_empty(self):
        config = {**grid_config(), "command": ["run.sh", "x${envvar:NOPE_VAR}y"]}
        with pytest.warns(UserWarning, match="NOPE_VAR"):
            argv = expand_command(config, {}, environ={})
        assert argv == ["run.sh", "xy"]

    def test_inline_program_and_interpreter_substitution(self):
        config = {
            **grid_config(),
            "program": "train.py",
            "command": ["${interpreter}", "-u", "${program}", "${args}"],
        }
        argv = expand_command(config, {"lr": 0.5})
        assert argv == [sys.executable, "-u", "train.py", "--lr=0.5"]

    def test_flatten_params_round_trip(self):
        nested = {"optimizer": {"lr": 0.1}, "seed": 3}
        flat = flatten_params(nested)
        assert flat == {"optimizer.lr": 0.1, "seed": 3}
        assert unflatten_params(flat) == nested


class TestRandomizeOrder:
    def test_randomize_order_shuffles_without_explicit_rng(self):
        config = {
            "method": "grid",
            "randomize_order": True,
            "parameters": {"x": {"values": list(range(50))}},
        }
        firsts = {GridSuggester(config).suggest([])["x"] for _ in range(20)}
        assert len(firsts) > 1


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


class TestTargetMet:
    def _config(self, goal, target):
        return {
            **grid_config(),
            "metric": {"name": "loss", "goal": goal, "target": target},
        }

    def test_no_target_never_met(self):
        config = {**grid_config(), "metric": {"name": "loss", "goal": "minimize"}}
        trials = [{"state": "finished", "metric_value": -100.0}]
        assert not target_met(config, trials)

    def test_minimize_met_at_or_below_target(self):
        config = self._config("minimize", 0.5)
        assert target_met(config, [{"state": "finished", "metric_value": 0.5}])
        assert target_met(config, [{"state": "finished", "metric_value": 0.4}])
        assert not target_met(config, [{"state": "finished", "metric_value": 0.6}])

    def test_maximize_met_at_or_above_target(self):
        config = self._config("maximize", 0.9)
        assert target_met(config, [{"state": "finished", "metric_value": 0.9}])
        assert target_met(config, [{"state": "finished", "metric_value": 0.95}])
        assert not target_met(config, [{"state": "finished", "metric_value": 0.8}])

    def test_only_finished_trials_count(self):
        config = self._config("minimize", 0.5)
        for state in ("assigned", "running", "failed", "pruned"):
            assert not target_met(config, [{"state": state, "metric_value": 0.1}])
        assert not target_met(config, [{"state": "finished", "metric_value": None}])


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
