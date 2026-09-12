import { useEffect, useState } from "react";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

const DISMISS_KEY = "pwa-install-dismissed";

function isStandalone(): boolean {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    window.matchMedia("(display-mode: fullscreen)").matches ||
    Boolean((navigator as Navigator & { standalone?: boolean }).standalone)
  );
}

function isIosSafari(): boolean {
  const ua = navigator.userAgent;
  const iOS = /iphone|ipad|ipod/i.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const webkit = /AppleWebKit/i.test(ua);
  const notOther = !/CriOS|FxiOS|OPiOS|EdgiOS/i.test(ua);
  return iOS && webkit && notOther;
}

export function OfflineBanner() {
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine));

  useEffect(() => {
    const sync = () => setOnline(navigator.onLine);
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    return () => {
      window.removeEventListener("online", sync);
      window.removeEventListener("offline", sync);
    };
  }, []);

  if (online) return null;
  return (
    <p className="offline-banner" role="status">
      Sei offline. L&apos;interfaccia si apre, ma serve la rete per giocare.
    </p>
  );
}

export function PwaInstall() {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [iosHint] = useState(() => {
    if (typeof window === "undefined") return false;
    if (isStandalone()) return false;
    if (localStorage.getItem(DISMISS_KEY) === "1") return false;
    return isIosSafari();
  });
  const [visible, setVisible] = useState(() => {
    if (typeof window === "undefined") return false;
    if (isStandalone()) return false;
    if (localStorage.getItem(DISMISS_KEY) === "1") return false;
    return isIosSafari();
  });

  useEffect(() => {
    if (isStandalone()) return;
    if (localStorage.getItem(DISMISS_KEY) === "1") return;

    const onPrompt = (event: Event) => {
      event.preventDefault();
      setDeferred(event as BeforeInstallPromptEvent);
      setVisible(true);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  if (!visible || (!deferred && !iosHint)) return null;

  async function install() {
    if (!deferred) return;
    await deferred.prompt();
    const { outcome } = await deferred.userChoice;
    setDeferred(null);
    if (outcome === "accepted") setVisible(false);
  }

  function dismiss() {
    localStorage.setItem(DISMISS_KEY, "1");
    setVisible(false);
  }

  return (
    <aside className="pwa-install" role="status">
      <p>
        {deferred
          ? "Installa l'app per usarla a schermo intero, come un'applicazione."
          : "Su iPhone: Condividi → Aggiungi a Home."}
      </p>
      <div className="pwa-install-actions">
        {deferred ? (
          <button type="button" className="btn primary" onClick={() => void install()}>
            Installa
          </button>
        ) : null}
        <button type="button" className="btn ghost" onClick={dismiss}>
          Non ora
        </button>
      </div>
    </aside>
  );
}
