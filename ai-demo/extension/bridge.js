if (location.origin !== "http://192.168.11.200:5187") {
  const notifyPage = message => {
    window.postMessage({ source: "ai-agent-extension", ...message }, location.origin);
  };

  window.addEventListener("message", event => {
    if (event.source !== window || event.origin !== location.origin ||
        event.data?.source !== "ai-agent") return;
    if (event.data.type === "ping") {
      notifyPage({ type: "ready" });
    } else if (event.data.type === "navigate") {
      chrome.runtime.sendMessage({
        type: "navigate",
        url: event.data.url,
        label: event.data.label
      }).catch(() => {
        notifyPage({ type: "navigation-status", message: "浏览器扩展未能处理跳转，请点击页面链接。" });
      });
    }
  });

  chrome.runtime.onMessage.addListener(message => {
    if (message.type === "navigation-status") notifyPage(message);
  });
  notifyPage({ type: "ready" });
}
