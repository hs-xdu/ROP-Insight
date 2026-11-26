-- P6-A schema v1. File publication is intentionally not implemented in this stage.
CREATE TABLE cases (
 case_id TEXT NOT NULL PRIMARY KEY CHECK (length(case_id)=36 AND substr(case_id,9,1)='-' AND substr(case_id,14,1)='-' AND substr(case_id,19,1)='-' AND substr(case_id,24,1)='-' AND length(replace(case_id,'-',''))=32 AND replace(case_id,'-','') NOT GLOB '*[^0-9a-f]*'), case_code TEXT NOT NULL CHECK(length(case_code) BETWEEN 1 AND 64 AND case_code NOT GLOB '*[^A-Za-z0-9_-]*' AND substr(case_code,1,1) GLOB '[A-Za-z0-9]'), case_code_key TEXT NOT NULL CHECK(case_code_key=lower(case_code)),
 current_revision_id TEXT NOT NULL  CHECK (length(current_revision_id)=36 AND substr(current_revision_id,9,1)='-' AND substr(current_revision_id,14,1)='-' AND substr(current_revision_id,19,1)='-' AND substr(current_revision_id,24,1)='-' AND length(replace(current_revision_id,'-',''))=32 AND replace(current_revision_id,'-','') NOT GLOB '*[^0-9a-f]*'), created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT,
 UNIQUE(case_code_key),
 FOREIGN KEY(case_id,current_revision_id) REFERENCES case_revisions(case_id,revision_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE case_revisions (
 revision_id TEXT NOT NULL PRIMARY KEY CHECK (length(revision_id)=36 AND substr(revision_id,9,1)='-' AND substr(revision_id,14,1)='-' AND substr(revision_id,19,1)='-' AND substr(revision_id,24,1)='-' AND length(replace(revision_id,'-',''))=32 AND replace(revision_id,'-','') NOT GLOB '*[^0-9a-f]*'), case_id TEXT NOT NULL  CHECK (length(case_id)=36 AND substr(case_id,9,1)='-' AND substr(case_id,14,1)='-' AND substr(case_id,19,1)='-' AND substr(case_id,24,1)='-' AND length(replace(case_id,'-',''))=32 AND replace(case_id,'-','') NOT GLOB '*[^0-9a-f]*'), previous_revision_id TEXT,
 case_code TEXT NOT NULL CHECK(length(case_code) BETWEEN 1 AND 64 AND case_code NOT GLOB '*[^A-Za-z0-9_-]*' AND substr(case_code,1,1) GLOB '[A-Za-z0-9]'), case_code_key TEXT NOT NULL CHECK(case_code_key=lower(case_code)), notes TEXT NOT NULL DEFAULT '' CHECK(length(notes)<=2000),
 default_eye TEXT CHECK(default_eye IS NULL OR default_eye IN ('left','right','unspecified')),
 default_exam_date TEXT, created_at TEXT NOT NULL,
 CHECK(previous_revision_id IS NULL OR previous_revision_id<>revision_id), UNIQUE(case_id,revision_id),
 FOREIGN KEY(case_id) REFERENCES cases(case_id) ON DELETE RESTRICT,
 FOREIGN KEY(case_id,previous_revision_id) REFERENCES case_revisions(case_id,revision_id) ON DELETE RESTRICT
);
CREATE TABLE images (
 image_id TEXT NOT NULL PRIMARY KEY CHECK (length(image_id)=36 AND substr(image_id,9,1)='-' AND substr(image_id,14,1)='-' AND substr(image_id,19,1)='-' AND substr(image_id,24,1)='-' AND length(replace(image_id,'-',''))=32 AND replace(image_id,'-','') NOT GLOB '*[^0-9a-f]*'), case_id TEXT NOT NULL  CHECK (length(case_id)=36 AND substr(case_id,9,1)='-' AND substr(case_id,14,1)='-' AND substr(case_id,19,1)='-' AND substr(case_id,24,1)='-' AND length(replace(case_id,'-',''))=32 AND replace(case_id,'-','') NOT GLOB '*[^0-9a-f]*'), case_revision_id TEXT NOT NULL  CHECK (length(case_revision_id)=36 AND substr(case_revision_id,9,1)='-' AND substr(case_revision_id,14,1)='-' AND substr(case_revision_id,19,1)='-' AND substr(case_revision_id,24,1)='-' AND length(replace(case_revision_id,'-',''))=32 AND replace(case_revision_id,'-','') NOT GLOB '*[^0-9a-f]*'),
 eye TEXT NOT NULL CHECK(eye IN ('left','right','unspecified')), exam_date TEXT,
 original_filename TEXT NOT NULL CHECK(length(original_filename)>0 AND instr(original_filename,'/')=0 AND instr(original_filename,char(92))=0),
 managed_relpath TEXT UNIQUE CHECK (managed_relpath IS NULL OR (length(managed_relpath)>0 AND substr(managed_relpath,1,1)<>'/' AND instr(managed_relpath,char(92))=0 AND instr(managed_relpath,':')=0 AND instr(managed_relpath,'//')=0 AND ('/'||managed_relpath||'/') NOT LIKE '%/../%' AND ('/'||managed_relpath||'/') NOT LIKE '%/./%' AND substr(managed_relpath,-1)<>'/')), width INTEGER CHECK(width IS NULL OR (typeof(width)='integer' AND width>0)),
 height INTEGER CHECK(height IS NULL OR (typeof(height)='integer' AND height>0)),
 format TEXT CHECK(format IS NULL OR format IN ('PNG','JPEG')),
 file_sha256 TEXT CHECK (file_sha256 IS NULL OR (length(file_sha256)=64 AND file_sha256 NOT GLOB '*[^0-9a-f]*')), rgb_pixel_sha256 TEXT CHECK (rgb_pixel_sha256 IS NULL OR (length(rgb_pixel_sha256)=64 AND rgb_pixel_sha256 NOT GLOB '*[^0-9a-f]*')), imported_at TEXT NOT NULL, save_state TEXT NOT NULL DEFAULT 'pending' CHECK(save_state IN ('pending','saving','ready','write_failed')), integrity_state TEXT NOT NULL DEFAULT 'unchecked' CHECK(integrity_state IN ('unchecked','valid','missing','corrupt')),
 operation_id TEXT NOT NULL UNIQUE CHECK (length(operation_id)=36 AND substr(operation_id,9,1)='-' AND substr(operation_id,14,1)='-' AND substr(operation_id,19,1)='-' AND substr(operation_id,24,1)='-' AND length(replace(operation_id,'-',''))=32 AND replace(operation_id,'-','') NOT GLOB '*[^0-9a-f]*'), failure_code TEXT, failure_message TEXT, last_verified_at TEXT,
 UNIQUE(image_id,case_id), FOREIGN KEY(case_id) REFERENCES cases(case_id) ON DELETE RESTRICT,
 FOREIGN KEY(case_id,case_revision_id) REFERENCES case_revisions(case_id,revision_id) ON DELETE RESTRICT,
 CHECK(save_state<>'ready' OR (managed_relpath IS NOT NULL AND width IS NOT NULL AND height IS NOT NULL AND format IS NOT NULL AND file_sha256 IS NOT NULL AND rgb_pixel_sha256 IS NOT NULL))
);
CREATE TABLE analysis_runs (
 run_id TEXT NOT NULL PRIMARY KEY CHECK (length(run_id)=36 AND substr(run_id,9,1)='-' AND substr(run_id,14,1)='-' AND substr(run_id,19,1)='-' AND substr(run_id,24,1)='-' AND length(replace(run_id,'-',''))=32 AND replace(run_id,'-','') NOT GLOB '*[^0-9a-f]*'), case_id TEXT NOT NULL  CHECK (length(case_id)=36 AND substr(case_id,9,1)='-' AND substr(case_id,14,1)='-' AND substr(case_id,19,1)='-' AND substr(case_id,24,1)='-' AND length(replace(case_id,'-',''))=32 AND replace(case_id,'-','') NOT GLOB '*[^0-9a-f]*'), image_id TEXT NOT NULL  CHECK (length(image_id)=36 AND substr(image_id,9,1)='-' AND substr(image_id,14,1)='-' AND substr(image_id,19,1)='-' AND substr(image_id,24,1)='-' AND length(replace(image_id,'-',''))=32 AND replace(image_id,'-','') NOT GLOB '*[^0-9a-f]*'), case_revision_id TEXT NOT NULL  CHECK (length(case_revision_id)=36 AND substr(case_revision_id,9,1)='-' AND substr(case_revision_id,14,1)='-' AND substr(case_revision_id,19,1)='-' AND substr(case_revision_id,24,1)='-' AND length(replace(case_revision_id,'-',''))=32 AND replace(case_revision_id,'-','') NOT GLOB '*[^0-9a-f]*'),
 source_image_id TEXT NOT NULL  CHECK (length(source_image_id)=36 AND substr(source_image_id,9,1)='-' AND substr(source_image_id,14,1)='-' AND substr(source_image_id,19,1)='-' AND substr(source_image_id,24,1)='-' AND length(replace(source_image_id,'-',''))=32 AND replace(source_image_id,'-','') NOT GLOB '*[^0-9a-f]*'), eye_snapshot TEXT NOT NULL CHECK(eye_snapshot IN ('left','right','unspecified')), exam_date_snapshot TEXT,
 association_snapshot_json TEXT NOT NULL CHECK(json_valid(association_snapshot_json) AND json_type(association_snapshot_json)='object'),
 started_at TEXT NOT NULL, finished_at TEXT,
 analysis_status TEXT NOT NULL CHECK(analysis_status IN ('running','success','partial_success','failed','cancelled')),
 module_states_json TEXT NOT NULL CHECK(json_valid(module_states_json) AND json_type(module_states_json)='object'),
 analysis_error_code TEXT, analysis_error_message TEXT, result_relpath TEXT  CHECK (result_relpath IS NULL OR (length(result_relpath)>0 AND substr(result_relpath,1,1)<>'/' AND instr(result_relpath,char(92))=0 AND instr(result_relpath,':')=0 AND instr(result_relpath,'//')=0 AND ('/'||result_relpath||'/') NOT LIKE '%/../%' AND ('/'||result_relpath||'/') NOT LIKE '%/./%' AND substr(result_relpath,-1)<>'/')), result_sha256 TEXT CHECK (result_sha256 IS NULL OR (length(result_sha256)=64 AND result_sha256 NOT GLOB '*[^0-9a-f]*')),
 result_kind TEXT CHECK(result_kind IS NULL OR result_kind IN ('p4_bundle','terminal_record')),
 run_manifest_relpath TEXT  CHECK (run_manifest_relpath IS NULL OR (length(run_manifest_relpath)>0 AND substr(run_manifest_relpath,1,1)<>'/' AND instr(run_manifest_relpath,char(92))=0 AND instr(run_manifest_relpath,':')=0 AND instr(run_manifest_relpath,'//')=0 AND ('/'||run_manifest_relpath||'/') NOT LIKE '%/../%' AND ('/'||run_manifest_relpath||'/') NOT LIKE '%/./%' AND substr(run_manifest_relpath,-1)<>'/')), run_manifest_sha256 TEXT CHECK (run_manifest_sha256 IS NULL OR (length(run_manifest_sha256)=64 AND run_manifest_sha256 NOT GLOB '*[^0-9a-f]*')), source_snapshot_sha256 TEXT CHECK (source_snapshot_sha256 IS NULL OR (length(source_snapshot_sha256)=64 AND source_snapshot_sha256 NOT GLOB '*[^0-9a-f]*')),
 a6_stage TEXT CHECK(a6_stage IS NULL OR a6_stage IN ('Normal','Stage 1','Stage 2','Stage 3')), save_state TEXT NOT NULL DEFAULT 'pending' CHECK(save_state IN ('pending','saving','ready','write_failed')), integrity_state TEXT NOT NULL DEFAULT 'unchecked' CHECK(integrity_state IN ('unchecked','valid','missing','corrupt')),
 operation_id TEXT NOT NULL UNIQUE CHECK (length(operation_id)=36 AND substr(operation_id,9,1)='-' AND substr(operation_id,14,1)='-' AND substr(operation_id,19,1)='-' AND substr(operation_id,24,1)='-' AND length(replace(operation_id,'-',''))=32 AND replace(operation_id,'-','') NOT GLOB '*[^0-9a-f]*'), save_error_code TEXT, save_error_message TEXT,
 recovery_state TEXT NOT NULL DEFAULT 'none' CHECK(recovery_state IN ('none','review_required')), last_verified_at TEXT,
 UNIQUE(run_id,image_id), FOREIGN KEY(image_id,case_id) REFERENCES images(image_id,case_id) ON DELETE RESTRICT,
 FOREIGN KEY(case_id,case_revision_id) REFERENCES case_revisions(case_id,revision_id) ON DELETE RESTRICT,
 CHECK(save_state<>'ready' OR (analysis_status<>'running' AND finished_at IS NOT NULL AND result_relpath IS NOT NULL AND result_sha256 IS NOT NULL AND run_manifest_relpath IS NOT NULL AND run_manifest_sha256 IS NOT NULL AND result_kind IS NOT NULL)),
 CHECK(save_state<>'ready' OR analysis_status NOT IN ('success','partial_success') OR result_kind='p4_bundle')
);
CREATE TABLE artifacts (
 artifact_id TEXT NOT NULL PRIMARY KEY CHECK (length(artifact_id)=36 AND substr(artifact_id,9,1)='-' AND substr(artifact_id,14,1)='-' AND substr(artifact_id,19,1)='-' AND substr(artifact_id,24,1)='-' AND length(replace(artifact_id,'-',''))=32 AND replace(artifact_id,'-','') NOT GLOB '*[^0-9a-f]*'), image_id TEXT NOT NULL  CHECK (length(image_id)=36 AND substr(image_id,9,1)='-' AND substr(image_id,14,1)='-' AND substr(image_id,19,1)='-' AND substr(image_id,24,1)='-' AND length(replace(image_id,'-',''))=32 AND replace(image_id,'-','') NOT GLOB '*[^0-9a-f]*'), run_id TEXT, report_id TEXT,
 artifact_kind TEXT NOT NULL CHECK(artifact_kind IN ('original_image','input_ridge','ridge_mask','vessel_mask','overlay','result_json','run_manifest','report_json','report_pdf','report_summary_text','report_detail_text','report_html','report_manifest','case_snapshot','image_manifest')),
 source_kind TEXT NOT NULL CHECK(source_kind IN ('imported','generated','legacy_import')),
 relpath TEXT UNIQUE CHECK (relpath IS NULL OR (length(relpath)>0 AND substr(relpath,1,1)<>'/' AND instr(relpath,char(92))=0 AND instr(relpath,':')=0 AND instr(relpath,'//')=0 AND ('/'||relpath||'/') NOT LIKE '%/../%' AND ('/'||relpath||'/') NOT LIKE '%/./%' AND substr(relpath,-1)<>'/')), sha256 TEXT CHECK (sha256 IS NULL OR (length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*')), byte_size INTEGER CHECK(byte_size IS NULL OR (typeof(byte_size)='integer' AND byte_size>=0)),
 schema_version TEXT, template_version TEXT, save_state TEXT NOT NULL DEFAULT 'pending' CHECK(save_state IN ('pending','saving','ready','write_failed')), integrity_state TEXT NOT NULL DEFAULT 'unchecked' CHECK(integrity_state IN ('unchecked','valid','missing','corrupt')), operation_id TEXT NOT NULL  CHECK (length(operation_id)=36 AND substr(operation_id,9,1)='-' AND substr(operation_id,14,1)='-' AND substr(operation_id,19,1)='-' AND substr(operation_id,24,1)='-' AND length(replace(operation_id,'-',''))=32 AND replace(operation_id,'-','') NOT GLOB '*[^0-9a-f]*'),
 failure_code TEXT, failure_message TEXT, created_at TEXT NOT NULL, last_verified_at TEXT,
 FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE RESTRICT,
 FOREIGN KEY(run_id,image_id) REFERENCES analysis_runs(run_id,image_id) ON DELETE RESTRICT,
 CHECK(report_id IS NULL OR run_id IS NOT NULL),
 CHECK(artifact_kind IN ('original_image','image_manifest') OR run_id IS NOT NULL),
 CHECK(artifact_kind NOT LIKE 'report_%' OR report_id IS NOT NULL),
 CHECK(save_state<>'ready' OR (relpath IS NOT NULL AND sha256 IS NOT NULL AND byte_size IS NOT NULL))
);
CREATE INDEX images_case_date ON images(case_id,exam_date);
CREATE INDEX images_hash ON images(file_sha256);
CREATE INDEX runs_case_started ON analysis_runs(case_id,started_at);
CREATE INDEX runs_image_started ON analysis_runs(image_id,started_at);
CREATE INDEX runs_status ON analysis_runs(analysis_status);
CREATE INDEX runs_stage ON analysis_runs(a6_stage);
CREATE UNIQUE INDEX report_kind_unique ON artifacts(report_id,artifact_kind) WHERE report_id IS NOT NULL;
CREATE INDEX artifacts_run ON artifacts(run_id);
CREATE INDEX artifacts_operation ON artifacts(operation_id);
CREATE TRIGGER revisions_no_update BEFORE UPDATE ON case_revisions BEGIN
 SELECT RAISE(ABORT,'case revisions are immutable');
END;
CREATE TRIGGER revisions_no_delete BEFORE DELETE ON case_revisions BEGIN
 SELECT RAISE(ABORT,'case revisions are immutable');
END;
PRAGMA user_version=1;
