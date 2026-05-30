importScripts("https://www.gstatic.com/firebasejs/12.14.0/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/12.14.0/firebase-messaging-compat.js");

firebase.initializeApp({
  apiKey: "AIzaSyD4gNqGPWf5e7YSPUMpXfI5sRq70pLPH-M",
  authDomain: "wexa-push.firebaseapp.com",
  projectId: "wexa-push",
  storageBucket: "wexa-push.firebasestorage.app",
  messagingSenderId: "119368741125",
  appId: "1:119368741125:web:1b6d9fe5c8ac0783cf876c",
  measurementId: "G-WNMDWD2XC4"
});

const messaging = firebase.messaging();

messaging.onBackgroundMessage(function(payload) {
  const title =
    payload.notification && payload.notification.title
      ? payload.notification.title
      : "WEXA 알림";

  const options = {
    body:
      payload.notification && payload.notification.body
        ? payload.notification.body
        : "근무 상태가 업데이트되었습니다.",
    icon: "/icon.png",
    badge: "/icon.png",
    data: payload.data || {}
  };

  self.registration.showNotification(title, options);
});

self.addEventListener("notificationclick", function(event) {
  event.notification.close();

  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(function(clientList) {
      for (const client of clientList) {
        if ("focus" in client) return client.focus();
      }

      if (clients.openWindow) {
        return clients.openWindow("/");
      }
    })
  );
});
