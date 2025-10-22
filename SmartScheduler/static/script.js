// --- Global variables ---
let currentWeekStart = new Date();
let selectedDate = new Date();
let scheduleData = { schedule: [], tasks: [], tests: [] };

// === MONTH AND YEAR SELECTORS ===
const monthNames = [
  "January", "February", "March", "April", "May", "June", 
  "July", "August", "September", "October", "November", "December"
];
let monthSelect;
let yearSelect;

// --- Main Initialization (runs on page load) ---
document.addEventListener('DOMContentLoaded', () => {
  // Get the elements
  monthSelect = document.getElementById('month-select');
  yearSelect = document.getElementById('year-select');

  // Populate them
  initializeSelectors();

  // Add event listeners
  monthSelect.addEventListener('change', handleDateSelectorChange);
  yearSelect.addEventListener('change', handleDateSelectorChange);

  // Initial render
  currentWeekStart = getWeekStart(new Date());
  renderWeek(); // This will be async but it's fine on first load
});


// === Populates the selectors ===
function initializeSelectors() {
  const deviceYear = new Date().getFullYear();
  
  // Populate months
  monthNames.forEach((name, index) => {
    const option = new Option(name, index); // e.g., value="0" for January
    monthSelect.add(option);
  });

  // Populate years (current year + next 2)
  for (let i = 0; i < 3; i++) {
    const year = deviceYear + i;
    const option = new Option(year, year);
    yearSelect.add(option);
  }
}

// === updateSelectors ===
// Now updates based on the *selectedDate* (the clicked day)
function updateSelectors() {
  const month = selectedDate.getMonth();
  const year = selectedDate.getFullYear();

  // Check if the year exists in the dropdown, add it if not
  if (!yearSelect.querySelector(`option[value="${year}"]`)) {
    const option = new Option(year, year);
    // Add it in sorted order
    if (year < yearSelect.options[0].value) {
      yearSelect.add(option, 0);
    } else {
      yearSelect.add(option);
    }
  }

  monthSelect.value = month;
  yearSelect.value = year;
}

// === Handles manual change of dropdowns ===
async function handleDateSelectorChange() {
  const newMonth = parseInt(monthSelect.value, 10);
  const newYear = parseInt(yearSelect.value, 10);

  // === START OF FIX ===
  // Set the *intended* selected date to the 1st of the new month
  const newDate = new Date(newYear, newMonth, 1);
  // Base the week render on the start of that date's week
  currentWeekStart = getWeekStart(newDate);
  // Pass the intended date to renderWeek so it's selected by default
  await renderWeek(newDate);
  // === END OF FIX ===
}


// --- Filtering and Display Logic ---
function displayDayDetails() {
    const detailsBox = document.getElementById('schedule-details');
    // We use our *new* helper function to get a reliable date string
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

    let itemsFound = false;

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
            let deadlineTime = new Date(item.deadline).toLocaleTimeString('en-US', { timeStyle: 'short' });
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
        detailsBox.innerHTML += '<p style="color: #666;">No schedule for this day. Chat with me to add a class, task, or test!</p>';
    }
}

// === START OF FIX ===
// handleDayClick now uses a robust, timezone-safe method to create the date
function handleDayClick(element, dateString) {
    // Manually parse the YYYY-MM-DD string to avoid timezone bugs
    const parts = dateString.split('-').map(part => parseInt(part, 10));
    // new Date(Year, Month-1, Day)
    selectedDate = new Date(parts[0], parts[1] - 1, parts[2]);

    document.querySelectorAll('.day-card.active').forEach(card => {
        card.classList.remove('active');
    });
    element.classList.add('active');

    // Update the dropdowns to match the clicked day
    updateSelectors();
    // Display the details for the clicked day
    displayDayDetails();
}
// === END OF FIX ===

// --- loadScheduleData is unchanged from previous fix ---
async function loadScheduleData() {
    try {
        const res = await fetch('/get_schedule');
        const data = await res.json();
        scheduleData = data.error ? { schedule: [], tasks: [], tests: [] } : data;
    } catch (e) {
        console.error("Fetch error:", e);
        scheduleData = { schedule: [], tasks: [], tests: [] };
    }
}

function formatDate(date) {
    const options = { month: 'short', day: 'numeric' };
    return date.toLocaleDateString('en-US', options);
}

// === Timezone-safe YYYY-MM-DD string formatter ===
function getLocalDateString(date) {
    const year = date.getFullYear();
    // getMonth() is 0-indexed, padStart adds the leading '0'
    const month = (date.getMonth() + 1).toString().padStart(2, '0');
    const day = date.getDate().toString().padStart(2, '0');
    return `${year}-${month}-${day}`;
}

// --- getWeekStart is correct ---
function getWeekStart(date) {
    const d = new Date(date); // Clone date
    let day = d.getDay(); // 0 is Sunday
    let diff = d.getDate() - day;
    // setDate correctly handles negative numbers and 0
    d.setDate(diff);
    return d;
}

// === START OF FIX ===
// renderWeek now accepts an optional 'dateToSelect'
async function renderWeek(dateToSelect) {
    const wrapper = document.getElementById('day-cards-wrapper');
    wrapper.innerHTML = '';

    const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    let currentDate = new Date(currentWeekStart);

    // If a dateToSelect is passed (from dropdown change), use it.
    // Otherwise, default to the start of the week.
    selectedDate = dateToSelect || new Date(currentWeekStart);
    const selectedDateString = getLocalDateString(selectedDate);

    for (let i = 0; i < 7; i++) {
        const date = new Date(currentDate);
        const dateString = getLocalDateString(date);

        // The active card is now the one that matches the selectedDate
        const isActive = (dateString === selectedDateString) ? 'active' : '';

        wrapper.innerHTML += `
          <div class="day-card ${isActive}"
               data-date-string="${dateString}"
               onclick="handleDayClick(this, '${dateString}')">
            <div class="day-name">${dayNames[date.getDay()]}</div>
            <div class="day-date">${date.getDate()}</div>
          </div>
        `;

        currentDate.setDate(currentDate.getDate() + 1);
    }

    // Update the dropdowns to match the selected day
    updateSelectors();

    // Wait for the data to load
    await loadScheduleData();

    // NOW display the details for the selected day
    displayDayDetails();
}
// === END OF FIX ===


// === Made functions async ===
// These now pass no argument, so renderWeek defaults to selecting the start of the week
async function loadPreviousWeek() {
  currentWeekStart.setDate(currentWeekStart.getDate() - 7);
  await renderWeek();
}
async function loadNextWeek() {
  currentWeekStart.setDate(currentWeekStart.getDate() + 7);
  await renderWeek();
}


// === MODIFIED: sendMessage ===
async function sendMessage() {
  const input = document.getElementById("user-input");
  const chatBox = document.getElementById("chat-box");
  const userMessage = input.value.trim();
  if (!userMessage) return;

  chatBox.innerHTML += `<div class="message user-message">${userMessage}</div>`;
  input.value = "";
  chatBox.scrollTop = chatBox.scrollHeight;

  const selectedYear = document.getElementById('year-select').value;

  const res = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ 
      message: userMessage,
      year: selectedYear
    })
  });

  const data = await res.json();
  chatBox.innerHTML += `<div class="message bot-message">${data.reply}</div>`;
  chatBox.scrollTop = chatBox.scrollHeight;

  // Wait for the new data to load
  await loadScheduleData();
  // NOW refresh the UI, which will use the new data and correct selectedDate
  displayDayDetails();
}

