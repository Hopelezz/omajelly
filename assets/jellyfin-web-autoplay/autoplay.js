(() => {
    const expected = new URL(location.href);
    if (!expected.hash.startsWith("#/details?id=")) return;

    let attempts = 0;
    const timer = setInterval(() => {
        attempts += 1;
        const button = [...document.querySelectorAll("button")].find((candidate) =>
            candidate.classList.contains("btnPlay")
            || candidate.getAttribute("data-action") === "play"
            || candidate.textContent.trim() === "Play"
        );
        if (button && !button.disabled) {
            button.click();
            clearInterval(timer);
        } else if (attempts >= 80) {
            clearInterval(timer);
        }
    }, 250);
})();
