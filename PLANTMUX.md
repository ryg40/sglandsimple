# PLAN: State-First Tmux Integration for Pi Coding Agent (PLANTMUX)

This document outlines the planning, architectural translation, and concrete implementation steps to migrate the dashboard extension from a standalone session/window model to a **State-First, Split-Pane Tmux Integration** closely matched after `oh-my-opencode`'s robust multi-pane layout manager.

---

## 1. Core Architectural Translation

| Feature | Old Dashboard Model | `oh-my-opencode` Model (State-First) |
| :--- | :--- | :--- |
| **Workspace Unit** | A separate standalone tmux session `pi-subagents` with separate tabs/windows. | Spawns panes *inside* the active user's viewport (the orchestrator/master pane). |
| **State Source of Truth** | Purely event-driven cache (`runs` Map). | **State-first queries**: Queries tmux list-panes to detect actual geometry prior to layout decisions. |
| **Logic/Decision** | Created a window per agent dynamically without spatial considerations. | Pure layout decider: Evaluates splits (Horizontal/Vertical) and handles capacity constraints (kills oldest to make room). |
| **Pane lifecycle** | Remains open forever until deleted or explicitly closed. | Automations are closed programmatically and replaced/resized via dynamic grid calculations on completion or idle timeout. |

---

## 2. Technical Decisions & Mechanics

### A. Inside vs. Outside Tmux Detection
The extension must carefully check the `process.env.TMUX` context to see if it is running inside an active tmux environment. If not, operations should gracefully degrade without throwing errors or starting background polling. 

### B. State-First Layout Loop (Query $\rightarrow$ Decide $\rightarrow$ Act)

```
   [Subagent Started]
          │
          ▼
┌──────────────────┐
│ QUERY TMUX STATE │ ─────► Capture exact window size and pane geometries
└──────────────────┘
          │
          ▼
┌──────────────────┐
│  DECIDE LAYOUT   │ ─────► Pure function computes grid column/row limits
└──────────────────┘
          │
          ▼
┌──────────────────┐
│  EXECUTE ACTION  │ ─────► Run 'tmux split-window' or 'respawn-pane -k'
└──────────────────┘
```

1. **Query**: List panes under the active window using format specifications:
   `tmux list-panes -F "#{pane_id}\t#{pane_width}\t#{pane_height}\t#{pane_left}\t#{pane_top}\t#{pane_active}"`
2. **Decide**: Calculate split availability using constraints:
   - Minimum pane width: `52` columns
   - Minimum pane height: `11` rows
   - Main Pane boundary ratio: `50%` of window width
3. **Act**:
   - Spawns tool session inside the newly created split pane.
   - Run `pi attach <serverUrl> --session <id>` inside the newly spawned pane, or use status tracking.

### C. Graceful Cleanup and Stability Polling
- We will implement an asynchronous polling loop checking `pi` active sessions.
- Clean up panes that host completed/idle workers. If a subagent completes, the pane should be reclaimed or closed gracefully.
- Prevent duplicate extensions loading inside nested/child sub-processes by checking:
  `if (process.env.PI_SUBAGENT_CHILD === "1") return;`

---

## 3. Concrete Implementation Plan

### Step 1: Geometry & Geometry helpers
Incorporate the pure mathematical helper functions for layouts (e.g. `computeGridPlan`, `calcCapacity`, `canSplitPane`).

### Step 2: Rewrite Tmux CLI Wrappers
Support selective targets and directional flags (`-h` / `-v`):
```typescript
function tmux(args: string[]): Promise<{ stdout: string; stderr: string; code: number }>
```

### Step 3: Implement `queryWindowState` & State Parsing
Write the parser to map standard stdout output from `list-panes` into a structured state object detailing borders, coordinates, active panes, and the identified primary orchestrator pane.

### Step 4: Splitting & Execution Actions
Implement `spawnTmuxPane` and `closeTmuxPane`.

---

This plan establishes the foundation to transform the tmux workspace into a parallel multi-pane cockpit. All changes will be developed inside the global extensions folder of the Pi coding agent environment.
