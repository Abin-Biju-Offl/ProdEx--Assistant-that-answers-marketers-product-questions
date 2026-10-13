-- ProdEx dashboard queries (spec section 13, step 12).
--
-- Metabase connects as metabase_ro, which has SELECT on requests and ingest_runs only.
-- Paste each block into Metabase > + New > Native query.
--
-- Suggested dashboard layout:
--   Row 1  Top questions (1, 2, 3) | Unanswered rate (4) | Helpful % (5)
--   Row 2  Feedback trend (6) | Latency over time (7) | Ingest runs (8)
--   Row 3  Escalations (9) | Low-confidence answers (10)

-- 1. Top questions asked
SELECT question,
       count(*)                    AS times_asked,
       count(*) FILTER (WHERE answered) AS answered,
       round(100.0 * count(*) FILTER (WHERE answered) / count(*), 1) AS answered_pct,
       max(created_at)              AS last_asked
FROM requests
WHERE created_at > now() - interval '30 days'
GROUP BY question
ORDER BY times_asked DESC
LIMIT 20;

-- 2. Top questions asked and never answered (the documentation gap report)
SELECT question,
       count(*) AS times_asked,
       max(created_at) AS last_asked,
       count(*) FILTER (WHERE escalated) AS escalations
FROM requests
WHERE answered = false
  AND created_at > now() - interval '30 days'
GROUP BY question
ORDER BY times_asked DESC
LIMIT 25;

-- 3. Unanswered questions by escalation status
SELECT question,
       count(*) AS times_asked,
       bool_or(escalated) AS ever_escalated
FROM requests
WHERE answered = false
  AND created_at > now() - interval '7 days'
GROUP BY question
ORDER BY times_asked DESC;

-- 4. Answered vs not-answered rate over time
SELECT date_trunc('day', created_at) AS day,
       count(*) AS total,
       count(*) FILTER (WHERE answered) AS answered,
       round(100.0 * count(*) FILTER (WHERE answered) / count(*), 1) AS answered_pct
FROM requests
WHERE created_at > now() - interval '30 days'
GROUP BY 1
ORDER BY 1;

-- 5. Feedback summary
SELECT count(*) FILTER (WHERE feedback = 1)  AS helpful,
       count(*) FILTER (WHERE feedback = -1) AS not_helpful,
       round(100.0 * count(*) FILTER (WHERE feedback = 1)
             / nullif(count(*) FILTER (WHERE feedback IS NOT NULL), 0), 1) AS helpful_pct
FROM requests
WHERE created_at > now() - interval '30 days';

-- 6. Feedback trend over time
SELECT date_trunc('day', created_at) AS day,
       count(*) FILTER (WHERE feedback = 1)  AS helpful,
       count(*) FILTER (WHERE feedback = -1) AS not_helpful
FROM requests
WHERE feedback IS NOT NULL
  AND created_at > now() - interval '30 days'
GROUP BY 1
ORDER BY 1;

-- 7. Latency over time (p50 and p95)
SELECT date_trunc('hour', created_at) AS hour,
       count(*) AS requests,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms
FROM requests
WHERE created_at > now() - interval '7 days'
GROUP BY 1
ORDER BY 1;

-- 8. Ingest runs
SELECT started_at,
       repo,
       status,
       files_seen,
       files_indexed,
       files_skipped_secrets,
       chunks_written,
       chunks_deprecated,
       finished_at - started_at AS duration
FROM ingest_runs
ORDER BY id DESC
LIMIT 20;

-- 9. Escalations to engineering
SELECT id,
       created_at,
       question,
       answer,
       slack_user_id
FROM requests
WHERE escalated
ORDER BY created_at DESC
LIMIT 25;

-- 10. Low-confidence answers: answered, but nobody found them useful
SELECT id,
       created_at,
       question,
       top_score,
       feedback
FROM requests
WHERE answered = true
  AND (feedback = -1 OR top_score < 0.5)
  AND created_at > now() - interval '30 days'
ORDER BY top_score ASC NULLS LAST
LIMIT 25;

-- 11. Who is using it (IDs only - never names or emails)
SELECT slack_user_id,
       count(*) AS questions,
       max(created_at) AS last_asked,
       count(*) FILTER (WHERE answered) AS answered
FROM requests
WHERE created_at > now() - interval '30 days'
GROUP BY slack_user_id
ORDER BY questions DESC;