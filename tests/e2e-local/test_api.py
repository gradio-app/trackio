import trackio
from trackio import Api
from trackio.sqlite_storage import SQLiteStorage


def test_delete_run(temp_dir):
    project = "test_delete_project"
    run_name = "test_delete_run"
    
    trackio.init(project=project, name=run_name)
    trackio.log(metrics={"loss": 0.1, "accuracy": 0.9})
    trackio.log(metrics={"loss": 0.2, "accuracy": 0.95})
    trackio.finish()
    
    logs = SQLiteStorage.get_logs(project=project, run=run_name)
    assert len(logs) == 2
    assert logs[0]["loss"] == 0.1
    assert logs[1]["loss"] == 0.2
    
    api = Api()
    runs = api.runs(project)
    run = runs[0]
    assert run.name == run_name
    
    success = run.delete()
    assert success is True
    
    logs_after = SQLiteStorage.get_logs(project=project, run=run_name)
    assert len(logs_after) == 0
    
    config_after = SQLiteStorage.get_run_config(project=project, run=run_name)
    assert config_after is None
    
    runs_after = SQLiteStorage.get_runs(project=project)
    assert run_name not in runs_after


def test_move_run(temp_dir, image_ndarray):
    source_project = "test_move_source"
    target_project = "test_move_target"
    run_name = "test_move_run"
    
    trackio.init(project=source_project, name=run_name)
    
    image1 = trackio.Image(image_ndarray, caption="test_image_1")
    image2 = trackio.Image(image_ndarray, caption="test_image_2")
    
    trackio.log(metrics={"loss": 0.1, "acc": 0.9, "img1": image1})
    trackio.log(metrics={"loss": 0.2, "acc": 0.95, "img2": image2})
    trackio.finish()
    
    source_logs = SQLiteStorage.get_logs(project=source_project, run=run_name)
    assert len(source_logs) == 2
    assert source_logs[0]["loss"] == 0.1
    assert source_logs[1]["loss"] == 0.2
    
    image1_path = source_logs[0]["img1"].get("file_path")
    assert image1_path is not None
    assert str(image1_path).startswith(f"{source_project}/{run_name}/")
    
    api = Api()
    runs = api.runs(source_project)
    run = runs[0]
    assert run.name == run_name
    assert run.project == source_project
    
    success = run.move(target_project)
    assert success is True
    assert run.project == target_project
    
    target_logs = SQLiteStorage.get_logs(project=target_project, run=run_name)
    assert len(target_logs) == 2
    assert target_logs[0]["loss"] == 0.1
    assert target_logs[1]["loss"] == 0.2
    
    target_image1_path = target_logs[0]["img1"].get("file_path")
    assert target_image1_path is not None
    assert str(target_image1_path).startswith(f"{target_project}/{run_name}/")
    
    target_image2_path = target_logs[1]["img2"].get("file_path")
    assert target_image2_path is not None
    assert str(target_image2_path).startswith(f"{target_project}/{run_name}/")
    
    source_logs_after = SQLiteStorage.get_logs(project=source_project, run=run_name)
    assert len(source_logs_after) == 0
    
    source_runs_after = SQLiteStorage.get_runs(project=source_project)
    assert run_name not in source_runs_after
    
    target_runs = SQLiteStorage.get_runs(project=target_project)
    assert run_name in target_runs
    
    source_config_after = SQLiteStorage.get_run_config(project=source_project, run=run_name)
    assert source_config_after is None
    
    target_config = SQLiteStorage.get_run_config(project=target_project, run=run_name)
    assert target_config is not None

