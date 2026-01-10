import os
import shutil
import sys
from pathlib import Path

# Add current dir to path so we can import trackio
sys.path.insert(0, os.getcwd())

try:
    from trackio.sqlite_storage import SQLiteStorage
except ImportError:
    print("Could not import trackio.sqlite_storage")
    sys.exit(1)


def test_move_run():
    print("Setting up test...")
    # Setup temp dir
    test_dir = Path("temp_debug_trackio")
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir()

    # Mock TRACKIO_DIR
    import trackio.sqlite_storage

    trackio.sqlite_storage.TRACKIO_DIR = test_dir

    src_proj = "src_proj"
    dst_proj = "dst_proj"
    run_name = "test_run"

    print("Creating run in source...")
    SQLiteStorage.log(src_proj, run_name, {"accuracy": 0.8}, step=1)
    SQLiteStorage.store_config(src_proj, run_name, {"param": "value"})

    logs = SQLiteStorage.get_logs(src_proj, run_name)
    with open("debug_result.txt", "w") as f:
        f.write(f"Source logs: {len(logs)}\n")

        print("Moving run...")
        success = SQLiteStorage.move_run(src_proj, dst_proj, run_name)
        f.write(f"Move result: {success}\n")

        print("Verifying destination...")
        dst_logs = SQLiteStorage.get_logs(dst_proj, run_name)
        f.write(f"Dest logs: {len(dst_logs)}\n")
        dst_config = SQLiteStorage.get_run_config(dst_proj, run_name)
        f.write(f"Dest config: {dst_config}\n")

        print("Verifying source...")
        src_logs = SQLiteStorage.get_logs(src_proj, run_name)
        f.write(f"Source logs: {len(src_logs)}\n")

        if success and len(dst_logs) == 1 and len(src_logs) == 0:
            f.write("SUCCESS: Run moved correctly.\n")
        else:
            f.write("FAILURE: Run move failed.\n")


if __name__ == "__main__":
    test_move_run()
