CREATE TABLE runs (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	name TEXT NOT NULL UNIQUE,
	group_name TEXT,
	created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_runs_name ON runs(name);

INSERT INTO runs
(name, created_at)
SELECT run_name, MIN(timestamp)
FROM metrics 
GROUP BY run_name;

ALTER TABLE metrics
ADD COLUMN run_id INTEGER NOT NULL REFERENCES runs(id);

UPDATE metrics
SET run_id = (
	SELECT id FROM runs
	WHERE runs.name = metrics.run_name
);

CREATE TABLE metrics_temp (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	run_id INTEGER NOT NULL,
	step INTEGER NOT NULL,
	metrics TEXT NOT NULL,
	timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
	FOREIGN KEY (run_id) REFERENCES runs(id)
);

INSERT INTO metrics_temp 
(id, run_id, step, metrics, timestamp)
SELECT id, run_id, step, metrics, timestamp
FROM metrics;

DROP TABLE metrics;
ALTER TABLE metrics_temp RENAME TO metrics;
CREATE INDEX idx_metrics_run_id_step ON metrics(run_id, step);