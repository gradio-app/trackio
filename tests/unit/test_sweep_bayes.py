import numpy as np
import pytest

from trackio.sqlite_storage import SQLiteStorage
from trackio.sweep_bayes import (
    BayesSuggester,
    _expected_improvement,
    _fit_gp,
    _GaussianProcess,
    _SpaceEncoder,
)
from trackio.sweeps import flatten_parameters, next_trial


def bayes_config(**overrides):
    config = {
        "method": "bayes",
        "metric": {"name": "loss", "goal": "minimize"},
        "parameters": {"x": {"min": 0.0, "max": 1.0}},
    }
    config.update(overrides)
    return config


def finished(params, value):
    return {"params": params, "state": "finished", "metric_value": value}


class TestSpaceEncoder:
    def _encoder(self, parameters):
        return _SpaceEncoder(flatten_parameters(parameters))

    def test_uniform_normalizes_to_unit_interval(self):
        encoder = self._encoder({"x": {"min": 10.0, "max": 20.0}})
        assert encoder.dim == 1
        assert encoder.encode({"x": 10.0})[0] == 0.0
        assert encoder.encode({"x": 20.0})[0] == 1.0
        assert encoder.encode({"x": 15.0})[0] == pytest.approx(0.5)

    def test_values_outside_bounds_are_clipped(self):
        encoder = self._encoder({"x": {"min": 0.0, "max": 1.0}})
        assert encoder.encode({"x": -5.0})[0] == 0.0
        assert encoder.encode({"x": 5.0})[0] == 1.0

    def test_log_uniform_values_encodes_in_log_space(self):
        encoder = self._encoder(
            {
                "lr": {
                    "distribution": "log_uniform_values",
                    "min": 1e-4,
                    "max": 1e-1,
                }
            }
        )
        low = encoder.encode({"lr": 1e-4})[0]
        mid = encoder.encode({"lr": 1e-3})[0]
        high = encoder.encode({"lr": 1e-1})[0]
        assert low == pytest.approx(0.0)
        assert high == pytest.approx(1.0)
        assert mid == pytest.approx(1.0 / 3.0)

    def test_categorical_one_hot(self):
        encoder = self._encoder({"opt": {"values": ["adam", "sgd", "lion"]}})
        assert encoder.dim == 3
        assert list(encoder.encode({"opt": "sgd"})) == [0.0, 1.0, 0.0]
        assert list(encoder.encode({"opt": "unknown"})) == [0.0, 0.0, 0.0]

    def test_normal_uses_cdf(self):
        encoder = self._encoder(
            {"x": {"distribution": "normal", "mu": 5.0, "sigma": 2.0}}
        )
        assert encoder.encode({"x": 5.0})[0] == pytest.approx(0.5)
        assert encoder.encode({"x": 100.0})[0] == pytest.approx(1.0)

    def test_constants_are_dropped(self):
        encoder = self._encoder({"seed": {"value": 42}, "x": {"min": 0, "max": 1}})
        assert encoder.dim == 1

    def test_missing_or_bad_values_fall_back(self):
        encoder = self._encoder(
            {
                "x": {"min": 0.0, "max": 1.0},
                "lr": {
                    "distribution": "log_uniform_values",
                    "min": 1e-4,
                    "max": 1e-1,
                },
            }
        )
        encoded = encoder.encode({"x": None, "lr": -3.0})
        assert list(encoded) == [0.5, 0.5]


class TestGaussianProcess:
    def test_posterior_interpolates_training_points(self):
        x = np.array([[0.0], [0.5], [1.0]])
        y = np.array([0.0, -1.0, 0.0])
        gp = _GaussianProcess(x, y, length_scale=1.0)
        mean, std = gp.predict(x)
        assert np.allclose(mean, y, atol=1e-3)
        assert np.all(std < 0.05)

    def test_uncertainty_grows_away_from_data(self):
        x = np.array([[0.0], [0.1]])
        y = np.array([0.0, 0.1])
        gp = _GaussianProcess(x, y, length_scale=0.3)
        _, std_near = gp.predict(np.array([[0.05]]))
        _, std_far = gp.predict(np.array([[1.0]]))
        assert std_far[0] > std_near[0]

    def test_duplicate_points_survive_via_jitter(self):
        x = np.array([[0.5], [0.5], [0.5]])
        y = np.array([1.0, 1.0, 1.0])
        gp = _GaussianProcess(x, y, length_scale=1.0)
        mean, _ = gp.predict(np.array([[0.5]]))
        assert mean[0] == pytest.approx(1.0, abs=1e-2)

    def test_fit_gp_picks_a_length_scale(self):
        rng = np.random.default_rng(0)
        x = rng.uniform(size=(20, 1))
        y = np.sin(6.0 * x[:, 0])
        gp = _fit_gp(x, y)
        assert gp is not None
        assert gp.length_scale in (0.1, 0.3, 1.0, 3.0)


class TestExpectedImprovement:
    def test_zero_improvement_when_mean_far_worse(self):
        ei = _expected_improvement(np.array([10.0]), np.array([1e-6]), best=0.0)
        assert ei[0] == pytest.approx(0.0, abs=1e-9)

    def test_improvement_positive_below_best(self):
        ei = _expected_improvement(np.array([-1.0]), np.array([0.1]), best=0.0)
        assert ei[0] > 0.9

    def test_uncertainty_adds_value_at_equal_mean(self):
        ei_low = _expected_improvement(np.array([0.0]), np.array([0.01]), best=0.0)
        ei_high = _expected_improvement(np.array([0.0]), np.array([1.0]), best=0.0)
        assert ei_high[0] > ei_low[0]


class TestBayesSuggester:
    def test_falls_back_to_random_below_two_completed(self):
        suggester = BayesSuggester(bayes_config())
        rng = np.random.default_rng(0)
        params = suggester.suggest([finished({"x": 0.5}, 1.0)], rng=rng)
        assert 0.0 <= params["x"] <= 1.0

    def test_deterministic_given_seed(self):
        trials = [finished({"x": 0.2}, 0.04), finished({"x": 0.8}, 0.36)]
        first = BayesSuggester(bayes_config()).suggest(
            trials, rng=np.random.default_rng(7)
        )
        second = BayesSuggester(bayes_config()).suggest(
            trials, rng=np.random.default_rng(7)
        )
        assert first == second

    def test_concentrates_near_optimum_on_quadratic(self):
        rng = np.random.default_rng(42)
        trials = [
            finished({"x": x}, (x - 0.3) ** 2) for x in (0.0, 0.15, 0.45, 0.6, 0.9)
        ]
        suggester = BayesSuggester(bayes_config())
        suggestions = [suggester.suggest(trials, rng=rng)["x"] for _ in range(5)]
        assert np.median([abs(s - 0.3) for s in suggestions]) < 0.15

    def test_maximize_goal_flips_direction(self):
        config = bayes_config(metric={"name": "acc", "goal": "maximize"})
        rng = np.random.default_rng(42)
        trials = [
            finished({"x": x}, -((x - 0.7) ** 2)) for x in (0.0, 0.2, 0.5, 0.8, 1.0)
        ]
        suggester = BayesSuggester(config)
        suggestions = [suggester.suggest(trials, rng=rng)["x"] for _ in range(5)]
        assert np.median([abs(s - 0.7) for s in suggestions]) < 0.15

    def test_failed_trials_imputed_as_worst_steer_away(self):
        rng = np.random.default_rng(3)
        trials = [
            finished({"x": 0.6}, 0.5),
            finished({"x": 0.9}, 0.4),
            {"params": {"x": 0.05}, "state": "failed", "metric_value": None},
            {"params": {"x": 0.1}, "state": "failed", "metric_value": None},
            {"params": {"x": 0.15}, "state": "failed", "metric_value": None},
        ]
        suggester = BayesSuggester(bayes_config())
        suggestions = [suggester.suggest(trials, rng=rng)["x"] for _ in range(5)]
        assert np.median(suggestions) > 0.3

    def test_fantasy_points_suppress_inflight_duplicates(self):
        trials = [
            finished({"x": x}, (x - 0.3) ** 2) for x in (0.0, 0.15, 0.45, 0.6, 0.9)
        ]
        rng = np.random.default_rng(11)
        baseline = BayesSuggester(bayes_config()).suggest(trials, rng=rng)
        in_flight = {"params": {"x": baseline["x"]}, "state": "assigned"}
        rng = np.random.default_rng(11)
        with_fantasy = BayesSuggester(bayes_config()).suggest(
            trials + [in_flight], rng=rng
        )
        assert abs(with_fantasy["x"] - baseline["x"]) > 1e-6

    def test_nested_and_categorical_params(self):
        config = bayes_config(
            parameters={
                "optimizer": {
                    "parameters": {
                        "name": {"values": ["adam", "sgd"]},
                        "lr": {
                            "distribution": "log_uniform_values",
                            "min": 1e-4,
                            "max": 1e-1,
                        },
                    }
                },
                "seed": {"value": 42},
            }
        )
        trials = [
            finished({"optimizer": {"name": "adam", "lr": 1e-3}, "seed": 42}, 0.2),
            finished({"optimizer": {"name": "sgd", "lr": 1e-2}, "seed": 42}, 0.8),
            finished({"optimizer": {"name": "adam", "lr": 3e-3}, "seed": 42}, 0.1),
        ]
        params = BayesSuggester(config).suggest(trials, rng=np.random.default_rng(0))
        assert params["optimizer"]["name"] in ("adam", "sgd")
        assert 1e-4 <= params["optimizer"]["lr"] <= 1e-1
        assert params["seed"] == 42

    def test_all_constant_space_falls_back_to_random(self):
        config = bayes_config(parameters={"seed": {"value": 42}})
        trials = [finished({"seed": 42}, 1.0), finished({"seed": 42}, 1.0)]
        params = BayesSuggester(config).suggest(trials, rng=np.random.default_rng(0))
        assert params == {"seed": 42}

    def test_identical_metric_values_do_not_crash(self):
        trials = [finished({"x": 0.2}, 1.0), finished({"x": 0.8}, 1.0)]
        params = BayesSuggester(bayes_config()).suggest(
            trials, rng=np.random.default_rng(0)
        )
        assert 0.0 <= params["x"] <= 1.0


class TestBayesIntegration:
    def test_next_trial_routes_bayes(self):
        params = next_trial(bayes_config(), trials=[], rng=np.random.default_rng(0))
        assert 0.0 <= params["x"] <= 1.0

    def test_bayes_beats_random_on_quadratic(self):
        def objective(x):
            return (x - 0.62) ** 2

        def run_sweep(method, seed):
            config = (
                bayes_config()
                if method == "bayes"
                else {
                    "method": "random",
                    "metric": {"name": "loss", "goal": "minimize"},
                    "parameters": {"x": {"min": 0.0, "max": 1.0}},
                }
            )
            rng = np.random.default_rng(seed)
            trials = []
            for _ in range(15):
                params = next_trial(config, trials, rng=rng)
                trials.append(finished(params, objective(params["x"])))
            return min(t["metric_value"] for t in trials)

        bayes_bests = [run_sweep("bayes", seed) for seed in range(5)]
        random_bests = [run_sweep("random", seed) for seed in range(5)]
        assert np.median(bayes_bests) <= np.median(random_bests)

    def test_bayes_sweep_through_storage(self, temp_dir):
        sweep_id = SQLiteStorage.create_sweep("proj", bayes_config(run_cap=6))
        for _ in range(6):
            command = SQLiteStorage.suggest_trial("proj", sweep_id)
            assert command["command"] == "run"
            x = command["params"]["x"]
            SQLiteStorage.report_trial(
                "proj",
                sweep_id,
                command["trial_id"],
                "finished",
                metric_value=(x - 0.5) ** 2,
            )
        assert SQLiteStorage.suggest_trial("proj", sweep_id) == {
            "command": "exit",
            "reason": "run_cap",
        }
        sweep = SQLiteStorage.get_sweep("proj", sweep_id)
        assert sweep["state"] == "finished"
        assert sweep["best_metric_value"] is not None
