// YouTube RAG Assistant Popup Logic
const BACKEND_URL = "http://localhost:8000";

let currentVideoUrl = null;
let currentVideoId = null;

document.addEventListener("DOMContentLoaded", () => {
  initApp();
  setupEventListeners();
});

async function initApp() {
  checkBackendHealth();
  detectYouTubeTab();
}

// 1. Check if backend FastAPI server is running
async function checkBackendHealth() {
  const statusBadge = document.getElementById("server-status");
  const statusText = statusBadge.querySelector(".status-text");

  try {
    const res = await fetch(`${BACKEND_URL}/api/health`);
    if (res.ok) {
      statusBadge.classList.add("online");
      statusText.innerText = "Connected";
    } else {
      throw new Error("Server error");
    }
  } catch (err) {
    statusBadge.classList.remove("online");
    statusText.innerText = "Offline (Port 8000)";
  }
}

// 2. Detect active Chrome tab for YouTube video URL
function detectYouTubeTab() {
  if (typeof chrome !== "undefined" && chrome.tabs) {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs && tabs[0] && tabs[0].url) {
        const url = tabs[0].url;
        if (url.includes("youtube.com/watch")) {
          currentVideoUrl = url;
          const urlParams = new URLSearchParams(new URL(url).search);
          currentVideoId = urlParams.get("v");

          updateVideoCard(currentVideoId, tabs[0].title);
        } else {
          showNoVideoState("Please open a YouTube video page to use RAG Assistant.");
        }
      }
    });
  } else {
    // Development preview fallback
    currentVideoUrl = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";
    currentVideoId = "dQw4w9WgXcQ";
    updateVideoCard(currentVideoId, "Demo YouTube Video");
  }
}

function updateVideoCard(videoId, title) {
  const thumbImg = document.getElementById("video-thumb");
  const titleEl = document.getElementById("video-title");
  const badgeEl = document.getElementById("video-id-badge");

  thumbImg.src = `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`;
  titleEl.innerText = title.replace("- YouTube", "").trim();
  badgeEl.innerText = `ID: ${videoId}`;
}

function showNoVideoState(msg) {
  const titleEl = document.getElementById("video-title");
  const badgeEl = document.getElementById("video-id-badge");

  titleEl.innerText = "No YouTube Video Detected";
  badgeEl.innerText = "Inactive";
}

// 3. Tab Navigation & Event Listeners
function setupEventListeners() {
  const tabChatBtn = document.getElementById("tab-chat-btn");
  const tabSummaryBtn = document.getElementById("tab-summary-btn");
  const chatPanel = document.getElementById("chat-panel");
  const summaryPanel = document.getElementById("summary-panel");

  tabChatBtn.addEventListener("click", () => {
    tabChatBtn.classList.add("active");
    tabSummaryBtn.classList.remove("active");
    chatPanel.classList.add("active");
    summaryPanel.classList.remove("active");
  });

  tabSummaryBtn.addEventListener("click", () => {
    tabSummaryBtn.classList.add("active");
    tabChatBtn.classList.remove("active");
    summaryPanel.classList.add("active");
    chatPanel.classList.remove("active");
  });

  const sendBtn = document.getElementById("send-btn");
  const chatInput = document.getElementById("chat-input");

  sendBtn.addEventListener("click", handleSendQuestion);
  chatInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") handleSendQuestion();
  });

  const genSummaryBtn = document.getElementById("generate-summary-btn");
  genSummaryBtn.addEventListener("click", handleGenerateSummary);
}

let chatHistory = [];

// 4. Send Question to RAG Endpoint via WebSocket Streaming
async function handleSendQuestion() {
  const chatInput = document.getElementById("chat-input");
  const question = chatInput.value.trim();

  if (!question) return;
  if (!currentVideoUrl) {
    appendMessage("bot", "Please open an active YouTube video first.");
    return;
  }

  appendMessage("user", question);
  chatInput.value = "";

  const loadingHTML = `<div class="indexing-state"><div class="typing-indicator"><span></span><span></span><span></span></div> Analyzing Request...</div>`;
  const botMsgId = appendMessage("bot", loadingHTML);

  const wsUrl = BACKEND_URL.replace("http", "ws") + "/api/stream/chat";
  const ws = new WebSocket(wsUrl);

  let fullAnswer = "";
  let isFirstChunk = true;

  ws.onopen = () => {
    ws.send(JSON.stringify({
      url_or_id: currentVideoUrl,
      question: question,
      chat_history: chatHistory
    }));
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    if (data.error) {
      updateMessage(botMsgId, `Error: ${data.error}`);
      ws.close();
    } else if (data.status === "indexing") {
      updateMessage(botMsgId, `<div class="indexing-state"><div class="typing-indicator"><span></span><span></span><span></span></div> Indexing transcript (this may take a moment for long videos)...</div>`);
    } else if (data.status === "thinking") {
      updateMessage(botMsgId, `<div class="indexing-state"><div class="typing-indicator"><span></span><span></span><span></span></div> Thinking...</div>`);
    } else if (data.chunk) {
      if (isFirstChunk) {
        fullAnswer = ""; // Clear the placeholder
        isFirstChunk = false;
      }
      fullAnswer += data.chunk;
      updateMessage(botMsgId, fullAnswer);
    } else if (data.done) {
      // Save to memory for follow-up questions!
      chatHistory.push({ role: "user", content: question });
      chatHistory.push({ role: "assistant", content: fullAnswer });
      ws.close();
    }
  };

  ws.onerror = (err) => {
    if (isFirstChunk) {
      updateMessage(botMsgId, `Connection error. Make sure the backend is running.`);
    }
  };
}

// 5. Generate Summary
async function handleGenerateSummary() {
  const container = document.getElementById("summary-container");
  if (!currentVideoUrl) {
    container.innerHTML = `<p class="placeholder-text">Please open an active YouTube video first.</p>`;
    return;
  }

  container.innerHTML = `<p class="placeholder-text">Analyzing video transcript and building summary...</p>`;

  try {
    const res = await fetch(`${BACKEND_URL}/api/summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url_or_id: currentVideoUrl })
    });

    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.detail || "Server error");
    }

    const data = await res.json();
    container.innerHTML = formatMarkdownWithTimestamps(data.summary);
    attachTimestampListeners(container);
  } catch (err) {
    container.innerHTML = `<p class="placeholder-text" style="color: #ff4757;">Error: ${err.message}</p>`;
  }
}

// 6. UI Helpers for Chat History
function appendMessage(sender, text) {
  const history = document.getElementById("chat-history");
  const msgEl = document.createElement("div");
  // Ensure absolute uniqueness even if called twice in the exact same millisecond
  const msgId = "msg-" + Date.now() + "-" + Math.random().toString(36).substr(2, 9);
  msgEl.id = msgId;
  msgEl.className = `msg ${sender}`;

  if (sender === "user") {
    msgEl.innerText = text;
  } else {
    msgEl.innerHTML = formatMarkdownWithTimestamps(text);
    attachTimestampListeners(msgEl);
  }

  history.appendChild(msgEl);
  history.scrollTop = history.scrollHeight;
  return msgId;
}

function updateMessage(msgId, newText) {
  const msgEl = document.getElementById(msgId);
  if (msgEl) {
    msgEl.innerHTML = formatMarkdownWithTimestamps(newText);
    attachTimestampListeners(msgEl);

    const history = document.getElementById("chat-history");
    history.scrollTop = history.scrollHeight;
  }
}

// 7. Timestamp Formatting & Interactive Seeking
function formatMarkdownWithTimestamps(text) {
  // Remove awkward newlines before and after timestamps generated by the LLM
  let formatted = text.replace(/\n?\s*(\[(?:\d{1,2}:)?\d{1,3}:\d{2}\])\s*\n?/g, ' $1 ');

  // Convert markdown bold/bullets
  formatted = formatted
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n- /g, "<br>• ")
    .replace(/\n/g, "<br>");

  // Replace timestamps like [02:15], [117:57], or [01:23:45] with interactive buttons
  const timestampRegex = /\[(?:(\d{1,2}):)?(\d{1,3}):(\d{2})\]/g;
  formatted = formatted.replace(timestampRegex, (match) => {
    let totalSeconds = 0;
    const cleanMatch = match.replace("[", "").replace("]", "");
    const parts = cleanMatch.split(":").map(Number);
    if (parts.length === 3) {
      totalSeconds = parts[0] * 3600 + parts[1] * 60 + parts[2];
    } else {
      totalSeconds = parts[0] * 60 + parts[1];
    }

    return `<button class="timestamp-btn" data-seconds="${totalSeconds}">${cleanMatch}</button>`;
  });

  return formatted;
}

function attachTimestampListeners(parentElement) {
  const buttons = parentElement.querySelectorAll(".timestamp-btn");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const seconds = parseInt(btn.getAttribute("data-seconds"), 10);
      const timestampStr = btn.innerText;

      if (typeof chrome !== "undefined" && chrome.tabs) {
        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
          if (tabs && tabs[0]) {
            chrome.tabs.sendMessage(tabs[0].id, {
              action: "SEEK",
              seconds: seconds,
              timestampStr: timestampStr
            });
          }
        });
      }
    });
  });
}
