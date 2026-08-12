// YouTube RAG Assistant Content Script
// Listens for seek events from popup script to control video playback

console.log("YouTube RAG Content Script Loaded");

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "SEEK") {
    const targetSeconds = request.seconds;
    const videoElement = document.querySelector("video");
    
    if (videoElement) {
      videoElement.currentTime = targetSeconds;
      videoElement.play();
      
      // Flash visual feedback on player
      showSeekToast(request.timestampStr || `${targetSeconds}s`);
      sendResponse({ status: "success", currentTime: videoElement.currentTime });
    } else {
      sendResponse({ status: "error", message: "Video element not found" });
    }
  } else if (request.action === "GET_VIDEO_INFO") {
    const videoElement = document.querySelector("video");
    const titleElement = document.querySelector("h1.ytd-watch-metadata yt-formatted-string, h1.title");
    
    sendResponse({
      title: titleElement ? titleElement.innerText : document.title,
      currentTime: videoElement ? videoElement.currentTime : 0,
      duration: videoElement ? videoElement.duration : 0
    });
  }
  return true;
});

function showSeekToast(timestampText) {
  let toast = document.getElementById("yt-rag-seek-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "yt-rag-seek-toast";
    toast.style.cssText = `
      position: fixed;
      top: 80px;
      right: 20px;
      background: rgba(138, 43, 226, 0.9);
      color: white;
      padding: 10px 18px;
      border-radius: 20px;
      font-family: Arial, sans-serif;
      font-size: 14px;
      font-weight: bold;
      z-index: 999999;
      box-shadow: 0 4px 15px rgba(0,0,0,0.4);
      transition: opacity 0.3s ease;
      backdrop-filter: blur(8px);
    `;
    document.body.appendChild(toast);
  }
  
  toast.innerText = `⏱ Jumped to ${timestampText}`;
  toast.style.opacity = "1";
  
  setTimeout(() => {
    toast.style.opacity = "0";
  }, 2000);
}
