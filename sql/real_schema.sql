PRAGMA foreign_keys = ON;
CREATE TABLE import_manifest (run_id TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL, schema_version TEXT NOT NULL, created_at_utc TEXT NOT NULL, institution_count INTEGER NOT NULL, metric_count INTEGER NOT NULL, fact_count INTEGER NOT NULL, derived_dimension_count INTEGER NOT NULL);
CREATE TABLE institutions (institution_id TEXT PRIMARY KEY, institution_name TEXT NOT NULL);
CREATE TABLE metrics (metric_id TEXT PRIMARY KEY, metric_name TEXT NOT NULL, metric_definition TEXT NOT NULL, metric_unit TEXT NOT NULL, value_scale INTEGER NOT NULL CHECK(value_scale BETWEEN 0 AND 12));
CREATE TABLE metric_facts (data_date TEXT NOT NULL CHECK(length(data_date)=10 AND data_date=strftime('%Y-%m-%d', data_date)), metric_id TEXT NOT NULL, institution_id TEXT NOT NULL, metric_value_scaled INTEGER NOT NULL CHECK(typeof(metric_value_scaled)='integer'), PRIMARY KEY(institution_id, metric_id, data_date), FOREIGN KEY(metric_id) REFERENCES metrics(metric_id), FOREIGN KEY(institution_id) REFERENCES institutions(institution_id));
CREATE TABLE derived_dimensions (dimension_name TEXT PRIMARY KEY, definition TEXT NOT NULL);
CREATE INDEX idx_metric_facts_metric_date_value ON metric_facts(metric_id, data_date, metric_value_scaled);
CREATE INDEX idx_metric_facts_date_metric_institution ON metric_facts(data_date, metric_id, institution_id);
