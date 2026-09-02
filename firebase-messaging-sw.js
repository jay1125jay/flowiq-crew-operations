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

firebase.messaging();

self.addEventListener("notificationclick", function(event) {
  event.notification.close();

  const fallbackUrl = "/flowiq-crew-operations/operations.html";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(function(clientList) {
      for (const client of clientList) {
        if (client.url.includes("/flowiq-crew-operations/") && "focus" in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(fallbackUrl);
    })
  );
});
