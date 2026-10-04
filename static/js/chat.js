document.addEventListener("DOMContentLoaded", () => {
  const chatApp = document.getElementById("chat-app");
  const feed = document.getElementById("chat-feed");
  const input = document.getElementById("prompt-input");
  const form = document.getElementById("chat-form");
  const resetBtn = document.getElementById("reset-btn");
  const modeBtn = document.getElementById("mode-btn");
  const sendBtn = document.getElementById("send-btn");

  let threadId = sessionStorage.getItem("thread_id") || crypto.randomUUID();
  sessionStorage.setItem("thread_id", threadId);
  let isStreaming = false;

  // Initialize Mode (Default: Normal)
  let isVerbose = localStorage.getItem("chat_verbose") === "true";
  updateModeUI();

  modeBtn.addEventListener("click", () => {
    isVerbose = !isVerbose;
    localStorage.setItem("chat_verbose", isVerbose);
    updateModeUI();
  });

  function updateModeUI() {
    if (isVerbose) {
      chatApp.classList.add("verbose");
      modeBtn.classList.add("active");
      modeBtn.textContent = "Verbose";
    } else {
      chatApp.classList.remove("verbose");
      modeBtn.classList.remove("active");
      modeBtn.textContent = "Normal";
    }
  }

  // Auto-resize textarea
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  resetBtn.addEventListener("click", async () => {
    if (isStreaming) return;
    try {
      const res = await fetch("/reset", { method: "POST" });
      const data = await res.json();
      threadId = data.thread_id;
    } catch {
      threadId = crypto.randomUUID();
    }
    sessionStorage.setItem("thread_id", threadId);
    feed.innerHTML = "";
    input.value = "";
    input.focus();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || isStreaming) return;

    // User Message Bubble
    const userMsg = document.createElement("div");
    userMsg.className = "msg user";
    userMsg.textContent = text;
    feed.appendChild(userMsg);

    input.value = "";
    input.style.height = "auto";
    setStreaming(true);

    // AI Message Bubble
    const botMsg = document.createElement("div");
    botMsg.className = "msg bot";

    // 1. ChatGPT-style Transient Status (Normal Mode)
    const transientStatus = document.createElement("div");
    transientStatus.className = "transient-status";
    transientStatus.style.display = "none";
    transientStatus.innerHTML = `<span class="status-dot-pulse"></span><span class="status-label"></span>`;

    // 2. Full Technical Reasoning Box (Verbose Mode)
    const reasoningBox = document.createElement("details");
    reasoningBox.className = "reasoning-box";
    const reasoningSum = document.createElement("summary");
    reasoningSum.textContent = "reasoning";
    const reasoningBody = document.createElement("div");
    reasoningBody.className = "reasoning-body";
    reasoningBox.appendChild(reasoningSum);
    reasoningBox.appendChild(reasoningBody);

    // 3. Full Technical Tool Trace (Verbose Mode)
    const toolBox = document.createElement("div");
    toolBox.className = "tool-box";
    const toolHead = document.createElement("div");
    toolHead.className = "tool-head";
    toolHead.innerHTML = `<span class="tool-name">tool</span><span class="tool-status">running</span>`;
    const toolLogs = document.createElement("div");
    toolLogs.className = "tool-logs";
    const toolRes = document.createElement("div");
    toolRes.className = "tool-res";
    toolRes.style.display = "none";
    toolBox.appendChild(toolHead);
    toolBox.appendChild(toolLogs);
    toolBox.appendChild(toolRes);

    // 4. Main Markdown Content
    const content = document.createElement("div");
    content.className = "content";

    // 5. Streaming Beam Cursor
    const beam = document.createElement("span");
    beam.className = "cursor-beam";

    botMsg.appendChild(transientStatus);
    botMsg.appendChild(reasoningBox);
    botMsg.appendChild(toolBox);
    botMsg.appendChild(content);
    botMsg.appendChild(beam);
    feed.appendChild(botMsg);
    feed.scrollTop = feed.scrollHeight;

    let hasReceivedText = false;

    try {
      const response = await fetch("/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, thread_id: threadId }),
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let accumulatedText = "";
      let accumulatedReasoning = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";

        for (const part of parts) {
          const trimmed = part.trim();
          if (!trimmed.startsWith("data: ")) continue;
          const jsonStr = trimmed.slice(6).trim();
          if (!jsonStr) continue;

          try {
            const ev = JSON.parse(jsonStr);

            // Handle Text Token
            if (ev.type === "token") {
              hasReceivedText = true;
              // In Normal mode, transient tool status gets replaced by the streaming text!
              transientStatus.style.display = "none";

              accumulatedText += ev.content;
              content.innerHTML = marked.parse(accumulatedText);
            } 
            // Handle Reasoning
            else if (ev.type === "reasoning") {
              accumulatedReasoning += ev.content;
              reasoningBody.textContent = accumulatedReasoning;
            } 
            // Handle Tool Call Starting
            else if (ev.type === "tool_chunk") {
              if (ev.name) {
                // Normal mode: Show ChatGPT style inline status (e.g., "calculator...")
                transientStatus.style.display = "inline-flex";
                transientStatus.querySelector(".status-label").textContent = `${ev.name}...`;

                // Verbose mode: Update technical tool box
                toolHead.querySelector(".tool-name").textContent = ev.name;
              }
            } 
            // Handle In-Tool Custom Writer Events
            else if (ev.type === "custom") {
              // Normal mode: update transient status text with custom progress
              transientStatus.style.display = "inline-flex";
              transientStatus.querySelector(".status-label").textContent = ev.content;

              // Verbose mode: append log line
              const log = document.createElement("div");
              log.textContent = `> ${ev.content}`;
              toolLogs.appendChild(log);
            } 
            // Handle Completed Tool Result
            else if (ev.type === "tool_result") {
              // Verbose mode: mark done and show result
              toolHead.querySelector(".tool-name").textContent = ev.tool;
              toolHead.querySelector(".tool-status").textContent = "done";
              toolHead.querySelector(".tool-status").classList.add("done");
              toolRes.style.display = "block";
              toolRes.textContent = `result: ${ev.result}`;
            } 
            // Completion Signal
            else if (ev.type === "done") {
              beam.remove();
              transientStatus.style.display = "none";
            } 
            // Error Handling
            else if (ev.type === "error") {
              beam.remove();
              transientStatus.style.display = "none";
              content.innerHTML += `<p style="color:#ef4444">Error: ${ev.message}</p>`;
            }
          } catch {}
          feed.scrollTop = feed.scrollHeight;
        }
      }
      beam.remove();
      transientStatus.style.display = "none";
    } catch (err) {
      beam.remove();
      transientStatus.style.display = "none";
      content.innerHTML = `<p style="color:#ef4444">Error: ${err.message}</p>`;
    } finally {
      setStreaming(false);
      input.focus();
    }
  });

  function setStreaming(state) {
    isStreaming = state;
    sendBtn.disabled = state;
  }
});
