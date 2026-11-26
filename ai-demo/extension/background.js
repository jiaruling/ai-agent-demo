const SYSTEM_ORIGIN = "http://192.168.11.200:5187";
const pendingKey = tabId => `navigation:${tabId}`;
const processing = new Set();
const recheck = new Set();

async function notify(pending, message) {
  try {
    await chrome.tabs.sendMessage(pending.sourceTabId, {
      type: "navigation-status",
      message
    });
  } catch (error) {
    console.warn("无法通知助手页面：", error.message);
  }
}

async function inspectSystem(tabId) {
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    func: async () => {
      let state;
      try {
        state = JSON.parse(localStorage.getItem("hdm_storage") || "{}").state;
      } catch {
        return { path: location.pathname, invalid: true };
      }
      if (location.pathname === "/login" || !state?.token) {
        return { path: location.pathname, loginRequired: true };
      }
      try {
        const response = await fetch("/detection-api/api/v1/me/access", {
          headers: { Authorization: state.token }
        });
        if (response.status === 401) {
          return { path: location.pathname, loginRequired: true };
        }
        if (!response.ok) return { path: location.pathname, permissionError: true };
        const result = await response.json();
        if (result.code !== 0 || !Array.isArray(result.data?.menus)) {
          return { path: location.pathname, permissionError: true };
        }
        const menuPaths = [];
        const collect = menus => menus.forEach(menu => {
          if (typeof menu.path === "string") menuPaths.push(menu.path);
          if (Array.isArray(menu.children)) collect(menu.children);
        });
        collect(result.data.menus);
        return { path: location.pathname, menuPaths };
      } catch {
        return { path: location.pathname, permissionError: true };
      }
    }
  });
  return results[0]?.result;
}

async function finish(tabId, pending, message) {
  await chrome.storage.session.remove(pendingKey(tabId));
  if (message) await notify(pending, message);
}

async function checkNavigation(tabId) {
  if (processing.has(tabId)) {
    recheck.add(tabId);
    return;
  }
  processing.add(tabId);
  try {
    const key = pendingKey(tabId);
    const pending = (await chrome.storage.session.get(key))[key];
    if (!pending) return;
    const tab = await chrome.tabs.get(tabId);
    if (!tab.url || new URL(tab.url).origin !== SYSTEM_ORIGIN || tab.status !== "complete") return;

    const state = await inspectSystem(tabId);
    if (!state || state.invalid) {
      await finish(tabId, pending, "无法读取内部系统的登录状态，请在系统页面确认。");
      return;
    }
    if (new URL(pending.url).pathname === "/login" && state.path === "/login") {
      await finish(tabId, pending, null);
      return;
    }
    if (state.loginRequired) {
      if (state.path !== "/login") {
        await chrome.tabs.update(tabId, { url: SYSTEM_ORIGIN + "/login" });
      }
      if (!pending.loginNotified) {
        pending.loginNotified = true;
        await chrome.storage.session.set({ [key]: pending });
        await notify(pending, `请在打开的内部系统页面手动登录，登录后将继续打开「${pending.label}」。`);
      }
      return;
    }
    if (state.permissionError || !state.menuPaths) {
      await finish(tabId, pending, "无法读取页面权限，请在内部系统中确认。");
      return;
    }

    const target = new URL(pending.url);
    const publicPaths = ["/home", "/profile", "/login"];
    if (!publicPaths.includes(target.pathname) && !state.menuPaths.includes(target.pathname)) {
      await chrome.tabs.update(tabId, { url: SYSTEM_ORIGIN + "/home" });
      await finish(tabId, pending, `当前用户没有「${pending.label}」页面的访问权限，已跳转到首页。`);
      return;
    }
    if (tab.url !== pending.url) {
      await chrome.tabs.update(tabId, { url: pending.url });
      return;
    }
    await finish(tabId, pending, null);
  } catch (error) {
    console.error("页面跳转失败：", error);
    const key = pendingKey(tabId);
    const pending = (await chrome.storage.session.get(key))[key];
    if (pending) {
      const current = await chrome.tabs.get(tabId).catch(() => null);
      if (current?.status === "loading") return;
      if (current?.url && new URL(current.url).origin === SYSTEM_ORIGIN &&
          recheck.has(tabId)) return;
      await finish(tabId, pending, "无法完成页面跳转，请点击页面链接并在系统中确认。");
    }
  } finally {
    processing.delete(tabId);
    if (recheck.delete(tabId)) checkNavigation(tabId);
  }
}

async function navigate(message, sender) {
  if (!sender.tab?.id || typeof message.url !== "string" || typeof message.label !== "string") {
    throw new Error("无效的跳转请求");
  }
  const target = new URL(message.url);
  if (target.origin !== SYSTEM_ORIGIN || target.username || target.password) {
    throw new Error("不允许跳转到此地址");
  }
  const tabs = await chrome.tabs.query({});
  let tab = tabs.find(item => item.url === target.href);
  if (tab) {
    await chrome.windows.update(tab.windowId, { focused: true });
    await chrome.tabs.update(tab.id, { active: true });
  } else {
    tab = await chrome.tabs.create({ url: SYSTEM_ORIGIN + "/home", active: true });
  }
  const pending = {
    sourceTabId: sender.tab.id,
    url: target.href,
    label: message.label,
    loginNotified: false
  };
  await chrome.storage.session.set({ [pendingKey(tab.id)]: pending });
  await checkNavigation(tab.id);
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type !== "navigate") return;
  navigate(message, sender).then(() => sendResponse({ ok: true })).catch(async error => {
    if (sender.tab?.id) {
      await notify({ sourceTabId: sender.tab.id }, "无法打开内部系统页面：" + error.message);
    }
    sendResponse({ ok: false });
  });
  return true;
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "complete") checkNavigation(tabId);
});
chrome.webNavigation.onHistoryStateUpdated.addListener(details => {
  if (details.frameId === 0) checkNavigation(details.tabId);
});
chrome.tabs.onRemoved.addListener(tabId => {
  chrome.storage.session.remove(pendingKey(tabId));
});
