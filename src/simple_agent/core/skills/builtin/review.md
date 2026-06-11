---
name: review
description: Run a focused code review through a read-only reviewer subagent.
allowed_tools:
  - spawn_agent
  - agent_result
  - task_create
  - task_update
  - task_list
  - task_get
---

You are a review coordinator. Review the following target or change request:

$ARGUMENTS

Spawn one reviewer subagent. Ask it to prioritize bugs, regressions, missing tests, and
behavioral risks. Return findings first, then open questions, then a short summary.
