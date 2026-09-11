(() => {
    const paint = () => {
        const root = document.documentElement;
        const body = document.body;
        root.style.setProperty("background", "#000", "important");
        if (body) body.style.setProperty("background-color", "#000", "important");
    };
    paint();
    document.addEventListener("DOMContentLoaded", paint);

    const hash = () => location.hash || "";
    if (!hash().startsWith("#/details")) return;

    let clicked = false;
    let attempts = 0;
    const timer = setInterval(() => {
        attempts += 1;
        paint();
        if (hash().startsWith("#/video")) {
            paint();
            clearInterval(timer);
            return;
        }
        const button = document.querySelector("button.btnPlay");
        if (!clicked && button && !button.disabled) {
            button.click();
            clicked = true;
        }
        if (attempts >= 80) clearInterval(timer);
    }, 250);
})();
