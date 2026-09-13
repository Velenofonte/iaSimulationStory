import { useEffect, useState } from "react";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

declare global {
  interface Window {
    __OVERLORD_PWA_PROMPT?: BeforeInstallPromptEvent;
  }
}

const DISMISS_KEY = "pwa-install-dismissed";

function isStandalone(): boolean {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    window.matchMedia("(display-mode: fullscreen)").matches ||
    Boolean((navigator as Navigator & { standalone?: boolean }).standalone)
  );
}

function isIos(): boolean {
  const ua = navigator.userAgent;
  return /iphone|ipad|ipod/i.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

function isLocalhost(): boolean {
  const host = window.location.hostname;
  return host === "localhost" || host === "127.0.0.1" || host === "[::1]";
}

function isInsecureRemote(): boolean {
  return window.location.protocol === "http:" && !isLocalhost();
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
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(() =>
    typeof window === "undefined" ? null : (window.__OVERLORD_PWA_PROMPT ?? null),
  );
  const [visible, setVisible] = useState(() => {
    if (typeof window === "undefined") return false;
    if (isStandalone()) return false;
    return localStorage.getItem(DISMISS_KEY) !== "1";
  });

  useEffect(() => {
    if (isStandalone()) {
      setVisible(false);
      return;
    }

    const onPrompt = (event: Event) => {
      event.preventDefault();
      const next = event as BeforeInstallPromptEvent;
      window.__OVERLORD_PWA_PROMPT = next;
      setDeferred(next);
      if (localStorage.getItem(DISMISS_KEY) !== "1") setVisible(true);
    };
    const onInstalled = () => {
      window.__OVERLORD_PWA_PROMPT = undefined;
      setDeferred(null);
      setVisible(false);
    };

    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  if (!visible || isStandalone()) return null;

  const ios = isIos();
  const insecure = isInsecureRemote();
  const origin = typeof window === "undefined" ? "" : window.location.origin;

  async function install() {
    if (!deferred) return;
    await deferred.prompt();
    const { outcome } = await deferred.userChoice;
    setDeferred(null);
    window.__OVERLORD_PWA_PROMPT = undefined;
    if (outcome === "accepted") setVisible(false);
  }

  function dismiss() {
    localStorage.setItem(DISMISS_KEY, "1");
    setVisible(false);
  }

  async function copyOrigin() {
    try {
      await navigator.clipboard.writeText(origin);
    } catch {
      /* ignore */
    }
  }

  return (
    <aside className="pwa-install" role="status">
      <p className="pwa-install-title">Installa come app</p>
      {deferred ? (
        <p>Puoi aggiungerla alla schermata Home e usarla a schermo intero, senza barra del browser.</p>
      ) : ios ? (
        <p>Safari non mostra un popup: tocca Condividi e poi Aggiungi a Home.</p>
      ) : insecure ? (
        <>
          <p>
            Chrome non installa da un IP in HTTP ({origin}). Sul PC apri{" "}
            <a className="pwa-install-link" href="http://localhost:5173/">
              http://localhost:5173
            </a>
            . Sul telefono sblocca l&apos;origine in Chrome:
          </p>
          <ol className="pwa-install-steps">
            <li>
              Apri{" "}
              <code>chrome://flags/#unsafely-treat-insecure-origin-as-secure</code>
            </li>
            <li>
              Incolla <code>{origin}</code> nel campo, Enabled, Relaunch
            </li>
            <li>Riapri questa pagina: comparirà Installa</li>
          </ol>
        </>
      ) : (
        <p>Chrome sul computer: icona Installa nella barra degli indirizzi, oppure menu ⋮ → Installa app.</p>
      )}
      <div className="pwa-install-actions">
        {deferred ? (
          <button type="button" className="btn primary" onClick={() => void install()}>
            Installa
          </button>
        ) : null}
        {insecure && !deferred ? (
          <button type="button" className="btn ghost" onClick={() => void copyOrigin()}>
            Copia indirizzo
          </button>
        ) : null}
        <button type="button" className="btn ghost" onClick={dismiss}>
          Non ora
        </button>
      </div>
    </aside>
  );
}
