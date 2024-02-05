// Removing the onboarding `div`s
// The snippet is wrapped in DOMContentLoaded to ensure document.body exists.
document.addEventListener('DOMContentLoaded', function() {
    function removeElements() {
        var elements = document.querySelectorAll('[class^="druids_onboarding_billboard"]');
        elements.forEach(function(element) {
            element.parentNode.removeChild(element);
        });
    }

    var observer = new MutationObserver(function(mutationsList, observer) {
        removeElements();
    });
    observer.observe(document.body, { childList: true, subtree: true });
});