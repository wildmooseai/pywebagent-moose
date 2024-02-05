(function() {
    function waitForElement(selector, timeout) {
        return new Promise((resolve, reject) => {
            const startTime = Date.now();
            function check() {
                const element = document.querySelector(selector);
                if (element) {
                    // Wait 1 more second after the element has loaded
                    setTimeout(() => resolve(element), 1000); 
                } else {
                    if (Date.now() - startTime >= timeout) {
                        reject(new Error(`Element ${selector} not found within ${timeout}ms`));
                    } else {
                        setTimeout(check, 100);  // Try again after a short delay
                    }
                }
            }
            check(); // Kickoff
        });
    }

    return waitForElement('div[role="main"]', 10000);
})();