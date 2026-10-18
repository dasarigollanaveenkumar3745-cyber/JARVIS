
from datetime import date, datetime, timedelta
from pathlib import Path
import sqlite3
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from assistant.router import process_message

# --------------------------------------------------
# Configuration
# --------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "jarvis.db"

app = FastAPI(
    title="JARVIS Personal Assistant API",
    version="0.2.0",
    description="Tasks, projects, notes, and personal planning.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now():
    return datetime.now().isoformat(timespec="seconds")


def row_dict(row):
    return dict(row) if row is not None else None


def require_project(conn, project_id):
    if project_id is not None:
        result = conn.execute(
            "SELECT id FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()

        if result is None:
            raise HTTPException(status_code=404, detail="Project not found")


# --------------------------------------------------
# Safe database initialization and migration
# --------------------------------------------------

def initialize_database():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS ideas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # Add new task fields without deleting existing task data.
        task_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
        }

        migrations = {
            "priority": "TEXT NOT NULL DEFAULT 'medium'",
            "due_date": "TEXT",
            "estimated_minutes": "INTEGER",
            "details": "TEXT",
            "project_id": "INTEGER",
            "updated_at": "TEXT",
        }

        for column, definition in migrations.items():
            if column not in task_columns:
                conn.execute(
                    f"ALTER TABLE tasks ADD COLUMN {column} {definition}"
                )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                goal TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                deadline TEXT,
                next_action TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                project_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_due_date
            ON tasks(due_date)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_project_id
            ON tasks(project_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_notes_project_id
            ON notes(project_id)
        """)


initialize_database()


# --------------------------------------------------
# Request models
# --------------------------------------------------

Priority = Literal["low", "medium", "high", "urgent"]
ProjectStatus = Literal["active", "paused", "completed", "archived"]


class TaskCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    priority: Priority = "medium"
    due_date: Optional[str] = None
    estimated_minutes: Optional[int] = Field(default=None, ge=1, le=100000)
    details: Optional[str] = None
    project_id: Optional[int] = None


class TaskUpdate(BaseModel):
    text: Optional[str] = Field(default=None, min_length=1, max_length=500)
    done: Optional[bool] = None
    priority: Optional[Priority] = None
    due_date: Optional[str] = None
    estimated_minutes: Optional[int] = Field(default=None, ge=1, le=100000)
    details: Optional[str] = None
    project_id: Optional[int] = None


class IdeaCreate(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    goal: Optional[str] = None
    status: ProjectStatus = "active"
    deadline: Optional[str] = None
    next_action: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    goal: Optional[str] = None
    status: Optional[ProjectStatus] = None
    deadline: Optional[str] = None
    next_action: Optional[str] = None


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = ""
    project_id: Optional[int] = None


class NoteUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    content: Optional[str] = None
    project_id: Optional[int] = None


def validate_date(value, field_name):
    if value is None or value == "":
        return None

    try:
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must use YYYY-MM-DD format",
        )


# --------------------------------------------------
# General
# --------------------------------------------------

@app.get("/")
def home():
    return {
        "app": "JARVIS Personal Assistant",
        "version": "0.2.0",
        "database": str(DB_PATH),
        "status": "running",
    }


@app.get("/api/health")
def health():
    with get_connection() as conn:
        conn.execute("SELECT 1").fetchone()

    return {"status": "healthy", "database": "connected"}


# --------------------------------------------------
# Tasks
# --------------------------------------------------

@app.get("/api/tasks")
def get_tasks(
    project_id: Optional[int] = None,
    include_completed: bool = True,
):
    query = """
        SELECT tasks.*, projects.name AS project_name
        FROM tasks
        LEFT JOIN projects ON projects.id = tasks.project_id
        WHERE 1 = 1
    """
    params = []

    if project_id is not None:
        query += " AND tasks.project_id = ?"
        params.append(project_id)

    if not include_completed:
        query += " AND tasks.done = 0"

    query += """
        ORDER BY
            CASE tasks.done WHEN 0 THEN 0 ELSE 1 END,
            CASE tasks.priority
                WHEN 'urgent' THEN 0
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                ELSE 3
            END,
            tasks.due_date IS NULL,
            tasks.due_date,
            tasks.id DESC
    """

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return [row_dict(row) for row in rows]


@app.post("/api/tasks", status_code=201)
def create_task(task: TaskCreate):
    data = task.model_dump()
    data["text"] = data["text"].strip()

    if not data["text"]:
        raise HTTPException(status_code=422, detail="Task text cannot be blank")

    data["due_date"] = validate_date(data["due_date"], "due_date")
    timestamp = now()

    with get_connection() as conn:
        require_project(conn, data["project_id"])

        cursor = conn.execute("""
            INSERT INTO tasks (
                text, done, created_at, priority, due_date,
                estimated_minutes, details, project_id, updated_at
            )
            VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["text"],
            timestamp,
            data["priority"],
            data["due_date"],
            data["estimated_minutes"],
            data["details"],
            data["project_id"],
            timestamp,
        ))

        task_id = cursor.lastrowid
        result = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()

    return row_dict(result)


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, update: TaskUpdate):
    data = update.model_dump(exclude_unset=True)

    if not data:
        raise HTTPException(status_code=400, detail="No fields supplied")

    if "text" in data and data["text"] is not None:
        data["text"] = data["text"].strip()
        if not data["text"]:
            raise HTTPException(status_code=422, detail="Task text cannot be blank")

    if "due_date" in data:
        data["due_date"] = validate_date(data["due_date"], "due_date")

    if "done" in data and data["done"] is not None:
        data["done"] = int(data["done"])

    allowed = {
        "text", "done", "priority", "due_date",
        "estimated_minutes", "details", "project_id",
    }

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()

        if existing is None:
            raise HTTPException(status_code=404, detail="Task not found")

        if "project_id" in data:
            require_project(conn, data["project_id"])

        assignments = [
            f"{column} = ?" for column in data if column in allowed
        ]
        values = [
            value for column, value in data.items() if column in allowed
        ]

        assignments.append("updated_at = ?")
        values.extend([now(), task_id])

        conn.execute(
            f"UPDATE tasks SET {', '.join(assignments)} WHERE id = ?",
            values,
        )

        result = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()

    return row_dict(result)


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int):
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found")

    return {"message": "Task deleted", "id": task_id}


# --------------------------------------------------
# Ideas
# --------------------------------------------------

@app.get("/api/ideas")
def get_ideas():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM ideas ORDER BY id DESC"
        ).fetchall()

    return [row_dict(row) for row in rows]


@app.post("/api/ideas", status_code=201)
def create_idea(idea: IdeaCreate):
    text = idea.text.strip()

    if not text:
        raise HTTPException(status_code=422, detail="Idea cannot be blank")

    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO ideas (text, created_at) VALUES (?, ?)",
            (text, now()),
        )
        result = conn.execute(
            "SELECT * FROM ideas WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()

    return row_dict(result)


@app.delete("/api/ideas/{idea_id}")
def delete_idea(idea_id: int):
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Idea not found")

    return {"message": "Idea deleted", "id": idea_id}


# --------------------------------------------------
# Projects
# --------------------------------------------------

@app.get("/api/projects")
def get_projects():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                projects.*,
                COUNT(tasks.id) AS total_tasks,
                COALESCE(SUM(
                    CASE WHEN tasks.done = 1 THEN 1 ELSE 0 END
                ), 0) AS completed_tasks
            FROM projects
            LEFT JOIN tasks ON tasks.project_id = projects.id
            GROUP BY projects.id
            ORDER BY projects.updated_at DESC, projects.id DESC
        """).fetchall()

    return [row_dict(row) for row in rows]


@app.post("/api/projects", status_code=201)
def create_project(project: ProjectCreate):
    data = project.model_dump()
    data["name"] = data["name"].strip()

    if not data["name"]:
        raise HTTPException(status_code=422, detail="Project name cannot be blank")

    data["deadline"] = validate_date(data["deadline"], "deadline")
    timestamp = now()

    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO projects (
                name, goal, status, deadline, next_action,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data["name"], data["goal"], data["status"],
            data["deadline"], data["next_action"],
            timestamp, timestamp,
        ))

        result = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()

    return row_dict(result)


@app.patch("/api/projects/{project_id}")
def update_project(project_id: int, update: ProjectUpdate):
    data = update.model_dump(exclude_unset=True)

    if not data:
        raise HTTPException(status_code=400, detail="No fields supplied")

    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
        if not data["name"]:
            raise HTTPException(status_code=422, detail="Project name cannot be blank")

    if "deadline" in data:
        data["deadline"] = validate_date(data["deadline"], "deadline")

    allowed = {"name", "goal", "status", "deadline", "next_action"}

    with get_connection() as conn:
        if conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone() is None:
            raise HTTPException(status_code=404, detail="Project not found")

        assignments = [
            f"{key} = ?" for key in data if key in allowed
        ]
        values = [value for key, value in data.items() if key in allowed]
        assignments.append("updated_at = ?")
        values.extend([now(), project_id])

        conn.execute(
            f"UPDATE projects SET {', '.join(assignments)} WHERE id = ?",
            values,
        )

        result = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()

    return row_dict(result)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int):
    with get_connection() as conn:
        if conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone() is None:
            raise HTTPException(status_code=404, detail="Project not found")

        # Keep tasks and notes; detach them from the deleted project.
        conn.execute(
            "UPDATE tasks SET project_id = NULL, updated_at = ? WHERE project_id = ?",
            (now(), project_id),
        )
        conn.execute(
            "UPDATE notes SET project_id = NULL, updated_at = ? WHERE project_id = ?",
            (now(), project_id),
        )
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    return {"message": "Project deleted; related tasks and notes were preserved"}


# --------------------------------------------------
# Notes
# --------------------------------------------------

@app.get("/api/notes")
def get_notes(
    project_id: Optional[int] = None,
    search: Optional[str] = Query(default=None, max_length=200),
):
    query = """
        SELECT notes.*, projects.name AS project_name
        FROM notes
        LEFT JOIN projects ON projects.id = notes.project_id
        WHERE 1 = 1
    """
    params = []

    if project_id is not None:
        query += " AND notes.project_id = ?"
        params.append(project_id)

    if search:
        query += " AND (notes.title LIKE ? OR notes.content LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term])

    query += " ORDER BY notes.updated_at DESC, notes.id DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return [row_dict(row) for row in rows]


@app.post("/api/notes", status_code=201)
def create_note(note: NoteCreate):
    data = note.model_dump()
    data["title"] = data["title"].strip()

    if not data["title"]:
        raise HTTPException(status_code=422, detail="Note title cannot be blank")

    timestamp = now()

    with get_connection() as conn:
        require_project(conn, data["project_id"])

        cursor = conn.execute("""
            INSERT INTO notes (
                title, content, project_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            data["title"], data["content"], data["project_id"],
            timestamp, timestamp,
        ))

        result = conn.execute(
            "SELECT * FROM notes WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()

    return row_dict(result)


@app.patch("/api/notes/{note_id}")
def update_note(note_id: int, update: NoteUpdate):
    data = update.model_dump(exclude_unset=True)

    if not data:
        raise HTTPException(status_code=400, detail="No fields supplied")

    if "title" in data and data["title"] is not None:
        data["title"] = data["title"].strip()
        if not data["title"]:
            raise HTTPException(status_code=422, detail="Note title cannot be blank")

    allowed = {"title", "content", "project_id"}

    with get_connection() as conn:
        if conn.execute(
            "SELECT id FROM notes WHERE id = ?", (note_id,)
        ).fetchone() is None:
            raise HTTPException(status_code=404, detail="Note not found")

        if "project_id" in data:
            require_project(conn, data["project_id"])

        assignments = [
            f"{key} = ?" for key in data if key in allowed
        ]
        values = [value for key, value in data.items() if key in allowed]
        assignments.append("updated_at = ?")
        values.extend([now(), note_id])

        conn.execute(
            f"UPDATE notes SET {', '.join(assignments)} WHERE id = ?",
            values,
        )

        result = conn.execute(
            "SELECT * FROM notes WHERE id = ?", (note_id,)
        ).fetchone()

    return row_dict(result)


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int):
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Note not found")

    return {"message": "Note deleted", "id": note_id}


# --------------------------------------------------
# Dashboard
# --------------------------------------------------

@app.get("/api/dashboard")
def get_dashboard():
    today = date.today()
    today_text = today.isoformat()
    next_week = (today + timedelta(days=7)).isoformat()

    with get_connection() as conn:
        unfinished = conn.execute("""
            SELECT tasks.*, projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE tasks.done = 0
            ORDER BY tasks.due_date IS NULL, tasks.due_date
        """).fetchall()

        project_rows = conn.execute("""
            SELECT
                projects.*,
                COUNT(tasks.id) AS total_tasks,
                COALESCE(SUM(
                    CASE WHEN tasks.done = 1 THEN 1 ELSE 0 END
                ), 0) AS completed_tasks
            FROM projects
            LEFT JOIN tasks ON tasks.project_id = projects.id
            WHERE projects.status = 'active'
            GROUP BY projects.id
            ORDER BY projects.deadline IS NULL, projects.deadline
        """).fetchall()

        total_tasks = conn.execute(
            "SELECT COUNT(*) FROM tasks"
        ).fetchone()[0]

        completed_tasks = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE done = 1"
        ).fetchone()[0]

        total_ideas = conn.execute(
            "SELECT COUNT(*) FROM ideas"
        ).fetchone()[0]

        total_notes = conn.execute(
            "SELECT COUNT(*) FROM notes"
        ).fetchone()[0]

    task_list = [row_dict(row) for row in unfinished]

    overdue = [
        task for task in task_list
        if task["due_date"] and task["due_date"] < today_text
    ]

    due_today = [
        task for task in task_list
        if task["due_date"] == today_text
    ]

    upcoming = [
        task for task in task_list
        if task["due_date"]
        and today_text < task["due_date"] <= next_week
    ]

    return {
        "date": today_text,
        "summary": {
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "open_tasks": total_tasks - completed_tasks,
            "overdue_tasks": len(overdue),
            "due_today": len(due_today),
            "upcoming_7_days": len(upcoming),
            "active_projects": len(project_rows),
            "total_ideas": total_ideas,
            "total_notes": total_notes,
        },
        "overdue": overdue,
        "due_today": due_today,
        "upcoming": upcoming,
        "active_projects": [row_dict(row) for row in project_rows],
    }
