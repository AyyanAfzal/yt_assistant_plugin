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
  } else if (request.action === "EXTRACT_TRANSCRIPT") {
    function extractFromLivePlayer() {
      return new Promise((resolve) => {
        const messageId = "YT_TRANSCRIPT_" + Date.now();
        
        const listener = (event) => {
          if (event.source !== window) return;
          if (event.data && event.data.type === messageId) {
            window.removeEventListener("message", listener);
            resolve(event.data.payload);
          }
        };
        window.addEventListener("message", listener);

        const script = document.createElement("script");
        script.textContent = `
          try {
            let pr = window.ytInitialPlayerResponse;
            if (!pr && window.ytplayer && window.ytplayer.config && window.ytplayer.config.args) {
              const args = window.ytplayer.config.args;
              if (args.raw_player_response) pr = args.raw_player_response;
              else if (args.player_response) pr = JSON.parse(args.player_response);
            }
            const captions = pr?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
            window.postMessage({ type: "${messageId}", payload: captions }, "*");
          } catch (e) {
            window.postMessage({ type: "${messageId}", payload: null }, "*");
          }
        `;
        document.documentElement.appendChild(script);
        script.remove();
        
        setTimeout(() => {
          window.removeEventListener("message", listener);
          resolve(null);
        }, 3000);
      });
    }

    async function fetchTranscript() {
      try {
        const captions = await extractFromLivePlayer();
        if (!captions || captions.length === 0) throw new Error("No captions found in live video memory");
        
        const track = captions.find(c => c.languageCode.includes('en')) || captions[0];
        
        // Force YouTube to return the transcript as clean JSON instead of XML
        const jsonUrl = track.baseUrl + "&fmt=json3";
        const jsonRes = await fetch(jsonUrl);
        const json = await jsonRes.json();
        
        const transcriptData = [];
        if (json.events) {
          for (const event of json.events) {
            if (event.segs) {
              const text = event.segs.map(s => s.utf8).join("");
              if (text.trim()) {
                transcriptData.push({
                  text: text.replace(/\n/g, ' ').trim(),
                  start: (event.tStartMs || 0) / 1000.0,
                  duration: (event.dDurationMs || 0) / 1000.0
                });
              }
            }
          }
        }
        
        if (transcriptData.length === 0) {
          throw new Error("Transcript was fetched but contained no readable text.");
        }
        
        sendResponse({ status: "success", transcript: transcriptData });
      } catch (err) {
        sendResponse({ status: "error", message: err.message });
      }
    }
    fetchTranscript();
    return true; // Keep message channel open for async response
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
