-- usage: psql -v run=<run_id> -v copies=<n> -f p11_seed_waiting.sql
SELECT set_config('p11.run', :'run', false), set_config('p11.copies', :'copies', false);

DO $$
DECLARE
  r orchestration.runs%ROWTYPE;
  a orchestration.approval_requests%ROWTYPE;
  p orchestration.proposals%ROWTYPE;
  nr text;
  na text;
  np text;
  i int;
BEGIN
  SELECT * INTO STRICT r FROM orchestration.runs WHERE run_id = current_setting('p11.run');
  SELECT * INTO STRICT a FROM orchestration.approval_requests WHERE run_id = r.run_id;
  SELECT * INTO STRICT p FROM orchestration.proposals WHERE proposal_id = a.proposal_id;
  FOR i IN 1 .. current_setting('p11.copies')::int LOOP
    nr := r.run_id || 'SEED' || lpad(i::text, 3, '0');
    na := a.approval_id || 'SEED' || lpad(i::text, 3, '0');
    np := p.proposal_id || 'SEED' || lpad(i::text, 3, '0');
    INSERT INTO orchestration.runs (run_id, use_case_id, idempotency_key, spec, started_by, started_at, updated_at,
                                    version, state, state_data, deadline_at, retried_by, carry_forward)
    VALUES (nr, r.use_case_id, r.idempotency_key || '-seed-' || i, r.spec, r.started_by,
            r.started_at - make_interval(mins => i), r.updated_at - make_interval(mins => i), r.version, r.state,
            replace(replace(replace(r.state_data::text, r.run_id, nr), a.approval_id, na), p.proposal_id, np)::jsonb,
            r.deadline_at, r.retried_by, r.carry_forward);
    INSERT INTO orchestration.proposals (proposal_id, run_id, actions, digest, created_at)
    VALUES (np, nr, p.actions, p.digest, p.created_at);
    INSERT INTO orchestration.approval_requests (approval_id, run_id, proposal_id, digest, policy, parties, created_at)
    VALUES (na, nr, np, a.digest, a.policy, a.parties, a.created_at);
    INSERT INTO monitoring.run_events (run_id, seq, ts, actor, kind, summary, data, dedupe_key)
    SELECT nr, e.seq, e.ts - make_interval(mins => i), e.actor, e.kind, e.summary,
           replace(replace(replace(e.data::text, r.run_id, nr), a.approval_id, na), p.proposal_id, np)::jsonb,
           replace(replace(e.dedupe_key, r.run_id, nr), a.approval_id, na)
    FROM monitoring.run_events e
    WHERE e.run_id = r.run_id;
  END LOOP;
END $$;

SELECT count(*) AS waiting_runs FROM orchestration.runs WHERE state = 'AwaitingApproval';
