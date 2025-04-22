document.addEventListener('DOMContentLoaded', () => {
    const loginButton = document.getElementById('login-button');
    const refreshButton = document.getElementById('refresh-button');
    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('password');
    const loginStatusDiv = document.getElementById('login-status');
    const dataStatusDiv = document.getElementById('data-status');
    const activitiesTableDiv = document.getElementById('activities-table');

    // Function to display data
    function displayActivities(activities) {
        if (!activities || activities.length === 0) {
            activitiesTableDiv.innerHTML = '<p>No activities found.</p>';
            return;
        }

        let tableHTML = `
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Name</th>
                        <th>Start Time (GMT)</th>
                        <th>Distance (m)</th>
                        <th>Duration (s)</th>
                    </tr>
                </thead>
                <tbody>
        `;
        activities.forEach(act => {
            // Basic formatting, you can improve this (dates, distance units etc.)
            const distanceKm = act.distance ? (act.distance / 1000).toFixed(2) + ' km' : 'N/A';
            const durationMin = act.duration ? (act.duration / 60).toFixed(1) + ' min' : 'N/A';
            const startTime = act.start_time_gmt ? new Date(act.start_time_gmt * 1000).toLocaleString() : 'N/A'; // Assuming start_time_gmt is Unix timestamp

            tableHTML += `
                <tr>
                    <td><span class="math-inline">\{act\.activity\_id \|\| 'N/A'\}</td\>
<td\></span>{act.activity_name || 'N/A'}</td>
                    <td><span class="math-inline">\{startTime\}</td\>
<td\></span>{distanceKm}</td>
                    <td>${durationMin}</td>
                </tr>
            `;
        });
        tableHTML += '</tbody></table>';
        activitiesTableDiv.innerHTML = tableHTML;
        dataStatusDiv.textContent = `Loaded ${activities.length} activities.`;
    }

    // --- Event Listener for Login Button ---
    loginButton.addEventListener('click', async () => {
        const username = usernameInput.value;
        const password = passwordInput.value;

        if (!username || !password) {
            loginStatusDiv.textContent = 'Please enter username and password.';
            loginStatusDiv.style.color = 'red';
            return;
        }

        loginStatusDiv.textContent = 'Logging in and fetching data... This may take a while.';
        loginStatusDiv.style.color = 'orange';
        loginButton.disabled = true; // Prevent multiple clicks

        try {
            const response = await fetch('/login-and-fetch', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ username, password }),
            });

            const result = await response.json();

            if (response.ok && result.success) {
                loginStatusDiv.textContent = 'Data fetch successful!';
                loginStatusDiv.style.color = 'green';
                displayActivities(result.activities);
                 // Clear password field after successful use
                 passwordInput.value = '';
            } else {
                loginStatusDiv.textContent = `Error: ${result.error || 'Unknown error'}`;
                loginStatusDiv.style.color = 'red';
            }
        } catch (error) {
            console.error('Fetch error:', error);
            loginStatusDiv.textContent = 'Failed to connect to the server.';
            loginStatusDiv.style.color = 'red';
        } finally {
            loginButton.disabled = false; // Re-enable button
        }
    });

     // --- Event Listener for Refresh Button ---
     refreshButton.addEventListener('click', async () => {
         dataStatusDiv.textContent = 'Refreshing data from database...';
         dataStatusDiv.style.color = 'orange';
         refreshButton.disabled = true;

         try {
             const response = await fetch('/get-data'); // Use the GET endpoint
             const result = await response.json();

             if (response.ok) {
                 displayActivities(result.activities);
                 dataStatusDiv.style.color = 'green';
             } else {
                 dataStatusDiv.textContent = `Error: ${result.error || 'Failed to load data'}`;
                 dataStatusDiv.style.color = 'red';
             }
         } catch (error) {
             console.error('Refresh error:', error);
             dataStatusDiv.textContent = 'Failed to connect to the server.';
             dataStatusDiv.style.color = 'red';
         } finally {
             refreshButton.disabled = false;
         }
     });

    // Optionally, load existing data when the page loads
    // refreshButton.click(); // Uncomment to load data on page load

});