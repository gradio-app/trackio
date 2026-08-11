import pytest

import trackio
from trackio.sweep import SweepConfig, SweepParameter, generate_configs, sweep


def test_sweep_parameter_requires_values_or_range():
    with pytest.raises(ValueError, match="values.*min.*max"):
        SweepParameter()


def test_sweep_parameter_rejects_both_values_and_range():
    with pytest.raises(ValueError, match="cannot define both"):
        SweepParameter(values=[1, 2], min=0, max=1)


def test_sweep_parameter_rejects_min_greater_than_max():
    with pytest.raises(ValueError, match="less than or equal to"):
        SweepParameter(min=10, max=1)


def test_sweep_config_from_dict_rejects_unknown_method():
    with pytest.raises(ValueError, match="Unsupported sweep method"):
        SweepConfig.from_dict(
            {"method": "bayes", "parameters": {"lr": {"values": [1e-3]}}}
        )


def test_sweep_config_from_dict_requires_parameters():
    with pytest.raises(ValueError, match="non-empty"):
        SweepConfig.from_dict({"method": "grid", "parameters": {}})


def test_generate_configs_grid_is_full_cartesian_product():
    configs = generate_configs(
        {
            "method": "grid",
            "parameters": {
                "lr": {"values": [0.1, 0.01]},
                "batch_size": {"values": [16, 32, 64]},
            },
        }
    )
    assert len(configs) == 6
    assert {(c["lr"], c["batch_size"]) for c in configs} == {
        (0.1, 16),
        (0.1, 32),
        (0.1, 64),
        (0.01, 16),
        (0.01, 32),
        (0.01, 64),
    }


def test_generate_configs_grid_can_be_truncated_with_count():
    configs = generate_configs(
        {"method": "grid", "parameters": {"lr": {"values": [1, 2, 3, 4]}}},
        count=2,
    )
    assert len(configs) == 2


def test_generate_configs_grid_rejects_continuous_parameters():
    with pytest.raises(ValueError, match="Grid search requires discrete"):
        generate_configs(
            {"method": "grid", "parameters": {"lr": {"min": 0.0, "max": 1.0}}}
        )


def test_generate_configs_random_requires_count():
    with pytest.raises(ValueError, match="`count` is required"):
        generate_configs(
            {"method": "random", "parameters": {"lr": {"values": [0.1, 0.01]}}}
        )


def test_generate_configs_random_respects_count_and_bounds():
    configs = generate_configs(
        {
            "method": "random",
            "parameters": {
                "lr": {"min": 0.0, "max": 1.0},
                "layers": {"min": 1, "max": 4, "distribution": "int_uniform"},
                "optimizer": {"values": ["adam", "sgd"]},
            },
        },
        count=25,
    )
    assert len(configs) == 25
    for config in configs:
        assert 0.0 <= config["lr"] <= 1.0
        assert 1 <= config["layers"] <= 4
        assert isinstance(config["layers"], int)
        assert config["optimizer"] in ("adam", "sgd")


def test_sweep_runs_function_once_per_config():
    calls = []

    def train():
        calls.append(1)

    sweep_id = sweep(
        {
            "method": "grid",
            "parameters": {"lr": {"values": [0.1, 0.01, 0.001]}},
        },
        function=train,
    )
    assert len(calls) == 3
    assert sweep_id.startswith("sweep-")


def test_sweep_raises_on_empty_configs():
    with pytest.raises(ValueError, match="zero configurations"):
        sweep(
            {"method": "grid", "parameters": {"lr": {"values": [1, 2]}}},
            function=lambda: None,
            count=0,
        )


def test_sweep_uses_provided_sweep_id():
    seen_ids = []

    def train():
        seen_ids.append(1)

    result = sweep(
        {"method": "grid", "parameters": {"lr": {"values": [1]}}},
        function=train,
        sweep_id="my-custom-sweep",
    )
    assert result == "my-custom-sweep"


def test_init_inside_sweep_merges_config_and_sets_group(temp_dir):
    seen_configs = []
    seen_groups = []

    def train():
        run = trackio.init(project="test_sweep_project", config={"epochs": 5})
        seen_configs.append(dict(run.config))
        seen_groups.append(run.group)
        run.finish()

    sweep_id = sweep(
        {
            "method": "grid",
            "parameters": {
                "lr": {"values": [0.1, 0.01]},
                "batch_size": {"values": [32]},
            },
        },
        function=train,
    )

    assert len(seen_configs) == 2
    for config in seen_configs:
        assert config["epochs"] == 5
        assert config["batch_size"] == 32
        assert config["lr"] in (0.1, 0.01)
    assert {c["lr"] for c in seen_configs} == {0.1, 0.01}
    assert seen_groups == [sweep_id, sweep_id]


def test_init_config_explicit_group_overrides_sweep_group(temp_dir):
    seen_groups = []

    def train():
        run = trackio.init(project="test_sweep_project_2", group="custom-group")
        seen_groups.append(run.group)
        run.finish()

    sweep(
        {"method": "grid", "parameters": {"lr": {"values": [1, 2]}}},
        function=train,
    )
    assert seen_groups == ["custom-group", "custom-group"]


def test_init_outside_sweep_is_unaffected(temp_dir):
    run = trackio.init(project="test_sweep_project_3", config={"epochs": 1})
    assert run.config["epochs"] == 1
    assert "lr" not in run.config
    assert run.group is None
    run.finish()
