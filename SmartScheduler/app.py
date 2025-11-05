from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from pymongo import MongoClient
from dotenv import load_dotenv, find_dotenv
from flask_bcrypt import Bcrypt
from openai import OpenAI
import os
import json
from datetime import datetime, timedelta

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

# === START OF CHANGE: UPDATED SYSTEM PROMPT ===
SYSTEM_PROMPT = """
You are a 'Smart Study Scheduler' assistant. Your goal is to be a proactive, intelligent planner for the user.

**CORE RULES & DATE HANDLING (CRITICAL):**
1.  **Look for the Current Date:** On the user's first turn, you will receive a system message stating "Today is [Date]". You MUST use this date as the absolute reference for all calculations.
2.  **Relative Date Logic (Examples):**
    * If "Today is Tuesday, Nov 4" and the user says "this Friday," you MUST use Nov 7.
    * If "Today is Tuesday, Nov 4" and the user says "this Saturday," you MUST use Nov 8.
    * If "Today is Tuesday, Nov 4" and the user says "next week Saturday," you MUST use Nov 15.
    * If "Today is Tuesday, Nov 4" and the user says "due Saturday," you MUST assume the *nearest future* Saturday, which is Nov 8.
3.  **Reject Explicit Past Dates:** If a user provides an explicit date that is in the past, you MUST NOT call any tool. Instead, respond directly: "Sorry, I can't add items for dates that have already passed. Please provide a future date."
4.  **Year Context:** You will be given the current year. Use it for all date calculations.

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
        * Call `reschedule_day(new_constraints="1 hour at lunch, low-focus")`.
        * Present the new plan: "No problem. [Response from tool, e.g., 'I recommend we use that 1 hour for History (Memorization) instead...']"

4.  **DATA ENTRY (Your main job):**
    * If the user is not in a planning flow, just add/update data.
    * Use `save_class`, `save_task`, `save_test`, `update_task_deadline`, etc. as requested.
    * If a new task/test is added, call `run_planner_engine` *after* saving the item to update the plan.

5.  **PLAN GENERATION (The "Engine"):**
    * If the user asks "Can you make my plan?" or "Update my plan", call the `run_planner_engine()` tool.
"""
# === END OF CHANGE ===

# (All your tools functions from lines 40-225 remain unchanged)
tools = [
    # (All your existing tools remain here... save_preference, save_class, etc.)
    # --- Existing Tools ---
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
            "description": "Saves a new task, assignment, or project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "task_type": {"type": "string", "enum": ["assignment", "project", "seatwork"]},
                    "deadline": {"type": "string", "description": "The deadline in YYYY-MM-DDTHH:MM:SS format"},
                },
                "required": ["name", "task_type", "deadline"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_test",
            "description": "Saves a new quiz or exam.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "test_type": {"type": "string", "enum": ["quiz", "exam"]},
                    "date": {"type": "string", "description": "The date of the test in YYYY-MM-DD format"},
                },
                "required": ["name", "test_type", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task_deadline",
            "description": "Updates the deadline of an *existing* task, identified by its name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_name": {"type": "string", "description": "The name of the task to find."},
                    "new_deadline": {"type": "string", "description": "The new deadline in YYYY-MM-DDTHH:MM:SS format."}
                },
                "required": ["task_name", "new_deadline"],
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
            "description": "Re-plans the current day based on new user constraints.",
            "parameters": {
                "type": "object",
                "properties": {
                    "new_constraints": {"type": "string",
                                        "description": "A natural language description of the new constraints (e.g., 'only 1 hour at lunch, low-focus')"}
                },
                "required": ["new_constraints"]
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


# ---------- AUTH ROUTES ----------
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

        return jsonify({"reply": f"Settings saved! {planner_response}"})

    except Exception as e:
        print(f"Error in /save_personalization: {e}")
        return jsonify({"reply": "Sorry, there was an error saving your settings."}), 500


# --- This is our "ADD" function ---
def update_user_data(username, data_type, data):
    if data_type == "class":
        users_collection.update_one({"username": username}, {"$push": {"schedule": data}})
    elif data_type == "task":
        users_collection.update_one({"username": username}, {"$push": {"tasks": data}})
    elif data_type == "test":
        users_collection.update_one({"username": username}, {"$push": {"tests": data}})
    elif data_type == "preference":
        users_collection.update_one({"username": username}, {"$set": {"preferences": data}})
        return f"Got it! I've saved your awake time as {data['awake_time']} and sleep time as {data['sleep_time']}."

    return f"OK, I've added the new {data_type} to your schedule."


# --- This is our "UPDATE TASK" function ---
def update_task_deadline_db(username, args):
    task_name = args.get("task_name")
    new_deadline = args.get("new_deadline")

    result = users_collection.update_one(
        {"username": username, "tasks.name": task_name},
        {"$set": {"tasks.$.deadline": new_deadline}}
    )

    if result.modified_count > 0:
        return f"OK, I've updated the deadline for '{task_name}'."
    else:
        return f"Sorry, I couldn't find a task named '{task_name}' to update."


# --- This is our "UPDATE CLASS" function ---
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


# --- This is your NEW function ---
def delete_schedule_item_db(username, args):
    item_name = args.get("item_name")

    # 1. Delete from 'schedule' (Classes)
    result_class = users_collection.update_one(
        {"username": username},
        {"$pull": {"schedule": {"subject": item_name}}}
    )
    # 2. Delete from 'tasks'
    result_task = users_collection.update_one(
        {"username": username},
        {"$pull": {"tasks": {"name": item_name}}}
    )
    # 3. Delete from 'tests'
    result_test = users_collection.update_one(
        {"username": username},
        {"$pull": {"tests": {"name": item_name}}}
    )

    # 4. NEW: Delete from 'generated_plan' (Cascading Delete)
    # We use $regex to find any plan item where the 'task' field *contains*
    # the item_name. '$options: "i"' makes it case-insensitive.
    result_plan = users_collection.update_one(
        {"username": username},
        {"$pull": {"generated_plan": {"task": {"$regex": item_name, "$options": "i"}}}}
    )

    # 5. NEW: Update the 'if' check to include result_plan
    if (result_class.modified_count > 0 or
            result_task.modified_count > 0 or
            result_test.modified_count > 0 or
            result_plan.modified_count > 0):
        return f"OK, I've deleted '{item_name}' and any related schedule blocks."
    else:
        return f"Sorry, I couldn't find an item named '{item_name}' to delete."


# --- NEW PLANNING FUNCTIONS ---

def save_study_windows_db(username, args):
    windows = args.get("windows", [])
    users_collection.update_one(
        {"username": username},
        {"$set": {"study_windows": windows}}
    )
    # Don't return text, as this will be called by another function
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
    hours = args.get("hours", 0)
    user_data = users_collection.find_one({"username": username})
    tasks = user_data.get("tasks", [])

    if not tasks:
        return "You have no pending tasks!"

    try:
        tasks.sort(key=lambda x: x['deadline'])
    except Exception as e:
        print(f"Could not sort tasks: {e}")

        # This is still a stub. A real version would estimate time.
    priority_list_str = "Here is your priority list: " + ", ".join([t['name'] for t in tasks[:2]])
    return priority_list_str


def reschedule_day_db(username, args):
    constraints = args.get("new_constraints", "No constraints")
    # This is a stub for a very complex function.
    new_task = "History (Memorization)" if "history" in constraints.lower() else "Quick Task Review"
    return (f"No problem. Based on '{constraints}', "
            f"I recommend you focus on: **{new_task}**. "
            "I've moved your other scheduled items to 'Flex Time'.")


def run_planner_engine_db(username, args):
    # This is a stub for your *main planning logic*.
    user_data = users_collection.find_one({"username": username})
    tasks = user_data.get("tasks", [])
    if not tasks:
        return "Planner ran, but you have no tasks to plan for."
    try:
        tasks.sort(key=lambda x: x['deadline'])
        soonest_task = tasks[0]
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        new_plan = [
            {
                "date": tomorrow,
                "start_time": "19:00",
                "end_time": "20:00",
                "task": f"Work on {soonest_task['name']}"
            }
        ]
        users_collection.update_one(
            {"username": username},
            {"$set": {"generated_plan": new_plan}}
        )
        return "I've regenerated your study plan."

    except Exception as e:
        return f"Planner ran into an error: {e}"


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

    # Get the *entire* chat history
    old_full_history = user_data.get("chat_history", [])

    # === START OF RESTRUCTURED MESSAGE LOGIC ===

    # 1. Get today's date (as before)
    today_string = datetime.now().strftime("%A, %B %d, %Y")

    # 2. Get the user's FRESH data (this is the critical fix)
    fresh_context_data = {
        "schedule": user_data.get("schedule", []),
        "tasks": user_data.get("tasks", []),
        "tests": user_data.get("tests", []),
        "preferences": user_data.get("preferences", {}),
        "study_windows": user_data.get("study_windows", [])
    }

    # 3. Create the "header" that MUST be sent every time.
    messages_header = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"For all date calculations, please be aware that **Today is {today_string}**."},
        {"role": "user",
         "content": f"Here is my current data. Assume all new dates are for the year {selected_year}. Context: {json.dumps(fresh_context_data)}"}
    ]

    # 4. Filter the old history to get *only* conversational turns.
    # We skip the old system/context messages to avoid duplication.
    conversational_history = [
        msg for msg in old_full_history
        if msg.get("role") in ["assistant", "tool"] or
           (msg.get("role") == "user" and not msg.get("content", "").startswith("Here is my current data."))
    ]

    # 5. Handle Daily Check-in: If it's a check-in, wipe the conversation.
    if user_message == "trigger:daily_checkin":
        conversational_history = []

    # 6. Build the *new* messages list to be used for this turn.
    # This is now the *only* "messages" variable we need.
    messages = messages_header + conversational_history
    messages.append({"role": "user", "content": user_message})

    # === END OF RESTRUCTURED MESSAGE LOGIC ===

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=messages,  # We send the newly constructed list
            tools=tools,
            tool_choice="auto"
        )
        response_message = response.choices[0].message

        if response_message.tool_calls:
            # Append the assistant's request to call tools
            messages.append(response_message.model_dump(exclude={'function_call'}))
        else:
            # Append the assistant's simple text response
            messages.append({
                "role": response_message.role,
                "content": response_message.content
            })

        reply_to_send = ""
        run_planner = False

        if response_message.tool_calls:
            # This block only runs if the AI requested a tool.
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
                elif function_name == "update_task_deadline":
                    response_msg_for_user = update_task_deadline_db(username, arguments)
                    run_planner = True
                elif function_name == "update_class_schedule":
                    response_msg_for_user = update_class_schedule_db(username, arguments)
                elif function_name == "delete_schedule_item":
                    response_msg_for_user = delete_schedule_item_db(username, arguments)
                    run_planner = True
                # --- NEW TOOL ROUTES ---
                elif function_name == "save_study_windows":
                    response_msg_for_user = save_study_windows_db(username, arguments)
                    run_planner_engine_db(username, {})  # Also run planner
                elif function_name == "get_daily_plan":
                    response_msg_for_user = get_daily_plan_db(username, arguments)
                elif function_name == "get_priority_list":
                    response_msg_for_user = get_priority_list_db(username, arguments)
                elif function_name == "reschedule_day":
                    response_msg_for_user = reschedule_day_db(username, arguments)
                elif function_name == "run_planner_engine":
                    response_msg_for_user = run_planner_engine_db(username, arguments)
                else:
                    response_msg_for_user = "Error: AI tried to call an unknown function."

                # Append the *result* of the tool call
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": function_name,
                    "content": response_msg_for_user
                })

                reply_to_send = response_msg_for_user
        else:
            # This block runs if the AI did *not* request a tool.
            reply_to_send = response_message.content

        # After all tools are run, check if we need to run the planner
        if run_planner:
            planner_response = run_planner_engine_db(username, {})
            reply_to_send += f" (Note: {planner_response})"
            # We do NOT append this to history as a tool call

        # Save the complete history (including the new header and conversation)
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
