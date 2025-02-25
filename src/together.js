const username = localStorage.getItem("result");
const meetingName = localStorage.getItem("meetingName");
const meetingTopic = localStorage.getItem("meetingTopic");
const id = localStorage.getItem("id");

function logout(condition) {
  if (condition === "auto" && username) {
    if (!meetingName && !meetingTopic) {
      if (!window.location.href.includes("dashboard.html")) {
        location.replace("dashboard.html");
      }
    }
  }

  if (
    (condition === "press" && username) ||
    (condition === "auto" && !username)
  ) {
    if (condition === "press") {
      const items = ["result", "meetingName", "meetingTopic", "id"];
      items.forEach((item) => localStorage.removeItem(item));
    }

    if (!window.location.href.includes("login.html")) {
      location.replace("login.html");
    }
  }
}

if (username) {
  document.getElementById("account").textContent = `Hello, ${username}!`;
}
