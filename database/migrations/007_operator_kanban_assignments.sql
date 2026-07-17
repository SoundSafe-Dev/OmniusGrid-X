-- Kanban API filters operator-role users to tasks where assigned_to = self OR NULL.
-- Seed data (005) assigned everything to the dev admin user, so omnius@omniusgrid.com saw an empty board.
-- This aligns mobile supervisor demo with tasks visible under that role.

UPDATE tasks t
SET assigned_to = '00000000-0000-0000-0000-000000000002'::uuid
WHERE t.board_id IN (
  SELECT id FROM task_boards
  WHERE organization_id = '00000000-0000-0000-0000-000000000001'::uuid
  AND is_active = TRUE
);

-- Keep a few unassigned so operator filter (NULL branch) is still exercised
UPDATE tasks t
SET assigned_to = NULL
WHERE t.id IN (
  SELECT t2.id
  FROM tasks t2
  JOIN task_boards b ON t2.board_id = b.id
  WHERE b.organization_id = '00000000-0000-0000-0000-000000000001'::uuid
  ORDER BY t2.created_at NULLS LAST
  LIMIT 2
);
