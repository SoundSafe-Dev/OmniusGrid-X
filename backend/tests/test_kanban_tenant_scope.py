from uuid import uuid4


async def test_task_endpoints_are_scoped_to_authenticated_organization(
    client_a, client_b, admin_sync_url, seeded_orgs
):
    import psycopg2

    board_id = uuid4()
    column_id = uuid4()
    task_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO task_boards "
                "(id, organization_id, name, board_type, is_active) "
                "VALUES (%s, %s, 'Org A board', 'unified', TRUE)",
                (str(board_id), str(seeded_orgs["org_a_id"])),
            )
            cur.execute(
                "INSERT INTO task_columns "
                "(id, board_id, name, position, column_type) "
                "VALUES (%s, %s, 'Backlog', 0, 'backlog')",
                (str(column_id), str(board_id)),
            )
            cur.execute(
                "INSERT INTO tasks "
                "(id, board_id, column_id, title, task_type, priority, status, position, "
                "progress_percent, time_logged_minutes, tags, custom_fields, checklist_items, "
                "approval_status, completion_actions, completion_result, approved_by, "
                "created_by, completed_by, created_at, updated_at) "
                "VALUES (%s, %s, %s, 'Tenant secret', 'custom', 'medium', 'draft', 0, "
                "0, 0, '[]', '{}', '[]', 'pending', '{}', '{}', %s, %s, %s, NOW(), NOW())",
                (
                    str(task_id),
                    str(board_id),
                    str(column_id),
                    str(seeded_orgs["user_a_id"]),
                    str(seeded_orgs["user_a_id"]),
                    str(seeded_orgs["user_a_id"]),
                ),
            )
    finally:
        conn.close()

    own_list = await client_a.get(f"/api/v1/kanban/tasks?board_id={board_id}")
    foreign_list = await client_b.get(f"/api/v1/kanban/tasks?board_id={board_id}")
    own = await client_a.get(f"/api/v1/kanban/tasks/{task_id}")
    foreign = await client_b.get(f"/api/v1/kanban/tasks/{task_id}")
    foreign_create = await client_b.post(
        "/api/v1/kanban/tasks",
        json={
            "board_id": str(board_id),
            "column_id": str(column_id),
            "title": "Cross-tenant task",
            "task_type": "custom",
        },
    )
    foreign_update = await client_b.put(
        f"/api/v1/kanban/tasks/{task_id}",
        json={"title": "Changed by another tenant"},
    )
    foreign_delete = await client_b.delete(f"/api/v1/kanban/tasks/{task_id}")
    foreign_comments = await client_b.get(f"/api/v1/kanban/tasks/{task_id}/comments")
    foreign_time_logs = await client_b.get(f"/api/v1/kanban/tasks/{task_id}/time-logs")

    assert [item["id"] for item in own_list.json()] == [str(task_id)]
    assert foreign_list.json() == []
    assert own.status_code == 200
    assert foreign.status_code == 404
    assert foreign_create.status_code == 404
    assert foreign_update.status_code == 404
    assert foreign_delete.status_code == 404
    assert foreign_comments.status_code == 404
    assert foreign_time_logs.status_code == 404

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT title, status FROM tasks WHERE id = %s", (str(task_id),))
            assert cur.fetchone() == ("Tenant secret", "draft")
    finally:
        conn.close()
