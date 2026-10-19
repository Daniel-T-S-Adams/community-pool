-- Operator-chosen offered challenges: one audited boolean control per
-- challenge, named offer:<challenge id>, beside the existing new-work pause.
-- The runtime roles keep their existing privileges on both tables.
ALTER TABLE runtime_controls DROP CONSTRAINT runtime_controls_name_check;
ALTER TABLE runtime_controls ADD CONSTRAINT runtime_controls_name_check
    CHECK (name = 'new_work_paused' OR name ~ '^offer:[a-z0-9_]{1,32}$');
ALTER TABLE runtime_control_events DROP CONSTRAINT runtime_control_events_name_check;
ALTER TABLE runtime_control_events ADD CONSTRAINT runtime_control_events_name_check
    CHECK (name = 'new_work_paused' OR name ~ '^offer:[a-z0-9_]{1,32}$');
