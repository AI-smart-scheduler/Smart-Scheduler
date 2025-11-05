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
              const chatBox = document.getElementById("chat-box");
              if (chatBox) {
                  chatBox.innerHTML += `<div class="message bot-message">${data.reply || '...'}</div>`;
                  setTimeout(() => { chatBox.scrollTop = chatBox.scrollHeight; }, 0);
              }
          })
          .catch(err => {
              console.error("Error triggering daily check-in:", err);
          });
          localStorage.setItem('lastDailyCheckin', today);
      }
  }

  triggerDailyCheckin(); // Run the check on page load.

  // === START OF CHANGE: MODAL LOGIC ===
  const modal = document.getElementById('personalizationModal');
  const settingsButton = document.getElementById('settings-button');
  const closeButton = document.getElementById('modal-close-button');
  const cancelButton = document.getElementById('modal-cancel-button');
  const saveButton = document.getElementById('modal-save-button');
  const addWindowButton = document.getElementById('add-window-button');
  const windowsContainer = document.getElementById('study-windows-container');

  const openModal = () => {
    modal.classList.remove('hidden');
    // Load existing data into modal (we'll fetch it)
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

    // Add event listener to the delete button
    row.querySelector('.window-delete-button').addEventListener('click', () => {
      row.remove();
    });

    windowsContainer.appendChild(row);
  }

  // Function to load existing user preferences into the modal
  async function loadPersonalizationData() {
    // We can re-use the /get_schedule endpoint since it has all user data
    // (Assuming app.py is updated to send preferences and windows)
    try {
        const res = await fetch('/get_schedule');
        const data = await res.json();

        // This is a future-proof change; app.py needs to be updated to send this
        if (data.preferences) {
            document.getElementById('awake-time').value = data.preferences.awake_time || '07:00';
            document.getElementById('sleep-time').value = data.preferences.sleep_time || '23:00';
        }

        // Clear old rows and load new ones
        windowsContainer.innerHTML = '';
        if (data.study_windows && data.study_windows.length > 0) {
            data.study_windows.forEach(window => createStudyWindowRow(window));
        } else {
            // Add one blank row if none exist
            createStudyWindowRow();
        }
    } catch (e) {
        console.error("Could not load personalization data", e);
        // Add one blank row on error
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

    // Send data to a new, dedicated endpoint
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

      // Give user feedback in the chat box
      const chatBox = document.getElementById("chat-box");
      chatBox.innerHTML += `<div class="message bot-message">${result.reply || 'Settings saved!'}</div>`;
      setTimeout(() => { chatBox.scrollTop = chatBox.scrollHeight; }, 0);

      closeModal();

      // Refresh the schedule display as the plan might have changed
      await loadScheduleData();
      displayDayDetails();

    } catch (e) {
      console.error('Error saving personalization:', e);
      // Show error in chat
      const chatBox = document.getElementById("chat-box");
      chatBox.innerHTML += `<div class="message bot-message" style="color: red;">Error: Could not save settings.</div>`;
      setTimeout(() => { chatBox.scrollTop = chatBox.scrollHeight; }, 0);
    }
  }
  // === END OF CHANGE ===

});

// === Populates the selectors ===
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

// === Updates selectors based on selectedDate ===
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

// === Handles manual change of dropdowns ===
async function handleDateSelectorChange() {
  const newMonth = parseInt(monthSelect.value, 10);
  const newYear = parseInt(yearSelect.value, 10);
  const newDate = new Date(newYear, newMonth, 1);
  currentWeekStart = getWeekStart(newDate);
  await renderWeek(newDate);
}

// === Filtering and Display Logic for Schedule Details ===
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
            detailsBox.innerHTML += `<p style="color: #004a9c; background: #e6f7ff; padding: 5px; border-radius: 4px; margin: 4px 0;">
                <b>${item.task}</b>: ${item.start_time} - ${item.end_time}
            </p>`;
        });
    }

    if (classesToday.length > 0) {
        itemsFound = true;
        detailsBox.innerHTML += '<h5>Classes</h5>';
        classesToday.forEach(item => {
            detailsBox.innerHTML += `<p><b>${item.subject}</b>: ${item.start_time} - ${item.end_time}</p>`;
        });
    }
    if (tasksToday.length > 0) {
        itemsFound = true;
        detailsBox.innerHTML += '<h5>Tasks Due</h5>';
        tasksToday.forEach(item => {
            let deadlineTime = 'All day';
             if (item.deadline && item.deadline.includes('T')) {
                 try {
                     deadlineTime = new Date(item.deadline).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
                 } catch (e) { console.warn("Could not format deadline time:", item.deadline); }
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

// === handleDayClick ===
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

// === loadScheduleData ===
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
            // === START OF CHANGE: Make sure we store this data for the modal ===
            preferences: data.preferences || { awake_time: '07:00', sleep_time: '23:00'},
            study_windows: data.study_windows || []
            // === END OF CHANGE ===
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

// === renderWeek ===
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

// --- Navigation Logic ---
async function loadPreviousWeek() {
  currentWeekStart.setDate(currentWeekStart.getDate() - 7);
  await renderWeek(new Date(currentWeekStart));
}
async function loadNextWeek() {
  currentWeekStart.setDate(currentWeekStart.getDate() + 7);
  await renderWeek(new Date(currentWeekStart));
}

// === sendMessage ===
async function sendMessage() {
  const input = document.getElementById("user-input");
  const chatBox = document.getElementById("chat-box");
  const userMessage = input.value.trim();
  if (!userMessage || !chatBox || !input) return;

  chatBox.innerHTML += `<div class="message user-message">${userMessage}</div>`;
  input.value = "";
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
      chatBox.innerHTML += `<div class="message bot-message">${data.reply || 'No reply received.'}</div>`;
       setTimeout(() => { chatBox.scrollTop = chatBox.scrollHeight; }, 0);

      await loadScheduleData();
      displayDayDetails();
  } catch (error) {
       console.error("Error sending message or processing reply:", error);
       chatBox.innerHTML += `<div class="message bot-message" style="color: red;">Error: Could not get reply from server.</div>`;
       setTimeout(() => { chatBox.scrollTop = chatBox.scrollHeight; }, 0);
  }
}

// === Notification Popup Functions ===
function toggleNotificationPopup() {
    const popup = document.getElementById('notificationPopup');
    if (!popup) return;
    if (popup.style.display === 'block') {
        closeNotificationPopup();
    } else {
        showNotificationPopup();
    }
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
