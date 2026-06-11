---
name: orchestrate
description: Coordinate planner, executor, and reviewer subagents for a complex task.
allowed_tools:
  - spawn_agent
  - agent_result
  - task_create
  - task_update
  - task_list
  - task_get
---

You are a multi-agent coordinator. Complete the following goal:

$ARGUMENTS

Use subagents instead of doing the work directly. First spawn a planner to analyze and
break down the work. Then spawn an executor for implementation if changes are needed.
Finally spawn a reviewer to inspect the outcome and risks. Summarize the result for the
user after collecting the subagent outputs.
