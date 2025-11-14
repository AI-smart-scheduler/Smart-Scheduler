// --- Global variables ---
let currentWeekStart = new Date();
let selectedDate = new Date();
let scheduleData = { schedule: [], tasks: [], tests: [], generated_plan: [] };

// === MONTH AND YEAR SELECTORS ===
const monthNames = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];
const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
let monthSelect;
let yearSelect;

// --- Main Initialization (runs on page load) ---
document.addEventListener('DOMContentLoaded', () => {
  monthSelect = document.getElementById('month-select');
  yearSelect = document.getElementById('year-select');

  initializeSelectors();

  monthSelect.addEventListener('change', handleDateSelectorChange);
  yearSelect.addEventListener('change', handleDateSelectorChange);

  currentWeekStart = getWeekStart(new Date());
  renderWeek(); // Start the async render process

  // Event listener to close popup when clicking outside
   document.addEventListener('click', function(event) {
    const popup = document.getElementById('notificationPopup');
    const bellIconContainer = document.querySelector('.notification-icon-container');
    if (popup && popup.style.display === 'block' && !popup.contains(event.target) && bellIconContainer && !bellIconContainer.contains(event.target)) {
      closeNotificationPopup();
    }
  });

  function triggerDailyCheckin() {
      const today = new Date().toLocaleDateString();
      const lastCheckin = localStorage.getItem('lastDailyCheckin');

      if (lastCheckin !== today) {
          console.log("First visit of the day, triggering daily check-in.");
          fetch("/chat", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                  message: "trigger:daily_checkin",
                  year: new Date().getFullYear().toString()
              })
          })
          .then(res => res.json())
          .then(data => {
              // === START OF V6 CHANGE: Handle complex JSON response ===
              handleChatResponse(data);
              // === END OF V6 CHANGE ===
          })
          .catch(err => {
              console.error("Error triggering daily check-in:", err);
          });
          localStorage.setItem('lastDailyCheckin', today);
      }
  }

  triggerDailyCheckin(); // Run the check on page load.

  // Add 'Enter' key listener to the chat input
  const userInput = document.getElementById('user-input');
  if (userInput) {
    userInput.addEventListener('keydown', (event) => {
      // Check if the key pressed was 'Enter' and no modifiers (like Shift)
      if (event.key === 'Enter' && !event.shiftKey) {
        // Prevent the default action (like adding a new line)
        event.preventDefault();
        // Call the existing sendMessage function
        sendMessage();
      }
    });
  }
  
  // === TASK MODAL LOGIC ===
  const addTaskModal = document.getElementById('addTaskModal');
  const taskNameInput = document.getElementById('task-name-input');
  const taskTypeInput = document.getElementById('task-type-input');
  const taskDeadlineInput = document.getElementById('task-deadline-input');
  const taskCancelButton = document.getElementById('task-cancel-button');
  const taskSaveButton = document.getElementById('task-save-button');

  document.getElementById("task-cancel-button").addEventListener("click", () => {
    document.getElementById("addTaskModal").classList.add("hidden");
  });

  taskCancelButton.addEventListener("click", () => {
    addTaskModal.classList.add("hidden");
});

  // === SAVE BUTTON HANDLER ===
  taskSaveButton.addEventListener("click", async () => {
      const name = taskNameInput.value.trim();
      const taskType = taskTypeInput.value;
      const deadlineRaw = taskDeadlineInput.value;

      if (!name || !deadlineRaw) {
          alert("Please fill in all fields.");
          return;
      }

      // Convert deadline to ISO format
      const deadlineISO = deadlineRaw.replace("T", " ") + ":00";

      try {
          const res = await fetch("/add_task", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                  name: name,
                  task_type: taskType,
                  deadline: deadlineISO
              })
          });

          const data = await res.json();

          handleChatResponse(data);
          await loadScheduleData();
          displayDayDetails();
      } catch (e) {
          console.error("Error adding task:", e);
      }

      addTaskModal.classList.add("hidden");
  });

  // === Personalization Modal Logic (Unchanged) ===
  const modal = document.getElementById('personalizationModal');
  const settingsButton = document.getElementById('settings-button');
  const closeButton = document.getElementById('modal-close-button');
  const cancelButton = document.getElementById('modal-cancel-button');
  const saveButton = document.getElementById('modal-save-button');
  const addWindowButton = document.getElementById('add-window-button');
  const windowsContainer = document.getElementById('study-windows-container');

  const openModal = () => {
    modal.classList.remove('hidden');
    loadPersonalizationData();
  }
  const closeModal = () => modal.classList.add('hidden');

  settingsButton.addEventListener('click', openModal);
  closeButton.addEventListener('click', closeModal);
  cancelButton.addEventListener('click', closeModal);
  addWindowButton.addEventListener('click', () => createStudyWindowRow());
  saveButton.addEventListener('click', savePersonalization);

  // Function to add a new study window row to the form
  function createStudyWindowRow(data = {}) {
    const row = document.createElement('div');
    row.className = 'study-window-row';
    const dayVal = data.day || 'Monday';
    const startVal = data.start_time || '09:00';
    const endVal = data.end_time || '10:00';
    const focusVal = data.focus_level || 'medium';
    row.innerHTML = `
      <select class="day-select modal-input">
        ${dayNames.slice(1).concat(dayNames[0]).map(day => `<option value="${day}" ${day === dayVal ? 'selected' : ''}>${day}</option>`).join('')}
      </select>
      <input type="time" class="time-select start-time modal-input" value="${startVal}">
      <input type="time" class="time-select end-time modal-input" value="${endVal}">
      <select class="focus-select modal-input">
        <option value="high" ${focusVal === 'high' ? 'selected' : ''}>High Focus</option>
        <option value="medium" ${focusVal === 'medium' ? 'selected' : ''}>Medium Focus</option>
        <option value="low" ${focusVal === 'low' ? 'selected' : ''}>Low Focus</option>
      </select>
      <button type="button" class="window-delete-button">&times;</button>
    `;
    row.querySelector('.window-delete-button').addEventListener('click', () => {
      row.remove();
    });
    windowsContainer.appendChild(row);
  }

  // Function to load existing user preferences into the modal
  async function loadPersonalizationData() {
    try {
        const res = await fetch('/get_schedule');
        const data = await res.json();
        if (data.preferences) {
            document.getElementById('awake-time').value = data.preferences.awake_time || '07:00';
            document.getElementById('sleep-time').value = data.preferences.sleep_time || '23:00';
        }
        windowsContainer.innerHTML = '';
        if (data.study_windows && data.study_windows.length > 0) {
            data.study_windows.forEach(window => createStudyWindowRow(window));
        } else {
            createStudyWindowRow();
        }
    } catch (e) {
        console.error("Could not load personalization data", e);
        windowsContainer.innerHTML = '';
        createStudyWindowRow();
    }
  }

  // Function to save the data from the modal
  async function savePersonalization() {
    const awakeTime = document.getElementById('awake-time').value;
    const sleepTime = document.getElementById('sleep-time').value;
    const windows = [];
    const windowRows = windowsContainer.querySelectorAll('.study-window-row');
    windowRows.forEach(row => {
      windows.push({
        day: row.querySelector('.day-select').value,
        start_time: row.querySelector('.start-time').value,
        end_time: row.querySelector('.end-time').value,
        focus_level: row.querySelector('.focus-select').value
      });
    });
    const dataToSend = {
      preferences: {
        awake_time: awakeTime,
        sleep_time: sleepTime
      },
      study_windows: windows
    };
    try {
      const res = await fetch('/save_personalization', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dataToSend)
      });
      if (!res.ok) {
        throw new Error('Server responded with an error');
      }
      const result = await res.json();

      // === START OF V6 CHANGE: Use new response handler ===
      handleChatResponse(result);
      // === END OF V6 CHANGE ===

      closeModal();
      await loadScheduleData();
      displayDayDetails();
    } catch (e)
{
      console.error('Error saving personalization:', e);
      const chatBox = document.getElementById("chat-box");
      chatBox.innerHTML += `<div class="message bot-message" style="color: red;">Error: Could not save settings.</div>`;
      setTimeout(() => { chatBox.scrollTop = chatBox.scrollHeight; }, 0);
    }
  }
  // === END OF PERSONALIZATION MODAL LOGIC ===

});

// === Populates the selectors (Unchanged) ===
function initializeSelectors() {
  const deviceYear = new Date().getFullYear();
  monthNames.forEach((name, index) => {
    monthSelect.add(new Option(name, index));
  });
  for (let i = 0; i < 3; i++) {
    const year = deviceYear + i;
    yearSelect.add(new Option(year, year));
  }
}

// === Updates selectors based on selectedDate (Unchanged) ===
function updateSelectors() {
  const month = selectedDate.getMonth();
  const year = selectedDate.getFullYear();
  if (yearSelect && !yearSelect.querySelector(`option[value="${year}"]`)) {
    const option = new Option(year, year);
    if (year < parseInt(yearSelect.options[0].value, 10)) {
      yearSelect.add(option, 0);
    } else {
      yearSelect.add(option);
    }
  }
  if (monthSelect) monthSelect.value = month;
  if (yearSelect) yearSelect.value = year;
}

// === Handles manual change of dropdowns (Unchanged) ===
async function handleDateSelectorChange() {
  const newMonth = parseInt(monthSelect.value, 10);
  const newYear = parseInt(yearSelect.value, 10);
  const newDate = new Date(newYear, newMonth, 1);
  currentWeekStart = getWeekStart(newDate);
  await renderWeek(newDate);
}

// === Filtering and Display Logic for Schedule Details (MODIFIED FOR AM/PM) ===
function displayDayDetails() {
    const detailsBox = document.getElementById('schedule-details');
    if (!detailsBox) return;

    const dateString = getLocalDateString(selectedDate);
    const dayName = selectedDate.toLocaleDateString('en-US', { weekday: 'long' });

    detailsBox.innerHTML = `<h4 style="margin-top:0;">Schedule for ${dayName}, ${selectedDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</h4>`;

    const classesToday = scheduleData.schedule.filter(item =>
        item.day.toLowerCase() === dayName.toLowerCase()
    );
    const tasksToday = scheduleData.tasks.filter(item =>
        item.deadline && item.deadline.startsWith(dateString)
    );
    const testsToday = scheduleData.tests.filter(item =>
        item.date === dateString
    );

    const generatedPlanToday = (scheduleData.generated_plan || []).filter(item =>
        item.date === dateString
    );

    let itemsFound = false;

    if (generatedPlanToday.length > 0) {
        itemsFound = true;
        detailsBox.innerHTML += '<h5>My Study Plan</h5>';
        generatedPlanToday.sort((a, b) => (a.start_time || "").localeCompare(b.start_time || ""));
        generatedPlanToday.forEach(item => {
            // === START OF CHANGE: Format time to 12-hour ===
            const startTime = formatTime12Hour(item.start_time);
            const endTime = formatTime12Hour(item.end_time);
            detailsBox.innerHTML += `<p style="color: #004a9c; background: #e6f7ff; padding: 5px; border-radius: 4px; margin: 4px 0;">
                <b>${item.task}</b>: ${startTime} - ${endTime}
            </p>`;
            // === END OF CHANGE ===
        });
    }

    if (classesToday.length > 0) {
        itemsFound = true;
        detailsBox.innerHTML += '<h5>Classes</h5>';
        classesToday.forEach(item => {
            // === START OF CHANGE: Format time to 12-hour ===
            const startTime = formatTime12Hour(item.start_time);
            const endTime = formatTime12Hour(item.end_time);
            detailsBox.innerHTML += `<p><b>${item.subject}</b>: ${startTime} - ${endTime}</p>`;
            // === END OF CHANGE ===
        });
    }
    if (tasksToday.length > 0) {
        itemsFound = true;
        detailsBox.innerHTML += '<h5>Tasks Due</h5>';
        tasksToday.forEach(item => {
            let deadlineTime = 'All day';
            if (item.deadline) {
                try {
                    // Convert "2025-11-15 18:30:00" → "2025-11-15T18:30:00"
                    const normalized = item.deadline.replace(' ', 'T');
                    deadlineTime = new Date(normalized).toLocaleTimeString(
                        'en-US',
                        { hour: 'numeric', minute: '2-digit', hour12: true }
                    );
                } catch (e) {
                    console.warn("Could not parse deadline:", item.deadline);
                }
            }
            detailsBox.innerHTML += `<p><b>${item.name}</b> (${item.task_type}) - Due: ${deadlineTime}</p>`;
        });
    }
    if (testsToday.length > 0) {
        itemsFound = true;
        detailsBox.innerHTML += '<h5>Tests/Quizzes</h5>';
        testsToday.forEach(item => {
            detailsBox.innerHTML += `<p><b>${item.name}</b> (${item.test_type})</p>`;
        });
    }
    if (!itemsFound) {
        detailsBox.innerHTML += '<p style="color: #666;">No schedule for this day. Chat with me to add items!</p>';
    }
}

// === handleDayClick (Unchanged) ===
function handleDayClick(element, dateString) {
    const [year, month, day] = dateString.split('-').map(Number);
    selectedDate = new Date(year, month - 1, day);

    document.querySelectorAll('.day-card.active').forEach(card => {
        card.classList.remove('active');
    });
    element.classList.add('active');

    updateSelectors();
    displayDayDetails();
}

// === loadScheduleData (Unchanged) ===
async function loadScheduleData() {
    try {
        const res = await fetch('/get_schedule');
        if (!res.ok) {
             throw new Error(`HTTP error! status: ${res.status}`);
        }
        const data = await res.json();
        scheduleData = {
            schedule: data.schedule || [],
            tasks: data.tasks || [],
            tests: data.tests || [],
            generated_plan: data.generated_plan || [],
            preferences: data.preferences || { awake_time: '07:00', sleep_time: '23:00'},
            study_windows: data.study_windows || []
        };
    } catch (e) {
        console.error("Fetch error:", e);
        scheduleData = { schedule: [], tasks: [], tests: [], generated_plan: [], preferences: {}, study_windows: [] }; // Reset on error
        const detailsBox = document.getElementById('schedule-details');
        if (detailsBox) {
            detailsBox.innerHTML = `<h4 style="margin-top:0;">Error Loading Schedule</h4><p>Could not fetch schedule data. Please try again later.</p>`;
        }
    }
}

// --- Helper functions ---
function formatDate(date) {
    const options = { month: 'short', day: 'numeric' };
    return date.toLocaleDateString('en-US', options);
}

// === NEW HELPER FUNCTION (AM/PM) ===
/**
 * Converts a "HH:MM" string to a "H:MM AM/PM" string.
 * @param {string} timeStr - The time string in 24-hour format (e.g., "14:30")
 * @returns {string} - The time string in 12-hour format (e.g., "2:30 PM")
 */
function formatTime12Hour(timeStr) {
    if (!timeStr || !timeStr.includes(':')) {
        return timeStr; // Return original if format is unexpected
    }
    try {
        const [hours, minutes] = timeStr.split(':');
        const hourNum = parseInt(hours, 10);
        const minNum = parseInt(minutes, 10);

        const ampm = hourNum >= 12 ? 'PM' : 'AM';
        const hour12 = hourNum % 12 || 12; // Convert 0 or 12 to 12

        const minStr = minNum < 10 ? `0${minNum}` : `${minNum}`;

        return `${hour12}:${minStr} ${ampm}`;
    } catch (e) {
        console.warn("Could not format time:", timeStr, e);
        return timeStr; // Fallback to original
    }
}
// === END NEW HELPER FUNCTION ===


function getLocalDateString(date) {
    if (!(date instanceof Date) || isNaN(date)) {
        console.error("Invalid date passed to getLocalDateString:", date);
        const today = new Date();
         const year = today.getFullYear();
         const month = (today.getMonth() + 1).toString().padStart(2, '0');
         const day = today.getDate().toString().padStart(2, '0');
         return `${year}-${month}-${day}`;
    }
    const year = date.getFullYear();
    const month = (date.getMonth() + 1).toString().padStart(2, '0');
    const day = date.getDate().toString().padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function getWeekStart(date) {
    const d = new Date(date);
    let dayOfWeek = d.getDay();
    let diff = d.getDate() - dayOfWeek;
    d.setDate(diff);
    d.setHours(0, 0, 0, 0);
    return d;
}

// === renderWeek (Unchanged) ===
async function renderWeek(dateToSelect = null) {
    const wrapper = document.getElementById('day-cards-wrapper');
    if (!wrapper) return;
    wrapper.innerHTML = '';
    let currentDateIterator = new Date(currentWeekStart);
    selectedDate = dateToSelect ? new Date(dateToSelect) : new Date(currentWeekStart);
    selectedDate.setHours(0,0,0,0);
    const selectedDateString = getLocalDateString(selectedDate);
    for (let i = 0; i < 7; i++) {
        const date = new Date(currentDateIterator);
        const dateString = getLocalDateString(date);
        const isActive = dateString === selectedDateString ? 'active' : '';
        if (typeof dayNames !== 'undefined' && dayNames[date.getDay()]) {
            wrapper.innerHTML += `
              <div class="day-card ${isActive}"
                   data-date-string="${dateString}"
                   onclick="handleDayClick(this, '${dateString}')">
                <div class.day-name">${dayNames[date.getDay()]}</div>
                <div class="day-date">${date.getDate()}</div>
              </div>
            `;
        } else {
             console.error("dayNames is not defined or index is out of bounds");
        }
        currentDateIterator.setDate(currentDateIterator.getDate() + 1);
    }
    updateSelectors();
    await loadScheduleData();
    displayDayDetails();
}

// --- Navigation Logic (Unchanged) ---
async function loadPreviousWeek() {
  currentWeekStart.setDate(currentWeekStart.getDate() - 7);
  await renderWeek(new Date(currentWeekStart));
}
async function loadNextWeek() {
  currentWeekStart.setDate(currentWeekStart.getDate() + 7);
  await renderWeek(new Date(currentWeekStart));
}

// === sendMessage (MODIFIED FOR V6) ===
async function sendMessage(messageOverride = null) {
  const input = document.getElementById("user-input");
  const chatBox = document.getElementById("chat-box");

  // Use the override message (from modal) or the input value
  const userMessage = messageOverride || input.value.trim();

  if (!userMessage || !chatBox || !input) return;

  // Only add to chat if it's not a hidden command
  if (!messageOverride) {
    chatBox.innerHTML += `<div class="message user-message">${userMessage}</div>`;
  } else {
    // Optionally, show what the user picked
    chatBox.innerHTML += `<div class="message user-message"><em>(Selected priority: ${userMessage.split(": ")[1]})</em></div>`;
  }

  input.value = ""; // Clear input box
  setTimeout(() => { chatBox.scrollTop = chatBox.scrollHeight; }, 0);

  const selectedYear = yearSelect ? yearSelect.value : new Date().getFullYear().toString();

  try {
      const res = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: userMessage,
          year: selectedYear
        })
      });

      if (!res.ok) {
          throw new Error(`HTTP error! status: ${res.status}`);
      }

      const data = await res.json();

      // === START OF V6 CHANGE: Handle complex response ===
      handleChatResponse(data);
      // === END OF V6 CHANGE ===

      // Refresh schedule data *after* handling the response
      await loadScheduleData();
      displayDayDetails();
  } catch (error) {
       console.error("Error sending message or processing reply:", error);
       chatBox.innerHTML += `<div class="message bot-message" style="color: red;">Error: Could not get reply from server.</div>`;
       setTimeout(() => { chatBox.scrollTop = chatBox.scrollHeight; }, 0);
  }
}

// === NEW FUNCTION: handleChatResponse (V6) ===
function handleChatResponse(data) {
    const chatBox = document.getElementById("chat-box");
    if (!data || !data.reply) {
        chatBox.innerHTML += `<div class="message bot-message" style="color: red;">Error: Received an invalid response.</div>`;
        return;
    }

    // 1. Add the bot's text reply to the chat
    chatBox.innerHTML += `<div class="message bot-message">${data.reply}</div>`;
    setTimeout(() => { chatBox.scrollTop = chatBox.scrollHeight; }, 0);

    // 2. Check if the server sent a special "action"
    if (data.action === 'show_priority_modal' && data.options) {
        openPriorityModal(data.options);
    }
}

// === NEW FUNCTION: openPriorityModal (V6) ===
function openPriorityModal(options) {
    const modal = document.getElementById('priorityConflictModal');
    // We get the *real* modal elements from index.html
    const content = document.getElementById('priority-modal-body-content');
    const buttons = document.getElementById('priority-modal-footer-buttons');

    if (!modal || !content || !buttons) {
        console.error("Priority modal elements not found in HTML.");
        return;
    }

    // Clear old buttons and set header text
    buttons.innerHTML = '';
    content.innerHTML = '<p>The AI planner found two tasks with the same deadline and priority. Which one should it work on first?</p>';

    // Create a button for each option
    options.forEach(optionName => {
        const button = document.createElement('button');
        button.className = 'modal-button-primary';
        button.textContent = `Prioritize: ${optionName}`;

        button.addEventListener('click', () => {
            // Send a specific message back to the bot
            sendMessage(`User priority choice: ${optionName}`);
            modal.classList.add('hidden'); // Close modal
        });

        buttons.appendChild(button);
    });

    // Add a "cancel" or "auto" button
    const autoButton = document.createElement('button');
    autoButton.className = 'modal-button-secondary';
    autoButton.textContent = 'Decide for Me (Auto)';
    autoButton.addEventListener('click', () => {
        // Send a message to let the bot decide
        sendMessage('User priority choice: Auto');
        modal.classList.add('hidden');
    });
    buttons.appendChild(autoButton);

    // Show the modal
    modal.classList.remove('hidden');
}


// === Notification Popup Functions (Unchanged) ===
function toggleNotificationPopup() {
    const popup = document.getElementById('notificationPopup');
    if (!popup) return;
    if (popup.style.display === 'block') {
        closeNotificationPopup();
    } else {
        showNotificationPopup();
    }
}

function addTask() {
    openAddTaskModal();
}

function showNotificationPopup() {
    const popup = document.getElementById('notificationPopup');
    const listDiv = document.getElementById('notification-list');
    if (!popup || !listDiv) return;

    listDiv.innerHTML = '';
    const now = new Date();
    let pendingTasksFound = false;

    if (scheduleData && scheduleData.tasks) {
        const futureTasks = scheduleData.tasks.filter(task => {
            if (!task.deadline) return false;
            try {
                 const deadlineDate = new Date(task.deadline.replace(' ', 'T') + (task.deadline.includes('T') ? '' : 'Z'));
                return !isNaN(deadlineDate) && deadlineDate > now;
            } catch (e) { return false; }
        }).sort((a, b) => {
            try { return new Date(a.deadline.replace(' ', 'T') + (a.deadline.includes('T') ? '' : 'Z')) - new Date(b.deadline.replace(' ', 'T') + (b.deadline.includes('T') ? '' : 'Z')); }
            catch (e) { return 0; }
        });

        if (futureTasks.length > 0) {
            pendingTasksFound = true;
             futureTasks.forEach(task => {
                 let formattedDeadline = 'Invalid Date';
                 try {
                     const deadlineDate = new Date(task.deadline.replace(' ', 'T') + (task.deadline.includes('T') ? '' : 'Z'));
                     formattedDeadline = deadlineDate.toLocaleString('en-US', {
                        weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true
                     });
                 } catch (e) {
                     console.warn("Could not format deadline for notification:", task.deadline);
                     formattedDeadline = task.deadline;
                 }
                listDiv.innerHTML += `<p><b>${task.name}</b> (${task.task_type}) - Due: ${formattedDeadline}</p>`;
            });
        }
    }
    if (!pendingTasksFound) {
        listDiv.innerHTML = '<p>No pending tasks found.</p>';
    }
    popup.style.display = 'block';
}

function closeNotificationPopup() {
    const popup = document.getElementById('notificationPopup');
     if (popup) popup.style.display = 'none';
}

function openAddTaskModal() {
    const addTaskModal = document.getElementById('addTaskModal');
    const taskNameInput = document.getElementById('task-name-input');
    const taskDeadlineInput = document.getElementById('task-deadline-input');

    taskNameInput.value = "";
    taskDeadlineInput.value = "";
    addTaskModal.classList.remove("hidden");
}