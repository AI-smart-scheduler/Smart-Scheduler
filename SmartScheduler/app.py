from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from pymongo import MongoClient
from dotenv import load_dotenv
from flask_bcrypt import Bcrypt
from openai import OpenAI
import os
import json

# Load .env file
load_dotenv()

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

# === START OF TOOLS (Unchanged from your file) ===
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
    }
]
# === END OF TOOLS ===


# === START OF SYSTEM PROMPT (Unchanged from your file) ===
SYSTEM_PROMPT = """
You are a friendly but efficient 'Smart Study Scheduler' assistant. Your primary job is to help students manage their academic life by gathering data and calling tools.

You will perform several functions:
1.  **Data Elicitation (Follow-ups):** Your main job is to gather the information needed for the tool arguments. If a user provides partial information (e.g., "I have a math class"), you MUST ask friendly follow-up questions to get the *remaining* arguments (e.g., "What day and time is your math class?").
2.  **Meta-Conversation:** Politely answer questions about your purpose (e.g., 'What can you do?').
3.  **Scheduling/Planning:** When a user asks for a study plan, use their data to generate a concise, actionable plan.
4.  **Refusal:** If the user asks for *anything* else (e.g., 'What is the capital of France?'), politely refuse.
5.  **Updating:** When a user asks to *change* an item (e.g., "move my task", "deadline was extended"), identify the correct item from the chat history and call the `update_task_deadline` tool.
6.  **Deleting:** When a user asks to *delete* or *remove* an item (e.g., "cancel my math class"), call the `delete_schedule_item` tool.

**CRITICAL RULE: CONTEXT IS KEY**
-   You MUST pay attention to the chat history to understand context.
-   If a user adds a task "Data Structure HW" and their *next* message is "oops, the deadline is Oct 23", you must call `update_task_deadline` for "Data Structure HW", not `save_task`.

**CRITICAL RULE: CALL TOOLS IMMEDIATELY**
-   As soon as you have all the required information for a tool (like `subject`, `day`, `start_time`, `end_time` for `save_class`), you MUST call that tool immediately.
-   **DO NOT** ask the user for confirmation (e.g., "Just to confirm...?"). Call the tool directly.

**PREFERENCE RULE:**
-   Only call `save_preference` if the user's message *explicitly mentions* "wake up," "sleep," "awake," or "bed time."
-   Do not confuse class times with preference times.
"""


# === END OF SYSTEM PROMPT ===


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
            "preferences": {"awake_time": None, "sleep_time": None},
            "chat_history": []  # <-- This is correct from your file
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
            # === START OF FIX: This is from your file, it's correct ===
            users_collection.update_one(
                {"username": username},
                {"$set": {"chat_history": []}}  # Clear history on login
            )
            # === END OF FIX ===
            return redirect(url_for("index"))
        return "Invalid credentials!"
    return render_template("login.html")


@app.route("/logout")
def logout():
    # === START OF FIX: This is from your file, it's correct ===
    if "username" in session:
        users_collection.update_one(
            {"username": session["username"]},
            {"$set": {"chat_history": []}}  # Clear history on logout
        )
    # === END OF FIX ===
    session.pop("username", None)
    return redirect(url_for("login"))


# ---------- MAIN APP ROUTES (Chat and Schedule) ----------
@app.route("/")
def index():
    if "username" not in session:
        return redirect(url_for("login"))
    return render_template("index.html", username=session["username"])


# --- Helper functions (Unchanged from your file) ---
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

    if result_class.modified_count > 0 or result_task.modified_count > 0 or result_test.modified_count > 0:
        return f"OK, I've deleted '{item_name}' from your schedule."
    else:
        return f"Sorry, I couldn't find an item named '{item_name}' to delete."


# === START OF FIX: THE /chat ROUTE (This is the bug) ===
# This route now correctly handles memory
@app.route("/chat", methods=["POST"])
def chat():
    if "username" not in session:
        return jsonify({"reply": "Error: Not logged in"}), 401

    user_message = request.json.get("message")
    selected_year = request.json.get("year", str(json.loads(os.getenv("CURRENT_DATE", '{"year": 2025}'))["year"]))
    username = session["username"]

    # 1. Load user data AND chat history from MongoDB
    user_data = users_collection.find_one({"username": username})

    # === START OF FIX: Handle missing user data (e.g., if deleted) ===
    if not user_data:
        session.pop("username", None)
        return jsonify({"reply": "Error: Your user data was not found. Please log in again."}), 401
    # === END OF FIX ===

    messages = user_data.get("chat_history", [])

    # 2. Initialize history if this is the first message
    if not messages:
        context_data = {
            "schedule": user_data.get("schedule", []),
            "tasks": user_data.get("tasks", []),
            "tests": user_data.get("tests", []),
            "preferences": user_data.get("preferences", {})
        }

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": f"Here is my current data. Assume all new dates are for the year {selected_year}. Context: {json.dumps(context_data)}"}
        ]

        prefs = context_data.get("preferences", {})
        is_onboarding_needed = not prefs.get("awake_time") or not prefs.get("sleep_time")

        if is_onboarding_needed:
            messages.append({
                "role": "system",
                "content": "IMPORTANT: Your top priority is to get the user's preferences. Greet the user, introduce yourself, and kindly ask for their typical awake time and sleep time before doing anything else."
            })

    # 3. Add the user's new message to the history
    messages.append({"role": "user", "content": user_message})

    try:
        # 4. Call OpenAI with the full conversation history
        response = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        response_message = response.choices[0].message

        # === START OF FIX: Clean the response before saving ===
        # We only save the parts the API needs for the *next* call
        # to prevent validation errors.
        if response_message.tool_calls:
            # If AI calls a tool, save the tool call message
            messages.append(response_message.model_dump(exclude={'function_call'}))
        else:
            # If AI sends text, only save the role and content
            messages.append({
                "role": response_message.role,
                "content": response_message.content
            })
        # === END OF FIX ===

        # 6. Process the Response
        reply_to_send = ""
        if response_message.tool_calls:
            tool_call = response_message.tool_calls[0]
            function_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)

            # Route to the correct helper function
            if function_name == "save_preference":
                response_msg_for_user = update_user_data(username, "preference", arguments)
            elif function_name == "save_class":
                response_msg_for_user = update_user_data(username, "class", arguments)
            elif function_name == "save_task":
                response_msg_for_user = update_user_data(username, "task", arguments)
            elif function_name == "save_test":
                response_msg_for_user = update_user_data(username, "test", arguments)
            elif function_name == "update_task_deadline":
                response_msg_for_user = update_task_deadline_db(username, arguments)
            elif function_name == "delete_schedule_item":
                response_msg_for_user = delete_schedule_item_db(username, arguments)
            else:
                response_msg_for_user = "Error: AI tried to call an unknown function."

            # 7. Add the *result* of the tool call to the history
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": function_name,
                "content": response_msg_for_user
            })
            reply_to_send = response_msg_for_user
        else:
            # No tool call, just a regular text reply
            reply_to_send = response_message.content

        # 8. Save the final, updated history back to the DATABASE
        users_collection.update_one(
            {"username": username},
            {"$set": {"chat_history": messages}}
        )

        return jsonify({"reply": reply_to_send})

    except Exception as e:
        # 9. Handle any error
        print(f"Error in /chat route: {e}")
        # Clear the broken history to prevent a loop
        users_collection.update_one(
            {"username": username},
            {"$set": {"chat_history": []}}
        )
        return jsonify({"reply": "Sorry, I ran into an error and had to reset my memory."}), 500


# === END OF FIX ===


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
        "tests": user_data.get("tests", [])
    }
    return jsonify(schedule_data)


if __name__ == "__main__":
    app.run(debug=True)

