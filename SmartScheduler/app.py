from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from pymongo import MongoClient
from dotenv import load_dotenv, find_dotenv
from flask_bcrypt import Bcrypt
from openai import OpenAI
import os
import json
from datetime import datetime, timedelta, time

# Load .env file
load_dotenv(find_dotenv(), override=True)

app = Flask(__name__)

# Load environment variables
MONGO_URI = os.getenv("MONGO_URI")
SECRET_KEY = os.getenv("SECRET_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize extensions
bcrypt = Bcrypt(app)
app.secret_key = SECRET_KEY

# Connect to MongoDB
client = MongoClient(MONGO_URI)
db = client["SmartSchedule"]
users_collection = db["users"]

# Initialize OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# === V7 SYSTEM PROMPT (Daily Check-in Updated) ===
SYSTEM_PROMPT = """
You are a 'Smart Study Scheduler' assistant. Your goal is to be a proactive, intelligent planner for the user.

**CORE RULES & DATE HANDLING (CRITICAL):**
1.  **Look for the Current Date:** On the user's first turn, you will receive a system message stating "CRITICAL: Today's date is [Date]". You MUST use this as the absolute, locked-in reference for all date math.
2.  **Relative Date Logic (Examples):**
    * **"This Week":** If "Today is Tuesday, Nov 4" and the user says "this Friday," you MUST use Nov 7.
    * **"Next Week":** If "Today is Tuesday, Nov 4" and the user says "next week Friday," you MUST use Nov 14.
    * **"Next Week" (Saturday):** If "Today is Tuesday, Nov 4" and the user says "next week Saturday," you MUST use Nov 15.
    * **Ambiguous/Nearest:** If "Today is Tuesday, Nov 4" and the user says "due Saturday," you MUST assume the *nearest future* Saturday, which is Nov 8.
3.  **Reject Explicit Past Dates:** If a user provides an explicit date that is in the past (e.g., "Add a task due yesterday"), you MUST NOT call any tool. Instead, respond directly: "Sorry, I can't add items for dates that have already passed. Please provide a future date."
4.  **Year Context:** You will be given the current year. Use it for all date calculations.
5.  **Freedom of Choice:** When saving or updating a task, the user can *optionally* provide a `priority` (low, medium, high) or a `duration_hours` (e.g., "3 hours"). If they provide these, pass them to the tool. If not, the planner will use smart defaults.

**YOUR PRIMARY LOGIC FLOW:**

1.  **ONBOARDING (Personalization Modal):**
    * The user will set their preferences (`awake_time`, `sleep_time`) and `study_windows` using a "Settings" modal.
    * You **DO NOT** need to ask for this information conversationally anymore.

2.  **THE "DAILY CHECK-IN" (CRITICAL):**
    * If the user's message is "trigger:daily_checkin", you MUST initiate the Daily Check-in.
    * Call `get_daily_plan()` to fetch what's scheduled for today.
    * Present the plan to the user: "Good morning! Your default plan for today is [Plan from get_daily_plan()]. How does your actual availability look today?"

3.  **HANDLING CHECK-IN RESPONSES (THE "HYBRID" LOGIC):**
    * **IF User says "Looks good!":** Respond with encouragement. No tools needed.
    * **IF User says "I have 2 hours, but no specific time":** (A "floating" commitment)
        * Call the `get_priority_list(hours=2)` tool.
        * Present this list: "Got it. No specific plan. Here is your priority task list for today, which should take about 2 hours: [List from tool]."
    * **IF User says "I only have 1 hour at lunch":** (A new, specific constraint)
        * You MUST parse this into a structured time (e.g., 12:00 to 13:00) and call `reschedule_day(time_blocks=[{"start_time": "12:00", "end_time": "13:00", "focus_level": "low"}])`.
        * Present the new plan: "No problem. [Response from tool, e.g., 'OK, I've re-planned your schedule...']"

4.  **DATA ENTRY (Your main job):**
    * If the user is not in a planning flow, just add/update data.
    * Use `save_class`, `save_task`, `update_task_details`, etc. as requested.
    * If a new task/test is added, call `run_planner_engine` *after* saving the item to update the plan.

5.  **PLAN GENERATION (The "Engine"):**
    * If the user asks "Can you make my plan?" or "Update my plan", call the `run_planner_engine()` tool.
"""

# === V8 TOOLS (Loop Fix) ===
tools = [
    {
        "type": "function",
        "function": {
            "name": "save_preference",
            "description": "Saves the user's awake and sleep time preferences.",
            "parameters": {
                "type": "object",
                "properties": {
                    "awake_time": {"type": "string", "description": "The user's wake-up time in HH:MM format."},
                    "sleep_time": {"type": "string", "description": "The user's sleep time in HH:MM format."},
                },
                "required": ["awake_time", "sleep_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_class",
            "description": "Saves a new class to the user's schedule.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "day": {"type": "string"},
                    "start_time": {"type": "string", "description": "Start time in HH:MM format"},
                    "end_time": {"type": "string", "description": "End time in HH:MM format"},
                },
                "required": ["subject", "day", "start_time", "end_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_task",
            "description": "Saves a new task, assignment, or project. User can optionally specify priority and duration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "task_type": {"type": "string", "enum": ["assignment", "project", "seatwork"]},
                    "deadline": {"type": "string", "description": "The deadline in YYYY-MM-DDTHH:MM:SS format"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"],
                                 "description": "Optional: User's priority for this task."},
                    "duration_hours": {"type": "number",
                                       "description": "Optional: How many hours the user estimates this task will take."}
                },
                "required": ["name", "task_type", "deadline"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_test",
            "description": "Saves a new quiz or exam. User can optionally specify priority and study duration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "test_type": {"type": "string", "enum": ["quiz", "exam"]},
                    "date": {"type": "string", "description": "The date of the test in YYYY-MM-DD format"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"],
                                 "description": "Optional: User's priority for studying."},
                    "duration_hours": {"type": "number",
                                       "description": "Optional: How many hours the user wants to study for this."}
                },
                "required": ["name", "test_type", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task_details",
            "description": "Updates an existing task or test. Can change its name, type, deadline, priority, or duration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "current_name": {"type": "string", "description": "The exact current name of the task or test."},
                    "new_name": {"type": "string", "description": "The new name (optional)."},
                    "new_task_type": {"type": "string", "enum": ["assignment", "project", "seatwork", "quiz", "exam"],
                                      "description": "The new type (optional)."},
                    "new_deadline": {"type": "string",
                                     "description": "The new deadline YYYY-MM-DDTHH:MM:SS (optional)."},
                    # === START OF V8 FIX: Added "top" to enum ===
                    "new_priority": {"type": "string", "enum": ["top", "high", "medium", "low"],
                                     "description": "Optional: The new priority."},
                    # === END OF V8 FIX ===
                    "new_duration_hours": {"type": "number", "description": "Optional: The new estimated duration."}
                },
                "required": ["current_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_class_schedule",
            "description": "Updates the day, start time, or end time of an *existing* class, identified by its subject name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string",
                                "description": "The subject name of the class to update (e.g., 'Math')."},
                    "new_day": {"type": "string", "description": "The new day for the class (e.g., 'Monday').",
                                "optional": True},
                    "new_start_time": {"type": "string", "description": "The new start time in HH:MM format.",
                                       "optional": True},
                    "new_end_time": {"type": "string", "description": "The new end time in HH:MM format.",
                                     "optional": True}
                },
                "required": ["subject"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_schedule_item",
            "description": "Deletes an *existing* class, task, or test from the user's schedule by its name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {"type": "string",
                                  "description": "The name or subject of the item to delete (e.g., 'Math', 'History Essay')."}
                },
                "required": ["item_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_study_windows",
            "description": "Saves the user's ideal weekly study windows, including focus level. This is their 'default' plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "windows": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "day": {"type": "string", "description": "e.g., Monday, Tuesday"},
                                "start_time": {"type": "string", "description": "HH:MM format"},
                                "end_time": {"type": "string", "description": "HH:MM format"},
                                "focus_level": {"type": "string", "enum": ["high", "medium", "low"]}
                            },
                            "required": ["day", "start_time", "end_time", "focus_level"]
                        }
                    }
                },
                "required": ["windows"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_daily_plan",
            "description": "Fetches the user's generated plan for today. Used during the 'Daily Check-in'.",
            "parameters": {"type": "object", "properties": {}}  # No parameters needed
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_priority_list",
            "description": "Generates a prioritized to-do list based on a user's floating time commitment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hours": {"type": "number", "description": "The number of hours the user can commit."}
                },
                "required": ["hours"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_day",
            "description": "Re-plans the *current day* based on a new, specific set of available time blocks. This OVERRIDES the user's default study windows for today only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_blocks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start_time": {"type": "string", "description": "HH:MM format"},
                                "end_time": {"type": "string", "description": "HH:MM format"},
                                "focus_level": {"type": "string", "enum": ["high", "medium", "low"],
                                                "description": "Optional focus."}
                            },
                            "required": ["start_time", "end_time"]
                        }
                    }
                },
                "required": ["time_blocks"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_planner_engine",
            "description": "Runs the full, multi-day smart planner to generate or update the 'generated_plan' based on all tasks, tests, and study windows. This is a heavy operation.",
            "parameters": {"type": "object", "properties": {}}  # No parameters needed
        }
    }
]


# ---------- AUTH ROUTES (Unchanged) ----------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if users_collection.find_one({"username": username}):
            return "Username already exists!"
        hashed_pw = bcrypt.generate_password_hash(password).decode("utf-8")

        users_collection.insert_one({
            "username": username, "password": hashed_pw,
            "schedule": [], "tasks": [], "tests": [],
            "preferences": {"awake_time": "07:00", "sleep_time": "23:00"},  # Default values
            "chat_history": [],
            "study_windows": [],
            "generated_plan": []
        })

        return redirect(url_for("login"))
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = users_collection.find_one({"username": username})
        if user and bcrypt.check_password_hash(user["password"], password):
            session["username"] = username
            users_collection.update_one(
                {"username": username},
                {"$set": {"chat_history": []}}
            )
            return redirect(url_for("index"))
        return "Invalid credentials!"
    return render_template("login.html")


@app.route("/logout")
def logout():
    if "username" in session:
        users_collection.update_one(
            {"username": session["username"]},
            {"$set": {"chat_history": []}}
        )
    session.pop("username", None)
    return redirect(url_for("login"))


# ---------- MAIN APP ROUTES (Chat and Schedule) ----------
@app.route("/")
def index():
    if "username" not in session:
        return redirect(url_for("login"))
    return render_template("index.html", username=session["username"])


@app.route("/save_personalization", methods=["POST"])
def save_personalization():
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401

    username = session["username"]
    data = request.json

    try:
        # 1. Save Preferences
        preferences = data.get("preferences", {})
        users_collection.update_one(
            {"username": username},
            {"$set": {"preferences": preferences}}
        )

        # 2. Save Study Windows
        windows = data.get("study_windows", [])
        save_study_windows_db(username, {"windows": windows})  # Use existing function

        # 3. Re-run the planner engine
        planner_response = run_planner_engine_db(username, {})

        if planner_response["status"] == "conflict":
            return jsonify({
                "reply": "Settings saved! But I found a scheduling conflict. Please choose which task to prioritize first:",
                "action": "show_priority_modal",
                "options": planner_response["options"]
            })
        else:
            return jsonify({"reply": f"Settings saved! {planner_response['message']}"})

    except Exception as e:
        print(f"Error in /save_personalization: {e}")
        return jsonify({"reply": "Sorry, there was an error saving your settings."}), 500


# --- This is our "ADD" function (Unchanged) ---
def update_user_data(username, data_type, data):
    if data_type == "class":
        users_collection.update_one({"username": username}, {"$push": {"schedule": data}})
    elif data_type == "task":
        users_collection.update_one({"username": username}, {"$push": {"tasks": data}})
    elif data_type == "test":
        # Convert test 'date' to a full 'deadline' for consistency
        data['deadline'] = f"{data['date']}T23:59:59"
        users_collection.update_one({"username": username}, {"$push": {"tests": data}})
    elif data_type == "preference":
        users_collection.update_one({"username": username}, {"$set": {"preferences": data}})
        return f"Got it! I've saved your awake time as {data['awake_time']} and sleep time as {data['sleep_time']}."

    return f"OK, I've added the new {data_type} to your schedule."


# --- This is our "UPDATE TASK" function (Unchanged) ---
def update_task_details_db(username, args):
    current_name = args.get("current_name")

    new_name = args.get("new_name")
    new_type = args.get("new_task_type")
    new_deadline = args.get("new_deadline")
    new_priority = args.get("new_priority")
    new_duration = args.get("new_duration_hours")

    updates = {}

    target_array = "tasks"
    task_search = users_collection.find_one({"username": username, "tasks.name": current_name})
    if not task_search:
        target_array = "tests"
        task_search = users_collection.find_one({"username": username, "tests.name": current_name})

    if not task_search:
        return f"Sorry, I couldn't find an item named '{current_name}' to update."

    if new_name:
        updates[f"{target_array}.$.name"] = new_name
    if new_type:
        # This logic handles renaming 'test_type' to 'task_type' if needed
        if target_array == "tests":
            updates[f"{target_array}.$.test_type"] = new_type
        else:
            updates[f"{target_array}.$.task_type"] = new_type
    if new_deadline:
        updates[f"{target_array}.$.deadline"] = new_deadline
    if new_priority:
        updates[f"{target_array}.$.priority"] = new_priority
    if new_duration:
        updates[f"{target_array}.$.duration_hours"] = new_duration

    if not updates:
        return "You didn't tell me what to update (name, type, deadline, priority, or duration)!"

    result = users_collection.update_one(
        {"username": username, f"{target_array}.name": current_name},
        {"$set": updates}
    )

    if result.modified_count == 0:
        return f"Sorry, I couldn't find an item named '{current_name}' to update."

    if new_name:
        users_collection.update_one(
            {"username": username},
            {"$set": {"generated_plan.$[elem].task": f"Work on {new_name}"}},
            array_filters=[{"elem.task": {"$regex": current_name, "$options": "i"}}]
        )

    return f"OK, I've updated the details for '{new_name or current_name}'."


# --- This is our "UPDATE CLASS" function (Unchanged) ---
def update_class_schedule_db(username, args):
    subject = args.get("subject")
    updates_to_make = {}
    if "new_day" in args:
        updates_to_make["schedule.$.day"] = args["new_day"]
    if "new_start_time" in args:
        updates_to_make["schedule.$.start_time"] = args["new_start_time"]
    if "new_end_time" in args:
        updates_to_make["schedule.$.end_time"] = args["new_end_time"]
    if not updates_to_make:
        return "Sorry, you need to provide what you want to change (the day, start time, or end time)."
    result = users_collection.update_one(
        {"username": username, "schedule.subject": subject},
        {"$set": updates_to_make}
    )
    if result.modified_count > 0:
        return f"OK, I've updated your '{subject}' class."
    else:
        return f"Sorry, I couldn't find a class with the subject '{subject}' to update."


# --- This is your NEW function (Unchanged) ---
def delete_schedule_item_db(username, args):
    item_name = args.get("item_name")

    result_class = users_collection.update_one(
        {"username": username},
        {"$pull": {"schedule": {"subject": item_name}}}
    )
    result_task = users_collection.update_one(
        {"username": username},
        {"$pull": {"tasks": {"name": item_name}}}
    )
    result_test = users_collection.update_one(
        {"username": username},
        {"$pull": {"tests": {"name": item_name}}}
    )
    result_plan = users_collection.update_one(
        {"username": username},
        {"$pull": {"generated_plan": {"task": {"$regex": item_name, "$options": "i"}}}}
    )
    if (result_class.modified_count > 0 or
            result_task.modified_count > 0 or
            result_test.modified_count > 0 or
            result_plan.modified_count > 0):
        return f"OK, I've deleted '{item_name}' and any related schedule blocks."
    else:
        return f"Sorry, I couldn't find an item named '{item_name}' to delete."


# --- Auto-cleanup function (Unchanged) ---
def auto_cleanup_past_items(username):
    try:
        now = datetime.now()
        now_iso = now.isoformat()
        today_date_str = now.strftime("%Y-%m-%d")

        users_collection.update_one(
            {"username": username},
            {
                "$pull": {
                    "tasks": {"deadline": {"$lt": now_iso}},
                    "tests": {"date": {"$lt": today_date_str}},
                    "generated_plan": {"date": {"$lt": today_date_str}}
                }
            }
        )
        print(f"Auto-cleanup completed for user {username}")
    except Exception as e:
        print(f"Error during auto-cleanup for {username}: {e}")


# --- NEW PLANNING FUNCTIONS (reschedule_day_db Updated) ---

def save_study_windows_db(username, args):
    windows = args.get("windows", [])
    users_collection.update_one(
        {"username": username},
        {"$set": {"study_windows": windows}}
    )
    return "Study windows saved."


def get_daily_plan_db(username, args):
    user_data = users_collection.find_one({"username": username})
    generated_plan = user_data.get("generated_plan", [])
    today_str = datetime.now().strftime("%Y-%m-%d")
    todays_plan_items = [item for item in generated_plan if item['date'] == today_str]

    if not todays_plan_items:
        return "You have no study blocks scheduled for today. Enjoy the break or ask me to plan something!"

    plan_summary = ", ".join(
        f"{item['task']} from {item['start_time']} to {item['end_time']}" for item in todays_plan_items)
    return f"Your default plan for today is: {plan_summary}."


def get_priority_list_db(username, args):
    # This function is now a STUB. The main logic is in run_planner_engine.
    # We will build this out later using the same V4 logic.
    hours = args.get("hours", 0)
    user_data = users_collection.find_one({"username": username})
    tasks = user_data.get("tasks", [])

    if not tasks:
        return "You have no pending tasks!"

    try:
        tasks.sort(key=lambda x: x['deadline'])
    except Exception as e:
        print(f"Could not sort tasks: {e}")

    priority_list_str = "Here is your priority list: " + ", ".join([t['name'] for t in tasks[:2]])
    return priority_list_str


def reschedule_day_db(username, args):
    """
    This function is a pass-through. It takes the structured time blocks
    from the AI and passes them to the Master Planner as a daily override.
    """
    # 1. Get the new time blocks from the AI
    time_blocks = args.get("time_blocks", [])

    # 2. Prepare the override
    today_str = datetime.now().strftime("%Y-%m-%d")
    daily_overrides = {
        today_str: time_blocks
    }

    # 3. Call the Master Planner, passing in this new override
    planner_args = {
        "daily_overrides": daily_overrides,
        "force_auto": True
    }
    planner_response = run_planner_engine_db(username, planner_args)

    # 4. Return the result to the user
    return f"OK, I've re-planned your schedule for today. {planner_response['message']}"


# === START OF V8 PLANNER ENGINE (Loop Fix) ===
# Define our default "heuristic" values
DEFAULT_PRIORITY_MAP = {
    "top": 0,  # <-- V8 FIX: Added "top" to break loops
    "high": 1, "medium": 2, "low": 3,
    # Fallback scores based on type
    "exam": 1, "project": 2, "quiz": 3, "assignment": 4, "seatwork": 5
}
DEFAULT_DURATION_MAP = {
    # Fallback durations in 1-hour blocks
    "exam": 3, "project": 5, "quiz": 1, "assignment": 2, "seatwork": 1
}
DAY_OF_WEEK_MAP = {
    0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
    4: "Friday", 5: "Saturday", 6: "Sunday"
}


def _time_to_minutes(time_str):
    """Helper to convert HH:MM string to minutes since midnight."""
    try:
        t = time.fromisoformat(time_str)
        return t.hour * 60 + t.minute
    except ValueError:
        return 0


def run_planner_engine_db(username, args):
    """
    This is the V8 "Master Planner" engine.
    """
    print("--- Running V8 Planner Engine ---")
    user_data = users_collection.find_one({"username": username})
    now = datetime.now()

    force_auto = args.get("force_auto", False)
    daily_overrides = args.get("daily_overrides", {})

    # 1. Build the prioritized "To-Do List"
    work_items = []
    all_items = user_data.get("tasks", []) + user_data.get("tests", [])
    for item in all_items:
        try:
            deadline_str = item.get("deadline", item.get("date"))
            if 'T' not in deadline_str:
                deadline_str += "T23:59:59"
            deadline = datetime.fromisoformat(deadline_str)

            if deadline < now:
                continue

            priority_str = item.get("priority", item.get("task_type", item.get("test_type", "low")))
            priority_score = DEFAULT_PRIORITY_MAP.get(priority_str, 99)

            item_type = item.get("task_type", item.get("test_type"))
            duration_blocks = item.get("duration_hours", DEFAULT_DURATION_MAP.get(item_type, 1))

            work_items.append({
                "name": item.get("name"),
                "deadline": deadline,
                "priority": priority_score,
                "blocks_needed": duration_blocks,
                "blocks_allocated": 0
            })
        except Exception as e:
            print(f"Skipping item due to parse error: {item.get('name')}, {e}")

    # 2. Sort the list (multi-level sort)
    # V8 FIX: We must sort by priority *first* then deadline to respect "top"
    work_items.sort(key=lambda x: (x["priority"], x["deadline"]))

    if not work_items:
        print("Planner: No work items to schedule.")
        return {"status": "success", "message": "Planner ran, but you have no upcoming tasks or tests to plan for."}

    print("--- Planner: Prioritized Work Queue ---")
    for item in work_items:
        print(
            f"  - {item['name']} (Priority: {item['priority']}, Deadline: {item['deadline'].strftime('%Y-%m-%d')}, Blocks: {item['blocks_needed']})")
    print("---------------------------------------")

    # 3. V8 CONFLICT DETECTION (Iterative)
    # Check for a "hard tie" anywhere in the list
    if not force_auto and len(work_items) > 1:
        for i in range(len(work_items) - 1):
            item1 = work_items[i]
            item2 = work_items[i + 1]

            # Check if adjacent items are tied
            if (item1["deadline"].date() == item2["deadline"].date() and
                    item1["priority"] == item2["priority"]):
                print(f"Planner: Hard conflict detected between '{item1['name']}' and '{item2['name']}'. Asking user.")
                return {
                    "status": "conflict",
                    "options": [item1["name"], item2["name"]]
                }

    # 4. Build Availability Map (14 days, in 60-min blocks)
    availability_map = {}
    start_date = now.date()
    for i in range(14):  # Plan for the next 14 days
        day = start_date + timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        availability_map[day_str] = {hour: "free" for hour in range(24)}  # Initialize all 24 hours as "free"

    # Block out sleep times
    prefs = user_data.get("preferences", {})
    sleep_min = _time_to_minutes(prefs.get("sleep_time", "23:00"))
    awake_min = _time_to_minutes(prefs.get("awake_time", "07:00"))

    for day_map in availability_map.values():
        for hour in range(24):
            hour_min = hour * 60
            if sleep_min > awake_min:
                if hour_min >= sleep_min or hour_min < awake_min:
                    day_map[hour] = "sleep"
            else:
                if sleep_min <= hour_min < awake_min:
                    day_map[hour] = "sleep"

    # Block out busy class times
    for class_item in user_data.get("schedule", []):
        class_day_name = class_item.get("day")
        start_min = _time_to_minutes(class_item.get("start_time", "00:00"))
        end_min = _time_to_minutes(class_item.get("end_time", "00:00"))

        for day_str, day_map in availability_map.items():
            day_dt = datetime.fromisoformat(day_str)
            if DAY_OF_WEEK_MAP.get(day_dt.weekday()) == class_day_name:
                for hour in range(24):
                    hour_start_min = hour * 60
                    hour_end_min = hour_start_min + 59
                    if max(start_min, hour_start_min) < min(end_min, hour_end_min):
                        day_map[hour] = "busy"

    # 5. Create a flat list of available slots, prioritizing study_windows & overrides
    available_slots = []
    non_preferred_slots = []

    study_windows = user_data.get("study_windows", [])

    for day_str, day_map in availability_map.items():
        day_dt = datetime.fromisoformat(day_str)
        day_name = DAY_OF_WEEK_MAP.get(day_dt.weekday())

        if day_str in daily_overrides:
            print(f"Planner: Applying daily override for {day_str}")
            override_blocks = daily_overrides[day_str]
            override_hours = set()
            for block in override_blocks:
                block_start_min = _time_to_minutes(block.get("start_time"))
                block_end_min = _time_to_minutes(block.get("end_time"))
                for hour in range(24):
                    hour_start_min = hour * 60
                    hour_end_min = hour_start_min + 59
                    if max(block_start_min, hour_start_min) < min(block_end_min, hour_end_min) and (
                            block_end_min - block_start_min > 0):
                        override_hours.add(hour)

            for hour in override_hours:
                if day_map.get(hour) == "free":
                    slot_time = time(hour, 0)
                    available_slots.append({
                        "date": day_str,
                        "start_time": slot_time.strftime("%H:%M"),
                        "end_time": (datetime.combine(day_dt, slot_time) + timedelta(hours=1)).strftime("%H:%M")
                    })
            continue

        for hour, status in day_map.items():
            if status == "free":
                slot_time = time(hour, 0)
                is_preferred = False
                for window in study_windows:
                    if window.get("day") == day_name:
                        win_start_min = _time_to_minutes(window.get("start_time"))
                        win_end_min = _time_to_minutes(window.get("end_time"))
                        hour_min = hour * 60
                        if win_start_min <= hour_min < win_end_min:
                            is_preferred = True
                            break
                slot_data = {
                    "date": day_str,
                    "start_time": slot_time.strftime("%H:%M"),
                    "end_time": (datetime.combine(day_dt, slot_time) + timedelta(hours=1)).strftime("%H:%M")
                }
                if is_preferred:
                    available_slots.append(slot_data)
                else:
                    non_preferred_slots.append(slot_data)

    available_slots.extend(non_preferred_slots)

    # 6. Run Round-Robin Scheduler
    new_plan = []
    total_blocks_needed = sum(item["blocks_needed"] for item in work_items)

    print(
        f"Planner: Starting round-robin. Tasks: {len(work_items)}, Blocks: {total_blocks_needed}, Slots: {len(available_slots)}")

    while total_blocks_needed > 0 and available_slots:
        made_progress = False
        for item in work_items:
            if item["blocks_allocated"] < item["blocks_needed"]:
                found_slot_index = -1
                for i, slot in enumerate(available_slots):
                    slot_dt = datetime.fromisoformat(f"{slot['date']}T{slot['start_time']}")
                    if slot_dt < item["deadline"]:
                        found_slot_index = i
                        break
                if found_slot_index != -1:
                    slot = available_slots.pop(found_slot_index)
                    new_plan.append({
                        "date": slot["date"],
                        "start_time": slot["start_time"],
                        "end_time": slot["end_time"],
                        "task": f"Work on {item['name']}"
                    })
                    item["blocks_allocated"] += 1
                    total_blocks_needed -= 1
                    made_progress = True
        if not made_progress:
            print("Planner: Stopping. No more valid slots.")
            break

    # 7. Save the new plan
    users_collection.update_one(
        {"username": username},
        {"$set": {"generated_plan": new_plan}}
    )

    print("Planner: V8 run complete. New plan saved.")
    return {"status": "success", "message": "I've regenerated your study plan."}


# === END OF V8 PLANNER ENGINE ===


@app.route("/chat", methods=["POST"])
def chat():
    if "username" not in session:
        return jsonify({"reply": "Error: Not logged in"}), 401

    user_message = request.json.get("message")
    selected_year = request.json.get("year", str(json.loads(os.getenv("CURRENT_DATE", '{"year": 2025}'))["year"]))
    username = session["username"]
    user_data = users_collection.find_one({"username": username})

    if not user_data:
        session.pop("username", None)
        return jsonify({"reply": "Error: Your user data was not found. Please log in again."}), 401

    old_full_history = user_data.get("chat_history", [])

    # === START OF V8 CHAT LOGIC (Loop Fix) ===

    # 1. Handle Modal Response
    # This is a special, non-AI path
    if user_message.startswith("User priority choice:"):
        choice = user_message.split(": ", 1)[1]

        if choice == "Auto":
            # User wants us to auto-schedule (round-robin)
            planner_response = run_planner_engine_db(username, {"force_auto": True})
            reply_to_send = f"OK, I'm scheduling both tasks. {planner_response['message']}"

        else:
            # User prioritized a specific task
            task_name = choice

            # V8 FIX: Set priority to "top" (score 0) to permanently win all
            # future tie-breaks, not just "high" (score 1).
            update_task_details_db(username, {"current_name": task_name, "new_priority": "top"})

            # Re-run the planner...
            planner_response = run_planner_engine_db(username, {})

            # ...and check if the re-run found ANOTHER conflict
            if planner_response["status"] == "conflict":
                # Yes, it found another tie. We must ask the user again.
                reply_to_send = f"OK, I've prioritized {task_name}. (Note: I found another scheduling conflict. Please choose again:)"

                # Save history and return the NEW modal action
                old_full_history.append({"role": "user", "content": user_message})
                old_full_history.append({"role": "assistant", "content": reply_to_send})
                users_collection.update_one(
                    {"username": username},
                    {"$set": {"chat_history": old_full_history}}
                )
                return jsonify({
                    "reply": reply_to_send,
                    "action": "show_priority_modal",
                    "options": planner_response["options"]
                })

            # --- If no new conflict, proceed as normal ---
            reply_to_send = f"OK, I've prioritized {task_name}. {planner_response['message']}"

        # Save this interaction to history (for non-conflict cases)
        old_full_history.append({"role": "user", "content": user_message})
        old_full_history.append({"role": "assistant", "content": reply_to_send})
        users_collection.update_one(
            {"username": username},
            {"$set": {"chat_history": old_full_history}}
        )
        return jsonify({"reply": reply_to_send, "action": "none"})

    # 2. Standard Chat Message Path (Builds context for AI)
    today_string = datetime.now().strftime("%A, %B %d, %Y")
    fresh_context_data = {
        "schedule": user_data.get("schedule", []),
        "tasks": user_data.get("tasks", []),
        "tests": user_data.get("tests", []),
        "preferences": user_data.get("preferences", {}),
        "study_windows": user_data.get("study_windows", [])
    }
    messages_header = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system",
         "content": f"CRITICAL: Today's date is {today_string}. Use this as the anchor for all date math."},
        {"role": "user",
         "content": f"Here is my current data. Assume all new dates are for the year {selected_year}. Context: {json.dumps(fresh_context_data)}"}
    ]
    conversational_history = [
        msg for msg in old_full_history
        if msg.get("role") in ["assistant", "tool"] or
           (msg.get("role") == "user" and not msg.get("content", "").startswith("Here is my current data."))
    ]
    if user_message == "trigger:daily_checkin":
        conversational_history = []

    messages = messages_header + conversational_history
    messages.append({"role": "user", "content": user_message})

    # === END OF V8 CHAT LOGIC ===

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        response_message = response.choices[0].message

        if response_message.tool_calls:
            messages.append(response_message.model_dump(exclude={'function_call'}))
        else:
            messages.append({
                "role": response_message.role,
                "content": response_message.content
            })

        reply_to_send = ""
        run_planner = False
        planner_response = None  # Store planner result

        if response_message.tool_calls:
            for tool_call in response_message.tool_calls:
                function_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)

                if function_name == "save_preference":
                    response_msg_for_user = update_user_data(username, "preference", arguments)
                elif function_name == "save_class":
                    response_msg_for_user = update_user_data(username, "class", arguments)
                elif function_name == "save_task":
                    response_msg_for_user = update_user_data(username, "task", arguments)
                    run_planner = True
                elif function_name == "save_test":
                    response_msg_for_user = update_user_data(username, "test", arguments)
                    run_planner = True
                elif function_name == "update_task_details":
                    response_msg_for_user = update_task_details_db(username, arguments)
                    run_planner = True
                elif function_name == "update_class_schedule":
                    response_msg_for_user = update_class_schedule_db(username, arguments)
                elif function_name == "delete_schedule_item":
                    response_msg_for_user = delete_schedule_item_db(username, arguments)
                    run_planner = True
                elif function_name == "save_study_windows":
                    response_msg_for_user = save_study_windows_db(username, arguments)
                    run_planner = True
                elif function_name == "get_daily_plan":
                    response_msg_for_user = get_daily_plan_db(username, arguments)
                elif function_name == "get_priority_list":
                    response_msg_for_user = get_priority_list_db(username, arguments)

                elif function_name == "reschedule_day":
                    response_msg_for_user = reschedule_day_db(username, arguments)
                    planner_response = {"status": "success", "message": response_msg_for_user}
                    run_planner = False

                elif function_name == "run_planner_engine":
                    planner_response = run_planner_engine_db(username, {})
                    response_msg_for_user = planner_response.get("message", "OK, I've run the planner.")
                else:
                    response_msg_for_user = "Error: AI tried to call an unknown function."

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": function_name,
                    "content": response_msg_for_user
                })
                reply_to_send = response_msg_for_user
        else:
            reply_to_send = response_message.content

        if run_planner and not planner_response:
            planner_response = run_planner_engine_db(username, {})

        if planner_response:
            if function_name == "reschedule_day":
                reply_to_send = planner_response['message']
            elif planner_response["status"] == "conflict":
                users_collection.update_one(
                    {"username": username},
                    {"$set": {"chat_history": messages}}
                )
                return jsonify({
                    "reply": f"{reply_to_send}. (Note: I found a scheduling conflict. Please choose which task to prioritize first:)",
                    "action": "show_priority_modal",
                    "options": planner_response["options"]
                })
            else:
                reply_to_send += f" (Note: {planner_response['message']})"

        users_collection.update_one(
            {"username": username},
            {"$set": {"chat_history": messages}}
        )

        return jsonify({"reply": reply_to_send})

    except Exception as e:
        print(f"Error in /chat route: {e}")
        return jsonify({"reply": "Sorry, I ran into an error. Please try that again."}), 500


@app.route("/get_schedule")
def get_schedule():
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401

    username = session["username"]

    auto_cleanup_past_items(username)

    user_data = users_collection.find_one({"username": username})

    if not user_data:
        return jsonify({"error": "User not found"}), 404

    schedule_data = {
        "schedule": user_data.get("schedule", []),
        "tasks": user_data.get("tasks", []),
        "tests": user_data.get("tests", []),
        "generated_plan": user_data.get("generated_plan", []),
        "preferences": user_data.get("preferences", {}),
        "study_windows": user_data.get("study_windows", [])
    }
    return jsonify(schedule_data)


if __name__ == "__main__":
    app.run(debug=True)
