
import os
import sqlite3
import pytest
from trackio.sqlite_storage import SQLiteStorage

def test_move_run_success(temp_dir):
    # Setup
    src_proj = "src_proj"
    dst_proj = "dst_proj"
    run_name = "test_run"
    
    # 1. Create run in source
    SQLiteStorage.log(src_proj, run_name, {"accuracy": 0.8}, step=1)
    SQLiteStorage.store_config(src_proj, run_name, {"param": "value"})
    SQLiteStorage.bulk_log_system(src_proj, run_name, [{"cpu": 10}])
    
    # Verify creation
    assert len(SQLiteStorage.get_logs(src_proj, run_name)) == 1
    assert SQLiteStorage.get_run_config(src_proj, run_name) is not None
    assert len(SQLiteStorage.get_system_logs(src_proj, run_name)) == 1
    
    # 2. Move run
    success = SQLiteStorage.move_run(src_proj, dst_proj, run_name)
    assert success is True
    
    # 3. Verify destination
    assert len(SQLiteStorage.get_logs(dst_proj, run_name)) == 1
    assert SQLiteStorage.get_logs(dst_proj, run_name)[0]["step"] == 1
    config = SQLiteStorage.get_run_config(dst_proj, run_name)
    assert config is not None
    assert config["param"] == "value"
    assert len(SQLiteStorage.get_system_logs(dst_proj, run_name)) == 1
    
    # 4. Verify source (should be empty)
    assert len(SQLiteStorage.get_logs(src_proj, run_name)) == 0
    assert SQLiteStorage.get_run_config(src_proj, run_name) is None

def test_move_run_target_exists(temp_dir):
    src_proj = "src_proj"
    dst_proj = "dst_proj"
    run_name = "conflict_run"
    
    # Create in both
    SQLiteStorage.log(src_proj, run_name, {"a": 1})
    SQLiteStorage.log(dst_proj, run_name, {"b": 2})
    
    # Attempt move
    success = SQLiteStorage.move_run(src_proj, dst_proj, run_name)
    assert success is False
    
    # Verify no changes
    logs_src = SQLiteStorage.get_logs(src_proj, run_name)
    assert logs_src[0]["a"] == 1
    
    logs_dst = SQLiteStorage.get_logs(dst_proj, run_name)
    assert logs_dst[0]["b"] == 2

def test_move_run_source_not_found(temp_dir):
    success = SQLiteStorage.move_run("non_existent", "dst", "run")
    assert success is False
    
    # Create empty source project
    SQLiteStorage.init_db("empty_src")
    success = SQLiteStorage.move_run("empty_src", "dst", "missing_run")
    assert success is False

def test_move_run_same_project(temp_dir):
    success = SQLiteStorage.move_run("p1", "p1", "r1")
    assert success is False
