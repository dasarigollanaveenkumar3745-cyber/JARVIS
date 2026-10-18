
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# Keep the database in the main JARVIS project folder.
PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "jarvis.db"


def connect_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_db():
    with connect_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS ideas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_db()
    yield


app = FastAPI(
    title="JARVIS API",
    description="Personal assistant task and idea storage",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow the local VS Code Live Server frontend to connect.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


class TaskCreate(BaseModel):
    text: str = Field(min_length=1, max_length=200)


class TaskUpdate(BaseModel):
    done: bool


class IdeaCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)


def current_time():
    return datetime.now(timezone.utc).isoformat()


def task_dict(row):
    item = dict(row)
    item["done"] = bool(item["done"])
    return item


@app.get("/")
def home():
    return {"message": "JARVIS API is running"}


@app.get("/api/tasks")
def get_tasks():
    with connect_db() as db:
        rows = db.execute(
            "SELECT * FROM tasks ORDER BY id DESC"
        ).fetchall()
    return [task_dict(row) for row in rows]


@app.post("/api/tasks", status_code=201)
def create_task(task: TaskCreate):
    text = task.text.strip()
    if not text:
        raise HTTPException(400, "Task cannot be empty")

    with connect_db() as db:
        cursor = db.execute(
            "INSERT INTO tasks (text, done, created_at) "
            "VALUES (?, 0, ?)",
            (text, current_time()),
        )
        row = db.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()

    return task_dict(row)


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, update: TaskUpdate):
    with connect_db() as db:
        cursor = db.execute(
            "UPDATE tasks SET done = ? WHERE id = ?",
            (int(update.done), task_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Task not found")

        row = db.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

    return task_dict(row)


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int):
    with connect_db() as db:
        cursor = db.execute(
            "DELETE FROM tasks WHERE id = ?",
            (task_id,),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Task not found")

    return {"deleted": True, "id": task_id}


@app.get("/api/ideas")
def get_ideas():
    with connect_db() as db:
        rows = db.execute(
            "SELECT * FROM ideas ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/ideas", status_code=201)
def create_idea(idea: IdeaCreate):
    text = idea.text.strip()
    if not text:
        raise HTTPException(400, "Idea cannot be empty")

    with connect_db() as db:
        cursor = db.execute(
            "INSERT INTO ideas (text, created_at) VALUES (?, ?)",
            (text, current_time()),
        )
        row = db.execute(
            "SELECT * FROM ideas WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()

    return dict(row)


@app.delete("/api/ideas/{idea_id}")
def delete_idea(idea_id: int):
    with connect_db() as db:
        cursor = db.execute(
            "DELETE FROM ideas WHERE id = ?",
            (idea_id,),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Idea not found")

    return {"deleted": True, "id": idea_id}
