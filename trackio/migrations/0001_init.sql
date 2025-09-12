CREATE TABLE IF NOT EXISTS metrics (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	timestamp TEXT NOT NULL,
	run_name TEXT NOT NULL,
	step INTEGER NOT NULL,
	metrics TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metrics_run_step
ON metrics(run_name, step);