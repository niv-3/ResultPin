(() => {
  let installPrompt = null;
  let installed = false;
  const standalone = window.matchMedia('(display-mode: standalone)');
  const isInstalled = () => installed || standalone.matches || navigator.standalone === true;
  const update = () => {
    const panel = document.getElementById('payvict-install');
    if (panel) panel.hidden = isInstalled();
  };
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    installPrompt = event;
    update();
  });
  window.addEventListener('appinstalled', () => {
    installed = true;
    installPrompt = null;
    document.getElementById('payvict-install-help')?.close();
    update();
  });
  standalone.addEventListener('change', update);
  window.addEventListener('pageshow', update);
  document.addEventListener('DOMContentLoaded', () => {
    const button = document.getElementById('payvict-install-button');
    const help = document.getElementById('payvict-install-help');
    if (!button || !help) return;
    const instructions = document.getElementById('payvict-install-instructions');
    const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
      (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    instructions.textContent = ios
      ? 'Open this link in Safari. Tap Share, then Add to Home Screen and Add. If shown, keep Open as Web App switched on.'
      : /Android/.test(navigator.userAgent)
        ? 'Open this link in Chrome. Tap the three-dot menu, then Install app or Add to Home screen, and confirm. If you opened the link inside WhatsApp or another app, choose Open in Chrome first.'
        : 'Open your browser menu and choose Install Payvict or Install this site as an app. You can also use the install icon beside the address bar when available.';
    const showHelp = () => { if (!help.open) help.showModal(); };
    button.addEventListener('click', async () => {
      if (isInstalled()) { update(); return; }
      if (!installPrompt) { showHelp(); return; }
      const prompt = installPrompt;
      installPrompt = null; // Browser prompts can only be used once.
      button.disabled = true;
      try {
        await prompt.prompt(); // Must run directly from the customer's tap.
        await prompt.userChoice;
      } catch { showHelp(); }
      finally { button.disabled = false; update(); }
    });
    update();
    if ('serviceWorker' in navigator && window.isSecureContext) {
      navigator.serviceWorker.register('/service-worker.js').catch(() => {});
    }
  });
})();
